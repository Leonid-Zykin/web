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
WEB_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'web_config.json')
RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

ALARM_MAX = 200

# Явные адреса для видеопотоков и сигналов
DEFAULT_URL1 = "rtsp://192.168.0.172:8554/stream"

def load_web_config():
    """Загружает конфигурацию веб-приложения"""
    default_config = {
        "api_host": "192.168.0.172",
        "api_port": 8000,
        "last_updated": ""
    }
    
    try:
        if os.path.exists(WEB_CONFIG_PATH):
            with open(WEB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # Обновляем с дефолтными значениями, если чего-то не хватает
                for key, value in default_config.items():
                    if key not in config:
                        config[key] = value
                return config
        else:
            # Создаем файл с дефолтными значениями
            save_web_config(default_config)
            return default_config
    except Exception as e:
        print(f"[ERROR] Failed to load web config: {e}")
        return default_config

def save_web_config(config):
    """Сохраняет конфигурацию веб-приложения"""
    try:
        config["last_updated"] = datetime.now().isoformat()
        with open(WEB_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to save web config: {e}")
        return False

# Глобальная очередь тревог
# Глобальный лог сырых UDP сообщений
raw_udp_log = deque(maxlen=ALARM_MAX)

# --- WebSocket listener ---
WS_URL = os.environ.get("ALARM_WS_URL", "ws://localhost:8008") 

# API конфигурация
web_config = load_web_config()
API_BASE_URL = f"http://{web_config['api_host']}:{web_config['api_port']}"  # Базовый URL для API

def load_config_from_api():
    """Загружает конфигурацию через API"""
    try:
        response = requests.get(f"{API_BASE_URL}/config", timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"[ERROR] Failed to load config from API: {response.status_code}")
            return {}
    except Exception as e:
        print(f"[ERROR] Failed to connect to API: {e}")
        return {}

def update_config_param(section, key, value):
    """Обновляет параметр конфигурации через API"""
    try:
        update_data = {
            "section": section,
            "key": key,
            "value": value
        }
        response = requests.patch(f"{API_BASE_URL}/config", json=update_data, timeout=10)
        if response.status_code == 200:
            return True, f"Параметр {section}.{key} обновлен"
        else:
            return False, f"Ошибка API: {response.status_code} - {response.text}"
    except Exception as e:
        return False, f"Ошибка подключения к API: {str(e)}"

def send_config_to_rockchip():
    # Загружаем параметры Rockchip из API
    config = load_config_from_api()
    rockchip = config.get('rockchip', {})
    ip = rockchip.get('ip')
    user = rockchip.get('user')
    password = rockchip.get('password')
    remote_path = rockchip.get('config_path')
    if not all([ip, user, password, remote_path]):
        return False, 'Не все параметры Rockchip заданы в конфиге'
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

def send_config_via_api():
    """Отправляет конфиг на рокчип через API вместо SCP"""
    try:
        # Получаем конфиг через API
        config = load_config_from_api()
        
        # Получаем параметры API из конфига
        rockchip = config.get('rockchip', {})
        api_host = rockchip.get('ip', '192.168.0.173')
        api_port = rockchip.get('api_port', 8000)
        
        # Формируем URL API
        api_url = f"http://{api_host}:{api_port}/config"
        
        # Отправляем конфиг через API
        response = requests.put(api_url, json=config, timeout=10)
        
        if response.status_code == 200:
            return True, f'Конфиг успешно отправлен через API на {api_host}:{api_port}'
        else:
            return False, f'Ошибка API: {response.status_code} - {response.text}'
            
    except requests.exceptions.ConnectionError:
        return False, f'Не удалось подключиться к API на {api_host}:{api_port}. Проверьте, запущен ли API сервис.'
    except requests.exceptions.Timeout:
        return False, 'Таймаут подключения к API'
    except Exception as e:
        return False, f'Ошибка отправки через API: {str(e)}'

def update_config_param_text(section, key, value):
    """Обертка: возвращает человекочитаемую строку вместо (ok, msg)"""
    ok, msg = update_config_param(section, key, value)
    return (msg if ok else f"❌ {msg}")

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
    # Загружаем конфигурацию через API
    config = load_config_from_api()
    
    # Если API недоступен, показываем сообщение об ошибке с формой для изменения адреса
    if not config:
        with gr.Blocks(title="Ошибка подключения к API") as demo:
            gr.Markdown("# ❌ Ошибка подключения к API")
            gr.Markdown("Не удалось подключиться к API сервису. Проверьте:")
            gr.Markdown("1. Запущен ли API сервис на Rockchip")
            gr.Markdown("2. Правильный ли IP адрес в переменной API_BASE_URL")
            gr.Markdown("3. Доступность порта 8000")
            gr.Markdown(f"**Текущий URL API:** {API_BASE_URL}")
            if web_config.get("last_updated"):
                last_updated = datetime.fromisoformat(web_config["last_updated"]).strftime("%d.%m.%Y %H:%M:%S")
                gr.Markdown(f"**Последнее обновление:** {last_updated}")
            
            # Форма для изменения адреса API
            gr.Markdown("## 🔧 Изменить адрес API")
            with gr.Row():
                api_host_input = gr.Textbox(
                    label="IP адрес API", 
                    value=web_config.get("api_host", "192.168.0.172"), 
                    placeholder="192.168.0.172",
                    interactive=True
                )
                api_port_input = gr.Textbox(
                    label="Порт API", 
                    value=str(web_config.get("api_port", 8000)), 
                    placeholder="8000",
                    interactive=True
                )
            with gr.Row():
                test_connection_btn = gr.Button("🔍 Проверить подключение", variant="secondary")
                apply_api_url_btn = gr.Button("✅ Применить новый адрес", variant="primary")
                reload_page_btn = gr.Button("🔄 Перезагрузить страницу", variant="secondary")
                reset_config_btn = gr.Button("🔄 Сбросить к умолчанию", variant="secondary")
            
            status_msg = gr.Markdown("")
            
            def test_api_connection(host, port):
                """Проверяет подключение к API"""
                try:
                    test_url = f"http://{host}:{port}/config"
                    response = requests.get(test_url, timeout=5)
                    if response.status_code == 200:
                        return "✅ Подключение успешно! API доступен."
                    else:
                        return f"❌ API отвечает с ошибкой: {response.status_code}"
                except requests.exceptions.ConnectionError:
                    return f"❌ Не удалось подключиться к {host}:{port}"
                except requests.exceptions.Timeout:
                    return f"❌ Таймаут подключения к {host}:{port}"
                except Exception as e:
                    return f"❌ Ошибка: {str(e)}"
            
            def apply_new_api_url(host, port):
                """Применяет новый адрес API и сохраняет в конфиг"""
                global API_BASE_URL, web_config
                
                # Обновляем конфигурацию
                web_config["api_host"] = host
                web_config["api_port"] = int(port)
                
                # Сохраняем в файл
                if save_web_config(web_config):
                    API_BASE_URL = f"http://{host}:{port}"
                    return f"✅ Новый адрес API сохранен: {API_BASE_URL}. Перезагрузите страницу для применения изменений."
                else:
                    return "❌ Ошибка сохранения конфигурации"
            
            test_connection_btn.click(
                test_api_connection, 
                inputs=[api_host_input, api_port_input], 
                outputs=[status_msg]
            )
            apply_api_url_btn.click(
                apply_new_api_url, 
                inputs=[api_host_input, api_port_input], 
                outputs=[status_msg]
            )
            
            def reload_page():
                """Перезагружает страницу"""
                return "🔄 Перезагрузка страницы..."
            
            def reset_config():
                """Сбрасывает конфигурацию к значениям по умолчанию"""
                global web_config
                default_config = {
                    "api_host": "192.168.0.172",
                    "api_port": 8000,
                    "last_updated": ""
                }
                if save_web_config(default_config):
                    web_config = default_config
                    return "✅ Конфигурация сброшена к значениям по умолчанию. Перезагрузите страницу."
                else:
                    return "❌ Ошибка сброса конфигурации"
            
            reload_page_btn.click(
                reload_page,
                outputs=[status_msg]
            )
            reset_config_btn.click(
                reset_config,
                outputs=[status_msg]
            )
            
            return demo

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
                alarm_box = gr.Textbox(label="RAW UDP тревоги (json)", value=update_alarm_box(), lines=30, interactive=False, elem_id="alarm_box", every=2)
                
                def clear_alarm_box():
                    """Очищает окно RAW UDP тревог"""
                    global raw_udp_log
                    raw_udp_log.clear()
                    return "Окно очищено"
                
                clear_alarm_btn = gr.Button("🗑️ Очистить окно тревог", variant="secondary")
        
        # --- Параметры config.yaml ---
        gr.Markdown("## Параметры конфигурации")
        
        # Кнопки обновления и отправки конфигурации
        with gr.Row():
            refresh_config_btn = gr.Button("🔄 Обновить из API", variant="secondary")
            api_send_btn = gr.Button("📤 Отправить через API", variant="secondary")
        
        # --- Блоки тревог ---
        gr.Markdown("### Настройки тревог")
        
        # Словарь переводов для тревог
        VIOLATION_TRANSLATIONS = {
            'cigarette': 'Курение',
            'closed_eyes': 'Закрытые глаза',
            'closed_eyes_duration': 'Длительность закрытых глаз',
            'head_pose': 'Поворот головы',
            'no_belt': 'Отсутствие ремня',
            'no_driver': 'Отсутствие водителя',
            'no_face': 'Отсутствие лица',
            'phone': 'Использование телефона',
            'yawn': 'Зевота'
        }
        
        violation_blocks = {}
        
        # Создаем блоки для каждой тревоги, группируя по 3 в строку
        violation_items = list(VIOLATION_TRANSLATIONS.items())
        for i in range(0, len(violation_items), 3):
            with gr.Row():
                for j in range(3):
                    if i + j < len(violation_items):
                        violation_type, label = violation_items[i + j]
                        violation_config = config.get(violation_type, {})
                        
                        with gr.Column():
                            with gr.Group():
                                with gr.Row():
                                    gr.Markdown(f"**{label}**")
                                    enable_checkbox = gr.Checkbox(
                                        label="Включить", 
                                        value=violation_config.get('enable', True),
                                        interactive=True
                                    )
                                
                                with gr.Column():
                                    duration_input = gr.Textbox(
                                        label="Длительность (сек)", 
                                        value=str(violation_config.get('duration', 5)),
                                        interactive=True
                                    )
                                    threshold_input = gr.Textbox(
                                        label="Уверенность", 
                                        value=str(violation_config.get('threshold', 0.5)),
                                        interactive=True
                                    )
                                
                                violation_blocks[violation_type] = {
                                    'enable': enable_checkbox,
                                    'duration': duration_input,
                                    'threshold': threshold_input
                                }
        
        # --- Rockchip IP ---
        with gr.Row():
            rockchip_ip_box = gr.Textbox(label="IP Rockchip", value=rockchip.get('ip', ''), interactive=True)
            save_ip_btn = gr.Button("Сохранить IP Rockchip")
        
        status = gr.Markdown(visible=False)
        
        # Собираем все поля блоков тревог для обновления
        violation_fields = []
        for violation_type, fields in violation_blocks.items():
            violation_fields.extend([fields['enable'], fields['duration'], fields['threshold']])
        
        # --- Обработчики событий ---
        
        def send_all_via_api(url1, rockchip_ip, *violation_values):
            """Отправляет только измененные параметры конфигурации через API"""
            try:
                # Получаем текущий конфиг из API
                current_config = load_config_from_api()
                if not current_config:
                    return "❌ Не удалось загрузить текущий конфиг из API"
                
                # Собираем текущие значения из интерфейса
                current_values = {}
                
                # Обрабатываем IP Rockchip
                if rockchip_ip and rockchip_ip != current_config.get('rockchip', {}).get('ip', ''):
                    current_values['rockchip.ip'] = rockchip_ip
                
                # Обрабатываем значения нарушений
                violation_items = list(VIOLATION_TRANSLATIONS.keys())
                value_index = 0
                
                for violation_type in violation_items:
                    # Получаем значения из интерфейса (3 значения на каждое нарушение: enable, duration, threshold)
                    enable_val = violation_values[value_index]
                    duration_val = float(violation_values[value_index + 1]) if violation_values[value_index + 1] else 5.0
                    threshold_val = float(violation_values[value_index + 2]) if violation_values[value_index + 2] else 0.5
                    
                    # Получаем текущие значения из конфига
                    current_violation = current_config.get(violation_type, {})
                    current_enable = current_violation.get('enable', True)
                    current_duration = current_violation.get('duration', 5.0)
                    current_threshold = current_violation.get('threshold', 0.5)
                    
                    # Сравниваем и добавляем измененные значения
                    if enable_val != current_enable:
                        current_values[f'{violation_type}.enable'] = enable_val
                    
                    if abs(duration_val - current_duration) > 0.001:  # Учитываем погрешность float
                        current_values[f'{violation_type}.duration'] = duration_val
                    
                    if abs(threshold_val - current_threshold) > 0.001:  # Учитываем погрешность float
                        current_values[f'{violation_type}.threshold'] = threshold_val
                    
                    value_index += 3
                
                # Если нет изменений
                if not current_values:
                    return "✅ Нет изменений для отправки"
                
                # Отправляем только измененные параметры
                success_count = 0
                error_count = 0
                error_messages = []
                
                for param_path, value in current_values.items():
                    section, key = param_path.split('.', 1)
                    ok, msg = update_config_param(section, key, value)
                    if ok:
                        success_count += 1
                    else:
                        error_count += 1
                        error_messages.append(f"{param_path}: {msg}")
                
                # Формируем итоговое сообщение
                if error_count == 0:
                    return f"✅ Успешно отправлено {success_count} измененных параметров"
                else:
                    error_summary = f"❌ Ошибки при отправке {error_count} из {len(current_values)} параметров:\n" + "\n".join(error_messages[:3])  # Показываем только первые 3 ошибки
                    return error_summary
                    
            except Exception as e:
                return f"❌ Ошибка при отправке: {str(e)}"
        
        def save_rockchip_ip(ip):
            """Сохраняет IP Rockchip через API"""
            ok, msg = update_config_param('rockchip', 'ip', ip)
            return (msg if ok else f"❌ {msg}")
        
        def refresh_config_from_api():
            """Обновляет конфигурацию из API"""
            config = load_config_from_api()
            if not config:
                return "❌ Не удалось загрузить конфигурацию из API"
            
            rtsp_stream_url, rtsp_annotated_url = get_default_urls(config)
            
            # Обновляем блоки тревог
            violation_updates = []
            for violation_type in VIOLATION_TRANSLATIONS:
                violation_config = config.get(violation_type, {})
                violation_updates.extend([
                    violation_config.get('enable', True),  # enable
                    str(violation_config.get('duration', 5)),  # duration
                    str(violation_config.get('threshold', 0.5))  # threshold
                ])
            
            # Обновляем IP Rockchip в поле ввода
            rockchip_ip = config.get('rockchip', {}).get('ip', '')
            
            return [rtsp_stream_url, "✅ Конфигурация обновлена из API"] + violation_updates + [rockchip_ip]
        
        # --- Привязка событий ---
        
        # Привязываем блоки тревог
        for violation_type, fields in violation_blocks.items():
            # Обработчик для чекбокса enable
            fields['enable'].change(
                fn=lambda checked, vt=violation_type: update_config_param_text(vt, 'enable', checked),
                inputs=[fields['enable']],
                outputs=[status]
            )
            
            # Обработчик для поля длительности
            fields['duration'].change(
                fn=lambda value, vt=violation_type: update_config_param_text(vt, 'duration', float(value) if value else 5.0),
                inputs=[fields['duration']],
                outputs=[status]
            )
            
            # Обработчик для поля уверенности
            fields['threshold'].change(
                fn=lambda value, vt=violation_type: update_config_param_text(vt, 'threshold', float(value) if value else 0.5),
                inputs=[fields['threshold']],
                outputs=[status]
            )
        
        # Привязываем кнопку очистки тревог
        clear_alarm_btn.click(clear_alarm_box, outputs=[alarm_box])
        
        api_send_btn.click(send_all_via_api, [url1, rockchip_ip_box] + violation_fields, [status])
        save_ip_btn.click(lambda ip: save_rockchip_ip(ip), [rockchip_ip_box], [status])
        
        refresh_config_btn.click(refresh_config_from_api, None, [url1] + [status] + violation_fields + [rockchip_ip_box])

        # Автообновление окна RAW UDP тревог через таймер (Gradio 5)
        refresh_timer = gr.Timer(2.0, visible=False)
        refresh_timer.tick(fn=lambda: get_raw_udp_text(), outputs=[alarm_box])
    
    return demo

# --- UDP listener for DSM alarms ---
def udp_alarm_listener(host="0.0.0.0", port=8008):
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
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
    except OSError as e:
        print(f"[UDP] Port {port} already in use, skipping UDP listener: {e}")
    except Exception as e:
        print(f"[UDP] Error: {e}")

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