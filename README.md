基於 Arduino UNO Q 之國道邊緣視覺測速與超速警示系統

本專案利用台灣高速公路局即時路況影像串流（國道五號南下 11K+873 彭山隧道，法定最高速限 80 km/h），在 Arduino UNO Q 邊緣運算平台上實現即時車輛偵測、雙虛擬感應線區間測速，並直接驅動板載 RGB LED 進行實體燈號警示。

一、 系統架構與運作原理
=============================================

1. 影像擷取與網路代理層（Host PC 端：webcam_stream.py）
  - 透過 HTTP 偽裝標頭（User-Agent 與 Referer）抓取高公局即時 MJPEG 串流，並具備單次連線逾時無縫自動重連機制。
  - 將畫面統一縮放為 480x270 解析度，內建防重複靜止幀濾波（cv2.absdiff），在確認取得新畫面的當下寫入真實擷取時間戳記（capture_time），避免網路緩衝延遲影響測速準確度。
  - 透過 Socket TCP（Port 9999）將即時影像與時間戳記封包傳送至 Arduino UNO Q，並於本機預覽視窗繪製橘色起點線（y = 219）與藍色終點線（y = 132）供視覺監控。

2. 邊緣視覺與區間測速層（Arduino UNO Q 端：speed-camera-app/python/main.py）
  - 車道 ROI 遮罩：建立多邊形遮罩鎖定左右兩線行車道，排除隧道頂部照明燈具反光與左側維修通道干擾。
  - 車輛前景擷取：採用 MOG2 背景相減法（關閉陰影偵測）結合 5x5 橢圓結構元素型態學閉運算（MORPH_CLOSE），過濾雜訊並完整聚合車輛輪廓。
  - 車底著地點追蹤與雙線區間測速：以車輛外框下緣（bottom_y = y + h）追蹤由下往上行駛之離去車流；對照隧道內路側緣石反光標記 6 個標準間隔，精準標定起點線（y = 219）與終點線（y = 132）間實際物理距離為 6.0 公尺。
  - 合理通過時間窗過濾：設定 0.18s <= dt <= 1.2s 保護區間（排除網路追幀或追蹤跳動極端值），單車依序通過雙線後計算平均時速 v = (6.0 / dt) * 3.6。

3. 容器權限與硬體警示層（speed-camera-app/app.yaml）
  - 採用 arduino/python-apps-base:0.1.0 映像檔，設定 network_mode: "host" 與 privileged: true，並掛載 /sys/class/leds 系統節點。
  - 依彭山隧道法定速限 80 km/h 進行狀態切換：正常車流維持穩定藍燈（unoq:user-blue1）；偵測超速（> 80 km/h）時立即切換為醒目紅燈警報（unoq:user-red1）並強制維持 1.2 秒。

二、 專案目錄結構
=============================================

uno-q-freeway-speed-camera/
├── README.md                          # 專案說明文件
├── webcam_stream.py                   # 電腦端高公局串流擷取與 Socket 代理程式
└── speed-camera-app/
    ├── app.yaml                       # Arduino UNO Q 容器網路與硬體裝置掛載設定
    └── python/
        └── main.py                    # 板子端 ROI 處理、雙線區間測速與 RGB LED 控制


三、 執行步驟（視窗 A / C / B 啟動順序與指令）
=============================================

本系統需在電腦端開啟三個終端機視窗協同運作，建議依照「視窗 A -> 視窗 C -> 視窗 B」的順序啟動，確保影像伺服器就緒後板子能立即連線。

【步驟 1：視窗 A（Host PC 終端機）－ 下載專案、建立通道與部署程式】
開啟第一個終端機視窗，從 GitHub 下載本專案、建立 USB SSH 轉發通道並將應用程式推送至 Arduino UNO Q：

1. 下載專案並進入專案目錄：
   git clone https://github.com/411221253/uno-q-freeway-speed-camera.git
   cd uno-q-freeway-speed-camera

2. 建立本機 2222 埠轉發至板子 22 埠（若未設定 ADB 環境變數請指定 adb.exe 完整路徑）：
   adb forward tcp:2222 tcp:22

3. 將板子端應用程式推送至開發板：
   adb push speed-camera-app /home/arduino/ArduinoApps/


【步驟 2：視窗 C（Host PC 終端機）－ 啟動高公局即時影像代理伺服器】
開啟第二個終端機視窗，先啟動電腦端 Socket 伺服器（Port 9999），等待板子前來連線：

1. 進入專案目錄：
   cd uno-q-freeway-speed-camera

2. 啟動即時影像串流與預覽視窗（需先安裝 opencv-python 與 numpy）：
   python webcam_stream.py

- 執行後終端機將顯示「高公局影像代理伺服器已啟動 (瀏覽器偽裝長連線模式)，等待 UNO Q 板子連線...」。


【步驟 3：視窗 B（Host PC 終端機）－ SSH 登入板子並啟動邊緣測速】
開啟第三個終端機視窗，透過剛建立的轉發埠登入板子並啟動容器服務：

1. 透過 SSH 連線進入 Arduino UNO Q（預設密碼為 arduino）：
   ssh -p 2222 arduino@127.0.0.1

2. 啟動邊緣測速應用程式：
   arduino-app-cli app start ~/ArduinoApps/speed-camera-app

- 此時視窗 C 會顯示「收到板子連線自: ...」並彈出即時監控畫面（含橘色起點線與藍色終點線）。

3. 查看即時測速與燈號狀態紀錄（Log）：
   arduino-app-cli app logs ~/ArduinoApps/speed-camera-app --tail 30

- 終端機將即時輸出每輛通過車輛的實測時速，超過 80 km/h 時板載 LED 將由藍燈切換為紅燈警報。


【步驟 4：測試結束與安全關機流程】
1. 視窗 B（板子端）：先停止應用程式再安全關閉 Linux 系統，避免檔案系統損毀：
   arduino-app-cli app stop ~/ArduinoApps/speed-camera-app
   sudo poweroff

2. 視窗 C（電腦端）：在預覽視窗按 'q' 鍵或於終端機按 Ctrl + C 結束串流程式，再關閉所有視窗並拔除硬體連接線。
