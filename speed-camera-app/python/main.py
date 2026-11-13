import cv2
import numpy as np
import time
import math
import socket
import struct
import pickle

print("邊緣測速儀啟動中 (離去車流方向修正 + 6.8m 實測比例尺校正版)...")

# --- 板載 RGB LED 控制設定 ---
RED_LED_PATH = "/sys/class/leds/unoq:user-red1/brightness"
BLUE_LED_PATH = "/sys/class/leds/unoq:user-blue1/brightness"

def set_led(red_on, blue_on):
    try:
        with open(RED_LED_PATH, "w") as f:
            f.write("1" if red_on else "0")
        with open(BLUE_LED_PATH, "w") as f:
            f.write("1" if blue_on else "0")
    except Exception as e:
        print(f"[LED 控制異常] {e}")

set_led(red_on=False, blue_on=True)

# --- 透過 Socket 連回電腦拿高公局即時畫面 ---
client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
host_ip = '192.168.137.1' 
port = 9999

connected = False
for i in range(10):
    try:
        client_socket.connect((host_ip, port))
        connected = True
        print("成功連接到高公局即時影像串流！")
        break
    except Exception as e:
        print(f"連接失敗，重試中... ({i+1}/10)")
        time.sleep(2)

if not connected:
    set_led(red_on=False, blue_on=False)
    exit()

data = b""
payload_size = struct.calcsize("Q")

# --- 彭山隧道雙線測速幾何校正參數 (車輛由下往上開) ---
LINE_START_Y = 215        # 第一條線 (下方橘線 - 進入測速區)
LINE_END_Y = 155          # 第二條線 (上方藍線 - 離開測速區)
REAL_DISTANCE_M = 6.8     # 依據影片實測白車通過時間反推之精確物理距離 (公尺)
SPEED_LIMIT = 80          # 國道速限 (km/h)

object_detector = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=50, detectShadows=False)
kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

tracked_objects = {}      # {obj_id: (cx, bottom_y)}
cross_start_time = {}     # {obj_id: capture_timestamp}
measured_ids = set()
object_id_counter = 0
overspeed_hold_until = 0

print(f"監測啟動：感應區間 {REAL_DISTANCE_M} 公尺 (由下往上偵測)，速限 {SPEED_LIMIT} km/h")

try:
    while True:
        while len(data) < payload_size:
            packet = client_socket.recv(4*1024)
            if not packet: break
            data += packet
        if len(data) < payload_size: break
        
        packed_msg_size = data[:payload_size]
        data = data[payload_size:]
        msg_size = struct.unpack("Q", packed_msg_size)[0]
        
        while len(data) < msg_size:
            data += client_socket.recv(4*1024)
        frame_data = data[:msg_size]
        data  = data[msg_size:]
        
        capture_time, frame = pickle.loads(frame_data)
        
        # 1. 車道 ROI 遮罩 (包覆完整左右兩車道)
        roi_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        road_polygon = np.array([[(50, 105), (220, 105), (430, 270), (45, 270)]], dtype=np.int32)
        cv2.fillPoly(roi_mask, road_polygon, 255)
        masked_frame = cv2.bitwise_and(frame, frame, mask=roi_mask)
        
        # 2. 背景相減與形態學處理
        mask = object_detector.apply(masked_frame)
        _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        current_vehicles = []
        
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > 800:
                x, y, w, h = cv2.boundingRect(cnt)
                cx = x + w // 2
                bottom_y = y + h  # 車尾輪胎著地點
                current_vehicles.append((cx, bottom_y))
                
        new_tracked = {}
        is_overspeed_now = False
        
        for (cx, bottom_y) in current_vehicles:
            matched_id = None
            min_dist = 95
            
            for obj_id, (prev_cx, prev_by) in tracked_objects.items():
                dist = math.hypot(cx - prev_cx, bottom_y - prev_by)
                # 彭山隧道南下畫面車輛是由下往上開 (bottom_y 遞減)
                if dist < min_dist and (bottom_y - prev_by) <= 5:
                    min_dist = dist
                    matched_id = obj_id
                    
            if matched_id is not None:
                prev_cx, prev_by = tracked_objects[matched_id]
                new_tracked[matched_id] = (cx, bottom_y)
                
                # 判斷車尾著地點由下往上跨過第一條線 (LINE_START_Y = 215)
                if prev_by > LINE_START_Y >= bottom_y and matched_id not in cross_start_time:
                    cross_start_time[matched_id] = capture_time
                    
                # 判斷車尾著地點由下往上跨過第二條線 (LINE_END_Y = 155)
                elif prev_by > LINE_END_Y >= bottom_y and matched_id in cross_start_time and matched_id not in measured_ids:
                    dt = capture_time - cross_start_time[matched_id]
                    # 過濾掉高公局快轉追幀造成的極端小時間差 (dt >= 0.22s，對應最高 111 km/h)
                    if 0.24 <= dt <= 1.2:
                        speed_ms = REAL_DISTANCE_M / dt
                        speed_kmh = speed_ms * 3.6
                        measured_ids.add(matched_id)
                        
                        if speed_kmh > SPEED_LIMIT:
                            is_overspeed_now = True
                            print(f"X[紅燈警報]車輛#{matched_id}實測時速:{speed_kmh:.1f}km/h (超速)")
                        else:
                            print(f"O[藍燈正常]車輛#{matched_id}實測時速:{speed_kmh:.1f}km/h (正常)")
            else:
                new_tracked[object_id_counter] = (cx, bottom_y)
                object_id_counter += 1
                
        tracked_objects = new_tracked.copy()

        # --- RGB LED 燈號控制 ---
        now = time.time()
        if is_overspeed_now:
            overspeed_hold_until = now + 1.2
            set_led(red_on=True, blue_on=False)
        elif now > overspeed_hold_until:
            set_led(red_on=False, blue_on=True)

finally:
    set_led(red_on=False, blue_on=False)
    client_socket.close()