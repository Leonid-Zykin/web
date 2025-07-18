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

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '../opi5test/core/config.yaml')
RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

ML_API_URL = os.environ.get("ML_API_URL", "http://ml-api:8000/infer")
ML_CONFIG_URL = os.environ.get("ML_CONFIG_URL", "http://ml-api:8000/config")
ALARM_UDP_PORT = int(os.environ.get("ALARM_UDP_PORT", 8008))
ALARM_MAX = 200

# Глобальная очередь тревог
alarm_queue = deque(maxlen=ALARM_MAX)

def udp_alarm_listener(port=ALARM_UDP_PORT):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", port))
    while True:
        try:
            data, _ = sock.recvfrom(65536)
            msg = data.decode("utf-8", errors="replace")
            try:
                parsed = json.loads(msg)
            except Exception:
                parsed = msg
            alarm_queue.appendleft(parsed)
        except Exception as e:
            alarm_queue.appendleft({"error": str(e), "raw": str(data)})

# Запуск UDP-listener в отдельном потоке
threading.Thread(target=udp_alarm_listener, daemon=True).start()

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

# Для отображения RTSP используем gr.HTML с тегом <video> (gr.Video не поддерживает rtsp напрямую)
def rtsp_video_html(url):
    # Для реального отображения RTSP нужен прокси/перевод в HLS или WebRTC, но для макета делаем заглушку
    return f'<div style="background:#222;color:#fff;padding:2em;text-align:center;">Поток: {url}</div>'

# Получаем список всех параметров для динамического UI
def flatten_config(config, prefix="", out=None):
    # out - для сохранения порядка и избежания дублирования
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
    # Берём из system.rtsp_stream_url или пусто
    url = config.get('system', {}).get('rtsp_stream_url', '')
    return url, url

def get_alarm_text():
    # Возвращает последние тревоги в виде текста
    lines = []
    for alarm in list(alarm_queue):
        if isinstance(alarm, dict):
            lines.append(json.dumps(alarm, ensure_ascii=False))
        else:
            lines.append(str(alarm))
    return '\n'.join(lines)

def build_interface():
    with open("/tmp/build_interface.txt", "a", encoding="utf-8") as dbg:
        dbg.write("build_interface: called\n")
    config = load_config()
    print("CONFIG FROM YAML:", config)
    flat_fields = flatten_config(config)
    print("FLATTENED CONFIG:", flat_fields)
    default_url1, default_url2 = get_default_urls(config)

    with gr.Blocks(title="Видеомониторинг и настройки") as demo:
        gr.Markdown("# Видеомониторинг и настройки")
        # RTSP и видео
        with gr.Row():
            with gr.Column():
                url1 = gr.Textbox(label="RTSP URL 1", value=default_url1, interactive=True)
                video1 = gr.HTML(rtsp_video_html(default_url1), elem_id="video1")
            with gr.Column():
                url2 = gr.Textbox(label="RTSP URL 2", value=default_url2, interactive=True)
                video2 = gr.HTML(rtsp_video_html(default_url2), elem_id="video2")
        # Параметры config.yaml
        gr.Markdown("## Параметры config.yaml")
        param_inputs = {}
        with gr.Row():
            with gr.Column():
                for key, value in flat_fields:
                    param_inputs[key] = gr.Textbox(label=key, value=str(value), interactive=True)
        with gr.Row():
            save_btn = gr.Button("Сохранить")
            reset_btn = gr.Button("Сбросить")
        status = gr.Markdown(visible=False)
        # Видео-анализ
        gr.Markdown("## Анализ видео и тревоги")
        with gr.Row():
            video_input = gr.Video(label="Загрузите видео для анализа")
            process_btn = gr.Button("Обработать видео")
        with gr.Row():
            video_output = gr.Video(label="Результат с bounding boxes")
            log_output = gr.File(label="Журнал нарушений (JSON)")
        with gr.Row():
            sync_to_ml_btn = gr.Button("Обновить конфиг на ML")
            sync_from_ml_btn = gr.Button("Загрузить конфиг с ML")
        sync_status = gr.Markdown(visible=False)
        gr.Markdown("## Последние тревоги (DSM Alarm Monitor)")
        alarm_box = gr.Textbox(label="Последние тревоги (до 200)", lines=10, interactive=False)
        def update_alarm_box():
            return get_alarm_text()
        gr.Timer(1, update_alarm_box, None, [alarm_box])

        def update_videos(u1, u2):
            return rtsp_video_html(u1), rtsp_video_html(u2)

        def save_all(url1, url2, *params):
            param_dict = {k: try_cast(params[i], flat_fields[i][1]) for i, (k, _) in enumerate(flat_fields)}
            config_new = unflatten_config(param_dict)
            if 'system.rtsp_stream_url' in param_dict:
                config_new['system']['rtsp_stream_url'] = url1
            save_config(config_new)
            return gr.update(visible=True, value="✅ Изменения сохранены!")

        def reset_all():
            config = load_config()
            flat_fields_new = flatten_config(config)
            values = [str(v) for _, v in flat_fields_new]
            url1, url2 = get_default_urls(config)
            return [url1, url2] + values + [gr.update(visible=True, value="🔄 Сброшено!")]

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

        def process_uploaded_video(video_file):
            if video_file is None:
                return None, None, gr.update(visible=True, value="❌ Не выбрано видео!")
            # out_path, log_path = process_video_rest(video_file)
            # return out_path, log_path, gr.update(visible=True, value="✅ Готово!")
            return None, None, gr.update(visible=True, value="(заглушка) Видео обработка отключена!")

        def sync_to_ml_click():
            # msg = sync_config_to_ml()
            # return gr.update(visible=True, value=msg)
            return gr.update(visible=True, value="(заглушка) sync_to_ml отключено!")

        def sync_from_ml_click():
            # msg = sync_config_from_ml()
            # return gr.update(visible=True, value=msg)
            return gr.update(visible=True, value="(заглушка) sync_from_ml отключено!")

        url1.change(update_videos, [url1, url2], [video1, video2])
        url2.change(update_videos, [url1, url2], [video1, video2])
        save_btn.click(save_all, [url1, url2] + list(param_inputs.values()), [status])
        reset_btn.click(reset_all, None, [url1, url2] + list(param_inputs.values()) + [status])
        process_btn.click(process_uploaded_video, [video_input], [video_output, log_output, status])
        sync_to_ml_btn.click(sync_to_ml_click, [], [sync_status])
        sync_from_ml_btn.click(sync_from_ml_click, [], [sync_status])
    return demo

def main():
    demo = build_interface()
    demo.launch(server_name="0.0.0.0", server_port=7860)

if __name__ == "__main__":
    main() 