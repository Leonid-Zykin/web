FROM python:3.10-slim

WORKDIR /app

# Зависимости для OpenCV
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libgomp1 \
    libgl1-mesa-dri \
    libgl1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgthread-2.0-0 \
    libgtk-3-0 \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    && rm -rf /var/lib/apt/lists/*

COPY mjpeg_server.py ./
COPY requirements.txt ./
RUN pip install -r requirements.txt

EXPOSE 5000

CMD ["python", "mjpeg_server.py"] 