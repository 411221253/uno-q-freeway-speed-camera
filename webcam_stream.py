import cv2
import numpy as np
import urllib.request
import socket
import struct
import pickle
import time

STREAM_URL = "https://cctvn5.freeway.gov.tw/abs2mjpg/bmjpg?camera=f946b673-3ddc-4ed1-a9ab-ef9fe0d4736b"

def connect_mjpeg_stream():
    req = urllib.request.Request(
        STREAM_URL,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://1968.freeway.gov.tw/'
        }
    )
    return urllib.request.urlopen(req, timeout=5)

server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_socket.bind(('0.0.0.0', 9999))
server_socket.listen(5)
print("高公局影像代理伺服器已啟動 (瀏覽器偽裝長連線模式)，等待 UNO Q 板子連線...")

last_frame_gray = None

while True:
    client_socket, addr = server_socket.accept()
    print('收到板子連線自:', addr)
    
    stream = None
    byte_buffer = b""
    
    while True:
        try:
            if stream is None:
                stream = connect_mjpeg_stream()
                byte_buffer = b""
                
            chunk = stream.read(4096)
            if not chunk:
                # 伺服器達到單次連線上限，無縫重新建立連線
                stream.close()
                stream = None
                continue
                
            byte_buffer += chunk
            start_idx = byte_buffer.find(b'\xff\xd8')
            end_idx = byte_buffer.find(b'\xff\xd9')
            
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                jpg_bytes = byte_buffer[start_idx:end_idx + 2]
                byte_buffer = byte_buffer[end_idx + 2:]
                
                frame = cv2.imdecode(np.frombuffer(jpg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    continue
                    
                frame = cv2.resize(frame, (480, 270))
                
                # 過濾重複靜止畫面
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if last_frame_gray is not None:
                    if np.mean(cv2.absdiff(gray, last_frame_gray)) < 0.5:
                        continue
                last_frame_gray = gray
                
                capture_time = time.time()
                payload = (capture_time, frame)
                a = pickle.dumps(payload)
                message = struct.pack("Q", len(a)) + a
                
                try:
                    client_socket.sendall(message)
                except Exception:
                    print("與板子的連線中斷，等待重新連線...")
                    break
                    
                # 預覽視窗繪製 (加粗文字外框提高辨識度)
                preview = frame.copy()
                cv2.line(preview, (45, 215), (370, 215), (0, 165, 255), 2)
                cv2.putText(preview, "LINE 1 (Start)", (50, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 2)
                cv2.line(preview, (45, 155), (320, 155), (255, 200, 0), 2)
                cv2.putText(preview, "LINE 2 (End - 6.8m)", (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 2)
                
                cv2.imshow('Freeway Live Stream (Virtual Speed Trap)', preview)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    if stream: stream.close()
                    client_socket.close()
                    cv2.destroyAllWindows()
                    exit()
                    
        except Exception as e:
            if stream:
                try: stream.close()
                except: pass
            stream = None
            time.sleep(0.2)