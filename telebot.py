import logging
from telegram import Update 
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import ollama
import nest_asyncio
from faster_whisper import WhisperModel
from pydub import AudioSegment
import tempfile
import os

nest_asyncio.apply()  # Фикс для работы asyncio в Jupyter/некоторых средах

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Инициализация модели распознавания речи
whisper_model = WhisperModel("base", device="cpu", compute_type="int8")

# Токен бота (замените на ваш реальный токен)
TOKEN = ''

# Хранилище данных пользователей
user_ids = {}  # Сессии пользователей
context_memory = {}  # История сообщений

# Системные настройки
system_prompt = "Youre a friendly helpful assistant answering in Russian"
PASSWORD = ""  # Пароль для доступа

# Доступные модели Ollama
models = {
    'model1': 'gemma3:12b',
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
    message_text = context.user_data.get('voice_text') or update.message.text  # Получаем текст из голоса или сообщения

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

    # Запуск бота
    await application.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
