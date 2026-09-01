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
import atexit
import urllib.request
try:
    import winreg
except ImportError:
    winreg = None

# Robust logging stream for PyInstaller --windowed mode and console mode
class SafeLogStream:
    def __init__(self, log_path=None, original_stream=None, max_bytes=5 * 1024 * 1024):
        self.log_path = log_path
        self.original_stream = original_stream
        self.encoding = "utf-8"
        self.errors = "replace"
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._check_rotation()

    def _check_rotation(self):
        if not self.log_path or not os.path.exists(self.log_path):
            return
        try:
            if os.path.getsize(self.log_path) > self.max_bytes:
                bak_path = self.log_path + ".old"
                if os.path.exists(bak_path):
                    os.remove(bak_path)
                os.rename(self.log_path, bak_path)
        except Exception:
            pass

    def write(self, s):
        if not s:
            return 0
        text = str(s)
        # Write to original stream (console) if available
        if self.original_stream and hasattr(self.original_stream, 'write'):
            try:
                self.original_stream.write(text)
            except Exception:
                pass

        # Write to log file safely
        if self.log_path:
            with self._lock:
                try:
                    with open(self.log_path, "a", encoding="utf-8", errors="replace") as f:
                        f.write(text)
                except Exception:
                    pass
        return len(text)

    def flush(self):
        if self.original_stream and hasattr(self.original_stream, 'flush'):
            try:
                self.original_stream.flush()
            except Exception:
                pass

    def isatty(self):
        if self.original_stream and hasattr(self.original_stream, 'isatty'):
            try:
                return self.original_stream.isatty()
            except Exception:
                return False
        return False

    def writable(self):
        return True

    def readable(self):
        return False

# Ensure working directory is set to the application directory
if getattr(sys, 'frozen', False):
    base_dir = os.path.dirname(sys.executable)
    meipass = getattr(sys, '_MEIPASS', base_dir)
    bundled_cfg = os.path.join(meipass, 'config_rules.json')
    target_cfg = os.path.join(base_dir, 'config_rules.json')
    data_cfg = os.path.join(base_dir, 'data', 'config_rules.json')
    if os.path.exists(bundled_cfg):
        import shutil
        try:
            if not os.path.exists(target_cfg):
                shutil.copy2(bundled_cfg, target_cfg)
            if not os.path.exists(data_cfg):
                os.makedirs(os.path.dirname(data_cfg), exist_ok=True)
                shutil.copy2(bundled_cfg, data_cfg)
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

# Setup safe dual-stream logging (both to console and logfile)
sys.stdout = SafeLogStream(log_path, sys.stdout)
sys.stderr = SafeLogStream(log_path, sys.stderr)

# Safely import webview without crashing if pythonnet/WebView2 DLLs are missing
try:
    import webview
except Exception:
    webview = None

# Dedicated profile directory to retain user window sizing/preferences without cluttering %TEMP%
desktop_profile_dir = os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "School_Schedule_Desktop")
os.makedirs(desktop_profile_dir, exist_ok=True)
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = os.path.join(desktop_profile_dir, "webview2_data")

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
        s.settimeout(0.5)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

def run_server(host, port):
    """Runs the WSGI server using Waitress for production performance and stability."""
    local_ip = get_local_ip()
    try:
        from waitress import serve
        print(f"\n==================================================")
        print(f" [系統] 智慧排課系統已啟動 (Waitress WSGI 高效能模式)")
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

def find_browser_executable():
    """Finds Google Chrome, Microsoft Edge, or other Chromium browsers via Windows Registry and system paths."""
    candidates = []

    # 1. Query Windows Registry for accurate installation paths (even on non-C drives)
    if winreg:
        reg_keys = [
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths\brave.exe"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths\brave.exe"),
        ]
        for root, subkey in reg_keys:
            try:
                with winreg.OpenKey(root, subkey) as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    if val and os.path.exists(val) and val not in candidates:
                        candidates.append(val)
            except Exception:
                pass

    # 2. Standard filesystem paths (Google Chrome prioritized, then Edge, Brave)
    std_paths = [
        # Google Chrome
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        # Microsoft Edge (Fixed 64-bit and 32-bit paths)
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
        # Brave Browser
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    ]
    for p in std_paths:
        if p and os.path.exists(p) and p not in candidates:
            candidates.append(p)

    return candidates[0] if candidates else None

