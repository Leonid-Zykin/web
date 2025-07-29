from flask import Flask, Response, abort
import cv2
import threading

app = Flask(__name__)

RTSP_URL = "rtsp://192.168.0.174:8554/stream"

# Глобальные переменные для обмена кадрами между потоками
latest_frame = None
frame_lock = threading.Lock()
stream_alive = threading.Event()


def rtsp_reader():
    import time
    import numpy as np
    import cv2
    from cv2 import FONT_HERSHEY_SIMPLEX

    # Заглушка
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    text = "No signal"
    font = FONT_HERSHEY_SIMPLEX
    font_scale = 2
    color = (255, 255, 255)
    thickness = 3
    text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
    text_x = (blank.shape[1] - text_size[0]) // 2
    text_y = (blank.shape[0] + text_size[1]) // 2
    cv2.putText(blank, text, (text_x, text_y), font, font_scale, color, thickness, cv2.LINE_AA)
    global latest_frame
    global stream_alive

    while True:
        cap = cv2.VideoCapture(RTSP_URL)
        if not cap.isOpened():
            print(f"[ERROR] Could not open RTSP stream: {RTSP_URL}")
            with frame_lock:
                latest_frame = blank.copy()
            stream_alive.clear()
            time.sleep(2)
            continue
        stream_alive.set()
        while True:
            ret, frame = cap.read()
            if not ret:
                print(f"[ERROR] Failed to read frame from RTSP, switching to 'No signal'...")
                with frame_lock:
                    latest_frame = blank.copy()
                stream_alive.clear()
                cap.release()
                time.sleep(2)
                break
            with frame_lock:
                latest_frame = frame.copy()
            stream_alive.set()
            time.sleep(0.01)  # ~100 FPS max, чтобы не грузить CPU
        cap.release()

# Запускаем поток RTSP reader
threading.Thread(target=rtsp_reader, daemon=True).start()

def generate():
    import time
    import numpy as np
    import cv2
    from cv2 import FONT_HERSHEY_SIMPLEX

    # Заглушка
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    text = "No signal"
    font = FONT_HERSHEY_SIMPLEX
    font_scale = 2
    color = (255, 255, 255)
    thickness = 3
    text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
    text_x = (blank.shape[1] - text_size[0]) // 2
    text_y = (blank.shape[0] + text_size[1]) // 2
    cv2.putText(blank, text, (text_x, text_y), font, font_scale, color, thickness, cv2.LINE_AA)
    _, jpeg_blank = cv2.imencode('.jpg', blank)
    frame_bytes_blank = jpeg_blank.tobytes()

    while True:
        with frame_lock:
            frame = latest_frame.copy() if latest_frame is not None else None
        if frame is not None and stream_alive.is_set():
            _, jpeg = cv2.imencode('.jpg', frame)
            frame_bytes = jpeg.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        else:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes_blank + b'\r\n')
        time.sleep(1/25)  # 25 FPS отдачи

@app.route('/video')
def video_feed():
    return Response(generate(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True) 