FROM python:3.10-slim
SHELL ["/bin/bash", "-c"]
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y libgl1-mesa-glx libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY . .
EXPOSE 7860
CMD ["python", "app.py"] 