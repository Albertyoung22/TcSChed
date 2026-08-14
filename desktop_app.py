import os
import sys
import time
import socket
import threading
import webview
from app import app, load_schedule_data

def get_free_port():
    """Finds an available free port on localhost."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port

def get_local_ip():
    """Gets the local machine LAN IP address (e.g. 192.168.x.x)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

def run_server(host, port):
    """Runs the WSGI server using Waitress for production performance and stability."""
    try:
        load_schedule_data()
    except Exception as e:
        print(f"Pre-load schedule data error: {e}")
        
    local_ip = get_local_ip()
    try:
        from waitress import serve
        print(f"\n==================================================")
        print(f" 🚀 土城高中課表系統已啟動 (Waitress WSGI Server)")
        print(f" 📍 本機瀏覽網址: http://127.0.0.1:{port}")
        print(f" 🌐 局域網/手機連線網址: http://{local_ip}:{port}")
        print(f"==================================================\n")
        serve(app, host=host, port=port, threads=8)
    except ImportError:
        print(f"Waitress not installed, falling back to Flask dev server...")
        app.run(host=host, port=port, debug=False, use_reloader=False)


def main():
    # Listen on 0.0.0.0 so both localhost and LAN IP can access
    bind_host = "0.0.0.0"
    port = 5000
    
    # Check if port 5000 is available, if not find another
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    res = sock.connect_ex(("127.0.0.1", port))
    sock.close()
    if res == 0:
        # Port 5000 is already occupied by a running server, use free port
        port = get_free_port()

    local_ip = get_local_ip()

    # Start Flask/Waitress server thread listening on 0.0.0.0
    server_thread = threading.Thread(target=run_server, args=(bind_host, port), daemon=True)
    server_thread.start()

    # Give Flask a second to spin up
    time.sleep(1.2)

    url = f"http://127.0.0.1:{port}"
    print(f"Launching Tucheng High School Schedule Desktop App on {url} (LAN IP: http://{local_ip}:{port})...")


    # Read dynamic school name from config_rules.json
    cfg = {}
    try:
        if os.path.exists("config_rules.json"):
            with open("config_rules.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
    except Exception:
        pass
    school_name = cfg.get("school_name", "土城高中")

    # Create native WebView Desktop Window
    window = webview.create_window(
        title=f"{school_name}課表查詢與智慧排課系統 - 桌面版",
        url=url,
        width=1400,
        height=900,
        min_size=(1024, 700),
        resizable=True,
        text_select=True,
        confirm_close=False
    )


    # Start Native GUI loop (Edge Chromium engine on Windows)
    webview.start(private_mode=False)
    print("Desktop Application closed.")

if __name__ == "__main__":
    main()
