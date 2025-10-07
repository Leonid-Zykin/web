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
WEB_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'web_config.yaml')
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
        "rtsp_stream_url": "rtsp://192.168.0.172:8554/stream",
        "last_updated": ""
    }
    
    try:
        if os.path.exists(WEB_CONFIG_PATH):
            with open(WEB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
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
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, indent=2)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to save web config: {e}")
        return False

# Глобальная очередь тревог
# Глобальный лог сырых UDP сообщений
raw_udp_log = deque(maxlen=ALARM_MAX)
# Флаг для отслеживания новых тревог
new_alarm_received = False

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

def call_head_calibrate(direction):
    """Отправляет команду калибровки; ядро возьмет текущие градусы и сохранит в raw_deg"""
    try:
        response = requests.post(f"{API_BASE_URL}/head_calibrate", json={"direction": direction}, timeout=10)
        if response.status_code == 200:
            return f"✅ Калибровка отправлена: {direction}"
        else:
            return f"❌ Ошибка API: {response.status_code} - {response.text}"
    except Exception as e:
        return f"❌ Ошибка подключения к API: {str(e)}"

def calibrate_and_refresh(direction):
    """Вызывает калибровку и возвращает статус и обновленные градусы (left,right,down,up)."""
    msg = call_head_calibrate(direction)
    # После калибровки сразу тянем актуальный конфиг, чтобы обновить градусы
    cfg = load_config_from_api()
    hp_cfg = cfg.get('head_pose', {}) if isinstance(cfg, dict) else {}
    raw_deg = hp_cfg.get('raw_deg', {}) if isinstance(hp_cfg, dict) else {}
    def fmt1(v):
        try:
            return f"{float(v):.1f}"
        except Exception:
            return "0.0"
    left = fmt1(raw_deg.get('left', 0.0))
    right = fmt1(raw_deg.get('right', 0.0))
    down = fmt1(raw_deg.get('down', 0.0))
    up = fmt1(raw_deg.get('up', 0.0))
    return [msg, left, right, down, up]

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
    # Сначала проверяем локальную конфигурацию веб-приложения
    local_rtsp_url = web_config.get('rtsp_stream_url', DEFAULT_URL1)
    
    # Затем проверяем конфигурацию API
    system_config = config.get('system', {})
    rtsp_stream_url = system_config.get('rtsp_stream_url', local_rtsp_url)
    rtsp_annotated_url = system_config.get('rtsp_annotated_url', rtsp_stream_url)
    return rtsp_stream_url, rtsp_annotated_url

def get_raw_udp_text():
    lines = list(raw_udp_log)
    if not lines:
        return "Нет UDP сообщений"
    return '\n'.join(lines)

