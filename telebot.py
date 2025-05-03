import logging
import os
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import ollama
import nest_asyncio
from faster_whisper import WhisperModel
from pydub import AudioSegment
from PIL import Image
import io
import base64
import tempfile
import aiohttp
import asyncio
from dotenv import load_dotenv
import aiosqlite
import bcrypt
import json
from duckduckgo_search import DDGS
nest_asyncio.apply()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

load_dotenv()

# Инициализация модели распознавания речи
whisper_model = WhisperModel("medium", device="cpu", compute_type="int8")

# Токен бота
TOKEN = os.getenv('TOKEN')
# Пароль для доступа
PASSWORD = os.getenv('PASSWORD')  # Пароль для доступа

# Проверка наличия токена и пароля
if not TOKEN or not PASSWORD:
    raise ValueError("❌ Не заданы TOKEN или PASSWORD в .env")

# Доступные модели Ollama
MODELS = {
    '1': 'qwen3:14b',  # Теперь по умолчанию
    '2': 'gemma3:12b'
}

# Глобальные переменные
db_path = 'bot.db'

async def init_db():
    """Инициализация базы данных"""
    async with aiosqlite.connect(db_path) as db:
        # Создание таблицы пользователей
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                authenticated BOOLEAN,
                model TEXT,
                think_mode BOOLEAN,
                temperature REAL,
                context_size INTEGER,
                name TEXT,
                password_hash TEXT
            )
        ''')
        
        # Создание таблицы контекста
        await db.execute('''
            CREATE TABLE IF NOT EXISTS context (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                role TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')
        
        # Создание таблицы системных промптов
        await db.execute('''
            CREATE TABLE IF NOT EXISTS system_prompt (
                id INTEGER PRIMARY KEY,
                prompt TEXT
            )
        ''')
        
        # Проверка наличия системного промпта
        async with db.execute('SELECT prompt FROM system_prompt WHERE id = 1') as cursor:
            result = await cursor.fetchone()
            if not result:
                await db.execute('INSERT INTO system_prompt (id, prompt) VALUES (1, ?)', 
                               ("You're a friendly helpful assistant answering in Russian, you running locally",))
        
        await db.commit()

async def hash_password(password: str) -> str:
    """Хеширование пароля"""
    loop = asyncio.get_event_loop()
    hashed = await loop.run_in_executor(None, bcrypt.hashpw, password.encode(), bcrypt.gensalt())
    return hashed.decode()

async def check_password(password: str, hashed: str) -> bool:
    """Проверка пароля"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, bcrypt.checkpw, password.encode(), hashed.encode())

async def get_user_data(user_id: str) -> dict:
    """Получение данных пользователя из БД"""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    'authenticated': bool(row[1]),
                    'model': row[2],
                    'think_mode': bool(row[3]),
                    'temperature': row[4],
                    'context_size': row[5],
                    'name': row[6]
                }
            return None

async def save_user_data(user_id: str, data: dict):
    """Сохранение данных пользователя в БД"""
    async with aiosqlite.connect(db_path) as db:
        # Если пользователь существует - обновляем, иначе создаем
        async with db.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,)) as cursor:
            exists = await cursor.fetchone()
        
        if exists:
            await db.execute('''
                UPDATE users SET 
                authenticated = ?, model = ?, think_mode = ?, 
                temperature = ?, context_size = ?, name = ?
                WHERE user_id = ?
            ''', (
                data['authenticated'], data['model'], data['think_mode'],
                data['temperature'], data['context_size'], data['name'], user_id
            ))
        else:
            await db.execute('''
                INSERT INTO users 
                (user_id, authenticated, model, think_mode, temperature, context_size, name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, data['authenticated'], data['model'], data['think_mode'],
                data['temperature'], data['context_size'], data['name']
            ))
        
        await db.commit()

async def get_system_prompt() -> str:
    """Получение системного промпта"""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute('SELECT prompt FROM system_prompt WHERE id = 1') as cursor:
            result = await cursor.fetchone()
            return result[0] if result else ""

async def add_context_message(user_id: str, role: str, content: str):
    """Добавление сообщения в контекст"""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            'INSERT INTO context (user_id, role, content) VALUES (?, ?, ?)',
            (user_id, role, content)
        )
        await db.commit()

async def get_context_messages(user_id: str, max_context: int = 21) -> list:
    """Получение последних сообщений контекста"""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute('''
            SELECT role, content FROM context 
            WHERE user_id = ? 
            ORDER BY timestamp DESC LIMIT ?
        ''', (user_id, max_context)) as cursor:
            rows = await cursor.fetchall()
            return [{'role': role, 'content': content} for role, content in reversed(rows)]

async def clear_context_data(user_id: str):
    async with aiosqlite.connect(db_path) as db:
        await db.execute('DELETE FROM context WHERE user_id = ?', (user_id,))
        await db.commit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    user_id = str(update.effective_user.id)
    
    # Инициализация данных пользователя
    user = await get_user_data(user_id)
    
    if not user:
        # Создаем нового пользователя
        password_hash = await hash_password(PASSWORD)
        await save_user_data(
            user_id,
            {
                'authenticated': False,
                'model': '1',
                'think_mode': False,
                'temperature': 0.7,
                'context_size': 21,
                'name': None
            }
        )
        
        # Сохраняем хеш пароля
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                'UPDATE users SET password_hash = ? WHERE user_id = ?',
                (password_hash, user_id)
            )
            await db.commit()
    
    user = await get_user_data(user_id)
    
    if user and user['authenticated']:
        name = user.get('name', 'пользователь')
        await update.message.reply_text(f'👋 С возвращением, {name}! Можете задавать вопросы.')
    else:
        await update.message.reply_text('🔐 Введите пароль для доступа:')

async def switch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик смены модели /switch [1/2]"""
    user_id = str(update.effective_user.id)
    user = await get_user_data(user_id)
    
    if not user or not user['authenticated']:
        await update.message.reply_text('🔒 Сначала авторизуйтесь')
        return
    
    if not context.args:
        model_name = MODELS[user['model']]
        await update.message.reply_text(f'🧠 Текущая модель: {model_name}')
        return
    
    model_choice = context.args[0]
    if model_choice in ['1', '2']:
        user['model'] = model_choice
        await save_user_data(user_id, user)
        model_name = MODELS[model_choice]
        await update.message.reply_text(f'✅ Модель изменена на {model_name}')
    else:
        await update.message.reply_text('⚠️ Доступные модели: 1 или 2')

async def set_thinking_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Настройка режима мышления через /think [0/1]"""
    user_id = str(update.effective_user.id)
    user = await get_user_data(user_id)
    
    if not user or not user['authenticated']:
        await update.message.reply_text('🔒 Сначала авторизуйтесь')
        return
    
    if not context.args:
        mode = "🧠 Мышление: ВКЛ" if user['think_mode'] else "🧠 Мышление: ВЫКЛ"
        await update.message.reply_text(f"{mode}\nДля изменения: /think [0/1]")
        return
    
    mode_arg = context.args[0]
    if mode_arg == '1':
        user['think_mode'] = True
        await save_user_data(user_id, user)
        await update.message.reply_text('🧠 Режим мышления: ВКЛ')
    elif mode_arg == '0':
        user['think_mode'] = False
        await save_user_data(user_id, user)
        await update.message.reply_text('🧠 Режим мышления: ВЫКЛ')
    else:
        await update.message.reply_text('⚠️ Неверный аргумент. Используйте:\n/think 0 - выключить\n/think 1 - включить')

async def set_temperature(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Настройка температуры генерации"""
    user_id = str(update.effective_user.id)
    user = await get_user_data(user_id)
    
    if not user or not user['authenticated']:
        await update.message.reply_text('🔒 Сначала авторизуйтесь')
        return
    
    if not context.args:
        temp = user['temperature']
        await update.message.reply_text(f'🌡️ Текущая температура: {temp}')
        return
    
    try:
        temp = float(context.args[0])
        if 0 <= temp <= 1:
            user['temperature'] = temp
            await save_user_data(user_id, user)
            await update.message.reply_text(f'🌡️ Температура установлена: {temp}')
        else:
            await update.message.reply_text('⚠️ Температура должна быть от 0 до 1')
    except ValueError:
        await update.message.reply_text('⚠️ Укажите числовое значение')

async def set_context_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Настройка размера контекстной памяти /cs [2-50]"""
    user_id = str(update.effective_user.id)
    user = await get_user_data(user_id)
    
    if not user or not user['authenticated']:
        await update.message.reply_text('🔒 Сначала авторизуйтесь')
        return
    
    if not context.args:
        size = user['context_size']
        await update.message.reply_text(f'💾 Размер контекста: {size}')
        return
    
    try:
        new_size = int(context.args[0])
        if 2 <= new_size <= 50:
            user['context_size'] = new_size
            await save_user_data(user_id, user)
            await update.message.reply_text(f'✅ Размер контекста изменен на {new_size}')
        else:
            await update.message.reply_text('⚠️ Допустимый диапазон: от 2 до 50')
    except ValueError:
        await update.message.reply_text('⚠️ Укажите числовое значение')

async def get_user_password_hash(user_id: str) -> str:
    """Получение хеша пароля пользователя"""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute('SELECT password_hash FROM users WHERE user_id = ?', (user_id,)) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else ""

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка текстовых сообщений"""
    user_id = str(update.effective_user.id)
    
    # Инициализация данных пользователя
    user = await get_user_data(user_id)
    
    if not user:
        # Создаем нового пользователя
        password_hash = await hash_password(PASSWORD)
        user_data = {
            'authenticated': False,
            'model': '1',
            'think_mode': False,
            'temperature': 0.7,
            'context_size': 21,
            'name': None
        }
        await save_user_data(user_id, user_data)
        
        # Сохраняем хеш пароля
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                'UPDATE users SET password_hash = ? WHERE user_id = ?',
                (password_hash, user_id)
            )
            await db.commit()
    
    user = await get_user_data(user_id)
    
    # Проверка аутентификации
    if not user['authenticated']:
        message_text = update.message.text
        password_hash = await get_user_password_hash(user_id)
        
        if await check_password(message_text, password_hash):
            user['authenticated'] = True
            user['name'] = None  # Флаг для запроса имени
            await save_user_data(user_id, user)
            
            # Добавляем системный промпт в контекст
            system_prompt = await get_system_prompt()
            await add_context_message(user_id, 'system', system_prompt)
            
            await update.message.reply_text('✅ Пароль принят!\n📝 Введите ваше имя:')
        else:
            await update.message.reply_text('❌ Неверный пароль')
        return
    
    # Обработка имени
    if user.get('name') is None:
        user['name'] = update.message.text
        await save_user_data(user_id, user)
        await update.message.reply_text(f'👋 Рад знакомству, {user["name"]}! Теперь вы можете задавать вопросы или просто общаться со мной!')
        return
    
    # Обработка сообщения
    message_text = context.user_data.get('voice_text') or update.message.text
    
    # Подготовка контекста
    system_prompt = await get_system_prompt()
    context_messages = await get_context_messages(user_id, user['context_size'])
    
    # Добавление метки мышления для Qwen3
    if user['model'] == '1':  # Qwen3
        if user['think_mode']:
            message_text = f"[THINK] {message_text}"
        else:
            message_text = f"[NO_THINK] {message_text}"
    
    # Добавляем сообщение пользователя
    context_messages.append({'role': 'user', 'content': message_text})
    
    try:
        # Получение ответа от модели
        response = await asyncio.get_event_loop().run_in_executor(
            None, 
            lambda: ollama.chat(
                model=MODELS[user['model']],
                messages=context_messages,
                options={'temperature': user['temperature']}
            )
        )
        
        # Добавление ответа в контекст
        await add_context_message(user_id, 'assistant', response['message']['content'])
        
        # Отправка ответа пользователю
        await update.message.reply_text(response['message']['content'])
    except Exception as e:
        logging.error(f"Ошибка Ollama: {e}")
        await update.message.reply_text('⚠️ Ошибка генерации ответа')

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка голосовых сообщений"""
    user_id = str(update.effective_user.id)
    user = await get_user_data(user_id)
    
    if not user or not user['authenticated']:
        await update.message.reply_text('Введите пароль для доступа!')
        return
    
    try:
        # Скачивание и конвертация аудио
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_ogg:
            await file.download_to_drive(temp_ogg.name)
            audio = AudioSegment.from_ogg(temp_ogg.name)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
                audio.export(temp_wav.name, format="wav", parameters=["-ac", "1", "-ar", "16000"])
                # Распознавание речи
                segments, _ = whisper_model.transcribe(
                    temp_wav.name,
                    language="ru",
                    beam_size=5,
                    vad_filter=True
                )
                text = " ".join([segment.text for segment in segments])
        # Удаление временных файлов
        os.unlink(temp_ogg.name)
        os.unlink(temp_wav.name)
        if text.strip():
            # Отправка транскрипта и обработка текста
            await update.message.reply_text(f"📝 Транскрипт:\n{text}")
            context.user_data['voice_text'] = text
            await handle_message(update, context)
            del context.user_data['voice_text']
        else:
            await update.message.reply_text("Не удалось распознать речь.")
    except Exception as e:
        logging.error(f"Ошибка обработки голоса: {e}")
        await update.message.reply_text(f"Произошла ошибка: {str(e)[:100]}")

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка изображений с использованием Gemma3"""
    user_id = str(update.effective_user.id)
    user = await get_user_data(user_id)
    
    if not user or not user['authenticated']:
        await update.message.reply_text('Введите пароль для доступа!')
        return
    
    try:
        # Получение фото
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        # Конвертация в base64
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        # Формирование multimodal-запроса
        context_messages = await get_context_messages(user_id, user['context_size'])
        context_messages.append({
            'role': 'user',
            'content': [
                {'type': 'image', 'data': image_base64},
                {'type': 'text', 'text': 'Опиши это изображение'}
            ]
        })
        # Получение ответа от Ollama
        response = await asyncio.get_event_loop().run_in_executor(
            None, 
            lambda: ollama.chat(
                model=MODELS[user['model']],
                messages=context_messages,
                options={'temperature': user['temperature']}
            )
        )
        await update.message.reply_text(f"🖼️ Описание изображения:\n{response['message']['content']}")
    except Exception as e:
        logging.error(f"Ошибка обработки изображения: {e}")
        await update.message.reply_text("Не удалось обработать изображение")

