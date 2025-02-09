import logging
from telegram import Update 
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
import ollama
import nest_asyncio

nest_asyncio.apply()

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Token you received from @BotFather
TOKEN = 'xxx'  # Replace with your actual token

# Dictionary to store user data
user_ids = {}
context_memory = {}

# System message
# Insert prompt
system_prompt = ""
# Password
PASSWORD = "xxx"

# Dictionary of models Insert your models
models = {
    'model1': '',
    'model2': '' 
}

# Variable to store the current model
current_model = 'model1'

# Function to handle the /start command
async def start(update: Update, context) -> None:
    await update.message.reply_text('Hello! I am a chat bot, your friendly assistant. Please enter the password to continue:')

# Function to handle the /switch command
async def switch(update: Update, context) -> None:
    global current_model
    if context.args:
        model_choice = context.args[0]
        if model_choice == '1':
            current_model = 'model1'
            await update.message.reply_text('Model switched to model1.')
        elif model_choice == '2':
            current_model = 'model2'
            await update.message.reply_text('Model switched to model2.')
        else:
            await update.message.reply_text('Invalid model. Available models: model1, model2.')
    else:
        await update.message.reply_text('Please specify a model to switch to. Example: /switch 1')
# Function to handle regular messages
async def handle_message(update: Update, context):
    user_id = update.effective_user.id
    if user_id not in user_ids:
        user_ids[user_id] = {'last_message': None, 'preferences': {}, 'authenticated': False}
        context_memory[user_id] = []

    message_text = update.message.text
    user_data = user_ids[user_id]

    # Check if the user is authenticated
    if not user_data['authenticated']:
        if message_text == PASSWORD:
            user_data['authenticated'] = True
            await update.message.reply_text('Password accepted! You can now chat with me.')
            # Add system message to context
            context_memory[user_id].append({'role': 'system', 'content': system_prompt})
        else:
            await update.message.reply_text('Incorrect password. Please try again.')
            return  # Do not process other messages until the correct password is entered

    context_messages = context_memory[user_id]

    # Add the user's new message to the context
    context_messages.append({'role': 'user', 'content': message_text})

    # Limit the context history to the last 8 messages
    context_memory[user_id] = context_messages[-8:]

    try:
        # Call the ollama.chat function with the context messages
        response = ollama.chat(model=models[current_model], messages=context_memory[user_id])
        # Send the response to the user
        await update.message.reply_text(response['message']['content'])
    except Exception as e:
        logging.error(f"Error while getting response from ollama: {e}")
        await update.message.reply_text('An error occurred, please try again later.')

# Main function
async def main() -> None:
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('switch', switch))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await application.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())