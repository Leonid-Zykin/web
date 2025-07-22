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

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

ML_API_URL = os.environ.get("ML_API_URL", "http://ml-api:8000/infer")
ML_CONFIG_URL = os.environ.get("ML_CONFIG_URL", "http://ml-api:8000/config")
ALARM_MAX = 200

# Явные адреса для видеопотоков и сигналов
RTSP_STREAM_URL = "rtsp://192.168.0.172:8554/stream"
RTSP_ANNOTATED_URL = "rtsp://192.168.0.172:8554/stream"
DEFAULT_URL1 = "rtsp://192.168.0.172:8554/stream"

# Глобальная очередь тревог
# Глобальный лог сырых UDP сообщений
raw_udp_log = deque(maxlen=ALARM_MAX)

# --- WebSocket listener ---
WS_URL = os.environ.get("ALARM_WS_URL", "ws://localhost:8008")  # поменяйте на ваш адрес



# --- Остальной код без изменений, кроме get_alarm_text и интерфейса ---
def load_config():
    try:
        with open("/tmp/build_interface.txt", "a", encoding="utf-8") as dbg:
            dbg.write("load_config: start\n")
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        with open("/tmp/build_interface.txt", "a", encoding="utf-8") as dbg:
            dbg.write(f"load_config: success {data}\n")
        return data
    except Exception as e:
        with open("/tmp/build_interface.txt", "a", encoding="utf-8") as dbg:
            dbg.write(f"load_config: error {e}\n")
        print(f"[ERROR] Failed to load config.yaml: {e}")
        return {}

def save_config(config):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True)
    except Exception as e:
        print(f"[ERROR] Failed to save config.yaml: {e}")

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
            with open("/tmp/flatten_debug.txt", "a", encoding="utf-8") as dbg:
                dbg.write(f"{prefix + k} = {v} ({type(v)})\n")
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
    return RTSP_STREAM_URL, RTSP_ANNOTATED_URL

def get_raw_udp_text():
    lines = list(raw_udp_log)
    if not lines:
        return "Нет UDP сообщений"
    return '\n'.join(lines)

def build_interface():
    config = load_config()
    flat_fields = flatten_config(config)
    with gr.Blocks(title="Видеомониторинг и настройки") as demo:
        gr.Markdown("# Видеомониторинг и настройки")
        with gr.Row():
            with gr.Column():
                url1 = gr.Textbox(label="RTSP URL 1 (Оригинал)", value=DEFAULT_URL1, interactive=True)
                gr.HTML('<img src="http://localhost:5000/video" style="width:100%; max-width: 800px; border: 2px solid #444; border-radius: 8px;">')
                # start_streams_btn = gr.Button("▶️ Запустить / Обновить стримы")
            with gr.Column():
                def update_alarm_box():
                    print(f"[Gradio] update_alarm_box called, raw_udp_log size: {len(raw_udp_log)}")
                    return get_raw_udp_text()
                alarm_box = gr.Textbox(label="RAW UDP тревоги (json)", value=update_alarm_box, lines=38, interactive=False, elem_id="alarm_box", every=2)
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
                        param_inputs[key] = gr.Textbox(label=key, value=str(value), interactive=True)
        with gr.Row():
            save_btn = gr.Button("Сохранить")
            reset_btn = gr.Button("Сбросить")
        status = gr.Markdown(visible=False)
        def save_all(url1, *params):
            param_dict = {k: try_cast(params[i], flat_fields[i][1]) for i, (k, _) in enumerate(flat_fields)}
            config_new = unflatten_config(param_dict)
            save_config(config_new)
            return gr.update(visible=True, value="✅ Изменения сохранены!")
        def reset_all():
            config = load_config()
            flat_fields_new = flatten_config(config)
            values = [str(v) for _, v in flat_fields_new]
            url1 = get_default_urls(config)
            return [url1] + values + [gr.update(visible=True, value="🔄 Сброшено!")]
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
        def update_alarm_box():
            return get_raw_udp_text()
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