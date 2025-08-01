import gradio as gr
import yaml
import os
import copy
import threading
import time
import cv2
import numpy as np
import json
from datetime import datetime
import requests
import socket
from collections import deque
import websocket  # pip install websocket-client
import subprocess

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

ALARM_MAX = 200

# Явные адреса для видеопотоков и сигналов
DEFAULT_URL1 = "rtsp://192.168.0.174:8554/stream"

# Глобальная очередь тревог
# Глобальный лог сырых UDP сообщений
raw_udp_log = deque(maxlen=ALARM_MAX)

# --- WebSocket listener ---
WS_URL = os.environ.get("ALARM_WS_URL", "ws://localhost:8008") 

# Словарь переводов параметров на русский язык
PARAM_TRANSLATIONS = {
    # Системные параметры
    'system.model': 'Модель YOLO',
    'system.rtsp_stream_url': 'URL исходного видеопотока',
    'system.shape_predictor': 'Файл shape_predictor',
    'system.alarm_host': 'Хост для тревог',
    'system.alarm_port': 'Порт для тревог',
    'system.target_host': 'Дополнительный хост',
    'system.target_port': 'Дополнительный порт',
    'system.output_stream_url': 'URL обработанного потока',
    
    # Параметры нарушений
    'cigarette.duration': 'Длительность курения (сек)',
    'cigarette.threshold': 'Порог курения',
    'closed_eyes.duration': 'Длительность закрытых глаз (сек)',
    'closed_eyes.threshold': 'Порог закрытых глаз',
    'closed_eyes_duration.tracking_window': 'Окно отслеживания (сек)',
    'closed_eyes_duration.threshold': 'Порог времени закрытых глаз (сек)',
    'head_pose.duration': 'Длительность поворота головы (сек)',
    'head_pose.pitch': 'Угол наклона головы',
    'head_pose.yaw': 'Угол поворота головы',
    'no_belt.duration': 'Длительность отсутствия ремня (сек)',
    'no_belt.threshold': 'Порог отсутствия ремня',
    'no_driver.duration': 'Длительность отсутствия водителя (сек)',
    'no_driver.threshold': 'Порог отсутствия водителя',
    'no_face.duration': 'Длительность отсутствия лица (сек)',
    'no_face.threshold': 'Порог отсутствия лица',
    'phone.duration': 'Длительность использования телефона (сек)',
    'phone.threshold': 'Порог использования телефона',
    'yawn.duration': 'Длительность зевоты (сек)',
    'yawn.threshold': 'Порог зевоты',
    
    # Параметры Rockchip
    'rockchip.ip': 'IP адрес Rockchip',
    'rockchip.user': 'Пользователь Rockchip',
    'rockchip.password': 'Пароль Rockchip',
    'rockchip.config_path': 'Путь к конфигу на Rockchip'
}

# --- Остальной код без изменений, кроме get_alarm_text и интерфейса ---
def load_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        return data
    except Exception as e:
        print(f"[ERROR] Failed to load config.yaml: {e}")
        return {}

def save_config(config):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True)
    except Exception as e:
        print(f"[ERROR] Failed to save config.yaml: {e}")

def send_config_to_rockchip():
    # Загружаем параметры Rockchip из config.yaml
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    rockchip = config.get('rockchip', {})
    ip = rockchip.get('ip')
    user = rockchip.get('user')
    password = rockchip.get('password')
    remote_path = rockchip.get('config_path')
    if not all([ip, user, password, remote_path]):
        return False, 'Не все параметры Rockchip заданы в config.yaml'
    # Используем sshpass для передачи пароля (sshpass должен быть установлен)
    local_path = CONFIG_PATH
    scp_cmd = [
        'sshpass', '-p', password,
        'scp', '-o', 'StrictHostKeyChecking=no', local_path, f'{user}@{ip}:{remote_path}'
    ]
    try:
        result = subprocess.run(scp_cmd, check=True, capture_output=True, text=True)
        return True, 'Конфиг отправлен на Rockchip!'
    except subprocess.CalledProcessError as e:
        return False, f'Ошибка отправки конфига: {e.stderr}'

