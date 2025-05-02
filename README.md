# 🤖 Telegram AI Chatbot with Local LLM Support

A privacy-focused Telegram bot that runs **100% locally** using open-source AI models. Supports text, voice, and image processing without sending data to external servers.

---

## 🔍 Features Overview

| Category          | Feature                          | Description                                                               |
|-------------------|----------------------------------|---------------------------------------------------------------------------|
| **Core**          | Local Execution                  | Runs entirely on your machine using Ollama                                |
|                   | User Authentication              | Password-protected access with personalized sessions                      |
| **AI Capabilities**| Model Switching                 | Choose between Gemma3 (image support) and Qwen3 (advanced reasoning)      |
|                   | Context Memory                   | Maintain conversation history (2-50 message pairs)                        |
|                   | Voice Processing                 | Transcribe voice messages using Whisper                                   |
| **Multimedia**    | Image Analysis                   | Describe images using Gemma3                                              |
|                   | Image Generation                 | Create images via Stable Diffusion integration                            |
| **Customization** | Temperature Control              | Adjust creativity level (0.0-1.0)                                         |
|                   | Thinking Modes                   | Toggle advanced reasoning mode for Qwen3                                  |
| **Security**      | Secret Management                | Store token/password in `.env` file                                       |
|                   | Private Logging                  | Optional message logging for analysis (can be disabled)                   |

---

## 🛠️ Requirements

### System Requirements
- Python 3.10+
- At least 16GB RAM (recommended for LLMs)
- Ollama running locally ([installation guide](https://ollama.ai))
- Optional: Stable Diffusion WebUI for image generation

### Required Models
```bash
ollama pull gemma3:12b
ollama pull qwen3:14b
📦 Dependencies:
pip install python-telegram-bot ollama faster-whisper pydub pillow python-dotenv aiohttp nest_asyncio
🧪 Configuration
Create .env file like this:
TOKEN=your_telegram_bot_token
PASSWORD=your_secure_password
🚀 Usage:
python telebot.py
This project uses open-source components: 

    Ollama (Apache 2.0)
    Faster-Whisper (MIT)
    Stable Diffusion (CreativeML Open RAIL++)
