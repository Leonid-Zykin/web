FROM python:3.10-slim

WORKDIR /app

COPY mjpeg_server.py ./
RUN pip install flask opencv-python-headless

EXPOSE 5000

CMD ["python", "mjpeg_server.py"] 