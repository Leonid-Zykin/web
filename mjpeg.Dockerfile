FROM python:3.10-slim

WORKDIR /app

# Минимальные зависимости для OpenCV
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY mjpeg_server.py ./
RUN pip install flask opencv-python-headless

EXPOSE 5000

CMD ["python", "mjpeg_server.py"] 