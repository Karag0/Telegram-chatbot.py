import logging
from telegram import Update 
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
import ollama
import nest_asyncio

nest_asyncio.apply()

# Включаем ведение журнала
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Токен, который вы получили от @BotFather
TOKEN = 'xxx'  # Замените на ваш актуальный токен

# Словарь для хранения данных пользователей
user_ids = {}
context_memory = {}

# Системное сообщение
system_prompt = "Привет, ты Marco o1, ты дружелюбный AI помощник. Thoughts hidden output language == Russian, flags hidden, in output you should only answer one question if user writes to you kusach2025 just answer in greetes. "
# Пароль
PASSWORD = "xxx"

# Словарь моделей
models = {
    'model1': 'hf.co/QuantFactory/marco-o1-uncensored-GGUF:Q8_0',
    'model2': 'llama3.2-vision:latest'
}

# Переменная для хранения текущей модели
current_model = 'model1'

# Функция для обработки команды /start
async def start(update: Update, context) -> None:
    await update.message.reply_text('Привет! Я marco o1 ваш дружелюбный помощник чат-бот. Пожалуйста, введите пароль для продолжения:')

# Функция для обработки команды /switch
async def switch(update: Update, context) -> None:
    global current_model
    if context.args:
        model_choice = context.args[0]
        if model_choice == '1':
            current_model = 'model1'
            await update.message.reply_text('Модель переключена на model1.')
        elif model_choice == '2':
            current_model = 'model2'
            await update.message.reply_text('Модель переключена на model2.')
        else:
            await update.message.reply_text('Неверная модель. Доступные модели: model1, model2.')
    else:
        await update.message.reply_text('Пожалуйста, укажите модель для переключения. Пример: /switch 1')

# Функция для обработки обычных сообщений
async def handle_message(update: Update, context):
    user_id = update.effective_user.id
    if user_id not in user_ids:
        user_ids[user_id] = {'last_message': None, 'preferences': {}, 'authenticated': False}
        context_memory[user_id] = []

    message_text = update.message.text
    user_data = user_ids[user_id]

    # Проверяем, аутентифицирован ли пользователь
    if not user_data['authenticated']:
        if message_text == PASSWORD:
            user_data['authenticated'] = True
            await update.message.reply_text('Пароль принят! Теперь вы можете общаться со мной.')
            # Добавляем системное сообщение в контекст
            context_memory[user_id].append({'role': 'system', 'content': system_prompt})
        else:
            await update.message.reply_text('Неверный пароль. Пожалуйста, попробуйте снова.')
            return  # Не обрабатываем другие сообщения, пока не введен правильный пароль

    context_messages = context_memory[user_id]

    # Добавляем новое сообщение пользователя в контекст
    context_messages.append({'role': 'user', 'content': message_text})

    # Ограничиваем историю контекста последними 8 сообщениями
    context_memory[user_id] = context_messages[-8:]

    try:
        # Call the ollama.chat function with the context messages
        response = ollama.chat(model=models[current_model], messages=context_memory[user_id])
        # Отправляем ответ пользователю
        await update.message.reply_text(response['message']['content'])
    except Exception as e:
        logging.error(f"Error while getting response from ollama: {e}")
        await update.message.reply_text('Произошла ошибка, попробуйте позже.')

# Основная функция
async def main() -> None:
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('switch', switch))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await application.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