def is_server_ready(port):
    """Verifies that the web server is answering HTTP requests."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"User-Agent": "DesktopApp-HealthCheck"})
        with urllib.request.urlopen(req, timeout=0.6) as resp:
            return resp.status in (200, 302)
    except Exception:
        return False

def launch_standalone_window(url, title):
    """Launches standalone app window using Chrome App mode, Edge App mode, or PyWebView/browser."""
    browser_exe = find_browser_executable()

    if browser_exe:
        try:
            print(f"[資訊] 使用獨立視窗模式開啟: {browser_exe}")
            # Use dedicated profile dir to retain window size/position without filling %TEMP% with hundreds of folders
            chrome_user_data = os.path.join(desktop_profile_dir, "browser_profile")
            os.makedirs(chrome_user_data, exist_ok=True)

            cmd = [
                browser_exe,
                f"--app={url}",
                "--window-size=1440,900",
                "--window-position=center",
                f"--user-data-dir={chrome_user_data}",
                "--disable-features=Translate,OptimizationHints",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-pinch",
                "--disable-sync",
                "--disable-background-networking"
            ]
            proc = subprocess.Popen(cmd)
            
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
                width=1440,
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

    cfg = {}
    current_semester = "115-1"
    try:
        if os.path.exists("config_rules.json"):
            with open("config_rules.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
                current_semester = cfg.get("current_semester", "115-1")
    except Exception:
        pass
    school_name = cfg.get("school_name", "學校名稱")
    title = f"智慧排課系統 - {school_name} ({current_semester}學期)"

    # Single Instance Detection: If 5000 is already active and running this system, just bring up the window
    if is_server_ready(port):
        print(f"[資訊] 偵測到智慧排課系統已在背景執行中 (連接埠 {port})，直接開啟視窗...")
        url = f"http://127.0.0.1:{port}"
        launch_standalone_window(url, title)
        return

    # Check if port 5000 is occupied by something else
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    res = sock.connect_ex(("127.0.0.1", port))
    sock.close()
    if res == 0:
        port = get_free_port()

    # Load schedule data once before starting server thread
    try:
        load_schedule_data()
    except Exception as e:
        print(f"[警告] 預先載入課表資料時發生錯誤: {e}")

    local_ip = get_local_ip()

    # Start Flask/Waitress server thread
    server_thread = threading.Thread(target=run_server, args=(bind_host, port), daemon=True)
    server_thread.start()

    # Wait until HTTP server is ACTUALLY answering requests
    print(f"[資訊] 正在等待 Web 伺服器於連接埠 {port} 啟動...")
    for _ in range(120):
        if is_server_ready(port):
            break
        time.sleep(0.1)

    url = f"http://127.0.0.1:{port}"
    lan_url = f"http://{local_ip}:{port}" if local_ip and local_ip != "127.0.0.1" else url
    print(f"[資訊] 本機電腦瀏覽網址: {url}")
    print(f"[資訊] 本機教師課表專頁: {url}/teacher")
    print(f"[資訊] 區域網路手機連線: {lan_url}/teacher (請使用 http:// 勿用 https://)")
    print(f"[資訊] ☁️ Render 雲端全球網址: https://tcsched.onrender.com/teacher")
    print(f"[資訊] 系統亮點與 AI 導覽 Showcase: {url}/showcase")

    launch_standalone_window(url, title)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[系統] 收到中斷信號 (Ctrl+C)，智慧排課系統已安全關閉。")
        sys.exit(0)
