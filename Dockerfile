# Используем официальный образ Arch Linux
FROM archlinux:latest

RUN pacman -Syu --noconfirm && \
    pacman -S --noconfirm \
    ollama \
    uv \
    ffmpeg \
    bash \
    python \
    base-devel

# Рабочая директория
WORKDIR /app

# Копируем lock файл
COPY uv.lock .
COPY pyproject.toml .
# Создаём виртуальное окружение через uv
RUN uv sync --locked

# Копируем исходный код
COPY . .

# Создаём директории для данных
RUN mkdir -p /app/data

# Запускаем Ollama и бота через uv run
# uv автоматически использует .venv из текущей директории
CMD [ "bash", "-c", "ollama serve & ollama pull qwen3:14b & ollama pull gemma3:12b uv run telebot.py" ]
