FROM python:3.12-alpine

# Добавляем репозитории community
RUN echo "http://dl-cdn.alpinelinux.org/alpine/edge/community" >> /etc/apk/repositories

# Обновляем и устанавливаем системные зависимости
RUN apk update && apk upgrade && \
    apk add --no-cache \
    ollama \
    uv \
    ffmpeg \
    bash

# Устанавливаем дополнительные зависимости для Python пакетов
RUN apk add --no-cache --virtual .build-deps \
    build-base \
    python3-dev

# Рабочая директория
WORKDIR /app

# Копируем и устанавливаем Python зависимости
COPY requirements.txt .
RUN uv pip install -r requirements.txt

# Удаляем временные зависимости для сборки
RUN apk del .build-deps

# Копируем исходный код
COPY . .

# Создаем директории для данных
RUN mkdir -p /app/data


# Запускаем Ollama и бота параллельно
CMD bash -c "ollama serve & python telebot.py"