def get_log_files_from_rockchip():
    """Получает список файлов логов с Rockchip"""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    rockchip = config.get('rockchip', {})
    ip = rockchip.get('ip')
    user = rockchip.get('user')
    password = rockchip.get('password')
    
    if not all([ip, user, password]):
        return []
    
    # Команда для получения списка файлов логов
    ssh_cmd = [
        'sshpass', '-p', password,
        'ssh', '-o', 'StrictHostKeyChecking=no',
        f'{user}@{ip}',
        'ls -1 /home/orangepi/opi5test/logs/alarms_*.log 2>/dev/null || echo ""'
    ]
    
    try:
        result = subprocess.run(ssh_cmd, check=True, capture_output=True, text=True)
        files = result.stdout.strip().split('\n')
        # Извлекаем только имена файлов
        log_files = [os.path.basename(f) for f in files if f.strip()]
        return sorted(log_files, reverse=True)  # Новые файлы первыми
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to get log files: {e.stderr}")
        return []

def get_log_content_from_rockchip(filename):
    """Получает содержимое файла лога с Rockchip"""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    rockchip = config.get('rockchip', {})
    ip = rockchip.get('ip')
    user = rockchip.get('user')
    password = rockchip.get('password')
    
    if not all([ip, user, password]):
        return "Ошибка: не заданы параметры Rockchip"
    
    if not filename:
        return "Выберите файл лога"
    
    # Команда для получения содержимого файла
    ssh_cmd = [
        'sshpass', '-p', password,
        'ssh', '-o', 'StrictHostKeyChecking=no',
        f'{user}@{ip}',
        f'cat /home/orangepi/opi5test/logs/{filename}'
    ]
    
    try:
        result = subprocess.run(ssh_cmd, check=True, capture_output=True, text=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"Ошибка чтения файла: {e.stderr}"

def stream_video(rtsp_url):
    if not rtsp_url:
        print("RTSP URL is empty. Returning blank image.")
        blank_image = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(blank_image, "No RTSP link", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        while True:
            yield blank_image
            time.sleep(1)
    while True:
        print(f"Connecting to RTSP stream: {rtsp_url}")
        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            print(f"Error: Could not open stream at {rtsp_url}. Retrying in 5 seconds...")
            cap.release()
            time.sleep(5)
            continue
        while True:
            ret, frame = cap.read()
            if not ret:
                print(f"Stream at {rtsp_url} ended. Reconnecting...")
                break
            yield cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            time.sleep(1/25)
        cap.release()

def flatten_config(config, prefix="", out=None):
    if out is None:
        out = []
    for k, v in config.items():
        if isinstance(v, dict):
            flatten_config(v, prefix + k + ".", out)
        else:
            out.append((prefix + k, v))
    return out

def unflatten_config(flat_items):
    config = {}
    for key, value in flat_items.items():
        parts = key.split('.')
        d = config
        for p in parts[:-1]:
            if p not in d or not isinstance(d[p], dict):
                d[p] = {}
            d = d[p]
        d[parts[-1]] = value
    return config

def get_default_urls(config):
    """Получает URL из конфигурации или возвращает значения по умолчанию"""
    system_config = config.get('system', {})
    rtsp_stream_url = system_config.get('rtsp_stream_url', DEFAULT_URL1)
    rtsp_annotated_url = system_config.get('rtsp_annotated_url', DEFAULT_URL1)
    return rtsp_stream_url, rtsp_annotated_url

def get_raw_udp_text():
    lines = list(raw_udp_log)
    if not lines:
        return "Нет UDP сообщений"
    return '\n'.join(lines)

def build_interface():
    config = load_config()
    flat_fields = flatten_config(config)
    rockchip = config.get('rockchip', {})
    
    # Получаем URL из конфигурации
    rtsp_stream_url, rtsp_annotated_url = get_default_urls(config)
    
    with gr.Blocks(title="Видеомониторинг и настройки") as demo:
        gr.Markdown("# Видеомониторинг и настройки")
        with gr.Row():
            with gr.Column():
                url1 = gr.Textbox(label="RTSP URL 1 (Оригинал)", value=rtsp_stream_url, interactive=True)
                gr.HTML('<img src="http://localhost:5000/video" style="width:100%; max-width: 800px; border: 2px solid #444; border-radius: 8px;">')
            with gr.Column():
                def update_alarm_box():
                    return get_raw_udp_text()
                alarm_box = gr.Textbox(label="RAW UDP тревоги (json)", value=update_alarm_box, lines=38, interactive=False, elem_id="alarm_box", every=2)
        
        # --- Логи тревог ---
        gr.Markdown("## Логи тревог")
        with gr.Row():
            with gr.Column():
                log_file_dropdown = gr.Dropdown(label="Выберите файл лога", choices=[], interactive=True)
                refresh_logs_btn = gr.Button("🔄 Обновить список логов")
            with gr.Column():
                log_content_box = gr.Textbox(label="Содержимое лога", lines=20, interactive=False)
        with gr.Row():
            load_log_btn = gr.Button("📖 Загрузить лог")
        
        def refresh_log_files():
            log_files = get_log_files_from_rockchip()
            return gr.update(choices=log_files)
        
        def load_log_content(filename):
            if not filename:
                return "Выберите файл лога"
            return get_log_content_from_rockchip(filename)
        
        refresh_logs_btn.click(refresh_log_files, outputs=[log_file_dropdown])
        load_log_btn.click(load_log_content, inputs=[log_file_dropdown], outputs=[log_content_box])
        
        gr.Markdown("## Параметры config.yaml")
        param_inputs = {}
        param_list = list(flat_fields)
        n = len(param_list)
        chunk_size = (n + 3) // 4
        chunks = [param_list[i:i + chunk_size] for i in range(0, n, chunk_size)]
        with gr.Row():
            for chunk in chunks:
                with gr.Column():
                    for key, value in chunk:
                        param_inputs[key] = gr.Textbox(label=PARAM_TRANSLATIONS.get(key, key), value=str(value), interactive=True)
        with gr.Row():
            save_btn = gr.Button("Сохранить")
            reset_btn = gr.Button("Сбросить")
        # --- Rockchip IP ---
        with gr.Row():
            rockchip_ip_box = gr.Textbox(label="IP Rockchip", value=rockchip.get('ip', ''), interactive=True)
            save_ip_btn = gr.Button("Сохранить IP Rockchip")
        status = gr.Markdown(visible=False)
        def save_all(url1, *params):
            param_dict = {k: try_cast(params[i], flat_fields[i][1]) for i, (k, _) in enumerate(flat_fields)}
            config_new = unflatten_config(param_dict)
            save_config(config_new)
            ok, msg = send_config_to_rockchip()
            return gr.update(visible=True, value=(msg if ok else f"❌ {msg}"))
        def save_rockchip_ip(ip):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            if 'rockchip' not in config:
                config['rockchip'] = {}
            config['rockchip']['ip'] = ip
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True)
            return gr.update(visible=True, value=f"IP Rockchip сохранён: {ip}")
        def reset_all():
            config = load_config()
            flat_fields_new = flatten_config(config)
            values = [str(v) for _, v in flat_fields_new]
            rtsp_stream_url, rtsp_annotated_url = get_default_urls(config)
            return [rtsp_stream_url] + values + [gr.update(visible=True, value="🔄 Сброшено!")]
        def try_cast(val, orig):
            if isinstance(orig, float):
                try:
                    return float(val)
                except:
                    return orig
            if isinstance(orig, int):
                try:
                    return int(val)
                except:
                    return orig
            return val
        save_btn.click(save_all, [url1] + list(param_inputs.values()), [status])
        reset_btn.click(reset_all, None, [url1] + list(param_inputs.values()) + [status])
        save_ip_btn.click(save_rockchip_ip, [rockchip_ip_box], [status])
    return demo

# --- UDP listener for DSM alarms ---
def udp_alarm_listener(host="0.0.0.0", port=8008):
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    print(f"[UDP] Listening for DSM alarms on {host}:{port}")
    while True:
        try:
            data, addr = sock.recvfrom(4096)
            msg = data.decode("utf-8")
            raw_udp_log.append(msg)
            print(f"[UDP] RAW from {addr}: {msg}")
        except Exception as e:
            print(f"[UDP] Error: {e}")
            time.sleep(1)
# --- Start UDP listener in background thread ---
def start_udp_listener():
    t = threading.Thread(target=udp_alarm_listener, daemon=True)
    t.start()

def main():
    start_udp_listener()
    demo = build_interface()
    demo.launch(server_name="0.0.0.0", server_port=7860)

if __name__ == "__main__":
    main() 