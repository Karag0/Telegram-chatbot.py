import logging
import json
import os
from telegram import Update, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
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

nest_asyncio.apply()
# Загрузка переменных окружения
load_dotenv()
# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Инициализация модели распознавания речи
whisper_model = WhisperModel("base", device="cpu", compute_type="int8")

# Токен бота
TOKEN = os.getenv("TOKEN")

# Файл для сохранения данных пользователей
USER_DATA_FILE = ".user_data.json"

# Системные настройки по умолчанию
DEFAULT_SYSTEM_PROMPT = "You're a friendly helpful assistant answering in Russian"
# Пароль для доступа
PASSWORD = os.getenv("PASSWORD")  # Пароль для доступа

# Проверка наличия токена и пароля
if not TOKEN or not PASSWORD:
    raise ValueError("❌ Не заданы TOKEN или PASSWORD в .env")

# Доступные модели Ollama
MODELS = {
    "1": "qwen3:14b",
    "2": "dolphin3:8b",
    "3": "qwen3-vl:8b",  # Мультимодальная модель для работы с изображениями
}

# Базовая структура данных пользователя
DEFAULT_USER_DATA = {
    "authenticated": False,
    "model": "1",
    "think_mode": False,
    "temperature": 0.7,
    "context_size": 21,
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "name": None,
}

# Загрузка данных пользователей из файла
def load_user_data():
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Обновляем старые данные, добавляя недостающие поля
                for user_id, user_info in data.items():
                    data[user_id] = {**DEFAULT_USER_DATA, **user_info}
                return data
        except (json.JSONDecodeError, IOError) as e:
            logging.warning(f"Ошибка загрузки данных: {e}")
            return {}
    return {}

