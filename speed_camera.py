import cv2
import math

# --- 參數設定區 ---
# 如果要用筆電鏡頭測試，把 'test_video.mp4' 換成 0
video_path = 'test_video.mp4'  

# 比例尺：先隨便設一個數值測試，之後去現場量實際距離再修改
PIXEL_TO_METER = 0.033 
FPS = 30
TIME_PER_FRAME = 1.0 / FPS
SPEED_LIMIT = 30 # 校園速限 30 km/h

# --- 初始化 OpenCV 物件 ---
# 如果用鏡頭測試，可以加上 cv2.CAP_DSHOW 加快啟動，例如 cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap = cv2.VideoCapture(video_path) 
object_detector = cv2.createBackgroundSubtractorMOG2(history=100, varThreshold=40)

tracked_objects = {}
object_id_counter = 0

while True:
    ret, frame = cap.read()
    if not ret:
        break
        
    mask = object_detector.apply(frame)
    _, mask = cv2.threshold(mask, 254, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    
    current_frame_centroids = []
    
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area > 1000: # 面積大於 1000 才算數，避開雜訊
            x, y, w, h = cv2.boundingRect(cnt)
            cx = x + w // 2
            cy = y + h // 2
            current_frame_centroids.append((cx, cy, x, y, w, h))
            
    new_tracked_objects = {}
    
    for (cx, cy, x, y, w, h) in current_frame_centroids:
        object_matched = False
        
        for obj_id, prev_pos in tracked_objects.items():
            prev_cx, prev_cy = prev_pos
            distance = math.hypot(cx - prev_cx, cy - prev_cy)
            
            if distance < 50: 
                distance_meters = distance * PIXEL_TO_METER
                speed_ms = distance_meters / TIME_PER_FRAME
                speed_kmh = speed_ms * 3.6
                
                color = (0, 255, 0)
                if speed_kmh > SPEED_LIMIT:
                    color = (0, 0, 255)
                    
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 3)
                cv2.putText(frame, f"{int(speed_kmh)} km/h", (x, y - 10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                
                new_tracked_objects[obj_id] = (cx, cy)
                object_matched = True
                break
                
        if not object_matched:
            new_tracked_objects[object_id_counter] = (cx, cy)
            object_id_counter += 1
            
    tracked_objects = new_tracked_objects.copy()

    cv2.imshow("Speed Camera - Prototype", frame)
    # 觀察遮罩 (Mask) 效果很有幫助，可以把下面這行取消註解
    # cv2.imshow("Mask", mask) 

    if cv2.waitKey(30) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()