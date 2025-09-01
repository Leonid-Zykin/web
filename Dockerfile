FROM python:3.10-slim

WORKDIR /app

# Копируем requirements.txt и устанавливаем Python зависимости
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Устанавливаем системные зависимости только для используемых библиотек
RUN apt-get update && \
    apt-get install -y \
        libglib2.0-0 \
        libgl1 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libgomp1 \
        sshpass \
        openssh-client && \
    rm -rf /var/lib/apt/lists/*

# Копируем код приложения
COPY . .

EXPOSE 7860

CMD ["python", "app.py"] 