# Сохранение данных пользователей в файл
def save_user_data(data):
    try:
        with open(USER_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logging.error(f"Ошибка сохранения данных: {e}")

# Инициализация хранилища данных
user_data = load_user_data()  # Сессии пользователей
context_memory = {}  # История сообщений

def ensure_user_data(user_id):
    """Обеспечивает наличие всех необходимых полей в данных пользователя"""
    if user_id not in user_data:
        user_data[user_id] = DEFAULT_USER_DATA.copy()
        save_user_data(user_data)
    else:
        # Добавляем отсутствующие поля
        for key, value in DEFAULT_USER_DATA.items():
            if key not in user_data[user_id]:
                user_data[user_id][key] = value
        save_user_data(user_data)
    return user_data[user_id]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    user_id = str(update.effective_user.id)
    
    # Инициализация данных пользователя
    user = ensure_user_data(user_id)
    
    if user["authenticated"]:
        name = user.get("name", "пользователь")
        await update.message.reply_text(
            f"👋 С возвращением, {name}! Можете задавать вопросы."
        )
    else:
        await update.message.reply_text("🔐 Введите пароль для доступа:")

async def switch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик смены модели /switch [1/2/3]"""
    user_id = str(update.effective_user.id)
    user = ensure_user_data(user_id)
    
    if not user["authenticated"]:
        await update.message.reply_text("🔒 Сначала авторизуйтесь")
        return
        
    if not context.args:
        current_model = user["model"]
        model_name = MODELS[current_model]
        await update.message.reply_text(f"🧠 Текущая модель: {model_name}")
        return
        
    model_choice = context.args[0]
    if model_choice in MODELS:
        user["model"] = model_choice
        save_user_data(user_data)
        model_name = MODELS[model_choice]
        await update.message.reply_text(f"✅ Модель изменена на {model_name}")
    else:
        await update.message.reply_text("⚠️ Доступные модели: 1, 2 или 3")

async def set_system_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Изменение системного промта /system_prompt [текст]"""
    user_id = str(update.effective_user.id)
    user = ensure_user_data(user_id)
    
    if not user["authenticated"]:
        await update.message.reply_text("🔒 Сначала авторизуйтесь")
        return
        
    if not context.args:
        current_prompt = user["system_prompt"]
        await update.message.reply_text(
            f"📝 Текущий системный промт:\n{current_prompt}\n\n"
            f"Для изменения: /system_prompt [новый промт]"
        )
        return
        
    new_prompt = " ".join(context.args)
    user["system_prompt"] = new_prompt
    save_user_data(user_data)
    
    # Обновляем системный промт в контекстной памяти
    if user_id in context_memory and len(context_memory[user_id]) > 0:
        # Находим и обновляем системное сообщение
        for i, msg in enumerate(context_memory[user_id]):
            if msg["role"] == "system":
                context_memory[user_id][i]["content"] = new_prompt
                break
    
    await update.message.reply_text(f"✅ Системный промт обновлен:\n{new_prompt}")

async def set_thinking_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Настройка режима мышления через /think [0/1]"""
    user_id = str(update.effective_user.id)
    user = ensure_user_data(user_id)
    
    if not user["authenticated"]:
        await update.message.reply_text("🔒 Сначала авторизуйтесь")
        return
        
    if not context.args:
        mode = (
            "🧠 Мышление: ВКЛ"
            if user["think_mode"]
            else "🧠 Мышление: ВЫКЛ"
        )
        await update.message.reply_text(f"{mode}\nДля изменения: /think [0/1]")
        return
        
    mode_arg = context.args[0]
    if mode_arg == "1":
        user["think_mode"] = True
        save_user_data(user_data)
        await update.message.reply_text("🧠 Режим мышления: ВКЛ")
    elif mode_arg == "0":
        user["think_mode"] = False
        save_user_data(user_data)
        await update.message.reply_text("🧠 Режим мышления: ВЫКЛ")
    else:
        await update.message.reply_text(
            "⚠️ Неверный аргумент. Используйте:\n/think 0 - выключить\n/think 1 - включить"
        )

async def set_temperature(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Настройка температуры генерации"""
    user_id = str(update.effective_user.id)
    user = ensure_user_data(user_id)
    
    if not user["authenticated"]:
        await update.message.reply_text("🔒 Сначала авторизуйтесь")
        return
        
    if not context.args:
        temp = user["temperature"]
        await update.message.reply_text(f"🌡️ Текущая температура: {temp}")
        return
        
    try:
        temp = float(context.args[0])
        if 0 <= temp <= 1:
            user["temperature"] = temp
            save_user_data(user_data)
            await update.message.reply_text(f"🌡️ Температура установлена: {temp}")
        else:
            await update.message.reply_text("⚠️ Температура должна быть от 0 до 1")
    except ValueError:
        await update.message.reply_text("⚠️ Укажите числовое значение")

async def set_context_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Настройка размера контекстной памяти /cs [2-50]"""
    user_id = str(update.effective_user.id)
    user = ensure_user_data(user_id)
    
    if not user["authenticated"]:
        await update.message.reply_text("🔒 Сначала авторизуйтесь")
        return
        
    if not context.args:
        size = user["context_size"]
        await update.message.reply_text(f"💾 Размер контекста: {size}")
        return
        
    try:
        new_size = int(context.args[0])
        if 2 <= new_size <= 50:
            user["context_size"] = new_size
            save_user_data(user_data)
            await update.message.reply_text(
                f"✅ Размер контекста изменен на {new_size}"
            )
        else:
            await update.message.reply_text("⚠️ Допустимый диапазон: от 2 до 50")
    except ValueError:
        await update.message.reply_text("⚠️ Укажите числовое значение")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка текстовых сообщений"""
    user_id = str(update.effective_user.id)
    
    # Инициализация данных пользователя
    user = ensure_user_data(user_id)
    
    # Проверка аутентификации
    if not user["authenticated"]:
        message_text = update.message.text
        if message_text == PASSWORD:
            user["authenticated"] = True
            user["name"] = None  # Флаг для запроса имени
            context_memory[user_id] = [{"role": "system", "content": user["system_prompt"]}]
            save_user_data(user_data)
            await update.message.reply_text("✅ Пароль принят!\n📝 Введите ваше имя:")
        else:
            await update.message.reply_text("❌ Неверный пароль")
        return
        
    # Обработка имени
    if user.get("name") is None:
        user["name"] = update.message.text
        save_user_data(user_data)
        await update.message.reply_text(
            f"👋 Рад знакомству, {user['name']}! Теперь вы можете задавать вопросы или просто общаться со мной!"
        )
        return
        
    # Обработка сообщения
    message_text = context.user_data.get("voice_text") or update.message.text
    
    # Подготовка контекста
    if user_id not in context_memory:
        context_memory[user_id] = [{"role": "system", "content": user["system_prompt"]}]
        
    # Добавление метки мышления для Qwen3
    if user["model"] == "1":  # Qwen3
        if user["think_mode"]:
            message_text = f"[THINK] {message_text}"
        else:
            message_text = f"[NO_THINK] {message_text}"
            
    # Обновление контекста
    context_memory[user_id].append({"role": "user", "content": message_text})
    
    # Ограничение длины контекста через настройку пользователя
    max_context = user.get("context_size", 21)
    while len(context_memory[user_id]) > max_context:
        context_memory[user_id].pop(1)
        
    try:
        # Получение ответа от модели
        response = ollama.chat(
            model=MODELS[user["model"]],
            messages=context_memory[user_id],
            options={"temperature": user["temperature"]},
        )
        
        # Добавление ответа в контекст
        context_memory[user_id].append(
            {"role": "assistant", "content": response["message"]["content"]}
        )
        
        # Отправка ответа пользователю
        await update.message.reply_text(response["message"]["content"])
    except Exception as e:
        logging.error(f"Ошибка Ollama: {e}")
        await update.message.reply_text("⚠️ Ошибка генерации ответа")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка голосовых сообщений"""
    user_id = str(update.effective_user.id)
    user = ensure_user_data(user_id)
    
    if not user["authenticated"]:
        await update.message.reply_text("Введите пароль для доступа!")
        return
        
    try:
        # Скачивание и конвертация аудио
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_ogg:
            await file.download_to_drive(temp_ogg.name)
            audio = AudioSegment.from_ogg(temp_ogg.name)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
                audio.export(
                    temp_wav.name, format="wav", parameters=["-ac", "1", "-ar", "16000"]
                )
                # Распознавание речи
                segments, _ = whisper_model.transcribe(
                    temp_wav.name, language="ru", beam_size=5, vad_filter=True
                )
                text = " ".join([segment.text for segment in segments])
                
        # Удаление временных файлов
        os.unlink(temp_ogg.name)
        os.unlink(temp_wav.name)
        
        if text.strip():
            # Отправка транскрипта и обработка текста
            await update.message.reply_text(f"📝 Транскрипт:\n{text}")
            context.user_data["voice_text"] = text
            await handle_message(update, context)
            del context.user_data["voice_text"]
        else:
            await update.message.reply_text("Не удалось распознать речь.")
    except Exception as e:
        logging.error(f"Ошибка обработки голоса: {e}")
        await update.message.reply_text(f"Произошла ошибка: {str(e)[:100]}")

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка изображений с использованием qwen3-vl:8b или текущей модели"""
    user_id = str(update.effective_user.id)
    user = ensure_user_data(user_id)
    
    if not user["authenticated"]:
        await update.message.reply_text("Введите пароль для доступа!")
        return
        
    try:
        # Получение фото
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        
        # Конвертация в base64
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        
        # Получение пользовательского промта (если есть текст вместе с фото)
        user_prompt = update.message.caption or "Что изображено на этой картинке? Опиши подробно."
        
        # Получаем данные пользователя
        model_name = MODELS[user["model"]]
        
        # Если пользователь не использует мультимодальную модель, переключаемся на qwen3-vl
        if user["model"] != "3":
            model_name = MODELS["3"]  # Используем qwen3-vl для обработки изображений
            await update.message.reply_text("🔄 Для обработки изображения используется qwen3-vl:8b")
        
        # Подготовка контекста
        if user_id not in context_memory:
            context_memory[user_id] = [{"role": "system", "content": user["system_prompt"]}]
        
        # Формирование запроса с изображением (используем chat API с images)
        messages = context_memory[user_id].copy()
        messages.append({
            "role": "user",
            "content": user_prompt,
            "images": [image_base64]
        })
        
        # Получение ответа от Ollama
        response = ollama.chat(
            model=model_name,
            messages=messages,
            options={"temperature": user["temperature"]},
        )
        
        # Добавляем ответ в контекстную память (без изображения)
        context_memory[user_id].append({"role": "user", "content": user_prompt})
        context_memory[user_id].append(
            {"role": "assistant", "content": response["message"]["content"]}
        )
        
        # Ограничение длины контекста
        max_context = user.get("context_size", 21)
        while len(context_memory[user_id]) > max_context:
            context_memory[user_id].pop(1)
        
        await update.message.reply_text(
            f"🖼️ Описание изображения:\n{response['message']['content']}"
        )
    except Exception as e:
        logging.error(f"Ошибка обработки изображения: {e}")
        await update.message.reply_text(f"Не удалось обработать изображение: {str(e)[:100]}")

async def draw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Генерация изображений через Stable Diffusion"""
    user_id = str(update.effective_user.id)
    user = ensure_user_data(user_id)
    
    logging.info(f"Draw command from {user_id}")
    if not user["authenticated"]:
        await update.message.reply_text("🔒 Требуется авторизация через /start")
        return
        
    if not context.args:
        await update.message.reply_text("📝 Формат: /d [описание изображения]")
        return
        
    prompt = " ".join(context.args)
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
        },
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            # Проверка доступности моделей
            async with session.get(
                "http://localhost:7860/sdapi/v1/sd-models"
            ) as model_check:
                if model_check.status != 200:
                    await update.message.reply_text("⚠️ Модель SD не загружена")
                    return
                    
            # Основной запрос
            async with session.post(
                "http://localhost:7860/sdapi/v1/txt2img", json=payload, timeout=300
            ) as response:
                logging.info(f"API Response: {response.status}")
                if response.status != 200:
                    error = await response.text()
                    logging.error(f"API Error: {error}")
                    await update.message.reply_text(f"❌ Ошибка API: {response.status}")
                    return
                    
                data = await response.json()
                if not data.get("images"):
                    await update.message.reply_text("🖼️ Пустой ответ от генератора")
                    return
                    
                image_data = base64.b64decode(data["images"][0])
                with io.BytesIO() as img_buffer:
                    Image.open(io.BytesIO(image_data)).save(img_buffer, format="PNG")
                    img_buffer.seek(0)
                    await update.message.reply_photo(
                        photo=InputFile(img_buffer, filename="art.png"),
                        caption=f"🎨 {prompt[:100]}...",
                    )
                    logging.info("Изображение успешно отправлено")
    except asyncio.TimeoutError:
        logging.warning("Таймаут генерации")
        await update.message.reply_text("⏳ Слишком долгая генерация, попробуйте позже")
    except Exception as e:
        logging.error(f"Critical Draw Error: {str(e)}", exc_info=True)
        await update.message.reply_text("🔥 Ошибка в процессе генерации")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик помощи /help"""
    help_text = (
        "Доступные команды:\n"
        "/start - Начать работу (требуется пароль)\n"
        "/switch [1/2/3] - Сменить модель (1-qwen3:14b, 2-dolphin3:8b, 3-qwen3-vl:8b)\n"
        "/system_prompt [текст] - Изменить системный промт\n"
        "/think [0/1] - Включить/выключить режим мышления\n"
        "/temp [0-1] - Установить температуру генерации\n"
        "/cs [2-50] - Установить размер контекстной памяти\n"
        "/clear - Очистить все данные и выйти\n"
        "/clearc - Очистить контекст диалога\n"
        "/info - Показать информацию о себе\n"
        "/changename [новое_имя] - Изменить ваше отображаемое имя\n"
        "/help - Показать справку\n"
        "/d [описание] - Сгенерировать изображение\n\n"
        "Также вы можете:\n"
        "• Отправлять текстовые сообщения для общения\n"
        "• Отправлять голосовые сообщения для распознавания речи\n"
        "• Отправлять изображения для их описания (используется qwen3-vl:8b)"
    )
    await update.message.reply_text(help_text)

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /clear - очищает данные пользователя и выходит"""
    user_id = str(update.effective_user.id)
    
    # Удаление данных пользователя
    if user_id in user_data:
        del user_data[user_id]
        save_user_data(user_data)
        
    # Очистка контекста диалога
    if user_id in context_memory:
        del context_memory[user_id]
        
    await update.message.reply_text(
        "✅ Все данные очищены. Для продолжения введите /start."
    )

async def clear_context(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Очистка контекста диалога /clearc"""
    user_id = str(update.effective_user.id)
    user = ensure_user_data(user_id)
    
    if not user["authenticated"]:
        await update.message.reply_text("🔒 Сначала авторизуйтесь")
        return
        
    if user_id in context_memory:
        # Оставляем только системный промт
        context_memory[user_id] = [{"role": "system", "content": user["system_prompt"]}]
        
    await update.message.reply_text("🧹 Контекст очищен.")

async def user_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать информацию о пользователе /info"""
    user_id = str(update.effective_user.id)
    user = ensure_user_data(user_id)
    
    if not user["authenticated"]:
        await update.message.reply_text("🔒 Сначала авторизуйтесь")
        return
        
    model_name = MODELS.get(user["model"], "Неизвестная модель")
    think_status = "ВКЛ" if user["think_mode"] else "ВЫКЛ"
    system_prompt_preview = user["system_prompt"][:50] + "..." if len(user["system_prompt"]) > 50 else user["system_prompt"]
    info_text = (
        f"ℹ️ Информация о пользователе:\n"
        f"Имя: {user.get('name', 'Не указано')}\n"
        f"Модель: {model_name}\n"
        f"Режим мышления: {think_status}\n"
        f"Температура генерации: {user['temperature']}\n"
        f"Размер контекста: {user.get('context_size', 21)}\n"
        f"Системный промт: {system_prompt_preview}"
    )
    await update.message.reply_text(info_text)

async def change_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /changename [новое_имя]"""
    user_id = str(update.effective_user.id)
    user = ensure_user_data(user_id)
    
    # Проверка авторизации
    if not user["authenticated"]:
        await update.message.reply_text("🔒 Сначала авторизуйтесь")
        return
        
    # Проверка наличия аргумента
    if not context.args:
        await update.message.reply_text("📝 Формат: /changename [ваше_новое_имя]")
        return
        
    new_name = " ".join(context.args)
    user["name"] = new_name
    save_user_data(user_data)
    await update.message.reply_text(f"✅ Имя изменено на: {new_name}")

async def analyze_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Анализ изображения с пользовательским промтом /analyze [промт]"""
    user_id = str(update.effective_user.id)
    user = ensure_user_data(user_id)
    
    if not user["authenticated"]:
        await update.message.reply_text("🔒 Сначала авторизуйтесь")
        return
    
    # Проверяем, есть ли изображение в сообщении
    if not update.message.photo:
        await update.message.reply_text("📷 Пожалуйста, отправьте изображение вместе с командой /analyze")
        return
    
    # Получаем промт из аргументов
    user_prompt = " ".join(context.args) if context.args else "Опиши это изображение подробно"
    
    try:
        # Получение фото
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        
        # Конвертация в base64
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        
        # Используем qwen3-vl для анализа
        model_name = MODELS["3"]
        
        # Формирование запроса с изображением
        messages = [
            {"role": "system", "content": "Ты - помощник, который анализирует и описывает изображения."},
            {
                "role": "user",
                "content": user_prompt,
                "images": [image_base64]
            }
        ]
        
        # Получение ответа от Ollama
        response = ollama.chat(
            model=model_name,
            messages=messages,
        )
        
        await update.message.reply_text(
            f"🔍 Анализ изображения:\n{response['message']['content']}"
        )
    except Exception as e:
        logging.error(f"Ошибка анализа изображения: {e}")
        await update.message.reply_text(f"Не удалось проанализировать изображение: {str(e)[:100]}")

async def list_models(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать список доступных моделей /models"""
    user_id = str(update.effective_user.id)
    user = ensure_user_data(user_id)
    
    if not user["authenticated"]:
        await update.message.reply_text("🔒 Сначала авторизуйтесь")
        return
    
    current_model = MODELS[user["model"]]
    
    models_text = "📚 Доступные модели:\n"
    for key, model in MODELS.items():
        prefix = "✅ " if user["model"] == key else "   "
        models_text += f"{prefix}{key}. {model}\n"
    
    models_text += f"\nТекущая модель: {current_model}"
    await update.message.reply_text(models_text)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик ошибок"""
    logging.error(f"Exception while handling an update: {context.error}")
    
    # Логируем ошибку
    try:
        raise context.error
    except Exception as e:
        logging.error(f"Error details: {e}", exc_info=True)

async def main() -> None:
    """Основная функция запуска бота"""
    application = ApplicationBuilder().token(TOKEN).build()
    
    # Добавляем обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("switch", switch))
    application.add_handler(CommandHandler("system_prompt", set_system_prompt))
    application.add_handler(CommandHandler("think", set_thinking_mode))
    application.add_handler(CommandHandler("temp", set_temperature))
    application.add_handler(CommandHandler("cs", set_context_size))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("models", list_models))
    application.add_handler(CommandHandler("analyze", analyze_image))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(CommandHandler("d", draw))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("clearc", clear_context))
    application.add_handler(CommandHandler("info", user_info))
    application.add_handler(CommandHandler("changename", change_name))
    
    # Запуск бота
    await application.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
