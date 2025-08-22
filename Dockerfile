# Используем официальный образ Python на Alpine
FROM python:3.12-alpine

# Устанавливаем системные зависимости
RUN apk update && apk add --no-cache \
    build-base \
    curl \
    ffmpeg \
    gcc \
    g++ \
    git \
    libc-dev \
    libffi-dev \
    libsndfile-dev \
    make \
    musl-dev \
    openssl-dev \
    portaudio-dev \
    rustup \
    cargo \
    bash

# Устанавливаем UV
ENV PATH="/root/.cargo/bin:${PATH}"
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Устанавливаем Ollama
RUN curl -fsSL https://ollama.com/install.sh | sh

# Создаем рабочую директорию
WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN uv pip install -r requirements.txt

# Копируем исходный код
COPY . .

# Создаем директорию для данных пользователей
RUN mkdir -p /app/data

# Запускаем Ollama в фоне и запускаем бота
CMD ollama serve & \
    sleep 10 && \
    ollama pull qwen3:14b && \
    ollama pull gemma3:12b && \
    python telebot.py
