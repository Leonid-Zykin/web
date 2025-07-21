from flask import Flask, Response
import cv2

app = Flask(__name__)

RTSP_URL = "rtsp://192.168.0.173:8554/stream"


def generate():
    cap = cv2.VideoCapture(RTSP_URL)
    if not cap.isOpened():
        print(f"[ERROR] Could not open RTSP stream: {RTSP_URL}")
        while True:
            # Пустой кадр-заглушка
            import numpy as np
            blank = np.zeros((480, 640, 3), dtype=np.uint8)
            _, jpeg = cv2.imencode('.jpg', blank)
            frame_bytes = jpeg.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        _, jpeg = cv2.imencode('.jpg', frame)
        frame_bytes = jpeg.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/video')
def video_feed():
    return Response(generate(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True) 