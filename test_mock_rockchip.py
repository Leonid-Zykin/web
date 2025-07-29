#!/usr/bin/env python3
"""
Мок-сервер для имитации Rockchip устройства
Запускается на localhost и имитирует основные функции
"""

import socket
import threading
import time
import json
import yaml
import os
from datetime import datetime
import subprocess
import tempfile

class MockRockchipServer:
    def __init__(self, host='0.0.0.0', port=8008):
        self.host = host
        self.port = port
        self.alarms = []
        self.config = {}
        self.logs = []
        self.running = False
        
    def load_config(self):
        """Загружает конфиг из файла"""
        config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
    
    def save_config(self, config_data):
        """Сохраняет конфиг в файл"""
        config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, allow_unicode=True)
        self.config = config_data
        print(f"[MOCK] Config saved: {config_data}")
    
    def add_alarm(self, alarm_data):
        """Добавляет тревогу в лог"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        alarm_entry = {
            'timestamp': timestamp,
            'data': alarm_data
        }
        self.alarms.append(alarm_entry)
        self.logs.append(f"[{timestamp}] ALARM: {alarm_data}")
        print(f"[MOCK] Alarm received: {alarm_data}")
    
    def get_logs(self):
        """Возвращает логи тревог"""
        return self.logs
    
    def start_udp_server(self):
        """Запускает UDP сервер для приема тревог"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.host, self.port))
        print(f"[MOCK] UDP server started on {self.host}:{self.port}")
        
        while self.running:
            try:
                data, addr = sock.recvfrom(1024)
                alarm_data = json.loads(data.decode('utf-8'))
                self.add_alarm(alarm_data)
            except Exception as e:
                print(f"[MOCK] UDP error: {e}")
        
        sock.close()
    
    def start_http_server(self):
        """Запускает HTTP сервер для API"""
        from http.server import HTTPServer, BaseHTTPRequestHandler
        import urllib.parse
        
        class MockHandler(BaseHTTPRequestHandler):
            def __init__(self, *args, mock_server=None, **kwargs):
                self.mock_server = mock_server
                super().__init__(*args, **kwargs)
            
            def do_GET(self):
                if self.path == '/logs':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    response = {'logs': self.mock_server.get_logs()}
                    self.wfile.write(json.dumps(response).encode())
                else:
                    self.send_response(404)
                    self.end_headers()
            
            def do_POST(self):
                if self.path == '/config':
                    content_length = int(self.headers['Content-Length'])
                    post_data = self.rfile.read(content_length)
                    config_data = json.loads(post_data.decode('utf-8'))
                    self.mock_server.save_config(config_data)
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    response = {'status': 'success', 'message': 'Config updated'}
                    self.wfile.write(json.dumps(response).encode())
                else:
                    self.send_response(404)
                    self.end_headers()
        
        # Создаем кастомный handler
        def handler_factory(mock_server):
            def create_handler(*args, **kwargs):
                return MockHandler(*args, mock_server=mock_server, **kwargs)
            return create_handler
        
        server = HTTPServer(('0.0.0.0', 8000), handler_factory(self))
        print(f"[MOCK] HTTP server started on 0.0.0.0:8000")
        
        while self.running:
            server.handle_request()
        
        server.server_close()
    
    def start(self):
        """Запускает мок-сервер"""
        self.running = True
        self.load_config()
        
        # Запускаем UDP сервер в отдельном потоке
        udp_thread = threading.Thread(target=self.start_udp_server)
        udp_thread.daemon = True
        udp_thread.start()
        
        # Запускаем HTTP сервер в отдельном потоке
        http_thread = threading.Thread(target=self.start_http_server)
        http_thread.daemon = True
        http_thread.start()
        
        print("[MOCK] Rockchip mock server started")
        print("[MOCK] UDP: 0.0.0.0:8008")
        print("[MOCK] HTTP: 0.0.0.0:8000")
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[MOCK] Shutting down...")
            self.running = False

if __name__ == "__main__":
    server = MockRockchipServer()
    server.start() 