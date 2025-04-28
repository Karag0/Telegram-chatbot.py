import logging
from telegram import Update 
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes 
from telegram import Update, InputFile
import ollama
import nest_asyncio
from faster_whisper import WhisperModel
from pydub import AudioSegment
from PIL import Image
import io
import base64
import tempfile
import os
import aiohttp
import requests
nest_asyncio.apply()  # Фикс для работы asyncio в Jupyter/некоторых средах

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Инициализация модели распознавания речи
whisper_model = WhisperModel("base", device="cpu", compute_type="int8")

# Токен бота (замените на ваш реальный токен)
TOKEN = 'x'

# Хранилище данных пользователей
user_ids = {}  # Сессии пользователей
context_memory = {}  # История сообщений

# Системные настройки
system_prompt = "ваш системный промт"
PASSWORD = "x"  # Пароль для доступа

# Доступные модели Ollama
models = {
    'model1': 'gemma3:12b',  # Поддерживает обработку изображений [[3]][[8]]
    'model2': 'qwq:latest'
}
current_model = 'model1'  # Модель по умолчанию

# ================================
# ОСНОВНЫЕ ОБРАБОТЧИКИ КОМАНД
# ================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    await update.message.reply_text('Привет! Я исскуственный интеллект. Введите пароль для доступа:')

async def switch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик смены модели /switch"""
    global current_model
    if context.args:
        model_choice = context.args[0]
        if model_choice in ['1', '2']:
            current_model = f'model{model_choice}'
            await update.message.reply_text(f'Модель изменена на {models[current_model]}')
        else:
            await update.message.reply_text('Доступные модели: 1 или 2')
    else:
        await update.message.reply_text('Использование: /switch [1/2]')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик помощи /help"""
    help_text = (
        "Доступные команды:\n"
        "/start - Начать работу (требуется пароль)\n"
        "/switch [1/2] - Сменить модель\n"
        "/help - Показать справку\n\n"
        "После авторизации:\n"
        "• Отправка текстовых сообщений\n"
        "• Распознавание голосовых сообщений (RU)\n"
        "• Анализ изображений (Gemma3) [[3]]\n"
        "• Сохранение контекста разговора"
    )
    await update.message.reply_text(help_text)

# ================================
# ОБРАБОТЧИКИ СООБЩЕНИЙ
# ================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка текстовых сообщений"""
    user_id = update.effective_user.id
    
    # Инициализация данных пользователя
    if user_id not in user_ids:
        user_ids[user_id] = {'authenticated': False}
        context_memory[user_id] = []

    user_data = user_ids[user_id]
    message_text = context.user_data.get('voice_text') or update.message.text

    # Проверка аутентификации
    if not user_data['authenticated']:
        if message_text == PASSWORD:
            user_data['authenticated'] = True
            context_memory[user_id].append({'role': 'system', 'content': system_prompt})
            await update.message.reply_text('Пароль принят! Можете задавать вопросы.')
        else:
            await update.message.reply_text('Неверный пароль. Попробуйте снова.')
        return

    # Добавление сообщения в контекст
    context_messages = context_memory[user_id]
    context_messages.append({'role': 'user', 'content': message_text})
    context_memory[user_id] = context_messages[-8:]  # Сохраняем последние 8 сообщений

    try:
        # Получение ответа от Ollama
        response = ollama.chat(
            model=models[current_model],
            messages=context_memory[user_id]
        )
        await update.message.reply_text(response['message']['content'])
    except Exception as e:
        logging.error(f"Ошибка Ollama: {e}")
        await update.message.reply_text('Ошибка генерации ответа. Проверьте логи.')

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка голосовых сообщений"""
    user_id = update.effective_user.id
    
    # Проверка аутентификации
    if not user_ids.get(user_id, {}).get('authenticated', False):
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
            context.user_data['voice_text'] = text  # Передаем текст через контекст
            await handle_message(update, context)
            del context.user_data['voice_text']  # Очистка после использования
        else:
            await update.message.reply_text("Не удалось распознать речь.")

    except Exception as e:
        logging.error(f"Ошибка обработки голоса: {e}")
        await update.message.reply_text(f"Произошла ошибка: {str(e)[:100]}")

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка изображений с использованием Gemma3 [[3]][[8]]"""
    user_id = update.effective_user.id
    
    # Проверка аутентификации
    if not user_ids.get(user_id, {}).get('authenticated', False):
        await update.message.reply_text('Введите пароль для доступа!')
        return

    try:
        # Получение фото
        photo = update.message.photo[-1]  # Самое качественное изображение
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        
        # Конвертация в base64 для SigLIP-энкодера [[8]]
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        
        # Формирование multimodal-запроса
        context_messages = context_memory.get(user_id, [])
        context_messages.append({
            'role': 'user',
            'content': [
                {'type': 'image', 'data': image_base64},
                {'type': 'text', 'text': 'Опиши это изображение'}
            ]
        })
        
        # Получение ответа от Ollama
        response = ollama.chat(
            model=models[current_model],
            messages=context_messages,
            options={'temperature': 0.7}
        )
        
        await update.message.reply_text(f"🖼️ Описание изображения:\n{response['message']['content']}")
        
    except Exception as e:
        logging.error(f"Ошибка обработки изображения: {e}")
        await update.message.reply_text("Не удалось обработать изображение")
async def draw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    logging.info(f"Draw command from {user_id}")

    if user_id not in user_ids or not user_ids[user_id]['authenticated']:
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
# ================================
# ЗАПУСК БОТА
# ================================

async def main() -> None:
    """Основная функция запуска бота"""
    application = ApplicationBuilder().token(TOKEN).build()

    # Регистрация обработчиков
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('switch', switch))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))  # Новый обработчик
    application.add_handler(CommandHandler('d', draw))
    # Запуск бота
    await application.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
