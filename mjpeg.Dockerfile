FROM python:3.10-slim

WORKDIR /app

# Установка системных зависимостей для OpenCV
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgstreamer1.0-0 \
    libgstreamer-plugins-base1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY mjpeg_server.py ./
RUN pip install flask opencv-python-headless

EXPOSE 5000

CMD ["python", "mjpeg_server.py"] 