def check_and_update_alarms():
    """Проверяет наличие новых тревог и возвращает обновленный текст"""
    global new_alarm_received
    if new_alarm_received:
        new_alarm_received = False  # Сбрасываем флаг
        return get_raw_udp_text()
    return gr.update()  # Возвращаем gr.update() если нет изменений

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
    

    
    with gr.Blocks(title="Видеомониторинг и настройки") as demo:
        gr.Markdown("# Видеомониторинг и настройки")
        with gr.Row():
            with gr.Column():
                # Локальная конфигурация RTSP URL
                local_rtsp_url = gr.Textbox(
                    label="Локальный RTSP URL (для MJPEG сервера)", 
                    value=web_config.get('rtsp_stream_url', DEFAULT_URL1), 
                    interactive=True
                )
                save_local_rtsp_btn = gr.Button("💾 Сохранить локальный RTSP URL", variant="secondary")
                
                gr.HTML('<img src="http://localhost:5000/video" style="width:100%; max-width: 800px; border: 2px solid #444; border-radius: 8px; display:block;">')
            with gr.Column():
                def update_alarm_box():
                    return get_raw_udp_text()
                alarm_box = gr.Textbox(label="RAW UDP тревоги (json)", value=update_alarm_box(), lines=30, interactive=False, elem_id="alarm_box")
                
                def clear_alarm_box():
                    """Очищает окно RAW UDP тревог"""
                    global raw_udp_log, new_alarm_received
                    raw_udp_log.clear()
                    new_alarm_received = False  # Сбрасываем флаг новых тревог
                    return "Окно очищено"
                
                with gr.Row():
                    clear_alarm_btn = gr.Button("🗑️ Очистить окно тревог", variant="secondary")
                    refresh_alarm_btn = gr.Button("🔄 Обновить тревоги", variant="secondary")
        
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
            'head_pose': 'Поворот головы',
            'no_belt': 'Отсутствие ремня',
            'no_driver': 'Отсутствие водителя',
            'no_face': 'Отсутствие лица',
            'phone': 'Использование телефона',
            'yawn': 'Зевота'
        }
        
        violation_blocks = {}

        # Размещение: слева сетка из 4 блоков в ряд для всех, кроме head_pose; справа — отдельный блок head_pose
        other_items = [(k, v) for k, v in VIOLATION_TRANSLATIONS.items() if k != 'head_pose']
        with gr.Row():
            # Левая колонка с сеткой 4х
            with gr.Column(scale=2):
                for i in range(0, len(other_items), 4):
                    with gr.Row():
                        for j in range(4):
                            if i + j < len(other_items):
                                violation_type, label = other_items[i + j]
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
            # Правая колонка — head_pose
            with gr.Column(scale=1):
                violation_type = 'head_pose'
                label = VIOLATION_TRANSLATIONS[violation_type]
                violation_config = config.get(violation_type, {})
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
                        head_center_pitch_input = gr.Textbox(
                            label="Центр по вертикали (0..1)",
                            value=str(violation_config.get('center_pitch', 0.5)),
                            interactive=True
                        )
                        head_center_yaw_input = gr.Textbox(
                            label="Центр по горизонтали (0..1)",
                            value=str(violation_config.get('center_yaw', 0.5)),
                            interactive=True
                        )
                        head_pitch_input = gr.Textbox(
                            label="Порог по вертикали (0..1)",
                            value=str(violation_config.get('pitch', 0.2)),
                            interactive=True
                        )
                        head_yaw_input = gr.Textbox(
                            label="Порог по горизонтали (0..1)",
                            value=str(violation_config.get('yaw', 0.2)),
                            interactive=True
                        )
                        with gr.Row():
                            left_btn = gr.Button("Запомнить левое", variant="secondary")
                            right_btn = gr.Button("Запомнить правое", variant="secondary")
                        with gr.Row():
                            up_btn = gr.Button("Запомнить верхнее", variant="secondary")
                            down_btn = gr.Button("Запомнить нижнее", variant="secondary")
                        # Поля для отображения порогов калибровки в градусах
                        hp_cfg = config.get('head_pose', {})
                        raw_deg = hp_cfg.get('raw_deg', {})
                        raw_left_box = gr.Textbox(label="Лево (°)", value=str(raw_deg.get('left', 0.0)), interactive=False)
                        raw_right_box = gr.Textbox(label="Право (°)", value=str(raw_deg.get('right', 0.0)), interactive=False)
                        raw_down_box = gr.Textbox(label="Вниз (°)", value=str(raw_deg.get('down', 0.0)), interactive=False)
                        raw_up_box = gr.Textbox(label="Вверх (°)", value=str(raw_deg.get('up', 0.0)), interactive=False)
                violation_blocks[violation_type] = {
                    'enable': enable_checkbox,
                    'duration': duration_input,
                    'threshold': gr.Textbox(visible=False),
                    'center_pitch': head_center_pitch_input,
                    'center_yaw': head_center_yaw_input,
                    'pitch': head_pitch_input,
                    'yaw': head_yaw_input,
                    'raw_left': raw_left_box,
                    'raw_right': raw_right_box,
                    'raw_down': raw_down_box,
                    'raw_up': raw_up_box
                }
        
        # --- Rockchip IP ---
        with gr.Row():
            rockchip_ip_box = gr.Textbox(label="IP Rockchip", value=rockchip.get('ip', ''), interactive=True)
            save_ip_btn = gr.Button("Сохранить IP Rockchip")
        
        status = gr.Markdown(visible=False)
        
        # Собираем поля блоков тревог
        violation_fields = []  # используется для массовой отправки через API (enable, duration, threshold)
        refresh_fields = []    # используется для обновления из API (включая дополнительные head_pose поля)
        for violation_type, fields in violation_blocks.items():
            # Базовые поля для всех нарушений
            base_components = [fields['enable'], fields['duration'], fields['threshold']]
            violation_fields.extend(base_components)
            refresh_fields.extend(base_components)
            # Дополнительные поля только для head_pose
            if violation_type == 'head_pose':
                refresh_fields.extend([
                    fields.get('center_pitch'),
                    fields.get('center_yaw'),
                    fields.get('pitch'),
                    fields.get('yaw')
                ])
        
        # --- Обработчики событий ---
        
        def send_all_via_api(rockchip_ip, *violation_values):
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
        
        def save_local_rtsp_url(rtsp_url):
            """Сохраняет локальный RTSP URL в конфигурацию веб-приложения"""
            global web_config
            web_config['rtsp_stream_url'] = rtsp_url
            if save_web_config(web_config):
                return f"✅ Локальный RTSP URL сохранен: {rtsp_url}"
            else:
                return "❌ Ошибка сохранения локального RTSP URL"
        
        def refresh_config_from_api():
            """Обновляет конфигурацию из API"""
            config = load_config_from_api()
            if not config:
                return "❌ Не удалось загрузить конфигурацию из API"
            
            # Обновляем блоки тревог в ТОЧНОМ порядке, как сформирован violation_blocks (соответствует refresh_fields)
            violation_updates = []
            for violation_type in violation_blocks.keys():
                violation_config = config.get(violation_type, {})
                # Базовые поля
                violation_updates.extend([
                    violation_config.get('enable', True),
                    str(violation_config.get('duration', 5)),
                    str(violation_config.get('threshold', 0.5))
                ])
                # Дополнительные поля для head_pose (в порядке, соответствующем refresh_fields)
                if violation_type == 'head_pose':
                    violation_updates.extend([
                        str(violation_config.get('center_pitch', 0.5)),
                        str(violation_config.get('center_yaw', 0.5)),
                        str(violation_config.get('pitch', 0.2)),
                        str(violation_config.get('yaw', 0.2))
                    ])
            
            # Обновляем IP Rockchip в поле ввода
            rockchip_ip = config.get('rockchip', {}).get('ip', '')
            
            # Обновляем локальный RTSP URL
            local_rtsp_url_value = web_config.get('rtsp_stream_url', DEFAULT_URL1)
            
            # Возвращаем данные: статус + значения полей + 4 калибровки в градусах + ip и rtsp
            raw_deg = config.get('head_pose', {}).get('raw_deg', {})
            def fmt1(v):
                try:
                    return f"{float(v):.1f}"
                except Exception:
                    return "0.0"
            raw_left = fmt1(raw_deg.get('left', 0.0))
            raw_right = fmt1(raw_deg.get('right', 0.0))
            raw_down = fmt1(raw_deg.get('down', 0.0))
            raw_up = fmt1(raw_deg.get('up', 0.0))
            return ["✅ Конфигурация обновлена из API"] + violation_updates + [raw_left, raw_right, raw_down, raw_up, rockchip_ip, local_rtsp_url_value]
        
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

            # Дополнительные обработчики только для head_pose
            if violation_type == 'head_pose':
                if fields.get('center_pitch') is not None:
                    fields['center_pitch'].change(
                        fn=lambda value, vt=violation_type: update_config_param_text(vt, 'center_pitch', max(0.0, min(1.0, float(value) if value else 0.5))),
                        inputs=[fields['center_pitch']],
                        outputs=[status]
                    )
                if fields.get('center_yaw') is not None:
                    fields['center_yaw'].change(
                        fn=lambda value, vt=violation_type: update_config_param_text(vt, 'center_yaw', max(0.0, min(1.0, float(value) if value else 0.5))),
                        inputs=[fields['center_yaw']],
                        outputs=[status]
                    )
                if fields.get('pitch') is not None:
                    fields['pitch'].change(
                        fn=lambda value, vt=violation_type: update_config_param_text(vt, 'pitch', max(0.0, min(1.0, float(value) if value else 0.2))),
                        inputs=[fields['pitch']],
                        outputs=[status]
                    )
                if fields.get('yaw') is not None:
                    fields['yaw'].change(
                        fn=lambda value, vt=violation_type: update_config_param_text(vt, 'yaw', max(0.0, min(1.0, float(value) if value else 0.2))),
                        inputs=[fields['yaw']],
                        outputs=[status]
                    )
                # Кнопки калибровки положения головы
                try:
                    left_btn.click(
                        fn=lambda: calibrate_and_refresh('left'),
                        outputs=[
                            status,
                            violation_blocks['head_pose']['raw_left'],
                            violation_blocks['head_pose']['raw_right'],
                            violation_blocks['head_pose']['raw_down'],
                            violation_blocks['head_pose']['raw_up'],
                        ],
                    )
                    right_btn.click(
                        fn=lambda: calibrate_and_refresh('right'),
                        outputs=[
                            status,
                            violation_blocks['head_pose']['raw_left'],
                            violation_blocks['head_pose']['raw_right'],
                            violation_blocks['head_pose']['raw_down'],
                            violation_blocks['head_pose']['raw_up'],
                        ],
                    )
                    up_btn.click(
                        fn=lambda: calibrate_and_refresh('up'),
                        outputs=[
                            status,
                            violation_blocks['head_pose']['raw_left'],
                            violation_blocks['head_pose']['raw_right'],
                            violation_blocks['head_pose']['raw_down'],
                            violation_blocks['head_pose']['raw_up'],
                        ],
                    )
                    down_btn.click(
                        fn=lambda: calibrate_and_refresh('down'),
                        outputs=[
                            status,
                            violation_blocks['head_pose']['raw_left'],
                            violation_blocks['head_pose']['raw_right'],
                            violation_blocks['head_pose']['raw_down'],
                            violation_blocks['head_pose']['raw_up'],
                        ],
                    )
                except NameError:
                    pass
        
        # Привязываем кнопки тревог
        clear_alarm_btn.click(clear_alarm_box, outputs=[alarm_box])
        refresh_alarm_btn.click(lambda: get_raw_udp_text(), outputs=[alarm_box])
        
        api_send_btn.click(send_all_via_api, [rockchip_ip_box] + violation_fields, [status])
        save_ip_btn.click(lambda ip: save_rockchip_ip(ip), [rockchip_ip_box], [status])
        save_local_rtsp_btn.click(save_local_rtsp_url, [local_rtsp_url], [status])
        
        # --- Настройки усталости ---
        gr.Markdown("### Настройки усталости (fatigue)")
        with gr.Row():
            fatigue_enable = gr.Checkbox(label="Включить усталость", value=bool(config.get('fatigue', {}).get('enable', False)), interactive=True)
            fatigue_window = gr.Textbox(label="Окно, секунд", value=str(config.get('fatigue', {}).get('window_seconds', 60)), interactive=True)
        with gr.Group():
            gr.Markdown("#### Композитная логика")
            with gr.Row():
                comp_enable = gr.Checkbox(label="Включить композитную сумму", value=bool(config.get('fatigue', {}).get('composite', {}).get('enable', False)), interactive=True)
                comp_target = gr.Textbox(label="Целевая сумма событий", value=str(config.get('fatigue', {}).get('composite', {}).get('target_sum', 3)), interactive=True)
        with gr.Group():
            gr.Markdown("#### Длинные моргания")
            with gr.Row():
                lb_enable = gr.Checkbox(label="Включить длинные моргания", value=bool(config.get('fatigue', {}).get('long_blinks', {}).get('enable', False)), interactive=True)
                lb_ear = gr.Textbox(label="EAR порог (пусто = closed_eyes.threshold)", value=str(config.get('fatigue', {}).get('long_blinks', {}).get('ear_threshold', '')), interactive=True)
            with gr.Row():
                lb_min = gr.Textbox(label="Мин. длительность, c", value=str(config.get('fatigue', {}).get('long_blinks', {}).get('min_duration_s', 0.1)), interactive=True)
                lb_max = gr.Textbox(label="Макс. длительность, c", value=str(config.get('fatigue', {}).get('long_blinks', {}).get('max_duration_s', 0.4)), interactive=True)
                lb_count = gr.Textbox(label="Мин. число событий", value=str(config.get('fatigue', {}).get('long_blinks', {}).get('min_count', 3)), interactive=True)
        with gr.Group():
            gr.Markdown("#### Тренд межморганий")
            with gr.Row():
                it_enable = gr.Checkbox(label="Включить тренд межморганий", value=bool(config.get('fatigue', {}).get('interblink_trend', {}).get('enable', False)), interactive=True)
                it_ear = gr.Textbox(label="EAR порог (пусто = closed_eyes.threshold)", value=str(config.get('fatigue', {}).get('interblink_trend', {}).get('ear_threshold', '')), interactive=True)
            with gr.Row():
                it_min_intervals = gr.Textbox(label="Мин. интервалов (>=5)", value=str(config.get('fatigue', {}).get('interblink_trend', {}).get('min_intervals', 5)), interactive=True)
                it_avg_span = gr.Textbox(label="Окно среднего (штук)", value=str(config.get('fatigue', {}).get('interblink_trend', {}).get('avg_span', 5)), interactive=True)
                it_decrease_ms = gr.Textbox(label="Падение среднего, мс", value=str(config.get('fatigue', {}).get('interblink_trend', {}).get('decrease_ms', 50)), interactive=True)
                it_min_trend_events = gr.Textbox(label="Мин. событий тренда", value=str(config.get('fatigue', {}).get('interblink_trend', {}).get('min_trend_events', 3)), interactive=True)
        with gr.Group():
            gr.Markdown("#### Зевки")
            with gr.Row():
                y_enable = gr.Checkbox(label="Включить зевки", value=bool(config.get('fatigue', {}).get('yawn', {}).get('enable', False)), interactive=True)
                y_mar = gr.Textbox(label="MAR порог (пусто = yawn.threshold)", value=str(config.get('fatigue', {}).get('yawn', {}).get('mar_threshold', '')), interactive=True)
            with gr.Row():
                y_min = gr.Textbox(label="Мин. длительность, c", value=str(config.get('fatigue', {}).get('yawn', {}).get('min_duration_s', 0.4)), interactive=True)
                y_count = gr.Textbox(label="Мин. число событий", value=str(config.get('fatigue', {}).get('yawn', {}).get('min_count', 2)), interactive=True)
        with gr.Group():
            gr.Markdown("#### «Клевки» головой")
            with gr.Row():
                hn_enable = gr.Checkbox(label="Включить клевки головой", value=bool(config.get('fatigue', {}).get('head_nod', {}).get('enable', False)), interactive=True)
                hn_pitch_down = gr.Textbox(label="Порог вниз, °", value=str(config.get('fatigue', {}).get('head_nod', {}).get('pitch_down_delta_deg', 10.0)), interactive=True)
            with gr.Row():
                hn_min_down = gr.Textbox(label="Мин. удержание вниз, c", value=str(config.get('fatigue', {}).get('head_nod', {}).get('min_down_duration_s', 0.3)), interactive=True)
                hn_hyst = gr.Textbox(label="Гистерезис, °", value=str(config.get('fatigue', {}).get('head_nod', {}).get('hysteresis_deg', 3.0)), interactive=True)
                hn_count = gr.Textbox(label="Мин. число событий", value=str(config.get('fatigue', {}).get('head_nod', {}).get('min_count', 2)), interactive=True)

        with gr.Row():
            fatigue_refresh_btn = gr.Button("🔄 Обновить усталость из API", variant="secondary")
            fatigue_save_btn = gr.Button("💾 Сохранить усталость", variant="primary")

        def fatigue_refresh():
            cfg = load_config_from_api() or {}
            f = cfg.get('fatigue', {}) if isinstance(cfg, dict) else {}
            def _g(path, default):
                try:
                    cur = f
                    for k in path.split('.'):
                        cur = cur.get(k, {}) if isinstance(cur, dict) else {}
                    return cur if isinstance(cur, (str, int, float, bool)) else default
                except Exception:
                    return default
            return [
                bool(f.get('enable', False)),
                str(f.get('window_seconds', 60)),
                bool(f.get('composite', {}).get('enable', False)),
                str(f.get('composite', {}).get('target_sum', 3)),
                bool(f.get('long_blinks', {}).get('enable', False)),
                str(f.get('long_blinks', {}).get('ear_threshold', '')),
                str(f.get('long_blinks', {}).get('min_duration_s', 0.1)),
                str(f.get('long_blinks', {}).get('max_duration_s', 0.4)),
                str(f.get('long_blinks', {}).get('min_count', 3)),
                bool(f.get('interblink_trend', {}).get('enable', False)),
                str(f.get('interblink_trend', {}).get('ear_threshold', '')),
                str(f.get('interblink_trend', {}).get('min_intervals', 5)),
                str(f.get('interblink_trend', {}).get('avg_span', 5)),
                str(f.get('interblink_trend', {}).get('decrease_ms', 50)),
                str(f.get('interblink_trend', {}).get('min_trend_events', 3)),
                bool(f.get('yawn', {}).get('enable', False)),
                str(f.get('yawn', {}).get('mar_threshold', '')),
                str(f.get('yawn', {}).get('min_duration_s', 0.4)),
                str(f.get('yawn', {}).get('min_count', 2)),
                bool(f.get('head_nod', {}).get('enable', False)),
                str(f.get('head_nod', {}).get('pitch_down_delta_deg', 10.0)),
                str(f.get('head_nod', {}).get('min_down_duration_s', 0.3)),
                str(f.get('head_nod', {}).get('hysteresis_deg', 3.0)),
                str(f.get('head_nod', {}).get('min_count', 2)),
            ]

        def fatigue_save(*vals):
            try:
                cfg = load_config_from_api() or {}
                f = cfg.get('fatigue', {}) if isinstance(cfg, dict) else {}
                # распаковка порядка из fatigue_refresh
                (
                    v_enable, v_window,
                    c_enable, c_target,
                    lb_enable_v, lb_ear_v, lb_min_v, lb_max_v, lb_count_v,
                    it_enable_v, it_ear_v, it_min_int_v, it_avg_span_v, it_dec_ms_v, it_min_trend_v,
                    y_enable_v, y_mar_v, y_min_v, y_count_v,
                    hn_enable_v, hn_pitch_v, hn_min_down_v, hn_hyst_v, hn_count_v
                ) = vals
                # базовые
                f['enable'] = bool(v_enable)
                f['window_seconds'] = int(float(v_window)) if str(v_window).strip() else 60
                # composite
                f.setdefault('composite', {})
                f['composite']['enable'] = bool(c_enable)
                f['composite']['target_sum'] = int(float(c_target)) if str(c_target).strip() else 3
                # long_blinks
                f.setdefault('long_blinks', {})
                f['long_blinks']['enable'] = bool(lb_enable_v)
                f['long_blinks']['ear_threshold'] = None if str(lb_ear_v).strip()=='' else float(lb_ear_v)
                f['long_blinks']['min_duration_s'] = float(lb_min_v)
                f['long_blinks']['max_duration_s'] = float(lb_max_v)
                f['long_blinks']['min_count'] = int(float(lb_count_v))
                # interblink_trend
                f.setdefault('interblink_trend', {})
                f['interblink_trend']['enable'] = bool(it_enable_v)
                f['interblink_trend']['ear_threshold'] = None if str(it_ear_v).strip()=='' else float(it_ear_v)
                f['interblink_trend']['min_intervals'] = max(5, int(float(it_min_int_v)))
                f['interblink_trend']['avg_span'] = int(float(it_avg_span_v))
                f['interblink_trend']['decrease_ms'] = int(float(it_dec_ms_v))
                f['interblink_trend']['min_trend_events'] = int(float(it_min_trend_v))
                # yawn
                f.setdefault('yawn', {})
                f['yawn']['enable'] = bool(y_enable_v)
                f['yawn']['mar_threshold'] = None if str(y_mar_v).strip()=='' else float(y_mar_v)
                f['yawn']['min_duration_s'] = float(y_min_v)
                f['yawn']['min_count'] = int(float(y_count_v))
                # head_nod
                f.setdefault('head_nod', {})
                f['head_nod']['enable'] = bool(hn_enable_v)
                f['head_nod']['pitch_down_delta_deg'] = float(hn_pitch_v)
                f['head_nod']['min_down_duration_s'] = float(hn_min_down_v)
                f['head_nod']['hysteresis_deg'] = float(hn_hyst_v)
                f['head_nod']['min_count'] = int(float(hn_count_v))
                cfg['fatigue'] = f
                # полное сохранение через PUT
                resp = requests.put(f"{API_BASE_URL}/config", json=cfg, timeout=10)
                if resp.status_code == 200:
                    return "✅ Настройки усталости сохранены"
                return f"❌ Ошибка API: {resp.status_code} - {resp.text}"
            except Exception as e:
                return f"❌ Ошибка сохранения: {str(e)}"

        fatigue_refresh_btn.click(
            fn=fatigue_refresh,
            outputs=[
                fatigue_enable, fatigue_window,
                comp_enable, comp_target,
                lb_enable, lb_ear, lb_min, lb_max, lb_count,
                it_enable, it_ear, it_min_intervals, it_avg_span, it_decrease_ms, it_min_trend_events,
                y_enable, y_mar, y_min, y_count,
                hn_enable, hn_pitch_down, hn_min_down, hn_hyst, hn_count,
            ]
        )

        fatigue_save_btn.click(
            fn=fatigue_save,
            inputs=[
                fatigue_enable, fatigue_window,
                comp_enable, comp_target,
                lb_enable, lb_ear, lb_min, lb_max, lb_count,
                it_enable, it_ear, it_min_intervals, it_avg_span, it_decrease_ms, it_min_trend_events,
                y_enable, y_mar, y_min, y_count,
                hn_enable, hn_pitch_down, hn_min_down, hn_hyst, hn_count,
            ],
            outputs=[status]
        )

        # Обновляем значения, включая дополнительные head_pose поля, плюс 4 калибровки в градусах
        refresh_config_btn.click(
            refresh_config_from_api,
            None,
            [
                status,
                *refresh_fields,
                violation_blocks['head_pose']['raw_left'],
                violation_blocks['head_pose']['raw_right'],
                violation_blocks['head_pose']['raw_down'],
                violation_blocks['head_pose']['raw_up'],
                rockchip_ip_box,
                local_rtsp_url,
            ],
        )

        # Автообновление окна RAW UDP тревог при получении новых сообщений
        alarm_timer = gr.Timer(value=1.0)  # Проверяем каждую секунду
        alarm_timer.tick(
            fn=check_and_update_alarms,
            outputs=[alarm_box]
        )
    
    return demo

# --- UDP listener for DSM alarms ---
def udp_alarm_listener(host="0.0.0.0", port=8008):
    import socket
    global new_alarm_received
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((host, port))
        print(f"[UDP] Listening for DSM alarms on {host}:{port}")
        while True:
            try:
                data, addr = sock.recvfrom(4096)
                msg = data.decode("utf-8")
                raw_udp_log.append(msg)
                new_alarm_received = True  # Устанавливаем флаг при получении новой тревоги
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