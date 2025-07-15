import gradio as gr
import yaml
import os
import copy
import threading
import time

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '../opi5test/core/config.yaml')

def load_config():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def save_config(config):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True)

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

def build_interface():
    config = load_config()
    flat_fields = flatten_config(config)
    default_url1, default_url2 = get_default_urls(config)

    with gr.Blocks(title="Видеомониторинг и настройки") as demo:
        gr.Markdown("# Видеомониторинг и настройки")
        with gr.Row():
            with gr.Column():
                url1 = gr.Textbox(label="RTSP URL 1", value=default_url1, interactive=True)
                video1 = gr.HTML(rtsp_video_html(default_url1), elem_id="video1")
            with gr.Column():
                url2 = gr.Textbox(label="RTSP URL 2", value=default_url2, interactive=True)
                video2 = gr.HTML(rtsp_video_html(default_url2), elem_id="video2")
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

        def update_videos(u1, u2):
            return rtsp_video_html(u1), rtsp_video_html(u2)

        def show_status(msg, status):
            status.update(visible=True, value=msg)
            def hide():
                time.sleep(3)
                status.update(visible=False)
            threading.Thread(target=hide, daemon=True).start()

        def save_all(url1, url2, *params):
            param_dict = {k: try_cast(params[i], flat_fields[i][1]) for i, (k, _) in enumerate(flat_fields)}
            config_new = unflatten_config(param_dict)
            if 'system.rtsp_stream_url' in param_dict:
                config_new['system']['rtsp_stream_url'] = url1
            save_config(config_new)
            show_status("✅ Изменения сохранены!", status)
            return gr.update(visible=True, value="✅ Изменения сохранены!")

        def reset_all():
            config = load_config()
            flat_fields_new = flatten_config(config)
            values = [str(v) for _, v in flat_fields_new]
            url1, url2 = get_default_urls(config)
            show_status("🔄 Сброшено!", status)
            return [url1, url2] + values + [gr.update(visible=True, value="🔄 Сброшено!")]

        def try_cast(val, orig):
            # Приводим к типу оригинального значения
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

        url1.change(update_videos, [url1, url2], [video1, video2])
        url2.change(update_videos, [url1, url2], [video1, video2])
        save_btn.click(save_all, [url1, url2] + list(param_inputs.values()), [status])
        reset_btn.click(reset_all, None, [url1, url2] + list(param_inputs.values()) + [status])

    return demo

def main():
    demo = build_interface()
    demo.launch(server_name="0.0.0.0", server_port=7860)

if __name__ == "__main__":
    main() 