# Telegram-chatbot.py
A Telegram AI Chatbot built with Python, supporting user authentication, model switching, and conversational context memory for seamless interactions.
Below is an example of a README.md file you might include in your GitHub repository. You can adjust and expand it as needed.
Telegram Chatbot

Telegram Chatbot is a friendly AI assistant built using Python, the Telegram Bot API, and the Ollama API. Users can interact with the bot after authentication using a predefined password. The chatbot supports switching between two different AI models and maintains a short conversation context to facilitate more coherent interactions.
Key Features

    User Authentication:

    The bot requires users to enter a predefined password (e.g., "kusach2077") to authenticate before engaging in conversation. This helps keep interactions secure and controlled.

    Multiple AI Model Support:

    The script allows switching between two AI models using the /switch command.
        Model 1: 
        Model 2: l
        Users can switch models by sending /switch 1 or /switch 2.

    Contextual Conversation Memory:

    The bot maintains a context of the last eight messages (including system and user messages) to improve conversational coherence.

    Telegram Integration:

    Built using the python-telegram-bot library, the bot listens for and responds to user commands and messages directly in Telegram.

    Error Handling:

    The bot is designed to catch and log errors during calls to external APIs (in this case, the Ollama API), and notifies the user if an issue occurs.

Requirements

    Python 3.7 or higher
    Telegram Bot API token (from BotFather on Telegram)
    Required Python libraries:
        python-telegram-bot
        ollama (or the relevant API client for your AI service)
        nest_asyncio
        logging (standard library)

You can install the required packages using pip:

Code

pip install python-telegram-bot nest_asyncio ollama

Setup and Installation

    Create a new bot using BotFather on Telegram to obtain your bot's API token.
    Replace the placeholder token in the script with your actual token:

python

TOKEN = 'YOUR_TELEGRAM_BOT_API_TOKEN'

(Optional) Adjust the model endpoints and the system prompt depending on your AI service or desired personality.
Run the script:

bash

    python your_script_name.py

Commands

    /start

    Starts the conversation and prompts the user to enter the password.

    /switch 1 or /switch 2

    Switches between the two available AI models.

    Regular text messages

    Processed as conversation prompts after successful authentication.

Customization

    System Prompt:

    The system_prompt variable sets the bot's initial behavior and context. Modify it to change the personality or behavior of Marco O1.

    Context Length:

    Currently, the conversation context is limited to the last eight messages. Adjust the slice ([-8:]) as needed.

    Model Management:

    Change or expand the models dictionary to support additional AI models if required.

Contributing

Pull requests and issues are welcome! If you have suggestions or improvements, feel free to fork the repository and submit a pull request.
License

This project is licensed under the GNU3 License – see the LICENSE file for details.

Feel free to modify any section to better suit your project’s needs. Happy coding!