async def draw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Генерация изображений через Stable Diffusion"""
    user_id = str(update.effective_user.id)
    logging.info(f"Draw command from {user_id}")
    user = await get_user_data(user_id)
    
    if not user or not user['authenticated']:
        await update.message.reply_text('🔒 Требуется авторизация через /start')
        return
    
    if not context.args:
        await update.message.reply_text('📝 Формат: /d [описание изображения]')
        return
    
    prompt = ' '.join(context.args)
    logging.info(f"Генерация для промпта: {prompt}")
    
    payload = {
        "prompt": prompt,
        "negative_prompt": "text, watermark, low quality",
        "steps": 20,
        "sampler_name": "Euler a",
        "width": 1024,
        "height": 1024,
        "override_settings": {
            "sd_model_checkpoint": "sdXL_v10VAEFix.safetensors [e6bb9ea85b]"
        }
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            # Проверка доступности моделей
            async with session.get('http://localhost:7860/sdapi/v1/sd-models') as model_check:
                if model_check.status != 200:
                    await update.message.reply_text('⚠️ Модель SD не загружена')
                    return
            
            # Основной запрос
            async with session.post(
                'http://localhost:7860/sdapi/v1/txt2img',
                json=payload,
                timeout=300
            ) as response:
                logging.info(f"API Response: {response.status}")
                if response.status != 200:
                    error = await response.text()
                    logging.error(f"API Error: {error}")
                    await update.message.reply_text(f'❌ Ошибка API: {response.status}')
                    return
                
                data = await response.json()
                if not data.get('images'):
                    await update.message.reply_text('🖼️ Пустой ответ от генератора')
                    return
                
                image_data = base64.b64decode(data['images'][0])
                with io.BytesIO() as img_buffer:
                    Image.open(io.BytesIO(image_data)).save(img_buffer, format='PNG')
                    img_buffer.seek(0)
                    await update.message.reply_photo(
                        photo=InputFile(img_buffer, filename='art.png'),
                        caption=f'🎨 {prompt[:100]}...'
                    )
                    logging.info("Изображение успешно отправлено")
    
    except asyncio.TimeoutError:
        logging.warning("Таймаут генерации")
        await update.message.reply_text('⏳ Слишком долгая генерация, попробуйте позже')
    
    except Exception as e:
        logging.error(f"Critical Draw Error: {str(e)}", exc_info=True)
        await update.message.reply_text('🔥 Ошибка в процессе генерации')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик помощи /help"""
    help_text = (
        "Доступные команды:\n"
        "/start - Начать работу (требуется пароль)\n"
        "/switch [1/2] - Сменить модель\n"
        "/think [0/1] - Включить/выключить режим мышления\n"
        "/temp [0-1] - Установить температуру генерации\n"
        "/cs [2-50] - Установить размер контекстной памяти\n"
        "/clear - Очистить все данные и выйти\n"
        "/clearc - Очистить контекст диалога\n"
        "/info - Показать информацию о себе\n"
        "/changename [новое_имя] - Изменить ваше отображаемое имя\n"
        "/help - Показать справку\n"
        "/d [описание] - Сгенерировать изображение"
    )
    await update.message.reply_text(help_text)

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /clear - очищает данные пользователя и выходит"""
    user_id = str(update.effective_user.id)
    async with aiosqlite.connect(db_path) as db:
        await db.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
        await db.execute('DELETE FROM context WHERE user_id = ?', (user_id,))
        await db.commit()
    await update.message.reply_text('✅ Все данные очищены. Для продолжения введите /start.')

async def clear_context(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    user = await get_user_data(user_id)
    if not user or not user['authenticated']:
        await update.message.reply_text('🔒 Сначала авторизуйтесь')
        return
    await clear_context_data(user_id)
    await update.message.reply_text('🧹 Контекст очищен.')

async def user_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать информацию о пользователе /info"""
    user_id = str(update.effective_user.id)
    user = await get_user_data(user_id)
    
    if not user or not user['authenticated']:
        await update.message.reply_text('🔒 Сначала авторизуйтесь')
        return
    
    model_name = MODELS.get(user['model'], 'Неизвестная модель')
    think_status = "ВКЛ" if user['think_mode'] else "ВЫКЛ"
    info_text = (
        f"ℹ️ Информация о пользователе:\n"
        f"Имя: {user.get('name', 'Не указано')}\n"
        f"Модель: {model_name}\n"
        f"Режим мышления: {think_status}\n"
        f"Температура генерации: {user['temperature']}\n"
        f"Размер контекста: {user.get('context_size', 21)}"
    )
    await update.message.reply_text(info_text)

async def change_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /changename [новое_имя]"""
    user_id = str(update.effective_user.id)
    user = await get_user_data(user_id)
    
    if not user or not user['authenticated']:
        await update.message.reply_text('🔒 Сначала авторизуйтесь')
        return
    
    if not context.args:
        await update.message.reply_text('📝 Формат: /changename [ваше_новое_имя]')
        return
    
    new_name = ' '.join(context.args)
    user['name'] = new_name
    await save_user_data(user_id, user)
    await update.message.reply_text(f'✅ Имя изменено на: {new_name}')

async def main() -> None:
    """Основная функция запуска бота"""
    # Инициализация базы данных
    await init_db()
    
    application = ApplicationBuilder().token(TOKEN).build()
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('switch', switch))
    application.add_handler(CommandHandler('think', set_thinking_mode))
    application.add_handler(CommandHandler('temp', set_temperature))
    application.add_handler(CommandHandler('cs', set_context_size))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(CommandHandler('d', draw))
    application.add_handler(CommandHandler('clear', clear_command))
    application.add_handler(CommandHandler('clearc', clear_context))
    application.add_handler(CommandHandler('info', user_info))
    application.add_handler(CommandHandler('changename', change_name))
    
    # Запуск бота
    await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
