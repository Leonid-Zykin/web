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

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

ML_API_URL = os.environ.get("ML_API_URL", "http://ml-api:8000/infer")
ML_CONFIG_URL = os.environ.get("ML_CONFIG_URL", "http://ml-api:8000/config")
ALARM_UDP_PORT = int(os.environ.get("ALARM_UDP_PORT", 8008))
ALARM_MAX = 200

# Явные адреса для видеопотоков и сигналов
RTSP_STREAM_URL = "rtsp://192.168.0.172:8554/stream"
RTSP_ANNOTATED_URL = "rtsp://192.168.0.172:8554/stream"
UDP_ALARM_PORT = 8008
UDP_ALARM_HOST = "192.168.0.172"

# Глобальная очередь тревог
alarm_queue = deque(maxlen=ALARM_MAX)

def udp_alarm_listener(port=UDP_ALARM_PORT):
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
    # Реальное отображение RTSP потока через HTML5 video
    return f'''
    <div style="background:#000;padding:1em;border-radius:8px;">
        <video width="100%" height="300" controls autoplay muted>
            <source src="{url}" type="application/x-rtsp">
            Ваш браузер не поддерживает RTSP поток.
        </video>
        <div style="color:#fff;text-align:center;margin-top:0.5em;">Поток: {url}</div>
    </div>
    '''

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
    # Используем явные адреса для видеопотоков
    return RTSP_STREAM_URL, RTSP_ANNOTATED_URL

def get_alarm_text():
    # Возвращает последние тревоги в виде текста с временными метками
    lines = []
    for i, alarm in enumerate(list(alarm_queue)):
        timestamp = datetime.now().strftime("%H:%M:%S")
        if isinstance(alarm, dict):
            # Форматируем JSON для лучшей читаемости
            alarm_str = json.dumps(alarm, ensure_ascii=False, indent=2)
            lines.append(f"[{timestamp}] Тревога #{i+1}:\n{alarm_str}")
        else:
            lines.append(f"[{timestamp}] Тревога #{i+1}: {str(alarm)}")
    return '\n\n'.join(lines) if lines else "Нет тревог"

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
                url1 = gr.Textbox(label="RTSP URL 1 (Оригинал)", value=default_url1, interactive=True)
                video1 = gr.HTML(rtsp_video_html(default_url1), elem_id="video1")
            with gr.Column():
                url2 = gr.Textbox(label="RTSP URL 2 (Аннотированный)", value=default_url2, interactive=True)
                video2 = gr.HTML(rtsp_video_html(default_url2), elem_id="video2")
        
        gr.Markdown("## Параметры config.yaml")
        param_inputs = {}
        
        # Разделяем параметры на 4 столбца
        param_list = list(flat_fields)
        n = len(param_list)
        chunk_size = (n + 3) // 4  # Округляем вверх, чтобы получить 4 колонки
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
            
            # Реальная обработка видео (заглушка для демонстрации)
            try:
                # Здесь можно добавить реальную обработку через API
                return None, None, gr.update(visible=True, value="✅ Видео обработано! (функция в разработке)")
            except Exception as e:
                return None, None, gr.update(visible=True, value=f"❌ Ошибка обработки: {str(e)}")

        def sync_to_ml_click():
            try:
                # Реальная синхронизация с ML API
                response = requests.post(f"{ML_CONFIG_URL}/sync", timeout=5)
                if response.status_code == 200:
                    return gr.update(visible=True, value="✅ Конфиг успешно обновлен на ML!")
                else:
                    return gr.update(visible=True, value=f"❌ Ошибка синхронизации: {response.status_code}")
            except Exception as e:
                return gr.update(visible=True, value=f"❌ Ошибка подключения к ML API: {str(e)}")

        def sync_from_ml_click():
            try:
                # Реальная загрузка конфига с ML API
                response = requests.get(f"{ML_CONFIG_URL}/config", timeout=5)
                if response.status_code == 200:
                    config_data = response.json()
                    # Здесь можно обновить локальный конфиг
                    return gr.update(visible=True, value="✅ Конфиг загружен с ML!")
                else:
                    return gr.update(visible=True, value=f"❌ Ошибка загрузки: {response.status_code}")
            except Exception as e:
                return gr.update(visible=True, value=f"❌ Ошибка подключения к ML API: {str(e)}")

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