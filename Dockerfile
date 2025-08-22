# Используем официальный образ Arch Linux
FROM archlinux:latest

# Обновляем систему и устанавливаем зависимости
RUN pacman -Syu --noconfirm && \
    pacman -S --noconfirm \
    ollama \
    python-uv \  # Пакет называется именно так в Arch
ffmpeg \
    bash \
    python \     # Python 3.12 по умолчанию в Arch
base-devel   # Для компиляции пакетов (удалится позже)

# Рабочая директория
WORKDIR /app

# Копируем requirements.txt
COPY requirements.txt .

# Создаём виртуальное окружение через uv
# В Arch python = Python 3.12, поэтому используем просто "python"
RUN uv venv .venv --python python3.12

# Активируем venv и устанавливаем зависимости
# (без --system, так как работаем внутри venv)
RUN ./.venv/bin/activate
RUN uv pip install -r requirements.txt

# Копируем исходный код
COPY . .

# Создаём директории для данных
RUN mkdir -p /app/data

# Запускаем Ollama и бота
# Важно: используем exec-форму для корректной обработки сигналов
CMD [ "bash", "-c", "ollama serve & python telebot.py" ]
