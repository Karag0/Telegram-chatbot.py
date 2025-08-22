# Используем официальный образ Arch Linux
FROM archlinux:latest

RUN pacman -Syu --noconfirm && \
    pacman -S --noconfirm \
    ollama \
    python-uv \
    ffmpeg \
    bash \
    python \
    base-devel

# Рабочая директория
WORKDIR /app

# Копируем requirements.txt
COPY requirements.txt .

# Создаём виртуальное окружение через uv
# Используем явный путь к python3.12 (гарантированно найдёт нужную версию)
RUN uv venv .venv --python python3.12

# Устанавливаем зависимости через uv ВНУТРИ venv
# Ключевой момент: --python указывает на созданное окружение
RUN uv pip install --python .venv -r requirements.txt

# Удаляем временные зависимости для компиляции
RUN pacman -Rns --noconfirm base-devel --noconfirm

# Копируем исходный код
COPY . .

# Создаём директории для данных
RUN mkdir -p /app/data

# Запускаем Ollama и бота через uv run
# uv автоматически использует .venv из текущей директории
CMD [ "bash", "-c", "ollama serve & uv run telebot.py" ]
