import os
import sys
import time
import socket
import json
import threading
import traceback
import tempfile
import webbrowser
import subprocess
import io

# Handle PyInstaller --windowed mode where sys.stdout and sys.stderr are None
class DummyStream:
    def __init__(self, log_path=None):
        self.log_path = log_path

    def write(self, s):
        if self.log_path and s:
            try:
                with open(self.log_path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(str(s))
            except Exception:
                pass
        return len(s) if s else 0

    def flush(self):
        pass

    def isatty(self):
        return False

# Ensure working directory is set to the application directory
if getattr(sys, 'frozen', False):
    base_dir = os.path.dirname(sys.executable)
    meipass = getattr(sys, '_MEIPASS', base_dir)
    bundled_cfg = os.path.join(meipass, 'config_rules.json')
    target_cfg = os.path.join(base_dir, 'config_rules.json')
    if not os.path.exists(target_cfg) and os.path.exists(bundled_cfg):
        import shutil
        try:
            shutil.copy2(bundled_cfg, target_cfg)
        except Exception:
            pass
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

if base_dir:
    try:
        os.chdir(base_dir)
    except Exception:
        pass

log_path = os.path.join(base_dir, "desktop_app.log")

if sys.stdout is None or not hasattr(sys.stdout, 'write'):
    sys.stdout = DummyStream(log_path)
elif hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

if sys.stderr is None or not hasattr(sys.stderr, 'write'):
    sys.stderr = DummyStream(log_path)
elif hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Safely import webview without crashing if pythonnet/WebView2 DLLs are missing
try:
    import webview
except Exception:
    webview = None

# Set a unique WebView2 user data directory to fix HRESULT 0x800700AA (Resource in use file lock)
user_data_dir = os.path.join(tempfile.gettempdir(), f"tucheng_wv2_{os.getpid()}")
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = user_data_dir



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
        print(f"[警告] 預先載入課表資料時發生錯誤: {e}")
        
    local_ip = get_local_ip()
    try:
        from waitress import serve
        print(f"\n==================================================")
        print(f" [系統] 智慧排課系統已啟動 (Waitress WSGI)")
        print(f" [本機電腦] http://127.0.0.1:{port}")
        print(f" [區域網路] http://{local_ip}:{port} (手機/平板在同Wi-Fi連線)")
        print(f" [Render雲端] https://tcsched.onrender.com (全球免開機直連)")
        print(f"==================================================\n")
        serve(app, host=host, port=port, threads=8)
    except Exception as ex:
        print(f"[警告] Waitress 啟動例外, 改用 Flask 開發伺服器: {ex}")
        try:
            app.run(host=host, port=port, debug=False, use_reloader=False)
        except Exception as e2:
            print(f"[錯誤] Flask 伺服器啟動失敗: {e2}")

def launch_standalone_window(url, title):
    """Launches standalone app window using Chrome App mode, Edge App mode, or PyWebView/browser."""
    # Method 1: Chrome / Edge App mode (Standalone desktop window without tabs/address bar)
    browser_paths = [
        # Google Chrome paths (Prioritized)
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        # Microsoft Edge fallback paths
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe")
    ]
    browser_exe = None
    for p in browser_paths:
        if os.path.exists(p):
            browser_exe = p
            break

    if browser_exe:
        try:
            print(f"[資訊] 使用獨立視窗模式開啟: {browser_exe}")
            chrome_user_data = os.path.join(tempfile.gettempdir(), f"tucheng_chrome_{os.getpid()}")
            proc = subprocess.Popen([
                browser_exe, 
                f"--app={url}", 
                f"--window-size=1400,900",
                f"--user-data-dir={chrome_user_data}"
            ])
            # Keep the app alive while the browser window is open.
            start_time = time.time()
            while proc.poll() is None:
                time.sleep(1)
            
            # If the process exited in less than 3 seconds, it was likely delegated
            # to an existing Chrome/Edge process. Keep the server alive so the user can browse it.
            if time.time() - start_time < 3:
                print("[資訊] 瀏覽器視窗已併入現有的瀏覽器程序中。")
                print("[資訊] 伺服器將持續在背景運作，請勿關閉此視窗。按 Ctrl+C 可結束程式。")
                while True:
                    time.sleep(1)
            return True
        except Exception as e:
            print(f"[警告] 獨立視窗模式啟動例外: {e}")

    # Method 2: PyWebView native window
    if webview:
        try:
            window = webview.create_window(
                title=title,
                url=url,
                width=1400,
                height=900,
                min_size=(1024, 700),
                resizable=True,
                text_select=True,
                confirm_close=False
            )
            webview.start(private_mode=False)
            print("[資訊] PyWebView 桌面視窗已關閉。")
            return True
        except Exception as e:
            print(f"[警告] PyWebView 啟動例外: {e}")

    # Method 3: Default Web Browser fallback
    print(f"[資訊] 改用預設瀏覽器開啟 {url}...")
    webbrowser.open(url)
    while True:
        time.sleep(1)
    return True

def main():
    bind_host = "0.0.0.0"
    port = 5000
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    res = sock.connect_ex(("127.0.0.1", port))
    sock.close()
    if res == 0:
        port = get_free_port()

    try:
        load_schedule_data()
    except Exception as e:
        print(f"[警告] 預先載入課表資料時發生錯誤: {e}")

    local_ip = get_local_ip()

    # Start Flask/Waitress server thread
    server_thread = threading.Thread(target=run_server, args=(bind_host, port), daemon=True)
    server_thread.start()

    # Wait until server is ACTUALLY listening on localhost
    print(f"[資訊] 正在等待 Web 伺服器於連接埠 {port} 啟動...")
    for _ in range(100):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.2)
            s.connect(('127.0.0.1', port))
            s.close()
            break
        except Exception:
            time.sleep(0.1)

    url = f"http://127.0.0.1:{port}"
    lan_url = f"http://{local_ip}:{port}" if local_ip and local_ip != "127.0.0.1" else url
    print(f"[資訊] 本機電腦瀏覽網址: {url}")
    print(f"[資訊] 本機教師課表專頁: {url}/teacher")
    print(f"[資訊] 區域網路手機連線: {lan_url}/teacher (請使用 http:// 勿用 https://)")
    print(f"[資訊] ☁️ Render 雲端全球網址: https://tcsched.onrender.com/teacher")
    print(f"[資訊] 系統亮點與 AI 導覽 Showcase: {url}/showcase")
    cfg = {}
    try:
        if os.path.exists("config_rules.json"):
            with open("config_rules.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
    except Exception:
        pass
    school_name = cfg.get("school_name", "學校名稱")
    title = f"智慧排課系統 - {school_name}"

    launch_standalone_window(url, title)

if __name__ == "__main__":
    main()
