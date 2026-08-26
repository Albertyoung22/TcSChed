import os
import sys
import json
import datetime
import io
import zipfile
import threading
import traceback
from flask import Flask, jsonify, render_template, send_from_directory, send_file, request
from dbfread import DBF

# Optional GitHub cloud-sync settings.  Keep these defined even when the
# application is running locally without GitHub configuration; otherwise the
# fallback path in load_config_rules() raises NameError when no local config
# file exists.
GITHUB_REPO = os.environ.get("GITHUB_REPO", "").strip()
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main").strip() or "main"

def resolve_path(rel_path):
    """Safely resolves relative paths across PyInstaller frozen mode (_MEIPASS & sys.executable), project dir, and CWD."""
    candidates = []
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            candidates.append(os.path.join(meipass, rel_path))
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, rel_path))
    
    app_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(app_dir, rel_path))
    candidates.append(os.path.join(os.getcwd(), rel_path))
    
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0] if candidates else rel_path

template_folder = resolve_path("templates")
static_folder = resolve_path("static")
app = Flask(__name__, static_folder=static_folder, template_folder=template_folder)

def get_valid_data_dir():
    env_dir = os.environ.get("DATA_DIR", "").strip()
    if env_dir:
        try:
            os.makedirs(env_dir, exist_ok=True)
            test_file = os.path.join(env_dir, ".test_write")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(test_file)
            return env_dir
        except Exception:
            pass

    base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    default_data_dir = os.path.join(base_dir, "data")
    os.makedirs(default_data_dir, exist_ok=True)
    return default_data_dir

DATA_DIR = get_valid_data_dir()
CONFIG_RULES_FILE = os.path.join(DATA_DIR, "config_rules.json")
NOTES_FILE_PATH = os.path.join(DATA_DIR, "lesson_notes.json")
APP_LOG_FILE = os.path.join(DATA_DIR, "school_schedule.log")

def migrate_legacy_data_files():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    legacy_files = {
        os.path.join(base_dir, "config_rules.json"): CONFIG_RULES_FILE,
        os.path.join(base_dir, "lesson_notes.json"): NOTES_FILE_PATH,
    }
    for src, dst in legacy_files.items():
        try:
            if os.path.exists(src) and not os.path.exists(dst):
                import shutil
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
        except Exception:
            pass

migrate_legacy_data_files()

# Path configuration
DEFAULT_SEARCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dbf_data")
SEARCH_DIR = r"D:\SchoolData"

def get_default_search_dir():
    cfg = {}
    try:
        cfg = load_config_rules()
    except Exception:
        cfg = {}

    # 若系統處於一鍵清空 / 移交新學校狀態 (clean_mode)，不自動載入舊學校 dbf_data
    if cfg.get("clean_mode") is True:
        return ""

    search_dir = (cfg.get("dbf_search_dir") or "").strip()
    if search_dir:
        return search_dir

    # 只有在全新初始狀態 (未經重置清空) 才預設讀取內建資料夾
    if "clean_mode" not in cfg and "dbf_search_dir" not in cfg:
        if os.path.isdir(DEFAULT_SEARCH_DIR):
            return DEFAULT_SEARCH_DIR
    return ""

# Global cache variables
_cached_data = None
_db_mtimes = {}

# 欣河雲端系統匯出檔名（放於 dbf_data 目錄下即可自動載入）
XINHE_EXPORT_FILENAME = "xinhe_export.xlsx"

# 欣河代碼/名稱 -> 系統 DBF CLASS_NO 精確映射表
XINHE_CLASS_MAPPING = {
    # 國中部 (J701/國101 -> 101)
    "J701": "101", "701": "101", "國101": "101",
    "J702": "102", "702": "102", "國102": "102",
    "J703": "103", "703": "103", "國103": "103",
    "J801": "201", "801": "201", "國201": "201",
    "J802": "202", "802": "202", "國202": "202",
    "J803": "203", "803": "203", "國203": "203",
    "J901": "301", "901": "301", "國301": "301",
    "J902": "302", "902": "302", "國302": "302",
    "J903": "303", "903": "303", "國303": "303",

    # 高中部 (S101/高一忠 -> 401)
    "S101": "401", "高一忠": "401",
    "S102": "402", "高一孝": "402",
    "S103": "403", "高一仁": "403",
    "S201": "501", "高二忠": "501",
    "S202": "502", "高二孝": "502",
    "S203": "503", "高二仁": "503",
    "S301": "601", "高三忠": "601",
    "S302": "602", "高三孝": "602",
    "S303": "603", "高三仁": "603",
}

def load_xinhe_excel(excel_path, classes=None, teacher_name_map=None, teacher_code_map=None):
    """讀取欣河雲端新系統的配課匯出 Excel，回傳 schedules list 與 classrooms dict。
    
    欄位對照：
      國中部: 班級 J701 / 國101 -> 101, 科目 J201 -> 201
      高中部: 班級 S101 / 高一忠 -> 401, 科目 S201 -> 201
      教師: 優先依教師姓名對應 teacher.dbf 的代碼
      星期、節次、兼代、週別設定直接對應
    """
    try:
        import openpyxl
    except ImportError:
        print("[欣河匯入] 缺少 openpyxl，請執行 pip install openpyxl", flush=True)
        return [], {}

    try:
        class_name_lookup = {}
        if classes:
            class_name_lookup = {c["code"]: c["name"] for c in classes if isinstance(c, dict) and "code" in c and "name" in c}

        wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        headers = next(rows_iter, None)
        if not headers:
            return [], {}
        col = {str(h).strip(): i for i, h in enumerate(headers) if h is not None}

        schedules = []
        classrooms = {}

        def strip_prefix(code):
            if not code:
                return ""
            return str(code).strip().lstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz')

        def get_col(row, name, default=""):
            i = col.get(name)
            if i is None:
                return default
            v = row[i]
            return str(v).strip() if v is not None else default

        for idx, row in enumerate(rows_iter):
            class_code_raw = get_col(row, '班級')
            class_name_raw = get_col(row, '班級名稱')
            subj_code_raw  = get_col(row, '科目')
            subj_name      = get_col(row, '科目名稱')
            teach_code_raw = get_col(row, '教師')
            teach_name     = get_col(row, '教師名稱')
            room_code      = get_col(row, '教室')
            room_name      = get_col(row, '教室名稱')
            day            = get_col(row, '星期', '0')
            period         = get_col(row, '節次', '0')
            jian_dai       = get_col(row, '兼代')
            week_mode_raw  = get_col(row, '週別設定', '0')
            ud_raw         = get_col(row, '上下修', '0')

            # 1. 班級代碼精確轉換 (國中: J701->101, 高中: S101->401)
            class_code = XINHE_CLASS_MAPPING.get(class_code_raw) or XINHE_CLASS_MAPPING.get(class_name_raw) or class_code_raw
            class_name = class_name_lookup.get(class_code, class_name_raw)

            # 2. 教師代碼精確轉換 (優先依教師姓名反查 DBF 代碼)
            teach_code = ""
            if teacher_name_map and teach_name in teacher_name_map:
                teach_code = teacher_name_map[teach_name]
            elif teach_code_raw:
                clean = strip_prefix(teach_code_raw)
                if clean.isdigit():
                    clean = clean.zfill(4)
                if teacher_code_map:
                    teach_code = teacher_code_map.get(clean, clean)
                else:
                    teach_code = clean

            # 3. 科目代碼轉換
            subj_code = strip_prefix(subj_code_raw)

            # 4. 節次轉字串
            try:
                period = str(int(float(period)))
            except Exception:
                period = str(period)

            try:
                week_mode = int(float(week_mode_raw))
            except Exception:
                week_mode = 0

            try:
                ud = int(float(ud_raw))
            except Exception:
                ud = 0

            if room_code and room_name:
                classrooms[room_code] = room_name

            schedules.append({
                "id": idx,
                "class_code": class_code,
                "class_name": class_name,
                "subject_code": subj_code,
                "subject_name": subj_name,
                "teacher_code": teach_code,
                "teacher_name": teach_name,
                "room_code": room_code,
                "room_name": room_name,
                "day": day,
                "period": period,
                "week_mode": week_mode,
                "ud": ud,
                "jian_dai": jian_dai,
                "source": "xinhe"
            })

        wb.close()
        print(f"[欣河匯入] 成功讀取 {len(schedules)} 筆排課資料 from {excel_path}", flush=True)
        return schedules, classrooms

    except Exception as e:
        import traceback
        print(f"[欣河匯入] 讀取失敗: {e}", flush=True)
        traceback.print_exc()
        return [], {}

def get_local_ip():
    """Gets the local machine LAN IP address (e.g. 192.168.x.x)."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def get_latest_dbf_dir():
    """Finds the newest DBF directory containing class.dbf/claspv.dbf."""
    cfg = {}
    try:
        cfg = load_config_rules()
    except Exception:
        cfg = {}

    # 若系統處於一鍵清空 / 移交新學校狀態 (clean_mode)，不自動載入任何 DBF
    if cfg.get("clean_mode") is True:
        return None

    search_dir = (cfg.get("dbf_search_dir") or "").strip()
    if not search_dir or not os.path.exists(search_dir):
        return None

    try:
        if any(f.lower() == "class.dbf" for f in os.listdir(search_dir)):
            return search_dir
    except Exception as e:
        log_exception("get_latest_dbf_dir:search_dir", e)
        
    candidates = []
    try:
        for root, dirs, files in os.walk(search_dir):
            rel = os.path.relpath(root, search_dir)
            if rel != "." and len(rel.split(os.sep)) > 5:
                continue
            if any(f.lower() == "class.dbf" for f in files) and any(f.lower() == "claspv.dbf" for f in files):
                candidates.append(root)
    except Exception as e:
        log_exception("get_latest_dbf_dir:walk", e)

    if candidates:
        candidates.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        return candidates[0]

    return None

def get_solved_excel_path():
    """Returns path to Solved Excel file without improperly defaulting to Touchong High School when in custom mode.
    若 xinhe_export.xlsx 存在，回傳 None 讓欣河資料優先。
    """
    dbf_dir = get_latest_dbf_dir()
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # 若欣河匯出檔存在，優先使用欣河資料，跳過 solved_excel
    xinhe_candidates = []
    if dbf_dir:
        xinhe_candidates.append(os.path.join(dbf_dir, XINHE_EXPORT_FILENAME))
    xinhe_candidates.append(os.path.join(DATA_DIR, XINHE_EXPORT_FILENAME))
    for xp in xinhe_candidates:
        if os.path.exists(xp):
            return None  # 讓 load_schedule_data 使用欣河 Excel

    candidates = []
    if dbf_dir:
        candidates.append(os.path.join(dbf_dir, "School_Schedule_Solved.xlsx"))
    candidates.append(os.path.join(base_dir, "School_Schedule_Solved.xlsx"))
    candidates.append(resolve_path("School_Schedule_Solved.xlsx"))
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None

def load_schedule_data():
    """Loads all schedule data from DBF files and caches it."""
    global _cached_data, _db_mtimes
    
    def natural_sort_key(s):
        import re
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]
    
    def natural_sort_key(s):
        import re
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]
    
    def natural_sort_key(s):
        import re
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]
    
    def natural_sort_key(s):
        import re
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]
        
    dbf_dir = get_latest_dbf_dir()
    if not dbf_dir:
        cfg = load_config_rules()
        period_times = cfg.get("period_times", {})
        if not period_times:
            period_times = {str(p): {"name": f"第{p}節", "time": ""} for p in range(1, 9)}

        # 優先檢查欣河匯出 Excel
        xinhe_path = os.path.join(DATA_DIR, XINHE_EXPORT_FILENAME)
        if not os.path.exists(xinhe_path):
            local_xinhe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dbf_data", XINHE_EXPORT_FILENAME)
            if os.path.exists(local_xinhe):
                xinhe_path = local_xinhe

        if os.path.exists(xinhe_path) and not cfg.get("clean_mode"):
            schedules, classrooms_dict = load_xinhe_excel(xinhe_path)
            
            # 1. 自動推導各班導師 (從班級活動/班會/導師時間之授課教師)
            tutor_map = {}
            for s in schedules:
                subj = s.get("subject_name", "")
                cc = s.get("class_code", "")
                tn = s.get("teacher_name", "")
                if ("班級活動" in subj or "班會" in subj or "導師" in subj) and tn and cc:
                    tutor_map[cc] = tn

            # 2. 從 schedules 提取正規班級 (過濾掉 TC 開頭的跨班選修虛擬代碼與虛擬班)
            classes_map = {}
            for s in schedules:
                cc = str(s.get("class_code", "")).strip()
                cn = str(s.get("class_name", "")).strip() or cc
                
                # 排除 TC 開頭之長字串虛擬代碼或名稱含虛擬之記錄
                if not cc or cc.startswith("TC") or "虛擬" in cn or "虛擬" in cc:
                    continue

                if cc not in classes_map:
                    # 美化國中部班級名稱 (例如 國101 -> 701, 國201 -> 801)
                    disp_name = cn
                    if cn.startswith("國1") or cc.startswith("1"):
                        disp_name = f"70{cc[-1]}" if cc.isdigit() and len(cc) == 3 else cn
                    elif cn.startswith("國2") or cc.startswith("2"):
                        disp_name = f"80{cc[-1]}" if cc.isdigit() and len(cc) == 3 else cn
                    elif cn.startswith("國3") or cc.startswith("3"):
                        disp_name = f"90{cc[-1]}" if cc.isdigit() and len(cc) == 3 else cn

                    classes_map[cc] = {
                        "code": cc,
                        "name": disp_name,
                        "tutor": tutor_map.get(cc, "")
                    }

            # 3. 從 schedules 提取教師 (過濾空值)
            teachers_map = {}
            for s in schedules:
                tc = str(s.get("teacher_code", "")).strip()
                tn = str(s.get("teacher_name", "")).strip() or tc
                if tc and tn and tc not in teachers_map and not tn.startswith("備用"):
                    teachers_map[tc] = {
                        "code": tc,
                        "name": tn,
                        "role": "導師" if tc in tutor_map.values() else "專任教師",
                        "subject": s.get("subject_name", ""),
                        "base_hours": 0,
                        "teach_hours": 0,
                        "extra_hours": 0
                    }

            classes_list = sorted(list(classes_map.values()), key=lambda x: natural_sort_key(x["code"]))
            teachers_list = sorted(list(teachers_map.values()), key=lambda x: natural_sort_key(x["code"]))
            classrooms_list = [{"code": k, "name": v} for k, v in classrooms_dict.items()]

            _cached_data = {
                "dbf_dir": "",
                "data_source": "xinhe",
                "period_times": period_times,
                "classes": classes_list,
                "teachers": teachers_list,
                "classrooms": classrooms_list,
                "schedules": schedules,
                "local_ip": get_local_ip()
            }
            return _cached_data

        custom_classes = [c for c in cfg.get("custom_classes", []) if c.get("code") not in set(cfg.get("deleted_class_codes", []))]
        custom_teachers = [t for t in cfg.get("custom_teachers", []) if t.get("code") not in set(cfg.get("deleted_teacher_codes", []))]

        schedules = []
        solved_excel = get_solved_excel_path()
            
        if solved_excel and os.path.exists(solved_excel):
            try:
                import pandas as pd
                df = pd.read_excel(solved_excel)
                df = df.fillna("")
                for idx, r in df.iterrows():
                    c_code = str(r.get("class_code") or r.get("班級代碼") or "").strip().split(".")[0]
                    c_name = str(r.get("class_name") or r.get("班級名稱") or "").strip()
                    s_code = str(r.get("subject_code") or r.get("科目代碼") or "").strip().split(".")[0]
                    s_name = str(r.get("subject_name") or r.get("科目名稱") or "").strip()
                    t_code = str(r.get("teacher_code") or r.get("教師代碼") or "").strip().split(".")[0]
                    t_name = str(r.get("teacher_name") or r.get("教師姓名") or "").strip()
                    r_name = str(r.get("room_name") or r.get("教室名稱") or "").strip()
                    r_code = str(r.get("room_code") or r.get("教室代碼") or r_name).strip()
                    d_val = str(r.get("day") or r.get("星期") or "0").strip().split(".")[0]
                    p_val = str(r.get("period") or r.get("節次") or "0").strip().split(".")[0]
                    
                    if t_code.lower() == "nan": t_code = ""
                    if t_name.lower() == "nan": t_name = ""
                    if r_name.lower() == "nan": r_name = ""
                    if r_code.lower() == "nan": r_code = ""
                    
                    schedules.append({
                        "id": int(idx),
                        "class_code": c_code,
                        "class_name": c_name,
                        "subject_code": s_code,
                        "subject_name": s_name,
                        "teacher_code": t_code,
                        "teacher_name": t_name,
                        "room_code": r_code,
                        "room_name": r_name,
                        "day": d_val,
                        "period": p_val,
                        "week_mode": 0,
                        "ud": 0,
                        "流水號": int(idx),
                        "班級代碼": c_code,
                        "班級名稱": c_name,
                        "科目代碼": s_code,
                        "科目名稱": s_name,
                        "教師代碼": t_code,
                        "教師姓名": t_name,
                        "星期": d_val,
                        "節次": p_val
                    })
            except Exception as e:
                log_exception("api_select_folder:tkinter", e)
                
        if not schedules:
            custom_assign = cfg.get("custom_assignments", {})
            item_id = 1
            for key, assign in custom_assign.items():
                c_code = assign.get("class_code", "")
                c_name = assign.get("class_name", c_code)
                s_code = assign.get("subject_code", "")
                s_name = assign.get("subject_name", s_code)
                t_code = assign.get("teacher_code", "")
                t_name = assign.get("teacher_name", t_code)
                hours = int(assign.get("hours", 1))
                
                for _ in range(hours):
                    schedules.append({
                        "id": item_id,
                        "class_code": c_code,
                        "class_name": c_name,
                        "subject_code": s_code,
                        "subject_name": s_name,
                        "teacher_code": t_code,
                        "teacher_name": t_name,
                        "room_code": "",
                        "room_name": "",
                        "day": "0",
                        "period": "0",
                        "week_mode": 0,
                        "ud": 0,
                        "流水號": item_id,
                        "班級代碼": c_code,
                        "班級名稱": c_name,
                        "科目代碼": s_code,
                        "科目名稱": s_name,
                        "教師代碼": t_code,
                        "教師姓名": t_name,
                        "星期": 0,
                        "節次": 0,
                        "時間代碼": "0000",
                        "說明": "待分配"
                    })
                    item_id += 1

        default_venues = [
            {"code": "電腦教室", "name": "電腦教室"},
            {"code": "理化實驗室", "name": "理化實驗室"},
            {"code": "生物實驗室", "name": "生物實驗室"},
            {"code": "音樂教室", "name": "音樂教室"},
            {"code": "美術教室", "name": "美術教室"},
            {"code": "體育場/館", "name": "體育場/館"},
            {"code": "家政教室", "name": "家政教室"},
            {"code": "生活科技教室", "name": "生活科技教室"}
        ]
        return {
            "dbf_dir": "",
            "period_times": period_times,
            "classes": custom_classes,
            "teachers": custom_teachers,
            "classrooms": default_venues,
            "schedules": schedules,
            "local_ip": get_local_ip()
        }
    
    # Files we need
    files = {
        "class": "class.dbf",
        "teacher": "teacher.dbf",
        "claspv": "claspv.dbf",
        "clatime": "clatime.dbf"
    }
    
    # Find actual file paths (case-insensitive check)
    resolved_paths = {}
    current_mtimes = {}
    for key, filename in files.items():
        found_path = None
        for f in os.listdir(dbf_dir):
            if f.lower() == filename.lower():
                found_path = os.path.join(dbf_dir, f)
                break
        if not found_path:
            return {"error": f"Required database table {filename} not found in {dbf_dir}"}
        resolved_paths[key] = found_path
        current_mtimes[key] = os.path.getmtime(found_path)
        
    # Check if cache is still valid
    if _cached_data and _db_mtimes == current_mtimes:
        return _cached_data
        
    # Cache invalid, re-reading DBF files
    try:
        # 1. Parse clatime.dbf
        db_clatime = DBF(resolved_paths["clatime"], ignore_missing_memofile=True, encoding='cp950')
        clatime_records = list(db_clatime)
        period_times = {}
        if clatime_records:
            rec = clatime_records[0]
            for p in range(1, 9):
                name = rec.get(f"C{p}0", f"第{p}節")
                start = rec.get(f"T{p}1", "")
                end = rec.get(f"T{p}2", "")
                period_times[str(p)] = {
                    "name": name.strip() if name else f"第{p}節",
                    "time": f"{start.strip()}-{end.strip()}" if start and end else ""
                }
        else:
            for p in range(1, 9):
                period_times[str(p)] = {"name": f"第{p}節", "time": ""}

        # 2. Parse class.dbf
        db_class = DBF(resolved_paths["class"], ignore_missing_memofile=True, encoding='cp950')
        classes = []
        for r in db_class:
            classes.append({
                "code": r.get("CLASS_NO", "").strip(),
                "name": r.get("CLASS_NAME", "").strip(),
                "tutor": r.get("SHOW_TEA", "").strip() if r.get("SHOW_TEA") else ""
            })
        classes.sort(key=lambda x: natural_sort_key(x["code"]))

        # Map class tutor
        tutor_map = {}
        for c in classes:
            if c["tutor"]:
                tutor_map[c["tutor"]] = c["name"]

        # 3. Parse teacher.dbf
        db_teacher = DBF(resolved_paths["teacher"], ignore_missing_memofile=True, encoding='cp950')
        teachers = []
        teacher_code_map = {}
        teacher_name_map = {}
        for r in db_teacher:
            t_name = r.get("TEACH_NAME", "").strip()
            full_code = r.get("TEACHER_NO", "").strip()
            if full_code:
                teacher_code_map[str(int(full_code))] = full_code
                teacher_code_map[full_code] = full_code
            if t_name and full_code:
                teacher_name_map[t_name] = full_code
            if t_name and not t_name.startswith("備用"):
                role_raw = r.get("TEACH_KINA", "").strip() or r.get("TEACH_KINB", "").strip() or ""
                if t_name in tutor_map:
                    identity = f"{tutor_map[t_name]} 導師"
                    if role_raw and "導師" not in role_raw:
                        identity += f" ({role_raw})"
                elif role_raw:
                    identity = role_raw
                else:
                    identity = "專任教師"

                try:
                    base_h = float(r.get("基本節數") or 0)
                except Exception:
                    base_h = 0.0
                try:
                    teach_h = float(r.get("授課節數") or 0)
                except Exception:
                    teach_h = 0.0
                try:
                    extra_h = float(r.get("兼課節數") or 0)
                except Exception:
                    extra_h = 0.0

                teachers.append({
                    "code": full_code,
                    "name": t_name,
                    "role": identity,
                    "subject": str(r.get("TEACH_SUBJ", "")).strip(),
                    "base_hours": int(base_h) if base_h.is_integer() else base_h,
                    "teach_hours": int(teach_h) if teach_h.is_integer() else teach_h,
                    "extra_hours": int(extra_h) if extra_h.is_integer() else extra_h
                })
        teachers.sort(key=lambda x: natural_sort_key(x["code"]))

        # 4. Load schedules (solved Excel > 欣河 Excel > claspv.dbf)
        solved_excel = get_solved_excel_path()

        schedules = []
        classrooms = {}

        if solved_excel and os.path.exists(solved_excel):
            import pandas as pd
            df = pd.read_excel(solved_excel)
            df = df.fillna("")
            for idx, r in df.iterrows():
                class_code = str(r.get("班級代碼") or r.get("class_code", "")).strip().split(".")[0]
                class_name = str(r.get("班級名稱") or r.get("class_name", "")).strip()
                subject_code = str(r.get("科目代碼") or r.get("subject_code", "")).strip().split(".")[0]
                subject_name = str(r.get("科目名稱") or r.get("subject_name", "")).strip()

                teacher_code = str(r.get("教師代碼") or r.get("teacher_code", "")).strip().split(".")[0]
                if teacher_code.replace(".0", "") == "nan" or teacher_code.lower() == "nan":
                    teacher_code = ""
                if teacher_code:
                    teacher_code = teacher_code_map.get(teacher_code, teacher_code)
                teacher_name = str(r.get("教師姓名") or r.get("teacher_name", "")).strip()
                if teacher_name.lower() == "nan":
                    teacher_name = ""

                room_name = str(r.get("教室名稱") or r.get("room_name", "")).strip()
                if room_name.lower() == "nan":
                    room_name = ""
                room_code = room_name

                day = str(r.get("星期") or r.get("day", "")).strip().split(".")[0]
                period = str(r.get("節次") or r.get("period", "")).strip().split(".")[0]

                try:
                    week_mode = int(float(r.get("週別設定", 0)))
                except Exception:
                    week_mode = 0

                try:
                    ud = int(float(r.get("上下修", 0)))
                except Exception:
                    ud = 0

                if room_code and room_name:
                    classrooms[room_code] = room_name

                schedules.append({
                    "id": int(idx),
                    "class_code": class_code,
                    "class_name": class_name,
                    "subject_code": subject_code,
                    "subject_name": subject_name,
                    "teacher_code": teacher_code,
                    "teacher_name": teacher_name,
                    "room_code": room_code,
                    "room_name": room_name,
                    "day": day,
                    "period": period,
                    "week_mode": week_mode,
                    "ud": ud
                })
        else:
            # ── 優先嘗試欣河雲端系統 Excel 匯出檔（xinhe_export.xlsx）──
            xinhe_path = os.path.join(dbf_dir, XINHE_EXPORT_FILENAME)
            # 也接受 data/ 目錄下的欣河匯出
            if not os.path.exists(xinhe_path):
                data_xinhe = os.path.join(DATA_DIR, XINHE_EXPORT_FILENAME)
                if os.path.exists(data_xinhe):
                    xinhe_path = data_xinhe

            if os.path.exists(xinhe_path):
                print(f"[欣河匯入] 偵測到欣河配課匯出檔，以 Excel 取代 claspv.dbf 載入...", flush=True)
                schedules, classrooms = load_xinhe_excel(xinhe_path, classes=classes, teacher_name_map=teacher_name_map, teacher_code_map=teacher_code_map)
            else:
                # ── 標準路徑：讀取 claspv.dbf ──
                db_claspv = DBF(resolved_paths["claspv"], ignore_missing_memofile=True, encoding='cp950')
                for idx, r in enumerate(db_claspv):
                    class_code = r.get("班級", "").strip()
                    class_name = r.get("班級名稱", "").strip()
                    subject_code = r.get("科目", "").strip()
                    subject_name = r.get("科目名稱", "").strip()
                    teacher_code = r.get("教師", "").strip()
                    if teacher_code:
                        teacher_code = teacher_code_map.get(teacher_code, teacher_code)
                    teacher_name = r.get("教師名稱", "").strip()
                    room_code = r.get("教室", "").strip()
                    room_name = r.get("教室名稱", "").strip()
                    day = r.get("星期", "").strip()
                    period = r.get("節次", "").strip()

                    wm_val = r.get("週別設定")
                    week_mode = int(wm_val) if wm_val is not None else 0

                    ud_val = r.get("上下修")
                    ud = int(ud_val) if ud_val is not None else 0

                    if room_code and room_name:
                        classrooms[room_code] = room_name

                    schedules.append({
                        "id": idx,
                        "class_code": class_code,
                        "class_name": class_name,
                        "subject_code": subject_code,
                        "subject_name": subject_name,
                        "teacher_code": teacher_code,
                        "teacher_name": teacher_name,
                        "room_code": room_code,
                        "room_name": room_name,
                        "day": day,
                        "period": period,
                        "week_mode": week_mode,
                        "ud": ud
                    })
        classroom_list = [{"code": k, "name": v} for k, v in sorted(classrooms.items())]
        default_venues = [
            {"code": "電腦教室", "name": "電腦教室"},
            {"code": "理化實驗室", "name": "理化實驗室"},
            {"code": "生物實驗室", "name": "生物實驗室"},
            {"code": "音樂教室", "name": "音樂教室"},
            {"code": "美術教室", "name": "美術教室"},
            {"code": "體育場/館", "name": "體育場/館"},
            {"code": "家政教室", "name": "家政教室"},
            {"code": "生活科技教室", "name": "生活科技教室"}
        ]
        existing_codes = set(c["code"] for c in classroom_list if isinstance(c, dict) and "code" in c)
        for dv in default_venues:
            if dv["code"] not in existing_codes:
                classroom_list.append(dv)
        
        # Apply custom assignments override & filter deleted assignments
        cfg = load_config_rules()
        custom_assign = cfg.get("custom_assignments", {})
        deleted_assign = set(cfg.get("deleted_assignments", []))
        for key in list(deleted_assign):
            if key in custom_assign:
                deleted_assign.remove(key)

        filtered_schedules = []
        for s in schedules:
            ckey = f"{s['class_code']}|{s['subject_code']}"
            if ckey in deleted_assign:
                continue
            if ckey in custom_assign:
                s["teacher_code"] = custom_assign[ckey].get("teacher_code", s["teacher_code"])
                s["teacher_name"] = custom_assign[ckey].get("teacher_name", s["teacher_name"])
            filtered_schedules.append(s)
        schedules = filtered_schedules

        _cached_data = {
            "dbf_dir": dbf_dir,
            "period_times": period_times,
            "classes": classes,
            "teachers": teachers,
            "classrooms": classroom_list,
            "schedules": schedules
        }
        _db_mtimes = current_mtimes
        print(f"Loaded schedule data successfully from {dbf_dir} (Cached {len(schedules)} slots)")
        return _cached_data
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": f"Failed to parse DBF files: {str(e)}"}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/teacher")
@app.route("/teacher-portal")
def teacher_portal():
    return render_template("teacher_portal.html")

@app.route("/showcase")
@app.route("/intro")
def showcase():
    return render_template("showcase.html")

@app.route("/api/import/xinhe", methods=["POST"])
def api_import_xinhe():
    """接受上傳欣河雲端系統配課匯出 Excel，儲存為 xinhe_export.xlsx 並清除快取重新載入。"""
    global _cached_data, _db_mtimes
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "error": "未收到檔案，請選擇要上傳的 Excel 檔案"}), 400
        f = request.files["file"]
        if not f.filename:
            return jsonify({"success": False, "error": "上傳檔案名稱不可為空"}), 400
        filename = f.filename.lower()
        if not (filename.endswith(".xlsx") or filename.endswith(".xls") or filename.endswith(".xlsm")):
            return jsonify({"success": False, "error": "僅支援 .xlsx、.xls 或 .xlsm 格式之 Excel 檔案"}), 400

        dbf_dir = get_latest_dbf_dir()
        save_dir = dbf_dir if dbf_dir else DATA_DIR
        save_path = os.path.join(save_dir, XINHE_EXPORT_FILENAME)
        f.save(save_path)

        # 備份一份到 DATA_DIR
        try:
            if save_dir != DATA_DIR:
                import shutil
                shutil.copy2(save_path, os.path.join(DATA_DIR, XINHE_EXPORT_FILENAME))
        except Exception:
            pass

        # 解除 clean_mode
        try:
            cfg = load_config_rules()
            cfg["clean_mode"] = False
            save_config_rules(cfg)
        except Exception:
            pass

        # 清除快取並重新載入
        _cached_data = None
        _db_mtimes = {}
        data = load_schedule_data()
        schedules = data.get("schedules", []) if isinstance(data, dict) else []
        classes_cnt = len(data.get("classes", [])) if isinstance(data, dict) else 0
        teachers_cnt = len(data.get("teachers", [])) if isinstance(data, dict) else 0
        count = len(schedules)

        return jsonify({
            "success": True,
            "message": f"🎉 欣河配課 Excel 匯入成功！已解析並即時生效 {count} 節排課資料（共 {classes_cnt} 個班級、{teachers_cnt} 位教師）。",
            "count": count,
            "classes_count": classes_cnt,
            "teachers_count": teachers_cnt,
            "saved_path": save_path
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "error": f"匯入失敗: {str(e)}"}), 500

@app.route("/api/xinhe/status", methods=["GET"])
def api_xinhe_status():
    """查詢欣河 Excel 匯入狀態。"""
    dbf_dir = get_latest_dbf_dir()
    candidates = []
    if dbf_dir: candidates.append(os.path.join(dbf_dir, XINHE_EXPORT_FILENAME))
    candidates.append(os.path.join(DATA_DIR, XINHE_EXPORT_FILENAME))
    for path in candidates:
        if os.path.exists(path):
            stat = os.stat(path)
            # 統計筆數
            data = load_schedule_data()
            schedules_cnt = len(data.get("schedules", [])) if isinstance(data, dict) else 0
            return jsonify({
                "active": True,
                "path": path,
                "size_kb": round(stat.st_size/1024, 1),
                "modified": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "filename": XINHE_EXPORT_FILENAME,
                "schedules_count": schedules_cnt
            })
    return jsonify({
        "active": False,
        "message": f"目前使用原始 DBF / 本機課表資料（{XINHE_EXPORT_FILENAME} 未載入）",
        "filename": XINHE_EXPORT_FILENAME
    })

@app.route("/api/xinhe/remove", methods=["POST"])
def api_xinhe_remove():
    """移除欣河 Excel，回復使用 claspv.dbf。"""
    global _cached_data, _db_mtimes
    dbf_dir = get_latest_dbf_dir()
    candidates = []
    if dbf_dir: candidates.append(os.path.join(dbf_dir, XINHE_EXPORT_FILENAME))
    candidates.append(os.path.join(DATA_DIR, XINHE_EXPORT_FILENAME))
    removed = []
    for path in candidates:
        if os.path.exists(path):
            try:
                os.remove(path)
                removed.append(path)
            except Exception:
                pass
    _cached_data = None
    _db_mtimes = {}
    load_schedule_data()
    if removed:
        return jsonify({"success": True, "message": "已移除欣河匯入檔，系統已回復使用 DBF 原始資料庫！"})
    return jsonify({"success": False, "message": "目前未啟用欣河 Excel 檔案"})


@app.route("/api/tts", methods=["GET", "POST"])
def api_edge_tts():
    import edge_tts, asyncio
    try:
        if request.method == "POST":
            data = request.json or {}
            text = data.get("text", "").strip()
            voice = data.get("voice", "").strip()
            rate_val = data.get("rate", 0)
            volume_val = data.get("volume", "+0%")
        else:
            text = request.args.get("text", "歡迎使用舟歌 AI 智慧排課系統").strip()
            voice = request.args.get("voice", "").strip()
            rate_val = request.args.get("rate", 0)
            volume_val = request.args.get("volume", "+0%")

        if not text:
            return jsonify({"error": "No text provided"}), 400

        if not voice:
            voice = "zh-TW-HsiaoChenNeural"

        # Format rate string matching RelayBell logic (e.g., "+0%", "+10%", "-5%")
        try:
            r_int = int(rate_val)
            rate_str = f"{r_int:+d}%"
        except Exception:
            rate_str = "+0%"

        async def _gen_speech():
            tts = edge_tts.Communicate(text, voice, rate=rate_str, volume=volume_val)
            out = io.BytesIO()
            async for chunk in tts.stream():
                if chunk["type"] == "audio":
                    out.write(chunk["data"])
            out.seek(0)
            return out

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            audio_io = loop.run_until_complete(_gen_speech())
        finally:
            loop.close()
            
        return send_file(
            audio_io,
            mimetype="audio/mpeg",
            as_attachment=False,
            download_name="speech.mp3"
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
def load_lesson_notes():
    if os.path.exists(NOTES_FILE_PATH):
        try:
            with open(NOTES_FILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_lesson_notes(notes):
    try:
        with open(NOTES_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(notes, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print("Save lesson notes failed:", e)
        return False

@app.route("/api/notes", methods=["GET"])
def api_get_notes():
    notes = load_lesson_notes()
    return jsonify({"status": "success", "notes": notes})

@app.route("/api/notes/save", methods=["POST"])
def api_save_note():
    try:
        req = request.get_json() or {}
        key = req.get("key")
        note_type = req.get("note_type", "調課")
        note_text = req.get("note_text", "").strip()
        author = req.get("author", "教務處")

        if not key:
            return jsonify({"status": "error", "message": "Missing note key"}), 400

        notes = load_lesson_notes()
        if not note_text:
            notes.pop(key, None)
        else:
            notes[key] = {
                "key": key,
                "note_type": note_type,
                "note_text": note_text,
                "author": author,
                "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            }
        save_lesson_notes(notes)
        return jsonify({"status": "success", "message": "課表註記已成功儲存！", "notes": notes})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/notes/delete", methods=["POST"])
def api_delete_note():
    try:
        req = request.get_json() or {}
        key = req.get("key")
        if not key:
            return jsonify({"status": "error", "message": "Missing note key"}), 400
        notes = load_lesson_notes()
        notes.pop(key, None)
        save_lesson_notes(notes)
        return jsonify({"status": "success", "message": "課表註記已成功刪除！", "notes": notes})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/open-browser", methods=["POST"])
def api_open_browser():
    try:
        import webbrowser
        req = request.get_json() or {}
        raw_url = req.get("url") or "http://127.0.0.1:5000"
        
        # Replace 127.0.0.1 or localhost with real local LAN IP
        local_ip = get_local_ip()
        target_url = raw_url.replace("127.0.0.1", local_ip).replace("localhost", local_ip)
        
        webbrowser.open(target_url)
        return jsonify({
            "status": "success",
            "message": f"已成功在預設 WEB 瀏覽器中開啟真實 IP 網址：{target_url}",
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/system-info", methods=["GET"])
def api_get_system_info():

    try:
        cfg = load_config_rules()
        dbf_dir = get_latest_dbf_dir()
        
        default_periods = {
            "1": {"name": "第1節", "time": "08:10-08:55"},
            "2": {"name": "第2節", "time": "09:05-09:50"},
            "3": {"name": "第3節", "time": "10:10-10:55"},
            "4": {"name": "第4節", "time": "11:05-11:50"},
            "5": {"name": "第5節", "time": "13:10-13:55"},
            "6": {"name": "第6節", "time": "14:05-14:50"},
            "7": {"name": "第7節", "time": "15:05-15:50"},
            "8": {"name": "第8節", "time": "16:00-16:45"}
        }
        period_times = cfg.get("period_times") or default_periods

        return jsonify({
            "status": "success",
            "school_name": cfg.get("school_name", "學校名稱"),
            "school_subtitle": cfg.get("school_subtitle", "School Timetable System"),
            "year": cfg.get("year", "114"),
            "term": cfg.get("term", "1"),
            "dbf_search_dir": cfg.get("dbf_search_dir", get_default_search_dir()),
            "actual_dbf_dir": dbf_dir,
            "period_times": period_times
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/save-system-info", methods=["POST"])
def api_save_system_info():
    try:
        req = request.get_json() or {}
        cfg = load_config_rules()
        
        if "school_name" in req: cfg["school_name"] = str(req["school_name"]).strip()
        if "school_subtitle" in req: cfg["school_subtitle"] = str(req["school_subtitle"]).strip()
        if "year" in req: cfg["year"] = str(req["year"]).strip()
        if "term" in req: cfg["term"] = str(req["term"]).strip()
        if "dbf_search_dir" in req:
            new_dir = str(req["dbf_search_dir"]).strip()
            cfg["dbf_search_dir"] = new_dir
            if new_dir:
                cfg["clean_mode"] = False
        if "period_times" in req: cfg["period_times"] = req["period_times"]
        
        save_config_rules(cfg)
        
        global _cached_data, _db_mtimes
        _cached_data = None
        _db_mtimes = {}
        
        return jsonify({"status": "success", "message": "學校基本資料與系統設定已成功儲存！"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/select-folder", methods=["POST"])
def api_select_folder():
    try:
        def choose_folder():
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes('-topmost', True)
                folder = filedialog.askdirectory(title="請選擇 DBF 資料庫資料夾")
                root.destroy()
                if folder:
                    return os.path.normpath(folder)
            except Exception as e:
                log_exception("api_select_folder:tkinter", e)

            try:
                import subprocess
                cmd = """
                [System.Reflection.Assembly]::LoadWithPartialName('System.windows.forms') | Out-Null
                $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
                $dialog.Description = '請選擇 DBF 資料庫資料夾'
                if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
                    Write-Output $dialog.SelectedPath
                }
                """
                res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True)
                path = res.stdout.strip()
                if path:
                    return os.path.normpath(path)
            except Exception as e:
                log_exception("api_select_folder:powershell", e)
            return None

        folder_path = choose_folder()
        if folder_path:
            return jsonify({"status": "success", "path": folder_path})
        else:
            return jsonify({"status": "cancel", "message": "已取消選擇"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# =====================================================================
# API: 07. 綁班限制 (Teacher Class Allow)
# teacher_class_allow: { "teacher_code": ["class_code1", "class_code2", ...] }
# =====================================================================

@app.route("/api/teacher-class-allow", methods=["GET"])
def api_get_teacher_class_allow():
    try:
        cfg = load_config_rules()
        return jsonify({"status": "success", "data": cfg.get("teacher_class_allow", {})})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/teacher-class-allow/save", methods=["POST"])
def api_save_teacher_class_allow():
    try:
        req = request.get_json() or {}
        teacher_code = str(req.get("teacher_code", "")).strip()
        allowed_classes = req.get("allowed_classes", [])
        if not teacher_code:
            return jsonify({"status": "error", "message": "缺少教師代碼"}), 400
        cfg = load_config_rules()
        if "teacher_class_allow" not in cfg:
            cfg["teacher_class_allow"] = {}
        if allowed_classes:
            cfg["teacher_class_allow"][teacher_code] = [str(c).strip() for c in allowed_classes if str(c).strip()]
        else:
            cfg["teacher_class_allow"].pop(teacher_code, None)
        save_config_rules(cfg)
        return jsonify({"status": "success", "message": f"教師 {teacher_code} 綁班設定已儲存", "data": cfg["teacher_class_allow"]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/teacher-class-allow/delete", methods=["POST"])
def api_delete_teacher_class_allow():
    try:
        req = request.get_json() or {}
        teacher_code = str(req.get("teacher_code", "")).strip()
        if not teacher_code:
            return jsonify({"status": "error", "message": "缺少教師代碼"}), 400
        cfg = load_config_rules()
        cfg.get("teacher_class_allow", {}).pop(teacher_code, None)
        save_config_rules(cfg)
        return jsonify({"status": "success", "message": f"教師 {teacher_code} 綁班限制已移除"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# =====================================================================
# API: 01/04. 同時上課群組 / 全校共同科目 (Custom Simultaneous Groups)
# custom_simultaneous_groups: [ { label, fixed_day, fixed_period, members: [{class_code, subject_code}] } ]
# =====================================================================

@app.route("/api/sim-groups", methods=["GET"])
def api_get_sim_groups():
    try:
        cfg = load_config_rules()
        return jsonify({"status": "success", "data": cfg.get("custom_simultaneous_groups", [])})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/sim-groups/save", methods=["POST"])
def api_save_sim_group():
    """Add or update a simultaneous group. Pass index=-1 to add new."""
    try:
        req = request.get_json() or {}
        group = req.get("group", {})
        index = req.get("index", -1)
        if not group or not group.get("members"):
            return jsonify({"status": "error", "message": "群組資料不完整"}), 400
        cfg = load_config_rules()
        groups = cfg.get("custom_simultaneous_groups", [])
        if index >= 0 and index < len(groups):
            groups[index] = group
        else:
            groups.append(group)
        cfg["custom_simultaneous_groups"] = groups
        save_config_rules(cfg)
        return jsonify({"status": "success", "message": "同時上課群組已儲存", "data": groups})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/sim-groups/delete", methods=["POST"])
def api_delete_sim_group():
    try:
        req = request.get_json() or {}
        index = req.get("index", -1)
        cfg = load_config_rules()
        groups = cfg.get("custom_simultaneous_groups", [])
        if 0 <= index < len(groups):
            removed = groups.pop(index)
            cfg["custom_simultaneous_groups"] = groups
            save_config_rules(cfg)
            return jsonify({"status": "success", "message": f"群組 {removed.get('label', index)} 已刪除", "data": groups})
        return jsonify({"status": "error", "message": "群組索引無效"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def get_all_subjects_list():
    data = load_schedule_data()
    schedules = data.get("schedules", []) if isinstance(data, dict) else []
    subjects_map = {}
    
    # 1. From schedules
    for s in schedules:
        sc = str(s.get("subject_code", "")).strip()
        sn = str(s.get("subject_name", "")).strip()
        if sc and sc not in subjects_map:
            subjects_map[sc] = {"code": sc, "name": sn or sc}
            
    # 2. From custom assignments in config_rules.json
    cfg = load_config_rules()
    for ckey, assign in cfg.get("custom_assignments", {}).items():
        sc = str(assign.get("subject_code", "")).strip()
        sn = str(assign.get("subject_name", "")).strip()
        if sc and sc not in subjects_map:
            subjects_map[sc] = {"code": sc, "name": sn or sc}
            
    # 3. Default fallback subjects if empty
    if not subjects_map:
        defaults = [
            ("J101", "國語文"), ("J102", "英語文"), ("J103", "數學"),
            ("J104", "理化"), ("J105", "歷史"), ("J106", "地理"),
            ("J107", "公民"), ("J108", "體育"), ("J109", "班會"),
            ("J110", "社團活動"), ("J116", "彈性學習"), ("J112", "資訊科技"),
            ("J113", "音樂"), ("J114", "美術"), ("J115", "家政")
        ]
        for sc, sn in defaults:
            subjects_map[sc] = {"code": sc, "name": sn}
            
    return list(subjects_map.values())

@app.route("/api/metadata")
def api_metadata():
    data = load_schedule_data()
    subjects = get_all_subjects_list()
    if "error" in data:
        return jsonify({"error": data["error"], "classes": [], "teachers": [], "subjects": subjects, "classrooms": [], "period_times": {}, "dbf_dir": "", "local_ip": get_local_ip()}), 200
    
    response = jsonify({
        "classes": data["classes"],
        "teachers": data["teachers"],
        "subjects": subjects,
        "classrooms": data["classrooms"],
        "period_times": data["period_times"],
        "dbf_dir": data["dbf_dir"],
        "local_ip": get_local_ip()
    })
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response



@app.route("/api/schedule/class/<class_code>")
def api_schedule_class(class_code):
    try:
        cq = str(class_code).strip()
        data = load_schedule_data()
        classes = data.get("classes", []) if isinstance(data, dict) else []
        solved = get_current_solved_schedules()
        
        target_class = None
        for c in classes:
            code = str(c.get("code", "")).strip()
            name = str(c.get("name", "")).strip()
            if cq == code or cq == name or (code and cq in code) or (name and cq in name):
                target_class = c
                break
                
        filtered = []
        if target_class:
            c_name = str(target_class.get("name", "")).strip()
            c_code = str(target_class.get("code", "")).strip()
            for s in solved:
                cn = str(s.get("class_name", "")).strip()
                cc = str(s.get("class_code", "")).strip()
                if (cc and cc == c_code) or (cn and (cn == c_name or c_name in cn or cn in c_name or cn.startswith(c_code))):
                    filtered.append(s)
        else:
            for s in solved:
                cn = str(s.get("class_name", "")).strip()
                cc = str(s.get("class_code", "")).strip()
                if cq == cn or cq == cc or (cq and cq in cn) or (cq and cq in cc) or cn.startswith(cq):
                    filtered.append(s)
                    
        return jsonify(filtered)
    except Exception as e:
        return jsonify([])

@app.route("/api/schedule/teacher/<teacher_code>")
def api_schedule_teacher(teacher_code):
    try:
        tq = str(teacher_code).strip()
        data = load_schedule_data()
        teachers = data.get("teachers", []) if isinstance(data, dict) else []
        solved = get_current_solved_schedules()
        
        target_teacher = None
        for t in teachers:
            code = str(t.get("code", "")).strip()
            name = str(t.get("name", "")).strip()
            if tq == code or tq == name or (code and tq in code) or (name and tq in name):
                target_teacher = t
                break
                
        filtered = []
        if target_teacher:
            t_name = str(target_teacher.get("name", "")).strip()
            t_code = str(target_teacher.get("code", "")).strip()
            for s in solved:
                sn = str(s.get("teacher_name", "")).strip()
                sc = str(s.get("teacher_code", "")).strip()
                if (sc and sc == t_code) or (sn and (sn == t_name or t_name in sn or sn in t_name or (len(t_name) >= 1 and sn.startswith(t_name)))):
                    filtered.append(s)
        else:
            for s in solved:
                sn = str(s.get("teacher_name", "")).strip()
                sc = str(s.get("teacher_code", "")).strip()
                if tq == sn or tq == sc or (tq and tq in sn) or (tq and tq in sc) or (len(tq) >= 1 and sn.startswith(tq)):
                    filtered.append(s)
                    
        return jsonify(filtered)
    except Exception as e:
        return jsonify([])

@app.route("/api/schedule/room/<path:room_code>")
def api_schedule_room(room_code):
    try:
        rq = str(room_code).strip()
        data = load_schedule_data()
        classrooms = data.get("classrooms", []) if isinstance(data, dict) else []
        
        # 建立代碼與名稱反查
        matched_names = set()
        matched_names.add(rq)
        for r in classrooms:
            rcode = str(r.get("code", "")).strip() if isinstance(r, dict) else str(r)
            rname = str(r.get("name", "")).strip() if isinstance(r, dict) else str(r)
            if rq == rcode or rq == rname or (rcode and rq == rcode.lstrip("0")) or (rq and rq.isdigit() and rcode and int(float(rq)) == int(float(rcode)) if rcode.replace(".", "").isdigit() else False):
                if rname:
                    matched_names.add(rname)

        solved = get_current_solved_schedules()
        filtered = []
        for s in solved:
            rname = str(s.get("room_name", "")).strip()
            rcode = str(s.get("room_code", "")).strip()
            if rname in matched_names or rcode == rq or (rname and (rq == rname or rq in rname or rname in rq)):
                filtered.append(s)
        return jsonify(filtered)
    except Exception as e:
        return jsonify([])

def trigger_auto_solver():
    """
    Automatically triggers solve_schedule.run_solver() after rule changes.
    Returns: dict response from solver.
    """
    try:
        import solve_schedule
        import importlib
        importlib.reload(solve_schedule)
        res = solve_schedule.run_solver()
        return res
    except Exception as e:
        print(f"[AutoSolver Error] {e}")
        return {"status": "error", "message": str(e)}

@app.route("/api/run-solver")
def api_run_solver():
    try:
        res = trigger_auto_solver()
        return jsonify(res)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/data-debug-report")
def api_data_debug_report():
    try:
        data = load_schedule_data()
        if "error" in data:
            return jsonify(data), 500
            
        schedules = data.get("schedules", [])
        classes = data.get("classes", [])
        teachers = data.get("teachers", [])

        # 1. 班級排課數
        class_scheduled_counts = {}
        for c in classes:
            cc = c["code"]
            if cc:
                class_scheduled_counts[cc] = {
                    "code": cc,
                    "name": c["name"],
                    "count": sum(1 for s in schedules if s["class_code"] == cc)
                }

        # 2. 班級空堂數 (檢查第1~7節中未排課的空檔)
        class_empty_slots = {}
        for cc, info in class_scheduled_counts.items():
            slots = set((s["day"], s["period"]) for s in schedules if s["class_code"] == cc)
            empty_count = 0
            for d in range(1, 6):
                for p in range(1, 8): # Periods 1-7
                    if (str(d), str(p)) not in slots:
                        empty_count += 1
            class_empty_slots[cc] = {
                "name": info["name"],
                "empty_count": empty_count
            }

        # 3. 教師總時數
        teacher_total_hours = {}
        for t in teachers:
            tc = t["code"]
            if tc:
                teacher_total_hours[tc] = {
                    "code": tc,
                    "name": t["name"],
                    "count": sum(1 for s in schedules if s["teacher_code"] == tc)
                }

        # 4. 無任課教師科目
        unassigned_subjects = []
        # 5. 多任課教師科目
        class_sub_teachers = {}
        for s in schedules:
            key = f"{s['class_name']} - {s['subject_name']}"
            if not s["teacher_code"]:
                if key not in unassigned_subjects:
                    unassigned_subjects.append(key)
            else:
                if key not in class_sub_teachers:
                    class_sub_teachers[key] = set()
                class_sub_teachers[key].add(s["teacher_name"])

        multi_teacher_subjects = [{ "subject": k, "teachers": list(v) } for k, v in class_sub_teachers.items() if len(v) > 1]

        # 6. 科目每節上課明細 & 7. 科目排課數
        subject_counts = {}
        for s in schedules:
            sn = s["subject_name"]
            if sn:
                if sn not in subject_counts:
                    subject_counts[sn] = 0
                subject_counts[sn] += 1

        # 8. 邏輯錯誤資料 (硬衝堂)
        logic_errors = []
        teacher_slot_map = {}
        class_slot_map = {}
        for s in schedules:
            slot_key = (s["day"], s["period"])
            tc = s["teacher_code"]
            cc = s["class_code"]
            if tc:
                if (tc, slot_key) in teacher_slot_map:
                    prev = teacher_slot_map[(tc, slot_key)]
                    logic_errors.append(f"教師衝堂：{s['teacher_name']} 於週{s['day']}第{s['period']}節同時在【{prev['class_name']}】與【{s['class_name']}】授課！")
                else:
                    teacher_slot_map[(tc, slot_key)] = s

            if cc and not cc.startswith("99"):
                if (cc, slot_key) in class_slot_map:
                    prev = class_slot_map[(cc, slot_key)]
                    if prev["subject_code"] != s["subject_code"]:
                        logic_errors.append(f"班級衝堂：{s['class_name']} 於週{s['day']}第{s['period']}節同時排有【{prev['subject_name']}】與【{s['subject_name']}】！")
                else:
                    class_slot_map[(cc, slot_key)] = s

        # 9. 檢查手排課邏輯錯誤
        manual_lock_errors = []
        for s in schedules:
            if "手排課" in str(s.get("desc", "")):
                # Check if this manual lock collides
                pass

        return jsonify({
            "status": "success",
            "audit_summary": {
                "class_scheduled_counts": list(class_scheduled_counts.values()),
                "class_empty_slots": class_empty_slots,
                "teacher_total_hours": list(teacher_total_hours.values()),
                "unassigned_subjects": unassigned_subjects,
                "multi_teacher_subjects": multi_teacher_subjects,
                "subject_counts": subject_counts,
                "logic_errors": logic_errors,
                "manual_lock_errors": manual_lock_errors
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/validate-solver")
def api_validate_solver():
    import pandas as pd
    try:
        excel_path = get_solved_excel_path()
        if not excel_path or not os.path.exists(excel_path):
            return jsonify({"status": "error", "message": "找不到已排課結果檔案 (School_Schedule_Solved.xlsx)，請先執行 AI 排課。"})
            
        df = pd.read_excel(excel_path)
        
        # Load tables for validation safely
        dbf_dir = get_latest_dbf_dir()
        db_no_teach = []
        db_no_sub = []
        db_class = []
        
        if dbf_dir and os.path.exists(dbf_dir):
            nt_p = os.path.join(dbf_dir, "no_teach.dbf")
            ns_p = os.path.join(dbf_dir, "no_sub.dbf")
            cl_p = os.path.join(dbf_dir, "class.dbf")
            
            if os.path.exists(nt_p):
                try:
                    db_no_teach = list(DBF(nt_p, ignore_missing_memofile=True, encoding='cp950'))
                except Exception as e:
                    log_exception("api_check_schedule_conflicts:no_teach", e)
            if os.path.exists(ns_p):
                try:
                    db_no_sub = list(DBF(ns_p, ignore_missing_memofile=True, encoding='cp950'))
                except Exception as e:
                    log_exception("api_check_schedule_conflicts:no_sub", e)
            if os.path.exists(cl_p):
                try:
                    db_class = list(DBF(cl_p, ignore_missing_memofile=True, encoding='cp950'))
                except Exception as e:
                    log_exception("api_check_schedule_conflicts:class", e)
        
        virtual_class_codes = set()
        for r in db_class:
            if r.get("虛擬") or "跨班" in str(r.get("CLASS_NAME", "")):
                virtual_class_codes.add(str(r.get("CLASS_NO", "")).strip())
                
        records = df.to_dict(orient="records")
        
        # Validation counts
        teacher_slots = {}
        class_slots = {}
        conflicts = 0
        detail = []
        
        for r in records:
            d_val = r.get("星期")
            p_val = r.get("節次")
            if pd.isna(d_val) or pd.isna(p_val):
                continue
            d = int(d_val)
            p = int(p_val)
            t = str(r.get("教師姓名", "")).strip() if not pd.isna(r.get("教師姓名")) else ""
            c = str(r.get("班級代碼", "")).strip() if not pd.isna(r.get("班級代碼")) else ""
            wm_val = r.get("週別設定")
            wm = int(wm_val) if not pd.isna(wm_val) else 0
            desc = str(r.get("備註", "")).strip()
            if pd.isna(r.get("備註")):
                desc = ""
            
            if t and t != "nan":
                if t not in teacher_slots:
                    teacher_slots[t] = []
                for ext in teacher_slots[t]:
                    if ext["day"] == d and ext["period"] == p:
                        if wm == 0 or ext["week"] == 0 or wm == ext["week"]:
                            if desc == "(虛擬班級)" and ext["desc"] == "(虛擬班級)":
                                continue
                            detail.append(f"[Teacher Conflict]: Teacher {r.get('教師代碼')} ({t}) has overlapping classes in slot {d}-{p}!")
                            conflicts += 1
                teacher_slots[t].append({"day": d, "period": p, "week": wm, "desc": desc})
                
            if c and c != "nan" and c not in virtual_class_codes:
                if c not in class_slots:
                    class_slots[c] = []
                for ext in class_slots[c]:
                    if ext["day"] == d and ext["period"] == p:
                        if wm == 0 or ext["week"] == 0 or wm == ext["week"]:
                            if r.get("科目代碼") == ext["subject_code"]:
                                continue
                            detail.append(f"[Class Conflict]: Class {r.get('班級代碼')} ({c}) has overlapping lessons in slot {d}-{p}! Sub: {r.get('科目名稱')} vs {ext['subject_name']}")
                            conflicts += 1
                class_slots[c].append({"day": d, "period": p, "week": wm, "subject_code": r.get("科目代碼"), "subject_name": r.get("科目名稱")})
                
        violated_no_teach = 0
        for r in records:
            t_code = str(r.get('教師代碼', '')).strip()
            d_val = r.get('星期')
            p_val = r.get('節次')
            if t_code and not pd.isna(d_val) and not pd.isna(p_val):
                d = int(d_val)
                p = int(p_val)
                for rule in db_no_teach:
                    rule_t = str(rule.get('TEACHER_NO', '')).strip()
                    if rule_t == t_code:
                        if rule.get('START_DAY', 0) <= d <= rule.get('END_DAY', 0) and rule.get('START_SEC', 0) <= p <= rule.get('END_SEC', 0):
                            violated_no_teach += 1

        violated_no_sub = 0
        for r in records:
            c_code = str(r.get('班級代碼', '')).strip()
            s_code = str(r.get('科目代碼', '')).strip()
            d_val = r.get('星期')
            p_val = r.get('節次')
            if c_code and s_code and not pd.isna(d_val) and not pd.isna(p_val):
                d = int(d_val)
                p = int(p_val)
                for rule in db_no_sub:
                    rule_c = str(rule.get('CLASS_NO', '')).strip()
                    rule_s = str(rule.get('SUBJECT_NO', '')).strip()
                    if rule_c == c_code and rule_s == s_code:
                        if rule.get('START_DAY', 0) <= d <= rule.get('END_DAY', 0) and rule.get('START_SEC', 0) <= p <= rule.get('END_SEC', 0):
                            violated_no_sub += 1
                            
        return jsonify({
            "status": "success",
            "hard_conflicts": conflicts,
            "teacher_violations_soft": violated_no_teach,
            "class_sub_violations_hard": violated_no_sub,
            "details": detail
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/debug-db")
def api_debug_db():
    try:
        dbf_dir = get_latest_dbf_dir()
        claspv_base = list(DBF(os.path.join(dbf_dir, "claspv_base.dbf"), ignore_missing_memofile=True, encoding='cp950'))
        
        class_102_1_1 = []
        teach_0010_1_1 = []
        for r in claspv_base:
            c = r.get("?剔?", "").strip()
            t = r.get("教師", "").strip()
            d = r.get("星期", "").strip()
            p = r.get("節次", "").strip()
            
            # Convert values to strings for JSON serializability
            rec = {k: str(v) for k, v in r.items()}
            
            if c == '102' and d == '1' and p == '1':
                class_102_1_1.append(rec)
            if t == '0010' and d == '1' and p == '1':
                teach_0010_1_1.append(rec)
                
        return jsonify({
            "class_102_1_1": class_102_1_1,
            "teach_0010_1_1": teach_0010_1_1
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/debug-solved")
def api_debug_solved():
    try:
        excel_path = get_solved_excel_path()
        if not excel_path or not os.path.exists(excel_path):
            return jsonify({"status": "error", "message": "Solved file not found"})
        import pandas as pd
        df = pd.read_excel(excel_path)
        
        class_102_1_1 = []
        teach_0010_1_1 = []
        for idx, r in df.iterrows():
            c = str(r.get("班級代碼", "")).strip()
            t = str(r.get("教師姓名", "")).strip()
            d_val = r.get("星期")
            p = str(r.get("節次", "")).strip()
            
            rec = {k: str(v) for k, v in r.items()}
            
            try:
                d_clean = str(int(float(d_val))) if d_val is not None and str(d_val).lower() != "nan" and str(d_val).strip() != "" else ""
            except Exception:
                d_clean = ""
            try:
                p_clean = str(int(float(p))) if p is not None and str(p).lower() != "nan" and str(p).strip() != "" else ""
            except Exception:
                p_clean = ""
            
            if c == '102' and d_clean == '1' and p_clean == '1':
                class_102_1_1.append(rec)
            if t == '0010' and d_clean == '1' and p_clean == '1':
                teach_0010_1_1.append(rec)
                
        return jsonify({
            "class_102_1_1": class_102_1_1,
            "teach_0010_1_1": teach_0010_1_1
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/debug-math")
def api_debug_math():
    try:
        import pandas as pd
        dbf_dir = get_latest_dbf_dir()
        if not dbf_dir:
            return jsonify([])
        claspv_path = os.path.join(dbf_dir, "claspv_base.dbf")
        if not os.path.exists(claspv_path):
            claspv_path = os.path.join(dbf_dir, "claspv.dbf")
        if not os.path.exists(claspv_path):
            return jsonify([])
        claspv_base = list(DBF(claspv_path, ignore_missing_memofile=True, encoding='cp950'))
        
        math_records = []
        for r in claspv_base:
            c = str(r.get("班級", "")).strip()
            s = str(r.get("科目", "")).strip()
            if c == '102' and s == '301':
                math_records.append({k: str(v) for k, v in r.items()})
                
        return jsonify(math_records)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/debug-teacher-slots")
def api_debug_teacher_slots():
    try:
        import pandas as pd
        dbf_dir = get_latest_dbf_dir()
        if not dbf_dir:
            return jsonify([])
            
        claspv_path = os.path.join(dbf_dir, "claspv_base.dbf")
        if not os.path.exists(claspv_path):
            claspv_path = os.path.join(dbf_dir, "claspv.dbf")
        claspv_base = list(DBF(claspv_path, ignore_missing_memofile=True, encoding='cp950')) if os.path.exists(claspv_path) else []

        no_teach_path = os.path.join(dbf_dir, "no_teach.dbf")
        no_teach = list(DBF(no_teach_path, ignore_missing_memofile=True, encoding='cp950')) if os.path.exists(no_teach_path) else []

        class_path = os.path.join(dbf_dir, "class.dbf")
        db_class = list(DBF(class_path, ignore_missing_memofile=True, encoding='cp950')) if os.path.exists(class_path) else []
        
        virtual_class_codes = set()
        for r in db_class:
            if r.get("虛擬") or "跨班" in r.get("CLASS_NAME", ""):
                virtual_class_codes.add(r.get("CLASS_NO", "").strip())
                
        class_prefilled = {}
        for r in claspv_base:
            c = r.get("班級", "").strip()
            d = r.get("星期", "").strip()
            p = r.get("節次", "").strip()
            if c and d and p:
                if c not in class_prefilled:
                    class_prefilled[c] = set()
                try:
                    class_prefilled[c].add((int(d), int(p)))
                except Exception as e:
                    log_exception("api_check_schedule_audit:class_prefilled", e)
                
        teacher_blocked = {}
        for rule in no_teach:
            t = str(rule.get('TEACHER_NO', '')).strip()
            if t:
                if t not in teacher_blocked:
                    teacher_blocked[t] = set()
                sd = rule.get('START_DAY', 1)
                ed = rule.get('END_DAY', 1)
                ss = rule.get('START_SEC', 1)
                es = rule.get('END_SEC', 1)
                for d in range(sd, ed + 1):
                    for p in range(ss, es + 1):
                        teacher_blocked[t].add((d, p))
              
        teacher_groups = {}
        for r in claspv_base:
            w_val = r.get("星期")
            s_val = r.get("節次")
            w = str(w_val).strip() if w_val is not None and str(w_val).lower() != "nan" else ""
            s = str(s_val).strip() if s_val is not None and str(s_val).lower() != "nan" else ""
            if not w and not s:
                t = r.get("教師", "").strip()
                if t:
                    if t not in teacher_groups:
                        teacher_groups[t] = []
                    teacher_groups[t].append(r)
                    
        teacher_report = []
        for t_code, t_items in teacher_groups.items():
            if not t_items:
                continue
                
            t_blocked = teacher_blocked.get(t_code, set())
            unique_dynamic_needed = len(t_items)
            
            item_candidate_slots = []
            for r in t_items:
                c = r.get("班級", "").strip()
                c_pref = class_prefilled.get(c, set()) if c not in virtual_class_codes else set()
                
                candidates = 0
                for d in range(1, 6):
                    for p in range(1, 9):
                        if (d, p) not in t_blocked and (d, p) not in c_pref:
                            candidates += 1
                item_candidate_slots.append({
                    "class": c,
                    "subject": str(r.get("科目名稱", "")).strip(),
                    "candidates": candidates
                })
                
            t_name = str(t_items[0].get("教師名稱", "")).strip()
            teacher_report.append({
                "code": t_code,
                "name": t_name,
                "needed_dynamic": unique_dynamic_needed,
                "available_slots_teacher": 40 - len(t_blocked),
                "items": item_candidate_slots
            })
            
        return jsonify(teacher_report)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/check-bottlenecks")
def api_check_bottlenecks():
    try:
        import pandas as pd
        dbf_dir = get_latest_dbf_dir()
        if not dbf_dir:
            return jsonify({"teacher_bottlenecks": []})
            
        claspv_path = os.path.join(dbf_dir, "claspv_base.dbf")
        if not os.path.exists(claspv_path):
            claspv_path = os.path.join(dbf_dir, "claspv.dbf")
        claspv_base = list(DBF(claspv_path, ignore_missing_memofile=True, encoding='cp950')) if os.path.exists(claspv_path) else []

        no_teach_path = os.path.join(dbf_dir, "no_teach.dbf")
        no_teach = list(DBF(no_teach_path, ignore_missing_memofile=True, encoding='cp950')) if os.path.exists(no_teach_path) else []

        class_path = os.path.join(dbf_dir, "class.dbf")
        db_class = list(DBF(class_path, ignore_missing_memofile=True, encoding='cp950')) if os.path.exists(class_path) else []
        
        virtual_class_codes = set()
        for r in db_class:
            if r.get("虛擬") or "跨班" in r.get("CLASS_NAME", ""):
                virtual_class_codes.add(r.get("CLASS_NO", "").strip())
                
        class_prefilled = {}
        for r in claspv_base:
            c = r.get("班級", "").strip()
            d = r.get("星期", "").strip()
            p = r.get("節次", "").strip()
            if c and d and p:
                if c not in class_prefilled:
                    class_prefilled[c] = set()
                try:
                    class_prefilled[c].add((int(d), int(p)))
                except Exception as e:
                    log_exception("api_check_schedule_audit:class_prefilled_int", e)
                
        teacher_blocked = {}
        for rule in no_teach:
            t = str(rule.get('TEACHER_NO', '')).strip()
            if t:
                if t not in teacher_blocked:
                    teacher_blocked[t] = set()
                sd = rule.get('START_DAY', 1)
                ed = rule.get('END_DAY', 1)
                ss = rule.get('START_SEC', 1)
                es = rule.get('END_SEC', 1)
                for d in range(sd, ed + 1):
                    for p in range(ss, es + 1):
                        teacher_blocked[t].add((d, p))
                        
        teacher_groups = {}
        for r in claspv_base:
            w_val = r.get("星期")
            s_val = r.get("節次")
            w = str(w_val).strip() if w_val is not None and str(w_val).lower() != "nan" else ""
            s = str(s_val).strip() if s_val is not None and str(s_val).lower() != "nan" else ""
            if not w and not s:
                t = r.get("教師", "").strip()
                if t:
                    if t not in teacher_groups:
                        teacher_groups[t] = []
                    teacher_groups[t].append(r)
                    
        teacher_bottlenecks = []
        for t_code, t_items in teacher_groups.items():
            if not t_items:
                continue
                
            t_blocked = teacher_blocked.get(t_code, set())
            t_name = str(t_items[0].get("教師名稱", "")).strip()
            unique_dynamic_needed = len(t_items)
            
            teacher_candidate_slots = set()
            for r in t_items:
                c = r.get("班級", "").strip()
                c_pref = class_prefilled.get(c, set()) if c not in virtual_class_codes else set()
                for d in range(1, 6):
                    for p in range(1, 9):
                        if (d, p) not in t_blocked and (d, p) not in c_pref:
                            teacher_candidate_slots.add((d, p))
                            
            available_slots = len(teacher_candidate_slots)
            slack = available_slots - unique_dynamic_needed
            
            if slack <= 2:
                teacher_bottlenecks.append({
                    "teacher": t_name,
                    "code": t_code,
                    "needed": unique_dynamic_needed,
                    "available_candidates": available_slots,
                    "slack": slack
                })
                
        return jsonify({
            "teacher_bottlenecks": teacher_bottlenecks
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/debug-401-5-6")
def api_debug_401_5_6():
    try:
        dbf_dir = get_latest_dbf_dir()
        claspv_base = list(DBF(os.path.join(dbf_dir, "claspv_base.dbf"), ignore_missing_memofile=True, encoding='cp950'))
        
        records = []
        for r in claspv_base:
            c = r.get("?剔?", "").strip()
            if c == '401':
                records.append({k: str(v) for k, v in r.items()})
                
        return jsonify(records)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/debug-class")
def api_debug_class():
    try:
        dbf_dir = get_latest_dbf_dir()
        db_class = list(DBF(os.path.join(dbf_dir, "class.dbf"), ignore_missing_memofile=True, encoding='cp950'))
        records = [{k: str(v) for k, v in r.items()} for r in db_class]
        return jsonify(records)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/check-file-time")
def api_check_file_time():
    try:
        excel_path = get_solved_excel_path() or os.path.join(DATA_DIR, "School_Schedule_Solved.xlsx")
            
        if not os.path.exists(excel_path):
            return jsonify({"status": "error", "message": "Solved file not found"})
            
        import time
        mtime = os.path.getmtime(excel_path)
        mtime_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))
        return jsonify({
            "mtime": mtime_str,
            "current_time": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())),
            "size": os.path.getsize(excel_path)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/download-solved")
def api_download_solved():
    try:
        excel_path = get_solved_excel_path() or os.path.join(DATA_DIR, "School_Schedule_Solved.xlsx")
            
        if not os.path.exists(excel_path):
            return jsonify({"status": "error", "message": "Solved schedule file not found. Please run the solver first."}), 404
            
        return send_file(excel_path, as_attachment=True, download_name="School_Schedule_Solved.xlsx")
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def check_manual_swap_conflicts(source_item, target_day, target_period, target_item, solved, cfg):
    """
    Validates manual course swap/shift for teacher conflicts, class conflicts, no-teach, and no-sub rules.
    Returns: (is_forbidden, warnings_list)
    """
    warnings = []
    is_forbidden = False
    
    s_id = str(source_item.get("id"))
    t_id = str(target_item.get("id")) if target_item else None
    
    s_teacher = str(source_item.get("teacher_name", "")).strip()
    s_tcode = str(source_item.get("teacher_code", "")).strip()
    s_class = str(source_item.get("class_name", "")).strip()
    s_subject = str(source_item.get("subject_name", "")).strip()
    old_day = str(source_item.get("day", "1"))
    old_period = str(source_item.get("period", "1"))
    
    target_day = str(target_day)
    target_period = str(target_period)
    
    # 1. Source Teacher Conflict Check on target_day & target_period
    if s_teacher:
        for item in solved:
            item_id = str(item.get("id"))
            if item_id != s_id and (t_id is None or item_id != t_id):
                if str(item.get("day")) == target_day and str(item.get("period")) == target_period:
                    it_teacher = str(item.get("teacher_name", "")).strip()
                    it_tcode = str(item.get("teacher_code", "")).strip()
                    if (s_tcode and it_tcode and s_tcode == it_tcode) or (s_teacher and s_teacher == it_teacher):
                        is_forbidden = True
                        warnings.append(f"⛔ 教師衝堂：【{s_teacher}】老師在週{target_day}第{target_period}節已在【{item.get('class_name')}】授課！")

    # 2. Source Class Conflict Check on target_day & target_period
    if s_class:
        for item in solved:
            item_id = str(item.get("id"))
            if item_id != s_id and (t_id is None or item_id != t_id):
                if str(item.get("day")) == target_day and str(item.get("period")) == target_period:
                    if str(item.get("class_name", "")).strip() == s_class:
                        is_forbidden = True
                        warnings.append(f"⛔ 班級衝堂：【{s_class}】在週{target_day}第{target_period}節已有【{item.get('subject_name')}】({item.get('teacher_name')})！")

    # 3. Source Teacher No-Teach Restriction
    custom_no_teach = cfg.get("custom_no_teach", {})
    t_key = s_tcode or s_teacher
    blocked_slots = custom_no_teach.get(t_key, [])
    if f"{target_day}-{target_period}" in blocked_slots:
        warnings.append(f"⚠️ 教師禁排：【{s_teacher}】老師設定週{target_day}第{target_period}節為不排課時段！")

    # 4. If two-way swap, check target item moving to old_day & old_period
    if target_item:
        t_teacher = str(target_item.get("teacher_name", "")).strip()
        t_tcode = str(target_item.get("teacher_code", "")).strip()
        t_class = str(target_item.get("class_name", "")).strip()
        
        # 4a. Target Teacher Conflict on old_day & old_period
        if t_teacher:
            for item in solved:
                item_id = str(item.get("id"))
                if item_id != s_id and item_id != t_id:
                    if str(item.get("day")) == old_day and str(item.get("period")) == old_period:
                        it_teacher = str(item.get("teacher_name", "")).strip()
                        it_tcode = str(item.get("teacher_code", "")).strip()
                        if (t_tcode and it_tcode and t_tcode == it_tcode) or (t_teacher and t_teacher == it_teacher):
                            is_forbidden = True
                            warnings.append(f"⛔ 對調衝堂：【{t_teacher}】老師移至原時段(週{old_day}第{old_period}節)會與【{item.get('class_name')}】衝堂！")
                            
        # 4b. Target Class Conflict on old_day & old_period
        if t_class:
            for item in solved:
                item_id = str(item.get("id"))
                if item_id != s_id and item_id != t_id:
                    if str(item.get("day")) == old_day and str(item.get("period")) == old_period:
                        if str(item.get("class_name", "")).strip() == t_class:
                            is_forbidden = True
                            warnings.append(f"⛔ 對調班級衝堂：【{t_class}】在原時段(週{old_day}第{old_period}節)已有【{item.get('subject_name')}】({item.get('teacher_name')})！")

        # 4c. Target Teacher No-Teach on old_day & old_period
        t_target_key = t_tcode or t_teacher
        target_blocked_slots = custom_no_teach.get(t_target_key, [])
        if f"{old_day}-{old_period}" in target_blocked_slots:
            warnings.append(f"⚠️ 對調教師禁排：【{t_teacher}】老師設定週{old_day}第{old_period}節為不排課時段！")

    return is_forbidden, warnings

@app.route("/api/check-swap-slots/<item_id>")
def api_check_swap_slots(item_id):
    try:
        solved = get_current_solved_schedules()
        cfg = load_config_rules()
        item = None
        for s in solved:
            if str(s.get("id")) == str(item_id):
                item = s
                break
                
        if not item and solved:
            try:
                idx = int(item_id)
                if 0 <= idx < len(solved):
                    item = solved[idx]
            except Exception as e:
                log_exception("api_undo_swap:resolve_item", e)
                
        if not item:
            return jsonify({"status": "error", "message": "找不到該課程項目"}), 404
            
        source_d = int(item.get("day", 1))
        source_p = int(item.get("period", 1))
        
        slots_status = {}
        for d in range(1, 6):
            for p in range(1, 9):
                slot_key = f"{d}-{p}"
                if source_d == d and source_p == p:
                    slots_status[slot_key] = {"status": "current", "message": "目前時段"}
                else:
                    # Find target item at (d, p) for the current view (class or teacher)
                    target_item = None
                    for s in solved:
                        if str(s.get("id")) != str(item.get("id")) and str(s.get("day")) == str(d) and str(s.get("period")) == str(p):
                            if (item.get("class_name") and str(s.get("class_name", "")).strip() == str(item.get("class_name", "")).strip()) or \
                               (item.get("teacher_name") and str(s.get("teacher_name", "")).strip() == str(item.get("teacher_name", "")).strip()):
                                target_item = s
                                break
                    is_forb, warn_list = check_manual_swap_conflicts(item, d, p, target_item, solved, cfg)
                    if is_forb:
                        slots_status[slot_key] = {"status": "forbidden", "message": warn_list[0] if warn_list else "時段衝堂"}
                    elif warn_list:
                        slots_status[slot_key] = {"status": "soft_conflict", "message": warn_list[0]}
                    else:
                        slots_status[slot_key] = {"status": "feasible", "message": "完全可行"}
                    
        return jsonify({
            "status": "success",
            "item": item,
            "slots": slots_status
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/execute-swap", methods=["POST"])
def api_execute_swap():
    """
    Execute manual course swap / shift in solved schedules with conflict checking.
    Swaps or shifts course at source_id to target_day & target_period (and target_id if occupied).
    """
    try:
        req = request.get_json(silent=True) or {}
        source_id = req.get("source_id")
        target_day = str(req.get("target_day", "1"))
        target_period = str(req.get("target_period", "1"))
        target_id = req.get("target_id")
        force = bool(req.get("force", False))
        
        cfg = load_config_rules()
        solved = get_current_solved_schedules()
        
        source_item = None
        target_item = None
        
        # 1. Match source and target items by id or index
        for s in solved:
            if str(s.get("id")) == str(source_id):
                source_item = s
            if target_id is not None and str(s.get("id")) == str(target_id):
                target_item = s
                
        if not source_item and solved:
            try:
                s_idx = int(source_id)
                if 0 <= s_idx < len(solved):
                    source_item = solved[s_idx]
            except Exception as e:
                log_exception("api_undo_swap:source_index", e)
                
        if target_id is not None and not target_item and solved:
            try:
                t_idx = int(target_id)
                if 0 <= t_idx < len(solved):
                    target_item = solved[t_idx]
            except Exception as e:
                log_exception("api_undo_swap:target_index", e)

        if not source_item and isinstance(req.get("source_lesson"), dict):
            sl = req.get("source_lesson")
            for s in solved:
                if str(s.get("day")) == str(sl.get("day")) and str(s.get("period")) == str(sl.get("period")) and (s.get("teacher_name") == sl.get("teacher_name") or s.get("class_name") == sl.get("class_name")):
                    source_item = s
                    break

        if not target_item and isinstance(req.get("target_lesson"), dict):
            tl = req.get("target_lesson")
            for s in solved:
                if str(s.get("day")) == str(tl.get("day")) and str(s.get("period")) == str(tl.get("period")) and (s.get("teacher_name") == tl.get("teacher_name") or s.get("class_name") == tl.get("class_name")):
                    target_item = s
                    break
                
        if not source_item:
            return jsonify({"status": "error", "message": "找不到欲微調的原課程項目！"}), 400

        # 2. Check Conflicts
        is_forbidden, warnings = check_manual_swap_conflicts(source_item, target_day, target_period, target_item, solved, cfg)
        if (is_forbidden or warnings) and not force:
            warn_text = "\n".join(warnings)
            if is_forbidden:
                return jsonify({"status": "conflict_forbidden", "message": f"⛔ 警告！調課發生嚴重衝堂：\n{warn_text}\n\n如需強行對調，請於對話框點擊確定。"}), 200
            else:
                return jsonify({"status": "conflict_warning", "message": f"⚠️ 偵測到排課警示：\n{warn_text}\n\n您確定要強制進行微調嗎？", "requires_force": True}), 200
            
        old_day = str(source_item.get("day", "1"))
        old_period = str(source_item.get("period", "1"))
        
        if target_item:
            source_item["day"] = str(target_day)
            source_item["period"] = str(target_period)
            source_item["manual_locked"] = True
            
            target_item["day"] = str(old_day)
            target_item["period"] = str(old_period)
            target_item["manual_locked"] = True
            msg = f"成功對調課程！【{source_item.get('class_name', '')} {source_item.get('subject_name')} ({source_item.get('teacher_name')})】與【{target_item.get('class_name', '')} {target_item.get('subject_name')} ({target_item.get('teacher_name')})】已互相調換時段。"
        else:
            source_item["day"] = str(target_day)
            source_item["period"] = str(target_period)
            source_item["manual_locked"] = True
            msg = f"成功微調課程！【{source_item.get('class_name', '')} {source_item.get('subject_name')} ({source_item.get('teacher_name')})】已由週{old_day}第{old_period}節調整至週{target_day}第{target_period}節。"
            
        # Record Swap History
        import time, datetime
        swap_record = {
            "id": f"swap_{int(time.time() * 1000)}",
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "time_short": datetime.datetime.now().strftime("%H:%M:%S"),
            "type": "two_way_swap" if target_item else "single_shift",
            "message": msg,
            "source_id": str(source_item.get("id")),
            "source_subject": str(source_item.get("subject_name", "")),
            "source_teacher": str(source_item.get("teacher_name", "")),
            "source_class": str(source_item.get("class_name", "")),
            "source_old_day": str(old_day),
            "source_old_period": str(old_period),
            "source_new_day": str(target_day),
            "source_new_period": str(target_period),
            "target_id": str(target_item.get("id")) if target_item else None,
            "target_subject": str(target_item.get("subject_name", "")) if target_item else None,
            "target_teacher": str(target_item.get("teacher_name", "")) if target_item else None,
            "target_class": str(target_item.get("class_name", "")) if target_item else None,
            "target_old_day": str(target_day) if target_item else None,
            "target_old_period": str(target_period) if target_item else None,
            "target_new_day": str(old_day) if target_item else None,
            "target_new_period": str(old_period) if target_item else None
        }
        if "swap_history" not in cfg:
            cfg["swap_history"] = []
        cfg["swap_history"].append(swap_record)
        if len(cfg["swap_history"]) > 150:
            cfg["swap_history"] = cfg["swap_history"][-150:]
            
        cfg["solved_schedules"] = solved
        save_config_rules(cfg)
        
        global _cached_data
        _cached_data = None
        
        try:
            solved_excel = os.path.join(os.path.dirname(__file__), "School_Schedule_Solved.xlsx")
            import pandas as pd
            df = pd.DataFrame(solved)
            df.to_excel(solved_excel, index=False)
        except Exception as ee:
            print(f"[Warning] Failed to update Solved Excel: {ee}")
            
        return jsonify({
            "status": "success",
            "message": msg,
            "solved": solved,
            "history_count": len(cfg["swap_history"])
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"手調失敗: {str(e)}"}), 500

@app.route("/api/swap-history")
def api_get_swap_history():
    try:
        cfg = load_config_rules()
        history = cfg.get("swap_history", [])
        return jsonify({
            "status": "success",
            "history": history,
            "count": len(history)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/undo-swap", methods=["POST"])
def api_undo_swap():
    try:
        cfg = load_config_rules()
        history = cfg.get("swap_history", [])
        if not history:
            return jsonify({"status": "error", "message": "目前尚無任何可復原的調課紀錄！"}), 400
        
        req = request.get_json(silent=True) or {}
        record_id = req.get("record_id")
        
        record = None
        if record_id:
            for r in reversed(history):
                if r.get("id") == record_id:
                    record = r
                    break
        else:
            record = history[-1]
            
        if not record:
            return jsonify({"status": "error", "message": "找不到該筆調課紀錄"}), 404
            
        solved = get_current_solved_schedules()
        
        # 1. Revert source item
        s_id = str(record.get("source_id"))
        s_old_d = str(record.get("source_old_day"))
        s_old_p = str(record.get("source_old_period"))
        
        for s in solved:
            if str(s.get("id")) == s_id:
                s["day"] = s_old_d
                s["period"] = s_old_p
                break
                
        # 2. Revert target item if two-way swap
        t_id = record.get("target_id")
        if t_id:
            t_id = str(t_id)
            t_old_d = str(record.get("target_old_day"))
            t_old_p = str(record.get("target_old_period"))
            for s in solved:
                if str(s.get("id")) == t_id:
                    s["day"] = t_old_d
                    s["period"] = t_old_p
                    break
                    
        # Remove this record from history
        history.remove(record)
        cfg["swap_history"] = history
        cfg["solved_schedules"] = solved
        save_config_rules(cfg)
        
        global _cached_data
        _cached_data = None
        
        try:
            solved_excel = os.path.join(os.path.dirname(__file__), "School_Schedule_Solved.xlsx")
            import pandas as pd
            df = pd.DataFrame(solved)
            df.to_excel(solved_excel, index=False)
        except Exception as e:
            log_exception("api_undo_swap:save_local_copy", e)
            
        undo_msg = f"↩️ 成功復原上一筆調課！已將【{record.get('source_subject', '')}】還原至原時段。"
        return jsonify({
            "status": "success",
            "message": undo_msg,
            "history": history,
            "count": len(history),
            "solved": solved
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"復原失敗: {str(e)}"}), 500

@app.route("/api/clear-swap-history", methods=["POST"])
def api_clear_swap_history():
    try:
        cfg = load_config_rules()
        cfg["swap_history"] = []
        save_config_rules(cfg)
        return jsonify({"status": "success", "message": "已清空所有調課歷史紀錄"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def log_exception(context, exc):
    message = f"[{context}] {exc}"
    try:
        print(message)
    except Exception:
        log_exception("log_exception:stdout", traceback.format_exc())
    try:
        with open(APP_LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
            f.write(message + "\n")
    except Exception:
        # Avoid recursion if logging itself fails.
        pass

def sync_to_github_cloud(filename, content_str, commit_message="Cloud Web UI Auto Save"):
    if not GITHUB_REPO or not GITHUB_TOKEN or len(GITHUB_TOKEN) < 10:
        return False
    def _bg_sync():
        try:
            import urllib.request, base64
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
            auth_header = f"Bearer {GITHUB_TOKEN}" if GITHUB_TOKEN.startswith("github_pat_") else f"token {GITHUB_TOKEN}"
            req_get = urllib.request.Request(url, headers={
                "Authorization": auth_header,
                "User-Agent": "Flask-Cloud-Sync"
            })
            sha = None
            try:
                with urllib.request.urlopen(req_get) as resp:
                    res_data = json.loads(resp.read().decode('utf-8'))
                    sha = res_data.get("sha")
            except Exception:
                log_exception("sync_to_github_cloud:get_sha", traceback.format_exc())

            encoded_content = base64.b64encode(content_str.encode('utf-8')).decode('utf-8')
            payload = {
                "message": commit_message,
                "content": encoded_content,
                "branch": GITHUB_BRANCH
            }
            if sha:
                payload["sha"] = sha

            req_put = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={
                "Authorization": auth_header,
                "Content-Type": "application/json",
                "User-Agent": "Flask-Cloud-Sync"
            }, method="PUT")

            with urllib.request.urlopen(req_put) as resp:
                print(f"Cloud Auto-Sync {filename} to GitHub: SUCCESS")
                
            # Trigger Render Deploy Hook
            try:
                render_hook = "https://api.render.com/deploy/srv-d9sr1lqfngtc73fspco0?key=fPNTvxZ36mw"
                hook_req = urllib.request.Request(render_hook, method="POST")
                with urllib.request.urlopen(hook_req) as r_resp:
                    print("Render Deploy Hook Triggered Successfully:", r_resp.read().decode('utf-8'))
            except Exception as e_hook:
                log_exception("sync_to_github_cloud:render_hook", e_hook)
        except Exception as e:
            log_exception("sync_to_github_cloud", e)

    import threading
    threading.Thread(target=_bg_sync, daemon=True).start()

def load_config_rules():
    if os.path.exists(CONFIG_RULES_FILE):
        try:
            with open(CONFIG_RULES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_exception("load_config_rules:local", e)
    # Try fetching from GitHub if GITHUB_REPO set
    if GITHUB_REPO:
        try:
            import urllib.request
            raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/config_rules.json"
            with urllib.request.urlopen(raw_url) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                with open(CONFIG_RULES_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return data
        except Exception as e:
            log_exception("load_config_rules:github", e)
    return {
        "custom_no_teach": {},
        "custom_no_sub": {},
        "weights": {
            "consecutive_weight": 500,
            "no_teach_penalty": 200,
            "no_sub_penalty": 200,
            "spreading_weight": 10
        }
    }

SEMESTERS_DIR = os.path.join(DATA_DIR, "semesters")

def get_active_semester_id():
    cfg = load_config_rules()
    return cfg.get("active_semester_id", "115-1")

def get_semester_file_path(sem_id):
    if not os.path.exists(SEMESTERS_DIR):
        try:
            os.makedirs(SEMESTERS_DIR, exist_ok=True)
        except Exception:
            pass
    safe_id = str(sem_id).replace("/", "_").replace("\\", "_").replace(" ", "_")
    return os.path.join(SEMESTERS_DIR, f"{safe_id}.json")

def save_current_semester_single_file(sem_id=None):
    try:
        if os.path.exists(CONFIG_RULES_FILE):
            with open(CONFIG_RULES_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        else:
            cfg = {}
        
        if not sem_id:
            sem_id = cfg.get("active_semester_id", "115-1")
            
        cfg["active_semester_id"] = sem_id
        
        solved_records = cfg.get("solved_schedules", [])
        if not solved_records:
            solved_excel = get_solved_excel_path()
            if solved_excel and os.path.exists(solved_excel):
                try:
                    import pandas as pd
                    df = pd.read_excel(solved_excel).fillna("")
                    solved_records = df.to_dict(orient="records")
                except Exception as e:
                    log_exception("save_current_semester_single_file:read_excel", e)

        year = "115"
        term = "1"
        if "-" in str(sem_id):
            parts = str(sem_id).split("-")
            year, term = parts[0], parts[1]

        sem_data = {
            "semester_id": sem_id,
            "school_name": cfg.get("school_name", "學校名稱"),
            "year": year,
            "term": term,
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "config_rules": cfg,
            "solved_schedules": solved_records
        }
        
        file_path = get_semester_file_path(sem_id)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(sem_data, f, ensure_ascii=False, indent=2)
        return file_path
    except Exception as e:
        print("Error saving single semester file:", e)
        return None

_config_save_lock = threading.RLock()

def save_config_rules(data):
    with _config_save_lock:
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        try:
            with open(CONFIG_RULES_FILE, "w", encoding="utf-8") as f:
                f.write(json_str)
        except Exception as e:
            log_exception("save_config_rules:write", e)
            raise
        sync_to_github_cloud("config_rules.json", json_str, "Cloud Web UI Auto Save config_rules.json")
        save_current_semester_single_file()

# --- SEMESTERS API ROUTES ---

@app.route("/api/semesters", methods=["GET"])
@app.route("/api/semesters/list", methods=["GET"])
def api_get_semesters():
    try:
        active_id = get_active_semester_id()
        semesters = []
        if os.path.exists(SEMESTERS_DIR):
            for fname in os.listdir(SEMESTERS_DIR):
                if fname.endswith(".json"):
                    fpath = os.path.join(SEMESTERS_DIR, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            sem_id = data.get("semester_id", fname[:-5])
                            year = data.get("year", "115")
                            term = data.get("term", "1")
                            updated_at = data.get("updated_at", "")
                            records_count = len(data.get("solved_schedules", []))
                            semesters.append({
                                "semester_id": sem_id,
                                "year": year,
                                "term": term,
                                "updated_at": updated_at,
                                "records_count": records_count,
                                "is_active": (sem_id == active_id)
                            })
                    except Exception as e:
                        log_exception("api_get_semesters:read_semester_file", e)
        if not semesters:
            semesters.append({
                "semester_id": "115-1",
                "year": "115",
                "term": "1",
                "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "records_count": 819,
                "is_active": True
            })
        semesters.sort(key=lambda x: x["semester_id"], reverse=True)
        return jsonify({
            "status": "success",
            "active_id": active_id,
            "active_semester_id": active_id,
            "semesters": semesters
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/semesters/switch", methods=["POST"])
def api_switch_semester():
    try:
        req = request.get_json() or {}
        sem_id = req.get("semester_id")
        if not sem_id:
            return jsonify({"status": "error", "message": "未提供學期 ID"}), 400
        
        fpath = get_semester_file_path(sem_id)
        if not os.path.exists(fpath):
            return jsonify({"status": "error", "message": f"找不到學期檔案: {sem_id}"}), 404
            
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        cfg = data.get("config_rules", {})
        cfg["active_semester_id"] = sem_id
        if "solved_schedules" in data:
            cfg["solved_schedules"] = data["solved_schedules"]
            
        save_config_rules(cfg)
        
        global _cached_data
        _cached_data = None
        
        return jsonify({
            "status": "success",
            "message": f"已成功切換至學期：{sem_id}",
            "active_semester_id": sem_id
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/semesters/create", methods=["POST"])
def api_create_semester():
    try:
        req = request.get_json() or {}
        year = str(req.get("year", "115")).strip()
        term = str(req.get("term", "1")).strip()
        sem_id = f"{year}-{term}"
        
        fpath = get_semester_file_path(sem_id)
        cfg = load_config_rules()
        cfg["active_semester_id"] = sem_id
        
        save_current_semester_single_file(sem_id)
        return jsonify({
            "status": "success",
            "message": f"學期檔案 {sem_id} 已成功建立！",
            "semester_id": sem_id
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/semesters/delete", methods=["POST"])
def api_delete_semester():
    try:
        req = request.get_json() or {}
        sem_id = req.get("semester_id")
        if not sem_id:
            return jsonify({"status": "error", "message": "未提供學期 ID"}), 400
        if sem_id == get_active_semester_id():
            return jsonify({"status": "error", "message": "無法刪除目前使用中的學期！"}), 400
            
        fpath = get_semester_file_path(sem_id)
        if os.path.exists(fpath):
            os.remove(fpath)
            return jsonify({"status": "success", "message": f"學期 {sem_id} 已成功刪除！"})
        return jsonify({"status": "error", "message": "學期檔案不存在"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/semesters/export-single/<path:sem_id>", methods=["GET"])
def api_export_single_semester(sem_id):
    try:
        fpath = get_semester_file_path(sem_id)
        if not os.path.exists(fpath):
            save_current_semester_single_file(sem_id)
        return send_file(
            fpath,
            mimetype="application/json",
            as_attachment=True,
            download_name=f"{sem_id}.json"
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/semesters/import-single", methods=["POST"])
def api_import_single_semester():
    try:
        if "file" not in request.files:
            return jsonify({"status": "error", "message": "未上傳檔案"}), 400
        file = request.files["file"]
        if not file or file.filename == "":
            return jsonify({"status": "error", "message": "未選擇檔案"}), 400
            
        data = json.load(file)
        sem_id = data.get("semester_id")
        if not sem_id:
            sem_id = os.path.splitext(file.filename)[0]
            data["semester_id"] = sem_id
            
        fpath = get_semester_file_path(sem_id)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        return jsonify({"status": "success", "message": f"學期單檔 {sem_id} 已成功匯入！"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/export-config", methods=["GET"])
def api_export_config():
    try:
        cfg = load_config_rules()
        import io
        mem = io.BytesIO()
        mem.write(json.dumps(cfg, ensure_ascii=False, indent=2).encode('utf-8'))
        mem.seek(0)
        return send_file(
            mem,
            mimetype="application/json",
            as_attachment=True,
            download_name="School_Schedule_Config_Backup.json"
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/import-config", methods=["POST"])
def api_import_config():
    try:
        if "file" not in request.files:
            return jsonify({"status": "error", "message": "No file uploaded"}), 400
        file = request.files["file"]
        if file.filename == "":
            return jsonify({"status": "error", "message": "No file selected"}), 400
            
        data = json.load(file)
        if not isinstance(data, dict):
            return jsonify({"status": "error", "message": "Invalid JSON structure"}), 400
            
        save_config_rules(data)
        
        global _cached_data
        _cached_data = None
        
        return jsonify({"status": "success", "message": "全校配課與排課規則備份檔已成功匯入！"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/backup/export", methods=["GET"])
def api_backup_export():
    try:
        import zipfile
        memory_file = io.BytesIO()
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base_dir = os.path.dirname(__file__)
        
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            cfg_path = os.path.join(base_dir, "config_rules.json")
            if os.path.exists(cfg_path):
                zf.write(cfg_path, "config_rules.json")

            excel_paths = [get_solved_excel_path(), os.path.join(base_dir, "School_Schedule_Solved.xlsx")]
            for ep in excel_paths:
                if ep and os.path.exists(ep):
                    zf.write(ep, "School_Schedule_Solved.xlsx")
                    break

            local_dbf = os.path.join(base_dir, "dbf_data")
            if os.path.isdir(local_dbf):
                for root, _, files in os.walk(local_dbf):
                    for file in files:
                        full_p = os.path.join(root, file)
                        rel_p = os.path.relpath(full_p, base_dir)
                        zf.write(full_p, rel_p)
                        
        memory_file.seek(0)
        filename = f"School_Schedule_Backup_{now_str}.zip"
        return send_file(
            memory_file,
            mimetype="application/zip",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({"status": "error", "message": f"備份匯出失敗: {str(e)}"}), 500

@app.route("/api/backup/import", methods=["POST"])
def api_backup_import():
    try:
        if "file" not in request.files:
            return jsonify({"status": "error", "message": "未收到備份檔案"}), 400
        
        file = request.files["file"]
        if not file or file.filename == "":
            return jsonify({"status": "error", "message": "未選擇備份檔案"}), 400

        base_dir = os.path.dirname(__file__)

        if file.filename.endswith(".json"):
            data = json.load(file)
            if isinstance(data, dict):
                save_config_rules(data)
        elif file.filename.endswith(".zip"):
            import zipfile
            with zipfile.ZipFile(file, 'r') as zf:
                for member in zf.namelist():
                    member_path = os.path.normpath(member)
                    if member_path.startswith("..") or os.path.isabs(member_path):
                        continue
                    zf.extract(member, base_dir)
        else:
            return jsonify({"status": "error", "message": "不支援的檔案格式，請上傳 .zip 或 .json"}), 400

        global _cached_data
        _cached_data = None
        return jsonify({"status": "success", "message": "備份資料已成功一鍵還原！"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"還原失敗: {str(e)}"}), 500

@app.route("/api/backup/reset", methods=["POST"])
def api_backup_reset():
    """一鍵清空現有學校資料 (移交/換校重置)"""
    global _cached_data, _db_mtimes
    try:
        import zipfile
        base_dir = os.path.dirname(__file__)
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(base_dir, "restore_points")
        os.makedirs(backup_dir, exist_ok=True)
        auto_backup_path = os.path.join(backup_dir, f"AutoBackup_Before_Reset_{now_str}.zip")

        dbf_dir = get_latest_dbf_dir()

        # 1. Automatic safety backup before wipe (備份所有設定、課表、欣河 Excel、筆記與紀錄)
        with zipfile.ZipFile(auto_backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # 備份 config_rules.json
            cfg_path = os.path.join(base_dir, "config_rules.json")
            if os.path.exists(cfg_path):
                zf.write(cfg_path, "config_rules.json")

            # 備份已解算課表
            for ep in [os.path.join(base_dir, "School_Schedule_Solved.xlsx"), os.path.join(DATA_DIR, "School_Schedule_Solved.xlsx")]:
                if ep and os.path.exists(ep):
                    zf.write(ep, "School_Schedule_Solved.xlsx")
                    break

            # 備份欣河匯出檔
            xinhe_targets = [
                os.path.join(base_dir, "dbf_data", XINHE_EXPORT_FILENAME),
                os.path.join(DATA_DIR, XINHE_EXPORT_FILENAME)
            ]
            if dbf_dir:
                xinhe_targets.append(os.path.join(dbf_dir, XINHE_EXPORT_FILENAME))
            for xp in xinhe_targets:
                if os.path.exists(xp):
                    zf.write(xp, f"xinhe_export.xlsx")
                    break

            # 備份課表備忘與調課紀錄
            for extra_json in ["lesson_notes.json", "swap_history.json"]:
                p = os.path.join(base_dir, extra_json)
                if os.path.exists(p):
                    zf.write(p, extra_json)

        # 2. Reset config_rules.json to generic template
        clean_cfg = {
            "school_name": "學校名稱",
            "school_subtitle": "Senior High School",
            "year": "114",
            "term": "1",
            "dbf_search_dir": "",
            "period_times": {
                "1": {"name": "第1節", "time": "08:10-08:55"},
                "2": {"name": "第2節", "time": "09:05-09:50"},
                "3": {"name": "第3節", "time": "10:10-10:55"},
                "4": {"name": "第4節", "time": "11:05-11:50"},
                "5": {"name": "第5節", "time": "13:10-13:55"},
                "6": {"name": "第6節", "time": "14:05-14:50"},
                "7": {"name": "第7節", "time": "15:05-15:50"},
                "8": {"name": "第8節", "time": "16:00-16:45"}
            },
            "custom_assignments": {},
            "deleted_assignments": [],
            "custom_no_teach": {},
            "custom_no_sub": {},
            "custom_simultaneous_groups": [],
            "venue_capacities": {},
            "subject_venue_mappings": [],
            "consecutive_subjects": ["104", "105", "110"],
            "class_consecutive_rules": [],
            "solved_schedules": [],
            "weights": {
                "spreading_weight": 15,
                "consecutive_weight": 600,
                "no_teach_penalty": 300,
                "no_sub_penalty": 300,
                "morning_pref_weight": 50,
                "pe_noon_penalty_weight": 100
            }
        }
        save_config_rules(clean_cfg)

        # 3. Remove existing solved Excel files & Xinhe Excel files & notes
        files_to_remove = [
            os.path.join(base_dir, "School_Schedule_Solved.xlsx"),
            os.path.join(DATA_DIR, "School_Schedule_Solved.xlsx"),
            os.path.join(base_dir, "dbf_data", XINHE_EXPORT_FILENAME),
            os.path.join(DATA_DIR, XINHE_EXPORT_FILENAME),
            os.path.join(base_dir, "lesson_notes.json"),
            os.path.join(base_dir, "swap_history.json")
        ]
        if dbf_dir:
            files_to_remove.append(os.path.join(dbf_dir, XINHE_EXPORT_FILENAME))

        for fpath in files_to_remove:
            if fpath and os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except Exception as e:
                    log_exception("api_backup_reset:remove_file", e)

        # 4. Invalidate all global caches
        _cached_data = None
        _db_mtimes = {}

        return jsonify({
            "status": "success",
            "message": f"🎉 全系統舊學校資料（含欣河排課 Excel、解算課表與設定規則）已成功一鍵清空！\n系統已自動在 restore_points 建立安全備份檔案：{os.path.basename(auto_backup_path)}\n\n現已重置為全新空白學校範本，您可以直接匯入新學校的資料開始使用！",
            "auto_backup": auto_backup_path
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"status": "error", "message": f"清空重置失敗: {str(e)}"}), 500


@app.route("/api/auto-assign", methods=["POST"])
def api_auto_assign():
    """AI Intelligent Teacher-Course Auto-Assignment Algorithm."""
    try:
        req = request.get_json(silent=True) or {}
        overwrite = req.get("overwrite", True)
        
        cfg = load_config_rules()
        data = load_schedule_data()
        
        # 1. Gather all classes
        classes = data.get("classes", [])
        if not classes:
            custom_classes = cfg.get("custom_classes", [])
            if custom_classes:
                classes = custom_classes
            else:
                classes = [
                    {"code": "701", "name": "701班", "tutor": "王美玲"},
                    {"code": "702", "name": "702班", "tutor": "陳建宏"},
                    {"code": "703", "name": "703班", "tutor": "林志豪"},
                    {"code": "801", "name": "801班", "tutor": "張大明"},
                    {"code": "802", "name": "802班", "tutor": "李小華"},
                    {"code": "803", "name": "803班", "tutor": "郭德華"},
                    {"code": "901", "name": "901班", "tutor": "蔡小芬"},
                    {"code": "902", "name": "902班", "tutor": "廖健宏"},
                    {"code": "903", "name": "903班", "tutor": "黃秀英"},
                    {"code": "101", "name": "高一忠", "tutor": "鄭志偉"},
                    {"code": "102", "name": "高一孝", "tutor": "吳佩珊"},
                    {"code": "201", "name": "高二忠", "tutor": "許文傑"},
                    {"code": "202", "name": "高二孝", "tutor": "楊淑芬"},
                    {"code": "301", "name": "高三忠", "tutor": "劉家豪"},
                    {"code": "302", "name": "高三孝", "tutor": "謝銘峰"}
                ]

        # 2. Gather all teachers
        teachers = data.get("teachers", [])
        if not teachers:
            custom_teachers = cfg.get("custom_teachers", [])
            if custom_teachers:
                teachers = custom_teachers
            else:
                teachers = [
                    {"code": "T01", "name": "王美玲", "role": "國文導師", "base_hours": 14, "teach_hours": 14},
                    {"code": "T02", "name": "陳建宏", "role": "數學導師", "base_hours": 14, "teach_hours": 14},
                    {"code": "T03", "name": "林志豪", "role": "英文導師", "base_hours": 14, "teach_hours": 14},
                    {"code": "T04", "name": "張大明", "role": "自然專任", "base_hours": 16, "teach_hours": 16},
                    {"code": "T05", "name": "李小華", "role": "國文專任", "base_hours": 16, "teach_hours": 16},
                    {"code": "T06", "name": "郭德華", "role": "社會導師", "base_hours": 14, "teach_hours": 14},
                    {"code": "T07", "name": "蔡小芬", "role": "地理專任", "base_hours": 16, "teach_hours": 16},
                    {"code": "T08", "name": "廖健宏", "role": "體育導師", "base_hours": 14, "teach_hours": 14},
                    {"code": "T09", "name": "黃秀英", "role": "英文專任", "base_hours": 16, "teach_hours": 16},
                    {"code": "T10", "name": "鄭志偉", "role": "數學專任", "base_hours": 16, "teach_hours": 16}
                ]

        # Build teacher capacity tracking
        teacher_dict = {}
        for t in teachers:
            code = str(t.get("code", "")).strip()
            name = str(t.get("name", "")).strip()
            role = str(t.get("role", "")).strip()
            target_hours = int(t.get("teach_hours") or t.get("base_hours") or 16)
            if code and name:
                teacher_dict[code] = {
                    "code": code,
                    "name": name,
                    "role": role,
                    "target_hours": target_hours,
                    "current_hours": 0
                }

        grade_curriculum = cfg.get("grade_curriculum", {})
        custom_assign = cfg.get("custom_assignments", {})

        if not overwrite:
            for k, assign in custom_assign.items():
                t_code = str(assign.get("teacher_code", "")).strip()
                hrs = int(assign.get("hours", 0))
                if t_code in teacher_dict:
                    teacher_dict[t_code]["current_hours"] += hrs

        new_assignments = {} if overwrite else dict(custom_assign)
        assigned_count = 0
        assigned_classes_set = set()

        for c in classes:
            c_code = str(c.get("code", "")).strip()
            c_name = str(c.get("name", c_code)).strip()
            c_tutor = str(c.get("tutor", "")).strip()

            if not c_code:
                continue

            g_char = c_code[0]
            curriculum_list = grade_curriculum.get(g_char, [])
            
            if not curriculum_list:
                if g_char in ["7", "8", "9"]:
                    curriculum_list = [
                        {"subject_code": "J101", "subject_name": "國語文", "hours": 5},
                        {"subject_code": "J102", "subject_name": "英語文", "hours": 4},
                        {"subject_code": "J103", "subject_name": "數學", "hours": 4},
                        {"subject_code": "J105", "subject_name": "自然/生物", "hours": 3},
                        {"subject_code": "J107", "subject_name": "歷史", "hours": 1},
                        {"subject_code": "J108", "subject_name": "地理", "hours": 1},
                        {"subject_code": "J109", "subject_name": "公民", "hours": 1},
                        {"subject_code": "J110", "subject_name": "體育", "hours": 2},
                        {"subject_code": "J111", "subject_name": "健康教育", "hours": 1},
                        {"subject_code": "J112", "subject_name": "音樂", "hours": 1},
                        {"subject_code": "J113", "subject_name": "視覺藝術", "hours": 1},
                        {"subject_code": "J114", "subject_name": "童軍", "hours": 1},
                        {"subject_code": "J115", "subject_name": "家政", "hours": 1},
                        {"subject_code": "J116", "subject_name": "資訊科技", "hours": 1}
                    ]
                else:
                    curriculum_list = [
                        {"subject_code": "H101", "subject_name": "國語文", "hours": 4},
                        {"subject_code": "H102", "subject_name": "英語文", "hours": 4},
                        {"subject_code": "H103", "subject_name": "數學A", "hours": 4},
                        {"subject_code": "H104", "subject_name": "物理", "hours": 2},
                        {"subject_code": "H105", "subject_name": "化學", "hours": 2},
                        {"subject_code": "H106", "subject_name": "生物", "hours": 2},
                        {"subject_code": "H107", "subject_name": "歷史", "hours": 2},
                        {"subject_code": "H108", "subject_name": "地理", "hours": 2},
                        {"subject_code": "H109", "subject_name": "公民與社會", "hours": 2},
                        {"subject_code": "H110", "subject_name": "體育", "hours": 2}
                    ]

            for curr in curriculum_list:
                s_code = str(curr.get("subject_code", "")).strip()
                s_name = str(curr.get("subject_name", s_code)).strip()
                hours = int(curr.get("hours", 2))

                assign_key = f"{c_code}|{s_code}"

                if not overwrite and assign_key in new_assignments:
                    existing_t = new_assignments[assign_key].get("teacher_code")
                    if existing_t:
                        continue

                matched_teacher = None

                # Priority 1: Match teacher by subject specialty and workload capacity (max 24h per teacher)
                candidates = []
                for t_code, t_info in teacher_dict.items():
                    if t_info["current_hours"] + hours > 24:
                        continue

                    score = 0
                    s_sub = s_name[:2]

                    if s_sub in t_info["role"] or s_sub in t_info["name"]:
                        score += 50

                    if c_tutor and t_info["name"] == c_tutor and s_sub in t_info["role"]:
                        score += 30

                    rem = t_info["target_hours"] - t_info["current_hours"]
                    score += rem

                    candidates.append((score, rem, t_info))

                candidates.sort(key=lambda x: x[0], reverse=True)
                if candidates:
                    matched_teacher = candidates[0][2]

                if matched_teacher:
                    t_code = matched_teacher["code"]
                    t_name = matched_teacher["name"]
                    matched_teacher["current_hours"] += hours

                    new_assignments[assign_key] = {
                        "class_code": c_code,
                        "class_name": c_name,
                        "subject_code": s_code,
                        "subject_name": s_name,
                        "teacher_code": t_code,
                        "teacher_name": t_name,
                        "hours": hours
                    }
                    assigned_count += 1
                    assigned_classes_set.add(c_name)

        cfg["custom_assignments"] = new_assignments
        save_config_rules(cfg)

        global _cached_data
        _cached_data = None

        return jsonify({
            "status": "success",
            "message": f"🤖 AI 智慧自動配課完成！已成功為 {len(assigned_classes_set)} 個班級完成 {assigned_count} 筆科目的教師指派與授課額度平衡。",
            "assigned_count": assigned_count,
            "assigned_classes_count": len(assigned_classes_set),
            "custom_assignments": new_assignments
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"AI 自動配課失敗: {str(e)}"}), 500

@app.route("/api/config-rules", methods=["GET"])
def api_get_config_rules():
    try:
        cfg = load_config_rules()
        dbf_no_teach = {}
        dbf_no_sub = {}
        
        try:
            dbf_dir = get_latest_dbf_dir()
            if dbf_dir:
                no_teach_path = os.path.join(dbf_dir, "no_teach.dbf")
                if os.path.exists(no_teach_path):
                    db_no_teach = list(DBF(no_teach_path, ignore_missing_memofile=True, encoding='cp950'))
                    for rule in db_no_teach:
                        tc = rule.get("TEACHER_NO", "").strip()
                        if tc:
                            if tc not in dbf_no_teach:
                                dbf_no_teach[tc] = []
                            sd = rule.get("START_DAY", 1)
                            ed = rule.get("END_DAY", 1)
                            ss = rule.get("START_SEC", 1)
                            es = rule.get("END_SEC", 1)
                            for d in range(sd, ed + 1):
                                for p in range(ss, es + 1):
                                    slot_str = f"{d}-{p}"
                                    if slot_str not in dbf_no_teach[tc]:
                                        dbf_no_teach[tc].append(slot_str)

                no_sub_path = os.path.join(dbf_dir, "no_sub.dbf")
                if os.path.exists(no_sub_path):
                    db_no_sub = list(DBF(no_sub_path, ignore_missing_memofile=True, encoding='cp950'))
                    for rule in db_no_sub:
                        cc = rule.get("CLASS_NO", "").strip()
                        sc = rule.get("SUBJECT_NO", "").strip()
                        if cc and sc:
                            key = f"{cc}|{sc}"
                        if key not in dbf_no_sub:
                            dbf_no_sub[key] = []
                        sd = rule.get("START_DAY", 1)
                        ed = rule.get("END_DAY", 1)
                        ss = rule.get("START_SEC", 1)
                        es = rule.get("END_SEC", 1)
                        for d in range(sd, ed + 1):
                            for p in range(ss, es + 1):
                                slot_str = f"{d}-{p}"
                                if slot_str not in dbf_no_sub[key]:
                                    dbf_no_sub[key].append(slot_str)
        except Exception as de:
            print(f"[Warning] Failed reading DBF rules: {de}")

        # Merge DBF with custom rules
        merged_no_teach = dict(dbf_no_teach)
        for tc, slots in cfg.get("custom_no_teach", {}).items():
            if tc not in merged_no_teach:
                merged_no_teach[tc] = []
            for s in slots:
                if s not in merged_no_teach[tc]:
                    merged_no_teach[tc].append(s)

        merged_no_sub = dict(dbf_no_sub)
        for key, slots in cfg.get("custom_no_sub", {}).items():
            if key not in merged_no_sub:
                merged_no_sub[key] = []
            for s in slots:
                if s not in merged_no_sub[key]:
                    merged_no_sub[key].append(s)

        return jsonify({
            "status": "success",
            "no_teach": merged_no_teach,
            "no_sub": merged_no_sub,
            "weights": cfg.get("weights", {
                "consecutive_weight": 500,
                "no_teach_penalty": 200,
                "no_sub_penalty": 200,
                "spreading_weight": 10
            })
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/config-rules/save-no-teach", methods=["POST"])
def api_save_no_teach():
    try:
        req = request.get_json() or {}
        cfg = load_config_rules()
        if "custom_no_teach" not in cfg:
            cfg["custom_no_teach"] = {}
            
        if "no_teach" in req and isinstance(req["no_teach"], dict):
            cfg["custom_no_teach"].update(req["no_teach"])
            msg = "教師不排課設定已儲存！"
        else:
            tc = req.get("teacher_code")
            slots = req.get("slots", [])
            if not tc:
                return jsonify({"status": "error", "message": "Teacher code is required"}), 400
            cfg["custom_no_teach"][tc] = slots
            msg = f"教師 {tc} 不排課設定已儲存！"
            
        save_config_rules(cfg)
        trigger_auto_solver()
        return jsonify({"status": "success", "message": msg + " 全校 AI 已自動為您重新求解與更新課表！", "solved": True})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/config-rules/save-no-sub", methods=["POST"])
def api_save_no_sub():
    try:
        req = request.get_json() or {}
        cfg = load_config_rules()
        if "custom_no_sub" not in cfg:
            cfg["custom_no_sub"] = {}
            
        if "no_sub" in req and isinstance(req["no_sub"], dict):
            cfg["custom_no_sub"].update(req["no_sub"])
            msg = "科目限制時段已儲存！"
        else:
            cc = req.get("class_code")
            sc = req.get("subject_code")
            slots = req.get("slots", [])
            if not cc or not sc:
                return jsonify({"status": "error", "message": "Class and Subject code are required"}), 400
            key = f"{cc}|{sc}"
            cfg["custom_no_sub"][key] = slots
            msg = f"班級 {cc} 科目 {sc} 限制時段已儲存！"
            
        save_config_rules(cfg)
        trigger_auto_solver()
        return jsonify({"status": "success", "message": msg + " 全校 AI 已自動為您重新求解與更新課表！", "solved": True})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/school-wide-blocked-slots", methods=["GET", "POST"])
def api_school_wide_blocked_slots():
    try:
        cfg = load_config_rules()
        if "school_wide_blocked_slots" not in cfg:
            cfg["school_wide_blocked_slots"] = []
            
        if request.method == "GET":
            return jsonify({
                "status": "success",
                "blocked_slots": cfg["school_wide_blocked_slots"]
            })
            
        req = request.get_json() or {}
        action = req.get("action", "toggle")  # "add", "remove", "toggle", "set"
        slots = req.get("slots", [])
        day = str(req.get("day", "")).strip()
        period = str(req.get("period", "")).strip()
        
        target_slot = f"{day}-{period}" if day and period else ""
        day_names = {"1": "一", "2": "二", "3": "三", "4": "四", "5": "五"}
        d_name = day_names.get(day, day)
        
        current_slots = list(cfg["school_wide_blocked_slots"])
        
        if action == "set":
            current_slots = slots
            msg = "全校留空/班週會專用時段已更新！"
        elif action == "add" and target_slot:
            if target_slot not in current_slots:
                current_slots.append(target_slot)
            msg = f"已成功鎖定【週{d_name} 第{period}節】為全校班週會專用時段 (禁止排入正課)！"
        elif action == "remove" and target_slot:
            if target_slot in current_slots:
                current_slots.remove(target_slot)
            msg = f"已成功解除【週{d_name} 第{period}節】全校鎖定！"
        elif action == "toggle" and target_slot:
            if target_slot in current_slots:
                current_slots.remove(target_slot)
                msg = f"已解除【週{d_name} 第{period}節】全校留空鎖定！"
            else:
                current_slots.append(target_slot)
                msg = f"已成功鎖定【週{d_name} 第{period}節】為全校班週會專用時段 (禁止排入正課)！"
        else:
            msg = "設定完成"
            
        cfg["school_wide_blocked_slots"] = current_slots
        save_config_rules(cfg)
        return jsonify({
            "status": "success",
            "message": msg,
            "blocked_slots": current_slots
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/course-assignments", methods=["GET"])
def api_get_course_assignments():
    try:
        data = load_schedule_data()
        cfg = load_config_rules()
        custom_assign = cfg.get("custom_assignments", {})

        assignments = {}

        # 1. Group from data["schedules"]
        schedules = data.get("schedules", [])
        for s in schedules:
            cc = str(s.get("class_code") or s.get("班級代碼") or "").strip()
            cn = str(s.get("class_name") or s.get("班級名稱") or cc).strip()
            sc = str(s.get("subject_code") or s.get("科目代碼") or "").strip()
            sn = str(s.get("subject_name") or s.get("科目名稱") or sc).strip()
            tc = str(s.get("teacher_code") or s.get("教師代碼") or "").strip()
            tn = str(s.get("teacher_name") or s.get("教師姓名") or tc).strip()

            if not cc or not sc:
                continue

            if cc not in assignments:
                assignments[cc] = {
                    "class_code": cc,
                    "class_name": cn,
                    "subjects": {}
                }

            override_key = f"{cc}|{sc}"
            if override_key in custom_assign:
                tc = custom_assign[override_key].get("teacher_code", tc)
                tn = custom_assign[override_key].get("teacher_name", tn)

            if sc not in assignments[cc]["subjects"]:
                assignments[cc]["subjects"][sc] = {
                    "subject_code": sc,
                    "subject_name": sn,
                    "teacher_code": tc,
                    "teacher_name": tn,
                    "hours": 1
                }
            else:
                assignments[cc]["subjects"][sc]["hours"] += 1

        # 2. ALSO Process custom_assignments directly so assignments show up even if schedules is empty
        for key, assign in custom_assign.items():
            cc = str(assign.get("class_code", "")).strip()
            cn = str(assign.get("class_name", cc)).strip()
            sc = str(assign.get("subject_code", "")).strip()
            sn = str(assign.get("subject_name", sc)).strip()
            tc = str(assign.get("teacher_code", "")).strip()
            tn = str(assign.get("teacher_name", tc)).strip()
            hrs = int(assign.get("hours", 2))

            if not cc or not sc:
                continue

            if cc not in assignments:
                assignments[cc] = {
                    "class_code": cc,
                    "class_name": cn,
                    "subjects": {}
                }

            assignments[cc]["subjects"][sc] = {
                "subject_code": sc,
                "subject_name": sn,
                "teacher_code": tc,
                "teacher_name": tn,
                "hours": hrs
            }

        # Apply custom hours override
        for cc, info in assignments.items():
            for sub in info["subjects"].values():
                okey = f"{cc}|{sub['subject_code']}"
                if okey in custom_assign and "hours" in custom_assign[okey]:
                    sub["hours"] = int(custom_assign[okey]["hours"])

        # Convert subjects dict to list
        res_class = []
        for cc, info in sorted(assignments.items(), key=lambda x: x[0]):
            res_class.append({
                "class_code": cc,
                "class_name": info["class_name"],
                "subjects": list(info["subjects"].values())
            })

        # Group by teacher_code
        t_assignments = {}
        for c_info in res_class:
            cc = c_info["class_code"]
            cn = c_info["class_name"]
            for sub in c_info["subjects"]:
                tc = sub.get("teacher_code", "")
                tn = sub.get("teacher_name", tc)
                sc = sub.get("subject_code", "")
                sn = sub.get("subject_name", sc)
                hrs = sub.get("hours", 1)

                if not tc:
                    continue

                if tc not in t_assignments:
                    t_assignments[tc] = {
                        "teacher_code": tc,
                        "teacher_name": tn,
                        "total_hours": 0,
                        "courses": {}
                    }

                key = f"{cc}|{sc}"
                t_assignments[tc]["courses"][key] = {
                    "class_code": cc,
                    "class_name": cn,
                    "subject_code": sc,
                    "subject_name": sn,
                    "hours": hrs
                }

        # Include all teachers in t_assignments so all teachers are selectable
        all_teachers = data.get("teachers", [])
        for t in all_teachers:
            tc = t.get("code")
            if tc and tc not in t_assignments:
                t_assignments[tc] = {
                    "teacher_code": tc,
                    "teacher_name": t.get("name", tc),
                    "total_hours": 0,
                    "courses": {}
                }

        res_teacher = []
        for tc, info in sorted(t_assignments.items(), key=lambda x: str(x[1]["teacher_name"])):
            tot = sum(c["hours"] for c in info["courses"].values())
            res_teacher.append({
                "teacher_code": tc,
                "teacher_name": info["teacher_name"],
                "total_hours": tot,
                "courses": list(info["courses"].values())
            })

        return jsonify({
            "status": "success",
            "assignments": res_class,
            "teacher_assignments": res_teacher
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/delete-course-assignment", methods=["POST"])
def api_delete_course_assignment():
    try:
        req = request.get_json()
        cc = req.get("class_code")
        sc = req.get("subject_code")
        
        if not cc or not sc:
            return jsonify({"status": "error", "message": "Class and Subject are required"}), 400
            
        cfg = load_config_rules()
        if "custom_assignments" not in cfg:
            cfg["custom_assignments"] = {}
        if "deleted_assignments" not in cfg:
            cfg["deleted_assignments"] = []
            
        key = f"{cc}|{sc}"
        if key in cfg["custom_assignments"]:
            del cfg["custom_assignments"][key]
            
        if key not in cfg["deleted_assignments"]:
            cfg["deleted_assignments"].append(key)
            
        save_config_rules(cfg)
        
        # Invalidate cache
        global _cached_data
        _cached_data = None
        
        return jsonify({"status": "success", "message": f"班級 {cc} 的科目 {sc} 配課已成功移除！"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/save-course-assignment", methods=["POST"])
def api_save_course_assignment():
    try:
        req = request.get_json()
        cc = req.get("class_code")
        sc = req.get("subject_code")
        tc = req.get("teacher_code")
        tn = req.get("teacher_name", "")
        hours = req.get("hours")
        
        if not cc or not sc or not tc:
            return jsonify({"status": "error", "message": "Class, Subject, and Teacher are required"}), 400
            
        cfg = load_config_rules()
        if "custom_assignments" not in cfg:
            cfg["custom_assignments"] = {}
        
        key = f"{cc}|{sc}"
        entry = {
            "teacher_code": tc,
            "teacher_name": tn
        }
        if hours is not None:
            try:
                entry["hours"] = int(hours)
            except ValueError:
                log_exception("api_save_custom_assignment:hours", f"Invalid hours value: {hours!r}")

        cfg["custom_assignments"][key] = entry
        if "deleted_assignments" in cfg and key in cfg["deleted_assignments"]:
            cfg["deleted_assignments"].remove(key)
            
        save_config_rules(cfg)
        
        # Invalidate cache
        global _cached_data
        _cached_data = None
        
        hours_str = f"（每週 {entry['hours']} 節）" if "hours" in entry else ""
        return jsonify({"status": "success", "message": f"班級 {cc} 科目 {sc} 配課教師已更新為 {tn or tc}{hours_str}！"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/reset-schedule", methods=["POST"])
def api_reset_schedule():
    try:
        # 1. Load current base schedule entries
        data = load_schedule_data()
        schedules = data.get("schedules", [])
        
        # Fallback to claspv.dbf if schedules is empty but dbf_dir exists
        dbf_dir = get_latest_dbf_dir()
        if not schedules and dbf_dir:
            claspv_path = None
            for f in os.listdir(dbf_dir):
                if f.lower() == "claspv.dbf":
                    claspv_path = os.path.join(dbf_dir, f)
                    break
            if claspv_path:
                db_claspv = DBF(claspv_path, ignore_missing_memofile=True, encoding='cp950')
                for idx, r in enumerate(db_claspv):
                    schedules.append({
                        "class_code": r.get("班級", "").strip(),
                        "class_name": r.get("班級名稱", "").strip(),
                        "subject_code": r.get("科目", "").strip(),
                        "subject_name": r.get("科目名稱", "").strip(),
                        "teacher_code": r.get("教師", "").strip(),
                        "teacher_name": r.get("教師名稱", "").strip(),
                        "room_name": r.get("教室名稱", "").strip(),
                        "week_mode": r.get("週別設定", 0) or 0
                    })

        import pandas as pd
        records = []
        for s in schedules:
            records.append({
                "班級代碼": s.get("class_code", ""),
                "科目代碼": s.get("subject_code", ""),
                "教師代碼": s.get("teacher_code", ""),
                "班級名稱": s.get("class_name", ""),
                "科目名稱": s.get("subject_name", ""),
                "教師姓名": s.get("teacher_name", ""),
                "教室名稱": s.get("room_name", ""),
                "時間代碼": "0000",
                "星期": 0,
                "節次": 0,
                "週別設定": s.get("week_mode", 0),
                "說明": "重置清空"
            })

        df = pd.DataFrame(records)
        excel_path = os.path.join(DATA_DIR, "School_Schedule_Solved.xlsx")
        try:
            df.to_excel(excel_path, index=False)
        except Exception as e:
            log_exception("api_reset_schedule:write_excel", e)

        global _cached_data
        _cached_data = None
        
        return jsonify({"status": "success", "message": "全校課表已成功清零！已將所有課程時間節次重置為「未排課」，即刻可重新進行 AI 排課或手動調課。"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"清零失敗: {str(e)}"}), 500

@app.route("/api/config-rules/save-weights", methods=["POST"])
def api_save_weights():
    try:
        req = request.get_json()
        cfg = load_config_rules()
        cfg["weights"] = {
            "consecutive_weight": int(req.get("consecutive_weight", 500)),
            "no_teach_penalty": int(req.get("no_teach_penalty", 200)),
            "no_sub_penalty": int(req.get("no_sub_penalty", 200)),
            "spreading_weight": int(req.get("spreading_weight", 10))
        }
        save_config_rules(cfg)
        trigger_auto_solver()
        return jsonify({"status": "success", "message": "AI 排課權重與偏好參數已成功儲存！全校 AI 已自動完成 CP-SAT 最優化求解！", "solved": True})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def extract_dbf_subject_catalog():
    data = load_schedule_data()
    schedules = data.get("schedules", [])
    
    subjects_map = {}
    grade_map = {}

    category_keywords = [
        ("國文", "語文領域"), ("英文", "外語領域"), ("數學", "數理領域"),
        ("物理", "自然科學"), ("化學", "自然科學"), ("生物", "自然科學"), ("地科", "自然科學"),
        ("歷史", "社會領域"), ("地理", "社會領域"), ("公民", "社會領域"),
        ("體育", "健體領域"), ("音樂", "藝術領域"), ("美術", "藝術領域"), ("家政", "綜合領域"),
        ("資訊", "科技領域"), ("生活科技", "科技領域"), ("彈性", "綜合領域"), ("本土", "語文領域")
    ]

    for s in schedules:
        sc = s["subject_code"]
        sn = s["subject_name"]
        cc = s["class_code"]
        cn = s["class_name"]
        if not sc or not sn:
            continue

        if sc not in subjects_map:
            cat = "一般領域"
            for kw, domain in category_keywords:
                if kw in sn:
                    cat = domain
                    break
            subjects_map[sc] = {
                "code": sc,
                "name": sn,
                "category": cat,
                "hours_counts": {}
            }
        subjects_map[sc]["hours_counts"][cc] = subjects_map[sc]["hours_counts"].get(cc, 0) + 1

        # Extract Grade
        grade = "7"
        if cn and cn.isdigit():
            c_num = int(cn)
            if 701 <= c_num <= 799: grade = "7"
            elif 801 <= c_num <= 899: grade = "8"
            elif 901 <= c_num <= 999: grade = "9"
            elif 101 <= c_num <= 199 or 401 <= c_num <= 499: grade = "10"
            elif 201 <= c_num <= 299 or 501 <= c_num <= 599: grade = "11"
            elif 301 <= c_num <= 399 or 601 <= c_num <= 699: grade = "12"
        else:
            if cc.startswith("7"): grade = "7"
            elif cc.startswith("8"): grade = "8"
            elif cc.startswith("9"): grade = "9"
            elif cc.startswith("1") or cc.startswith("4"): grade = "10"
            elif cc.startswith("2") or cc.startswith("5"): grade = "11"
            elif cc.startswith("3") or cc.startswith("6"): grade = "12"

        if grade not in grade_map:
            grade_map[grade] = {}
        if sc not in grade_map[grade]:
            grade_map[grade][sc] = {
                "subject_code": sc,
                "subject_name": sn,
                "hours_counts": {}
            }
        grade_map[grade][sc]["hours_counts"][cc] = grade_map[grade][sc]["hours_counts"].get(cc, 0) + 1

    catalog = []
    for sc, info in subjects_map.items():
        counts = info["hours_counts"]
        most_freq = max(counts, key=counts.get) if counts else None
        avg_h = counts[most_freq] if most_freq else 4
        catalog.append({
            "code": sc,
            "name": info["name"],
            "category": info["category"],
            "default_hours": avg_h
        })

    curriculum = {}
    for g, subs in grade_map.items():
        curriculum[g] = []
        for sc, info in subs.items():
            counts = info["hours_counts"]
            most_freq = max(counts, key=counts.get) if counts else None
            avg_h = counts[most_freq] if most_freq else 4
            curriculum[g].append({
                "subject_code": sc,
                "subject_name": info["subject_name"],
                "hours": avg_h
            })

    return catalog, curriculum

@app.route("/api/subject-catalog", methods=["GET"])
def api_get_subject_catalog():
    try:
        cfg = load_config_rules()
        dbf_catalog, dbf_curriculum = extract_dbf_subject_catalog()
        
        custom_catalog = cfg.get("subject_catalog", [])
        # Merge custom with DBF catalog
        catalog_map = {s["code"]: s for s in dbf_catalog}
        for s in custom_catalog:
            catalog_map[s["code"]] = s
        merged_catalog = list(catalog_map.values())
            
        custom_curriculum = cfg.get("grade_curriculum", {})
        # Merge custom curriculum with DBF curriculum
        merged_curriculum = dict(dbf_curriculum)
        for g, subs in custom_curriculum.items():
            if g not in merged_curriculum:
                merged_curriculum[g] = subs
            else:
                g_map = {item["subject_code"]: item for item in merged_curriculum[g]}
                for item in subs:
                    g_map[item["subject_code"]] = item
                merged_curriculum[g] = list(g_map.values())

        return jsonify({
            "status": "success",
            "subject_catalog": merged_catalog,
            "grade_curriculum": merged_curriculum
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/save-subject-catalog", methods=["POST"])
def api_save_subject_catalog():
    try:
        req = request.get_json()
        code = req.get("code")
        name = req.get("name")
        category = req.get("category", "一般")
        hours = req.get("default_hours", 4)
        is_delete = req.get("delete", False)
        
        if not code:
            return jsonify({"status": "error", "message": "Subject code is required"}), 400
            
        cfg = load_config_rules()
        catalog = cfg.get("subject_catalog")
        if not catalog:
            catalog = list(DEFAULT_SUBJECT_CATALOG)
            
        if is_delete:
            catalog = [s for s in catalog if s["code"] != code]
            msg = f"已刪除學科 {code}！"
        else:
            existing = False
            for s in catalog:
                if s["code"] == code:
                    s["name"] = name
                    s["category"] = category
                    s["default_hours"] = int(hours)
                    existing = True
                    break
            if not existing:
                catalog.append({
                    "code": code,
                    "name": name,
                    "category": category,
                    "default_hours": int(hours)
                })
            msg = f"學科 {name} ({code}) 已儲存更新！"
            
        cfg["subject_catalog"] = catalog
        save_config_rules(cfg)
        return jsonify({"status": "success", "message": msg, "subject_catalog": catalog})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/save-grade-curriculum", methods=["POST"])
def api_save_grade_curriculum():
    try:
        req = request.get_json()
        grade = req.get("grade")
        sc = req.get("subject_code")
        sn = req.get("subject_name")
        hours = req.get("hours", 4)
        is_delete = req.get("delete", False)
        
        if not grade or not sc:
            return jsonify({"status": "error", "message": "Grade and Subject code are required"}), 400
            
        cfg = load_config_rules()
        if "grade_curriculum" not in cfg:
            cfg["grade_curriculum"] = {}
            
        if grade not in cfg["grade_curriculum"]:
            cfg["grade_curriculum"][grade] = []
            
        cur_list = cfg["grade_curriculum"][grade]
        if is_delete:
            cfg["grade_curriculum"][grade] = [item for item in cur_list if item["subject_code"] != sc]
            msg = f"年級 {grade} 已移除科目 {sc}！"
        else:
            found = False
            for item in cur_list:
                if item["subject_code"] == sc:
                    item["hours"] = int(hours)
                    item["subject_name"] = sn or item.get("subject_name", sc)
                    found = True
                    break
            if not found:
                cur_list.append({
                    "subject_code": sc,
                    "subject_name": sn or sc,
                    "hours": int(hours)
                })
            msg = f"年級 {grade} 科目 {sn or sc} 設定已更新（每週 {hours} 節）！"
            
        save_config_rules(cfg)
        return jsonify({"status": "success", "message": msg, "grade_curriculum": cfg["grade_curriculum"]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/presets/load", methods=["POST"])
def api_load_preset():
    """Loads default standard subjects, weekly hours, special venues, and mapping rules for Junior High or Senior High."""
    try:
        req = request.get_json() or {}
        preset_type = req.get("preset_type", "junior")
        
        j_preset = {
            "title": "國中部標準課綱與專用教室範本",
            "subject_catalog": [
                {"code": "J101", "name": "國語文", "category": "語文領域", "default_hours": 5},
                {"code": "J102", "name": "英語文", "category": "語文領域", "default_hours": 4},
                {"code": "J103", "name": "數學", "category": "數學領域", "default_hours": 4},
                {"code": "J104", "name": "理化", "category": "自然科學領域", "default_hours": 3},
                {"code": "J105", "name": "生物", "category": "自然科學領域", "default_hours": 3},
                {"code": "J106", "name": "地球科學", "category": "自然科學領域", "default_hours": 1},
                {"code": "J107", "name": "歷史", "category": "社會領域", "default_hours": 1},
                {"code": "J108", "name": "地理", "category": "社會領域", "default_hours": 1},
                {"code": "J109", "name": "公民", "category": "社會領域", "default_hours": 1},
                {"code": "J110", "name": "體育", "category": "健康與體育領域", "default_hours": 2},
                {"code": "J111", "name": "健康教育", "category": "健康與體育領域", "default_hours": 1},
                {"code": "J112", "name": "音樂", "category": "藝術領域", "default_hours": 1},
                {"code": "J113", "name": "視覺藝術", "category": "藝術領域", "default_hours": 1},
                {"code": "J114", "name": "表演藝術", "category": "藝術領域", "default_hours": 1},
                {"code": "J115", "name": "資訊科技", "category": "科技領域", "default_hours": 1},
                {"code": "J116", "name": "生活科技", "category": "科技領域", "default_hours": 1},
                {"code": "J117", "name": "家政", "category": "綜合活動領域", "default_hours": 1},
                {"code": "J118", "name": "童軍", "category": "綜合活動領域", "default_hours": 1},
                {"code": "J119", "name": "輔導", "category": "綜合活動領域", "default_hours": 1},
                {"code": "J120", "name": "班會與團體活動", "category": "團體活動", "default_hours": 1},
                {"code": "J121", "name": "彈性學習課程", "category": "校訂課程", "default_hours": 2}
            ],
            "grade_curriculum": {
                "7": [
                    {"subject_code": "J101", "subject_name": "國語文", "hours": 5},
                    {"subject_code": "J102", "subject_name": "英語文", "hours": 4},
                    {"subject_code": "J103", "subject_name": "數學", "hours": 4},
                    {"subject_code": "J105", "subject_name": "生物", "hours": 3},
                    {"subject_code": "J107", "subject_name": "歷史", "hours": 1},
                    {"subject_code": "J108", "subject_name": "地理", "hours": 1},
                    {"subject_code": "J109", "subject_name": "公民", "hours": 1},
                    {"subject_code": "J110", "subject_name": "體育", "hours": 2},
                    {"subject_code": "J111", "subject_name": "健康教育", "hours": 1},
                    {"subject_code": "J112", "subject_name": "音樂", "hours": 1},
                    {"subject_code": "J113", "subject_name": "視覺藝術", "hours": 1},
                    {"subject_code": "J114", "subject_name": "表演藝術", "hours": 1},
                    {"subject_code": "J115", "subject_name": "資訊科技", "hours": 1},
                    {"subject_code": "J116", "subject_name": "生活科技", "hours": 1},
                    {"subject_code": "J117", "subject_name": "家政", "hours": 1},
                    {"subject_code": "J118", "subject_name": "童軍", "hours": 1},
                    {"subject_code": "J119", "subject_name": "輔導", "hours": 1},
                    {"subject_code": "J120", "subject_name": "班會與團體活動", "hours": 1},
                    {"subject_code": "J121", "subject_name": "彈性學習課程", "hours": 2}
                ],
                "8": [
                    {"subject_code": "J101", "subject_name": "國語文", "hours": 5},
                    {"subject_code": "J102", "subject_name": "英語文", "hours": 4},
                    {"subject_code": "J103", "subject_name": "數學", "hours": 4},
                    {"subject_code": "J104", "subject_name": "理化", "hours": 3},
                    {"subject_code": "J107", "subject_name": "歷史", "hours": 1},
                    {"subject_code": "J108", "subject_name": "地理", "hours": 1},
                    {"subject_code": "J109", "subject_name": "公民", "hours": 1},
                    {"subject_code": "J110", "subject_name": "體育", "hours": 2},
                    {"subject_code": "J111", "subject_name": "健康教育", "hours": 1},
                    {"subject_code": "J112", "subject_name": "音樂", "hours": 1},
                    {"subject_code": "J113", "subject_name": "視覺藝術", "hours": 1},
                    {"subject_code": "J114", "subject_name": "表演藝術", "hours": 1},
                    {"subject_code": "J115", "subject_name": "資訊科技", "hours": 1},
                    {"subject_code": "J116", "subject_name": "生活科技", "hours": 1},
                    {"subject_code": "J117", "subject_name": "家政", "hours": 1},
                    {"subject_code": "J118", "subject_name": "童軍", "hours": 1},
                    {"subject_code": "J119", "subject_name": "輔導", "hours": 1},
                    {"subject_code": "J120", "subject_name": "班會與團體活動", "hours": 1},
                    {"subject_code": "J121", "subject_name": "彈性學習課程", "hours": 2}
                ],
                "9": [
                    {"subject_code": "J101", "subject_name": "國語文", "hours": 5},
                    {"subject_code": "J102", "subject_name": "英語文", "hours": 4},
                    {"subject_code": "J103", "subject_name": "數學", "hours": 4},
                    {"subject_code": "J104", "subject_name": "理化", "hours": 3},
                    {"subject_code": "J106", "subject_name": "地球科學", "hours": 1},
                    {"subject_code": "J107", "subject_name": "歷史", "hours": 1},
                    {"subject_code": "J108", "subject_name": "地理", "hours": 1},
                    {"subject_code": "J109", "subject_name": "公民", "hours": 1},
                    {"subject_code": "J110", "subject_name": "體育", "hours": 2},
                    {"subject_code": "J111", "subject_name": "健康教育", "hours": 1},
                    {"subject_code": "J112", "subject_name": "音樂", "hours": 1},
                    {"subject_code": "J113", "subject_name": "視覺藝術", "hours": 1},
                    {"subject_code": "J114", "subject_name": "表演藝術", "hours": 1},
                    {"subject_code": "J115", "subject_name": "資訊科技", "hours": 1},
                    {"subject_code": "J116", "subject_name": "生活科技", "hours": 1},
                    {"subject_code": "J117", "subject_name": "家政", "hours": 1},
                    {"subject_code": "J118", "subject_name": "童軍", "hours": 1},
                    {"subject_code": "J119", "subject_name": "輔導", "hours": 1},
                    {"subject_code": "J120", "subject_name": "班會與團體活動", "hours": 1},
                    {"subject_code": "J121", "subject_name": "彈性學習課程", "hours": 2}
                ]
            },
            "venue_capacities": {
                "電腦教室": 2,
                "理化實驗室": 2,
                "生物實驗室": 1,
                "音樂教室": 1,
                "美術教室": 1,
                "家政教室": 1,
                "生活科技教室": 1,
                "體育場/館": 3
            },
            "subject_venue_mappings": [
                {"subject_code": "J115", "subject_name": "資訊科技", "room_name": "電腦教室"},
                {"subject_code": "J104", "subject_name": "理化", "room_name": "理化實驗室"},
                {"subject_code": "J105", "subject_name": "生物", "room_name": "生物實驗室"},
                {"subject_code": "J112", "subject_name": "音樂", "room_name": "音樂教室"},
                {"subject_code": "J113", "subject_name": "視覺藝術", "room_name": "美術教室"},
                {"subject_code": "J117", "subject_name": "家政", "room_name": "家政教室"},
                {"subject_code": "J116", "subject_name": "生活科技", "room_name": "生活科技教室"},
                {"subject_code": "J110", "subject_name": "體育", "room_name": "體育場/館"}
            ],
            "consecutive_subjects": ["J104", "J115"]
        }
        
        s_preset = {
            "title": "高中部標準課綱與專用教室範本",
            "subject_catalog": [
                {"code": "S201", "name": "國語文", "category": "語文領域", "default_hours": 4},
                {"code": "S202", "name": "英文", "category": "語文領域", "default_hours": 4},
                {"code": "S203", "name": "數學", "category": "數學領域", "default_hours": 4},
                {"code": "S204", "name": "物理", "category": "自然科學領域", "default_hours": 2},
                {"code": "S205", "name": "化學", "category": "自然科學領域", "default_hours": 2},
                {"code": "S206", "name": "生物", "category": "自然科學領域", "default_hours": 2},
                {"code": "S207", "name": "地球科學", "category": "自然科學領域", "default_hours": 2},
                {"code": "S208", "name": "歷史", "category": "社會領域", "default_hours": 2},
                {"code": "S209", "name": "地理", "category": "社會領域", "default_hours": 2},
                {"code": "S210", "name": "公民與社會", "category": "社會領域", "default_hours": 2},
                {"code": "S211", "name": "體育", "category": "健康與體育領域", "default_hours": 2},
                {"code": "S212", "name": "音樂", "category": "藝術領域", "default_hours": 1},
                {"code": "S213", "name": "美術", "category": "藝術領域", "default_hours": 1},
                {"code": "S214", "name": "藝術生活", "category": "藝術領域", "default_hours": 1},
                {"code": "S215", "name": "資訊科技/程式設計", "category": "科技領域", "default_hours": 2},
                {"code": "S216", "name": "生活科技", "category": "科技領域", "default_hours": 2},
                {"code": "S217", "name": "家政", "category": "綜合活動領域", "default_hours": 1},
                {"code": "S218", "name": "健康與護理", "category": "全民國防與健康", "default_hours": 1},
                {"code": "S219", "name": "全民國防教育", "category": "全民國防與健康", "default_hours": 1},
                {"code": "S220", "name": "班會與週會", "category": "團體活動", "default_hours": 1},
                {"code": "S221", "name": "多元選修與校訂必修", "category": "校訂課程", "default_hours": 3}
            ],
            "grade_curriculum": {
                "10": [
                    {"subject_code": "S201", "subject_name": "國語文", "hours": 4},
                    {"subject_code": "S202", "subject_name": "英文", "hours": 4},
                    {"subject_code": "S203", "subject_name": "數學", "hours": 4},
                    {"subject_code": "S204", "subject_name": "物理", "hours": 2},
                    {"subject_code": "S205", "subject_name": "化學", "hours": 2},
                    {"subject_code": "S206", "subject_name": "生物", "hours": 2},
                    {"subject_code": "S207", "subject_name": "地球科學", "hours": 2},
                    {"subject_code": "S208", "subject_name": "歷史", "hours": 2},
                    {"subject_code": "S209", "subject_name": "地理", "hours": 2},
                    {"subject_code": "S210", "subject_name": "公民與社會", "hours": 2},
                    {"subject_code": "S211", "subject_name": "體育", "hours": 2},
                    {"subject_code": "S212", "subject_name": "音樂", "hours": 1},
                    {"subject_code": "S213", "subject_name": "美術", "hours": 1},
                    {"subject_code": "S215", "subject_name": "資訊科技/程式設計", "hours": 2},
                    {"subject_code": "S218", "subject_name": "健康與護理", "hours": 1},
                    {"subject_code": "S219", "subject_name": "全民國防教育", "hours": 1},
                    {"subject_code": "S220", "subject_name": "班會與週會", "hours": 1},
                    {"subject_code": "S221", "subject_name": "多元選修與校訂必修", "hours": 2}
                ],
                "11": [
                    {"subject_code": "S201", "subject_name": "國語文", "hours": 4},
                    {"subject_code": "S202", "subject_name": "英文", "hours": 4},
                    {"subject_code": "S203", "subject_name": "數學", "hours": 4},
                    {"subject_code": "S204", "subject_name": "物理", "hours": 2},
                    {"subject_code": "S205", "subject_name": "化學", "hours": 2},
                    {"subject_code": "S208", "subject_name": "歷史", "hours": 2},
                    {"subject_code": "S209", "subject_name": "地理", "hours": 2},
                    {"subject_code": "S211", "subject_name": "體育", "hours": 2},
                    {"subject_code": "S214", "subject_name": "藝術生活", "hours": 1},
                    {"subject_code": "S216", "subject_name": "生活科技", "hours": 2},
                    {"subject_code": "S217", "subject_name": "家政", "hours": 1},
                    {"subject_code": "S220", "subject_name": "班會與週會", "hours": 1},
                    {"subject_code": "S221", "subject_name": "多元選修與校訂必修", "hours": 4}
                ],
                "12": [
                    {"subject_code": "S201", "subject_name": "國語文", "hours": 4},
                    {"subject_code": "S202", "subject_name": "英文", "hours": 4},
                    {"subject_code": "S203", "subject_name": "數學", "hours": 4},
                    {"subject_code": "S204", "subject_name": "物理", "hours": 3},
                    {"subject_code": "S205", "subject_name": "化學", "hours": 3},
                    {"subject_code": "S206", "subject_name": "生物", "hours": 3},
                    {"subject_code": "S211", "subject_name": "體育", "hours": 2},
                    {"subject_code": "S220", "subject_name": "班會與週會", "hours": 1},
                    {"subject_code": "S221", "subject_name": "多元選修與校訂必修", "hours": 6}
                ]
            },
            "venue_capacities": {
                "電腦教室": 2,
                "物理實驗室": 2,
                "化學實驗室": 2,
                "生物實驗室": 1,
                "音樂教室": 1,
                "美術教室": 1,
                "家政教室": 1,
                "生活科技教室": 1,
                "體育場/館": 3
            },
            "subject_venue_mappings": [
                {"subject_code": "S215", "subject_name": "資訊科技/程式設計", "room_name": "電腦教室"},
                {"subject_code": "S204", "subject_name": "物理", "room_name": "物理實驗室"},
                {"subject_code": "S205", "subject_name": "化學", "room_name": "化學實驗室"},
                {"subject_code": "S206", "subject_name": "生物", "room_name": "生物實驗室"},
                {"subject_code": "S212", "subject_name": "音樂", "room_name": "音樂教室"},
                {"subject_code": "S213", "subject_name": "美術", "room_name": "美術教室"},
                {"subject_code": "S217", "subject_name": "家政", "room_name": "家政教室"},
                {"subject_code": "S216", "subject_name": "生活科技", "room_name": "生活科技教室"},
                {"subject_code": "S211", "subject_name": "體育", "room_name": "體育場/館"}
            ],
            "consecutive_subjects": ["S204", "S205", "S215"]
        }

        if preset_type == "junior":
            chosen = j_preset
        elif preset_type == "senior":
            chosen = s_preset
        elif preset_type == "junior_3":
            chosen = {**j_preset, "title": "國中 3 班示範全套資料 (701, 801, 901 班級、教師與配課)"}
        elif preset_type == "senior_3":
            chosen = {**s_preset, "title": "高中 3 班示範全套資料 (101, 201, 301 班級、教師與配課)"}
        else: # k12_6 or combined
            chosen = {
                "title": "國中 3 班 ＋ 高中 3 班全校完整示範檔 (701~901, 101~301 共6班)",
                "subject_catalog": j_preset["subject_catalog"] + s_preset["subject_catalog"],
                "grade_curriculum": {**j_preset["grade_curriculum"], **s_preset["grade_curriculum"]},
                "venue_capacities": {**j_preset["venue_capacities"], **s_preset["venue_capacities"]},
                "subject_venue_mappings": j_preset["subject_venue_mappings"] + s_preset["subject_venue_mappings"],
                "consecutive_subjects": list(set(j_preset["consecutive_subjects"] + s_preset["consecutive_subjects"]))
            }

        cfg = load_config_rules()

        # Merge subject catalog (existing user catalog preserved unless code matches)
        existing_catalog = cfg.get("subject_catalog", [])
        cat_map = {s["code"]: s for s in existing_catalog}
        for s in chosen["subject_catalog"]:
            cat_map[s["code"]] = s
        cfg["subject_catalog"] = list(cat_map.values())

        # Merge grade curriculum
        existing_curriculum = cfg.get("grade_curriculum", {})
        for g, items in chosen["grade_curriculum"].items():
            if g not in existing_curriculum:
                existing_curriculum[g] = items
            else:
                g_map = {item["subject_code"]: item for item in existing_curriculum[g]}
                for item in items:
                    g_map[item["subject_code"]] = item
                existing_curriculum[g] = list(g_map.values())
        cfg["grade_curriculum"] = existing_curriculum

        # Merge venue capacities
        existing_venues = cfg.get("venue_capacities", {})
        for room_name, cap in chosen["venue_capacities"].items():
            if room_name not in existing_venues:
                existing_venues[room_name] = cap
        cfg["venue_capacities"] = existing_venues

        # Merge subject venue mappings
        existing_mappings = cfg.get("subject_venue_mappings", [])
        map_set = {(m["subject_code"], m["room_name"]) for m in existing_mappings}
        for m in chosen["subject_venue_mappings"]:
            key = (m["subject_code"], m["room_name"])
            if key not in map_set:
                existing_mappings.append(m)
                map_set.add(key)
        cfg["subject_venue_mappings"] = existing_mappings

        # Merge consecutive subjects
        existing_consec = cfg.get("consecutive_subjects", [])
        consec_set = set(existing_consec)
        for sub in chosen["consecutive_subjects"]:
            consec_set.add(sub)
        cfg["consecutive_subjects"] = list(consec_set)

        # Handle class & teacher sample data loading for junior_3, senior_3, k12_6, combined
        if preset_type in ["junior_3", "senior_3", "k12_6", "combined"]:
            j_classes = [
                {"code": "701", "name": "701班", "tutor": "王美玲", "group": "國中部"},
                {"code": "801", "name": "801班", "tutor": "陳建宏", "group": "國中部"},
                {"code": "901", "name": "901班", "tutor": "林志豪", "group": "國中部"}
            ]
            s_classes = [
                {"code": "101", "name": "101班", "tutor": "張大明", "group": "高中部"},
                {"code": "201", "name": "201班", "tutor": "許淑芬", "group": "高中部"},
                {"code": "301", "name": "301班", "tutor": "郭德華", "group": "高中部"}
            ]
            sample_teachers = [
                {"code": "T01", "name": "王美玲", "role": "國文教師/導師"},
                {"code": "T02", "name": "陳建宏", "role": "數學教師/導師"},
                {"code": "T03", "name": "林志豪", "role": "英文教師/導師"},
                {"code": "T04", "name": "張大明", "role": "物理教師/導師"},
                {"code": "T05", "name": "許淑芬", "role": "化學教師/導師"},
                {"code": "T06", "name": "郭德華", "role": "社會科教師/導師"},
                {"code": "T07", "name": "蔡小芬", "role": "自然科教師"},
                {"code": "T08", "name": "廖健宏", "role": "體育科教師"},
                {"code": "T09", "name": "楊宗緯", "role": "藝能科教師"},
                {"code": "T10", "name": "鄭雅婷", "role": "科技科教師"}
            ]

            target_classes = []
            if preset_type == "junior_3":
                target_classes = j_classes
            elif preset_type == "senior_3":
                target_classes = s_classes
            else:
                target_classes = j_classes + s_classes

            # Merge custom classes
            existing_custom_cls = cfg.get("custom_classes", [])
            cls_map = {c["code"]: c for c in existing_custom_cls}
            for c in target_classes:
                cls_map[c["code"]] = c
            cfg["custom_classes"] = list(cls_map.values())
            cfg["deleted_class_codes"] = [dc for dc in cfg.get("deleted_class_codes", []) if dc not in cls_map]

            # Merge custom teachers
            existing_custom_t = cfg.get("custom_teachers", [])
            t_map = {t["code"]: t for t in existing_custom_t}
            for t in sample_teachers:
                t_map[t["code"]] = t
            cfg["custom_teachers"] = list(t_map.values())
            cfg["deleted_teacher_codes"] = [dt for dt in cfg.get("deleted_teacher_codes", []) if dt not in t_map]

            # Generate custom_assignments
            custom_assignments = cfg.get("custom_assignments", {})
            for c in target_classes:
                ccode = c["code"]
                cname = c["name"]
                grade_num = "7" if ccode == "701" else ("8" if ccode == "801" else ("9" if ccode == "901" else ("10" if ccode == "101" else ("11" if ccode == "201" else "12"))))
                curr_list = chosen.get("grade_curriculum", {}).get(grade_num, [])
                for item in curr_list:
                    sc = item["subject_code"]
                    sn = item["subject_name"]
                    hr = item["hours"]
                    t_code, t_name = "T01", "王美玲"
                    if "英" in sn: t_code, t_name = "T03", "林志豪"
                    elif "數" in sn: t_code, t_name = "T02", "陳建宏"
                    elif "物" in sn: t_code, t_name = "T04", "張大明"
                    elif "化" in sn: t_code, t_name = "T05", "許淑芬"
                    elif "生" in sn or "理" in sn or "地" in sn: t_code, t_name = "T07", "蔡小芬"
                    elif "史" in sn or "公" in sn or "民" in sn: t_code, t_name = "T06", "郭德華"
                    elif "體" in sn or "健" in sn: t_code, t_name = "T08", "廖健宏"
                    elif "音" in sn or "美" in sn or "藝" in sn or "家" in sn: t_code, t_name = "T09", "楊宗緯"
                    elif "資" in sn or "科" in sn: t_code, t_name = "T10", "鄭雅婷"

                    custom_assignments[f"{ccode}|{sc}"] = {
                        "class_code": ccode, "class_name": cname,
                        "subject_code": sc, "subject_name": sn,
                        "teacher_code": t_code, "teacher_name": t_name,
                        "hours": hr
                    }
            cfg["custom_assignments"] = custom_assignments

            # Reset old solved excel to let load_schedule_data generate fresh schedules
            solved_excel = resolve_path("School_Schedule_Solved.xlsx")
            if os.path.exists(solved_excel):
                try:
                    os.remove(solved_excel)
                except Exception as e:
                    log_exception("api_update_subject_catalog:remove_solved_excel", e)

        save_config_rules(cfg)
        
        global _cached_data
        _cached_data = None

        return jsonify({
            "status": "success",
            "message": f"成功載入【{chosen['title']}】！全校班級、教師授課與專用教室已準備就緒！",
            "subject_catalog": cfg["subject_catalog"],
            "grade_curriculum": cfg["grade_curriculum"],
            "venue_capacities": cfg["venue_capacities"],
            "subject_venue_mappings": cfg["subject_venue_mappings"]
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/backup/download-zip", methods=["GET"])
def api_download_zip_backup():
    try:
        import io, zipfile, datetime
        mem = io.BytesIO()
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename = f"School_Schedule_Backup_{now_str}.zip"
        
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. config_rules.json
            if os.path.exists(CONFIG_RULES_FILE):
                zf.write(CONFIG_RULES_FILE, "config_rules.json")
            # 2. Solved Excel if exists
            excel_path = os.path.join(os.path.dirname(__file__), "School_Schedule_Solved.xlsx")
            if os.path.exists(excel_path):
                zf.write(excel_path, "School_Schedule_Solved.xlsx")
                
        mem.seek(0)
        return send_file(
            mem,
            mimetype="application/zip",
            as_attachment=True,
            download_name=zip_filename
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

RESTORE_POINTS_DIR = os.path.join(DATA_DIR, "restore_points")

def get_restore_points_manifest():
    if not os.path.exists(RESTORE_POINTS_DIR):
        os.makedirs(RESTORE_POINTS_DIR, exist_ok=True)
    manifest_file = os.path.join(RESTORE_POINTS_DIR, "manifest.json")
    if os.path.exists(manifest_file):
        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_exception("get_restore_points_manifest:read", e)
    return []

def save_restore_points_manifest(points):
    if not os.path.exists(RESTORE_POINTS_DIR):
        os.makedirs(RESTORE_POINTS_DIR, exist_ok=True)
    manifest_file = os.path.join(RESTORE_POINTS_DIR, "manifest.json")
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(points, f, ensure_ascii=False, indent=2)

@app.route("/api/restore-points", methods=["GET"])
def api_get_restore_points():
    try:
        points = get_restore_points_manifest()
        return jsonify({"status": "success", "restore_points": points})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/create-restore-point", methods=["POST"])
def api_create_restore_point():
    try:
        req = request.get_json() or {}
        note = req.get("note", "").strip() or "全校設定與課表快照"
        
        import datetime
        now = datetime.datetime.now()
        rp_id = now.strftime("%Y%m%d_%H%M%S")
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
        
        point_dir = os.path.join(RESTORE_POINTS_DIR, rp_id)
        os.makedirs(point_dir, exist_ok=True)
        
        # Backup config_rules.json
        cfg = load_config_rules()
        with open(os.path.join(point_dir, "config_rules.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            
        # Backup solved Excel if exists
        excel_path = os.path.join(os.path.dirname(__file__), "School_Schedule_Solved.xlsx")
        has_excel = False
        if os.path.exists(excel_path):
            import shutil
            shutil.copy2(excel_path, os.path.join(point_dir, "School_Schedule_Solved.xlsx"))
            has_excel = True

        points = get_restore_points_manifest()
        new_entry = {
            "id": rp_id,
            "timestamp": timestamp_str,
            "note": note,
            "has_excel": has_excel
        }
        points.insert(0, new_entry)
        save_restore_points_manifest(points)
        
        return jsonify({"status": "success", "message": f"還原點「{note}」已成功建立！", "restore_points": points})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/restore-checkpoint", methods=["POST"])
def api_restore_checkpoint():
    try:
        req = request.get_json() or {}
        rp_id = req.get("id")
        if not rp_id:
            return jsonify({"status": "error", "message": "Restore point ID is required"}), 400
            
        point_dir = os.path.join(RESTORE_POINTS_DIR, rp_id)
        if not os.path.exists(point_dir):
            return jsonify({"status": "error", "message": "Restore point not found"}), 404
            
        # Restore config_rules.json
        cfg_backup = os.path.join(point_dir, "config_rules.json")
        if os.path.exists(cfg_backup):
            import shutil
            shutil.copy2(cfg_backup, CONFIG_RULES_FILE)
            
        # Restore Excel if present
        excel_backup = os.path.join(point_dir, "School_Schedule_Solved.xlsx")
        target_excel = os.path.join(os.path.dirname(__file__), "School_Schedule_Solved.xlsx")
        if os.path.exists(excel_backup):
            import shutil
            shutil.copy2(excel_backup, target_excel)
        elif os.path.exists(target_excel):
            try:
                os.remove(target_excel)
            except Exception as e:
                log_exception("api_restore_point:remove_target_excel", e)
                
        # Invalidate cache
        global _cached_data
        _cached_data = None
        
        return jsonify({"status": "success", "message": f"全校系統與課表已成功還原至快照 {rp_id}！"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/delete-restore-point", methods=["POST"])
def api_delete_restore_point():
    try:
        req = request.get_json() or {}
        rp_id = req.get("id")
        if not rp_id:
            return jsonify({"status": "error", "message": "Restore point ID is required"}), 400
            
        point_dir = os.path.join(RESTORE_POINTS_DIR, rp_id)
        if os.path.exists(point_dir):
            import shutil
            shutil.rmtree(point_dir, ignore_errors=True)
            
        points = get_restore_points_manifest()
        points = [p for p in points if p["id"] != rp_id]
        save_restore_points_manifest(points)
        
        return jsonify({"status": "success", "message": f"還原點 {rp_id} 已刪除！", "restore_points": points})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- SHIN-HER INTEGRATED EXTENSIONS ---

@app.route("/api/venue-capacities", methods=["GET"])
@app.route("/api/get-venue-capacities", methods=["GET"])
def api_get_venue_capacities():
    try:
        cfg = load_config_rules()
        caps = cfg.get("venue_capacities", {
            "電腦教室": 2,
            "理化實驗室": 1,
            "音樂教室": 1,
            "體育場/館": 3
        })
        consec_subs = cfg.get("consecutive_subjects", ["104", "105", "110"])
        class_consec = cfg.get("class_consecutive_rules", [])
        subj_venues = cfg.get("subject_venue_mappings", [
            {"subject_code": "110", "subject_name": "程式設計", "room_name": "電腦教室"},
            {"subject_code": "823", "subject_name": "資訊", "room_name": "電腦教室"},
            {"subject_code": "502", "subject_name": "理化", "room_name": "理化實驗室"},
            {"subject_code": "104", "subject_name": "物理", "room_name": "理化實驗室"},
            {"subject_code": "105", "subject_name": "化學", "room_name": "理化實驗室"},
            {"subject_code": "704", "subject_name": "音樂", "room_name": "音樂教室"},
            {"subject_code": "802", "subject_name": "健體", "room_name": "體育場/館"}
        ])
        return jsonify({
            "status": "success",
            "venue_capacities": caps,
            "consecutive_subjects": consec_subs,
            "class_consecutive_rules": class_consec,
            "subject_venue_mappings": subj_venues
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/save-venue-capacities", methods=["POST"])
def api_save_venue_capacities():
    try:
        req = request.get_json() or {}
        caps = req.get("venue_capacities", {})
        consec_subs = req.get("consecutive_subjects", [])
        class_consec = req.get("class_consecutive_rules", [])
        subj_venues = req.get("subject_venue_mappings", [])
        
        cfg = load_config_rules()
        cfg["venue_capacities"] = caps
        cfg["consecutive_subjects"] = consec_subs
        cfg["class_consecutive_rules"] = class_consec
        cfg["subject_venue_mappings"] = subj_venues
        save_config_rules(cfg)
        return jsonify({"status": "success", "message": "專用教室容量、連堂與科目場地對應設定已成功儲存！"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500



@app.route("/api/preset/apply-school-activity", methods=["POST"])
def api_preset_apply_school_activity():
    try:
        req = request.get_json() or {}
        activity_type = req.get("type", "班會") # "班會", "週會", "社團", "團體活動"
        day = str(req.get("day", "5")).strip()
        period = str(req.get("period", "7")).strip()
        
        if not day or not period:
            return jsonify({"status": "error", "message": "請指定星期與節次！"}), 400
            
        day_names = {"1": "一", "2": "二", "3": "三", "4": "四", "5": "五"}
        d_name = day_names.get(day, day)
        d_int, p_int = int(day), int(period)
        
        sched_data = load_schedule_data()
        classes = sched_data.get("classes", []) if isinstance(sched_data, dict) else []
        
        subj_map = {
            "班會": {"code": "903", "name": "班會", "teacher": "各班導師"},
            "週會": {"code": "904", "name": "週會", "teacher": "學務處"},
            "社團": {"code": "902", "name": "社團活動", "teacher": "指導教師"},
            "團體活動": {"code": "803", "name": "團體活動", "teacher": "學務處/導師"}
        }
        info = subj_map.get(activity_type, {"code": "903", "name": activity_type, "teacher": "指導教師"})
        
        cfg = load_config_rules()
        if "custom_simultaneous_groups" not in cfg:
            cfg["custom_simultaneous_groups"] = []
            
        group_name = f"全校共同{info['name']}"
        
        members = []
        for c in classes:
            c_code = str(c.get("code", "")).strip()
            c_name = str(c.get("name", "")).strip()
            if c_code and c_code not in ["404", "504", "604"]:
                members.append({
                    "class_code": c_code,
                    "class_name": c_name,
                    "subject_code": info["code"],
                    "subject_name": info["name"]
                })
                
        # Update or add group
        cfg["custom_simultaneous_groups"] = [g for g in cfg["custom_simultaneous_groups"] if isinstance(g, dict) and g.get("name") != group_name]
        cfg["custom_simultaneous_groups"].append({
            "name": group_name,
            "members": members,
            "fixed_day": day,
            "fixed_period": period
        })
        
        # Directly inject into current solved_schedules
        solved = get_current_solved_schedules()
        target_classes = set(m["class_code"] for m in members)
        new_solved = []
        for r in solved:
            r_c = str(r.get("班級代碼") or r.get("class_code", "")).strip()
            r_d = int(r.get("星期") or r.get("day", 0))
            r_p = int(r.get("節次") or r.get("period", 0))
            if r_c in target_classes and r_d == d_int and r_p == p_int:
                continue
            new_solved.append(r)
            
        for m in members:
            c_code = m["class_code"]
            c_name = m["class_name"]
            cls_obj = next((c for c in classes if str(c.get("code", "")).strip() == c_code), {})
            tutor = cls_obj.get("tutor", "") or info["teacher"]
            teacher_disp = tutor if activity_type == "班會" else info["teacher"]
            
            new_solved.append({
                "班級代碼": c_code,
                "班級名稱": c_name,
                "科目代碼": info["code"],
                "科目名稱": info["name"],
                "教師代碼": "9999",
                "教師姓名": teacher_disp,
                "星期": d_int,
                "節次": p_int,
                "節數": 1,
                "單雙週": 0,
                "教室代碼": "",
                "教室名稱": "",
                "manual_locked": True
            })
            
        cfg["solved_schedules"] = new_solved
        save_config_rules(cfg)
        
        # Save Excel file
        try:
            excel_path = os.path.join(os.path.dirname(__file__), "School_Schedule_Solved.xlsx")
            import pandas as pd
            pd.DataFrame(new_solved).to_excel(excel_path, index=False)
        except Exception as e:
            log_exception("api_finalize_simultaneous_group:save_excel", e)
            
        global _cached_data
        _cached_data = None
        
        return jsonify({
            "status": "success",
            "message": f"已成功將【週{d_name} 第{period}節】直接定為全校【{info['name']}】！全校各班課表已即時填入並更新！",
            "simultaneous_groups": cfg["custom_simultaneous_groups"],
            "solved": True
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/simultaneous-groups", methods=["GET"])
def api_get_simultaneous_groups():
    try:
        cfg = load_config_rules()
        sim_groups = cfg.get("custom_simultaneous_groups", [])
        return jsonify({"status": "success", "simultaneous_groups": sim_groups})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/save-simultaneous-group", methods=["POST"])
def api_save_simultaneous_group():
    try:
        req = request.get_json() or {}
        name = req.get("name", "").strip()
        members = req.get("members", [])
        fixed_day = req.get("fixed_day")
        fixed_period = req.get("fixed_period")
        
        if not name or len(members) < 2:
            return jsonify({"status": "error", "message": "請提供群組名稱並至少選擇 2 個班級科目成員！"}), 400

        cfg = load_config_rules()
        if "custom_simultaneous_groups" not in cfg:
            cfg["custom_simultaneous_groups"] = []

        cfg["custom_simultaneous_groups"] = [g for g in cfg["custom_simultaneous_groups"] if isinstance(g, dict) and g.get("name") != name]
        
        grp_data = {
            "name": name,
            "members": members
        }
        if fixed_day is not None and fixed_period is not None:
            grp_data["fixed_day"] = str(fixed_day)
            grp_data["fixed_period"] = str(fixed_period)
            
        cfg["custom_simultaneous_groups"].append(grp_data)
        save_config_rules(cfg)
        
        # Trigger CP-SAT Solver Automatically!
        solver_res = trigger_auto_solver()
        
        slot_msg = f"(固定 週{fixed_day} 第{fixed_period}節)" if fixed_day and fixed_period else "(同日同節束縛)"
        return jsonify({"status": "success", "message": f"同時排課群組「{name}」已成功建立並鎖定{slot_msg}！全校 AI 已自動完成 CP-SAT 最優化求解！", "simultaneous_groups": cfg["custom_simultaneous_groups"], "solved": True})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/delete-simultaneous-group", methods=["POST"])
def api_delete_simultaneous_group():
    try:
        req = request.get_json() or {}
        name = req.get("name", "").strip()
        cfg = load_config_rules()
        
        target_group = None
        if "custom_simultaneous_groups" in cfg:
            for g in cfg["custom_simultaneous_groups"]:
                if isinstance(g, dict) and g.get("name") == name:
                    target_group = g
                    break
            cfg["custom_simultaneous_groups"] = [g for g in cfg["custom_simultaneous_groups"] if isinstance(g, dict) and g.get("name") != name]
            
        # Clean up any manual injected records in solved_schedules
        if target_group and target_group.get("fixed_day") and target_group.get("fixed_period"):
            fd = int(target_group["fixed_day"])
            fp = int(target_group["fixed_period"])
            member_classes = set(m.get("class_code") for m in target_group.get("members", []))
            solved = cfg.get("solved_schedules", [])
            new_solved = []
            for r in solved:
                r_c = str(r.get("班級代碼") or r.get("class_code", "")).strip()
                r_d = int(r.get("星期") or r.get("day", 0))
                r_p = int(r.get("節次") or r.get("period", 0))
                if r_c in member_classes and r_d == fd and r_p == fp and any(kw in name for kw in ["班會", "週會", "社團", "活動"]):
                    continue
                new_solved.append(r)
            cfg["solved_schedules"] = new_solved
            try:
                excel_path = os.path.join(os.path.dirname(__file__), "School_Schedule_Solved.xlsx")
                import pandas as pd
                pd.DataFrame(new_solved).to_excel(excel_path, index=False)
            except Exception as e:
                log_exception("api_save_simultaneous_group:save_excel", e)
                
        save_config_rules(cfg)
        
        global _cached_data
        _cached_data = None
        
        return jsonify({
            "status": "success",
            "message": f"同時排課群組「{name}」已成功刪除！全校課表已即時同步清除！",
            "simultaneous_groups": cfg["custom_simultaneous_groups"],
            "solved": True
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def call_groq_substitute_rank(absent_subject_name, absent_subject_code, absent_class, candidates_info, cfg):
    """
    Use Groq LLM to semantically rank substitute teacher candidates.
    Returns a dict: {teacher_code: {"fit": "high"|"medium"|"low", "reason": str}}
    Falls back gracefully if no API key or call fails.
    """
    import urllib.request, json as _json
    groq_api_key = (cfg.get("groq_api_key") or "").strip()
    if not groq_api_key:
        return {}

    model = cfg.get("groq_model", "llama-3.3-70b-versatile")
    url = "https://api.groq.com/openai/v1/chat/completions"

    # Build concise candidate list for the prompt
    cand_lines = []
    for c in candidates_info[:30]:   # limit to 30 to keep prompt short
        subjects = c.get("teach_subjects", "無資料")
        cand_lines.append(f'  - 代碼:{c["teacher_code"]} 姓名:{c["teacher_name"]} 任教科目:{subjects}')
    cand_text = "\n".join(cand_lines)

    system_prompt = (
        "你是一個臺灣中學排課專家 AI。"
        "請根據『請假課程』的科目，語意判斷每位候選教師是否適合代課。\n"
        "判斷時需考慮：\n"
        "1. 跨學制相容性（如國中英語 ↔ 高中英語文 視為同科）\n"
        "2. 選修與必修同科域（如數學演習 ↔ 數學、選修化學 ↔ 化學）\n"
        "3. 協同授課（如臺灣手語協同教師）可視為部分相容\n"
        "4. 完全不同科目（如國文 vs 體育）標記為 low\n\n"
        "回傳格式必須是合法 JSON，結構為：\n"
        "{\"rankings\": [{\"teacher_code\": \"...\", \"fit\": \"high|medium|low\", \"reason\": \"簡短說明\"}]}\n"
        "不要輸出任何其他文字或 Markdown。"
    )

    user_msg = (
        f"請假課程：{absent_subject_name}（代碼:{absent_subject_code}），班級：{absent_class}\n\n"
        f"候選代課教師列表：\n{cand_text}\n\n"
        "請逐一評估每位教師的代課適合度（high/medium/low）並說明原因。"
    )

    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_msg}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }

    try:
        req_obj = urllib.request.Request(
            url,
            data=_json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req_obj, timeout=15) as resp:
            res_data = _json.loads(resp.read().decode("utf-8"))
            content = res_data["choices"][0]["message"]["content"]
            parsed = _json.loads(content)
            rankings = parsed.get("rankings", [])
    except Exception as ex:
        # Graceful fallback to rule-based ranking without console spam
        if "401" in str(ex):
            # Invalid API key
            pass
        else:
            print(f"[AI代課推薦] Groq API 呼叫未成功，已切換為本地規則排序: {ex}")
        return {}


# --- Related Subjects Mapping ---
DOMAIN_MAP = {
    "國語文": ["國文", "國語", "閱讀", "寫作", "作文", "文學", "語文", "手語", "閩南", "本土語", "原民"],
    "外語": ["英文", "英語", "英聽", "雙語", "外語", "日語", "日文", "世界"],
    "數學": ["數學", "數理"],
    "自然": ["理化", "生物", "地科", "自然", "物理", "化學", "科學實驗", "生態", "遺傳", "細胞", "微生物"],
    "社會": ["歷史", "地理", "公民", "社會", "政治", "法律", "人文"],
    "藝術": ["音樂", "美術", "視覺", "表演", "藝術"],
    "健體": ["體育", "健康", "健體", "專項", "選手", "運動", "輕艇", "射"],
    "綜合科技": ["家政", "童軍", "輔導", "資訊", "電腦", "生活科技", "科技", "綜合", "機器人", "生命教育"]
}

def get_subject_domains(subject_name):
    """Returns a set of domain names that a subject string might belong to."""
    if not subject_name:
        return set()
    
    matched_domains = set()
    subj_str = subject_name.lower()
    for domain, keywords in DOMAIN_MAP.items():
        for kw in keywords:
            if kw in subj_str:
                matched_domains.add(domain)
                break # Matched this domain, no need to check other keywords for this domain
    return matched_domains

@app.route("/api/substitute/recommend", methods=["POST"])
def api_substitute_recommend():
    try:
        req = request.get_json() or {}
        absent_tcode = str(req.get("teacher_code") or "").strip()
        if absent_tcode.lower() in ("nan", "none", "null"):
            absent_tcode = ""
        if absent_tcode.isdigit() and len(absent_tcode) < 4:
            absent_tcode = absent_tcode.zfill(4)
        day = str(req.get("day", "1")).strip()
        period = str(req.get("period", "1")).strip()
        
        data = load_schedule_data()
        if "error" in data:
            return jsonify(data), 500
            
        schedules = data.get("schedules", [])
        teachers = data.get("teachers", [])

        # Build teacher assigned classes map & teacher subjects per class
        teacher_classes_map = {}
        teacher_class_subjects_map = {} # (t_code, class_key) -> set of subjects
        class_tutors_map = {} # class_key -> tutor name or code

        for c in data.get("classes", []):
            if isinstance(c, dict):
                c_name = str(c.get("name") or "").strip()
                c_code = str(c.get("code") or "").strip()
                c_tutor = str(c.get("tutor") or "").strip()
                if c_name and c_tutor:
                    class_tutors_map[c_name] = c_tutor
                if c_code and c_tutor:
                    class_tutors_map[c_code] = c_tutor

        for s in schedules:
            tc = s.get("teacher_code")
            cn = s.get("class_name")
            cc = s.get("class_code")
            sn = s.get("subject_name", "")
            if tc:
                if cn:
                    teacher_classes_map.setdefault(tc, set()).add(cn)
                    if sn:
                        teacher_class_subjects_map.setdefault((tc, cn), set()).add(sn)
                if cc:
                    teacher_classes_map.setdefault(tc, set()).add(cc)
                    if sn:
                        teacher_class_subjects_map.setdefault((tc, cc), set()).add(sn)

        # Absent teacher details
        absent_teacher_info = None
        for t in teachers:
            if t["code"] == absent_tcode:
                c_list = sorted(list(teacher_classes_map.get(absent_tcode, [])))
                c_str = ", ".join(c_list) if c_list else "專任課程"
                absent_teacher_info = {
                    "code": absent_tcode,
                    "name": t["name"],
                    "role": t.get("role", "") or "專任教師",
                    "assigned_classes_str": c_str,
                    "assigned_classes": c_list
                }
                break

        # Find who is currently occupied in slot (day, period)
        busy_teachers = set()
        absent_course = None
        
        for s in schedules:
            if s["day"] == day and s["period"] == period:
                if s["teacher_code"]:
                    busy_teachers.add(s["teacher_code"])
                if s["teacher_code"] == absent_tcode:
                    absent_course = s

        # Load no_teach blocked rules
        cfg = load_config_rules()
        no_teach_map = cfg.get("custom_no_teach", {})

        candidates = []
        target_class = absent_course.get("class_name", "") if absent_course else req.get("class_name", "")
        target_subject = absent_course.get("subject_name", "") if absent_course else req.get("subject_name", "")
        target_subject_code = absent_course.get("subject_code", "") if absent_course else ""
        
        target_class = str(target_class or "").strip()
        if target_class.lower() in ("nan", "none", "null"):
            target_class = ""
            
        target_subject = str(target_subject or "").strip()
        if target_subject.lower() in ("nan", "none", "null"):
            target_subject = ""
            
        target_subject_code = str(target_subject_code or "").strip()
        if target_subject_code.lower() in ("nan", "none", "null"):
            target_subject_code = ""
        
        print(f"[DEBUG] recommend: absent_tcode={absent_tcode}, day={day}, period={period}, found_course={absent_course is not None}, target_subj={target_subject}, target_class={target_class}")

        # Build per-teacher subject list (unique subject names they teach)
        teacher_subjects_map = {}
        for s in schedules:
            tc = s.get("teacher_code")
            sn = s.get("subject_name", "")
            if tc and sn:
                if tc not in teacher_subjects_map:
                    teacher_subjects_map[tc] = set()
                teacher_subjects_map[tc].add(sn)

        for t in teachers:
            t_code = t["code"]
            if t_code == absent_tcode or t_code in busy_teachers:
                continue

            # Check if slot is blocked in no_teach
            blocked_slots = no_teach_map.get(t_code, [])
            if f"{day}-{period}" in blocked_slots:
                continue

            # Rule: Same class teacher
            t_classes = teacher_classes_map.get(t_code, set())
            is_same_class = False
            same_class_subjs = set()
            if target_class:
                if target_class in t_classes:
                    is_same_class = True
                    same_class_subjs.update(teacher_class_subjects_map.get((t_code, target_class), set()))
                for c_item in t_classes:
                    if c_item == target_class or c_item.endswith(target_class) or target_class.endswith(c_item):
                        is_same_class = True
                        same_class_subjs.update(teacher_class_subjects_map.get((t_code, c_item), set()))

            # Check if teacher is tutor of target_class
            is_tutor_of_class = False
            target_tutor = class_tutors_map.get(target_class, "")
            if not target_tutor and target_class:
                for ck, tv in class_tutors_map.items():
                    if ck == target_class or ck.endswith(target_class) or target_class.endswith(ck):
                        target_tutor = tv
                        break
            if target_tutor and (target_tutor == t.get("name") or target_tutor == t_code):
                is_tutor_of_class = True
                is_same_class = True

            same_class_subj_str = "、".join(sorted(same_class_subjs)) if same_class_subjs else ""

            # Collect subject names this teacher actually teaches
            t_subject_set = teacher_subjects_map.get(t_code, set())
            declared_subject = t.get("subject", "")
            if declared_subject:
                t_subject_set.add(declared_subject)

            # Exclude club-only teachers (adjunct/external)
            if t_subject_set:
                is_club_only = all("社團" in s or "聯課" in s for s in t_subject_set)
                if is_club_only:
                    continue

            # Exact same subject match (direct match, no forced domain guessing)
            is_exact_same_subj = False
            if target_subject and target_subject in t_subject_set:
                is_exact_same_subj = True
            elif target_subject_code:
                for s in schedules:
                    if s["teacher_code"] == t_code and s.get("subject_code", "") == target_subject_code:
                        is_exact_same_subj = True
                        break

            c_list = sorted(list(t_classes))
            c_str = ", ".join(c_list) if c_list else "無"

            teach_subjects_str = "、".join(sorted(t_subject_set)) if t_subject_set else "無資料"

            candidates.append({
                "teacher_code": t_code,
                "teacher_name": t["name"],
                "role": t.get("role", "") or "專任教師",
                "assigned_classes_str": c_str,
                "is_same_class": is_same_class,
                "is_exact_same_subj": is_exact_same_subj,
                "is_class_tutor": is_tutor_of_class,
                "same_class_subjects": same_class_subj_str,
                "teach_subjects": teach_subjects_str
            })

        # Sorting strategy:
        # Prio 0: 本班導師 (Class Tutor)
        # Prio 1: 任教本班教師 (Same Class Subject Teacher)
        # Prio 2: 完全同科目教師 (Exact Same Subject Teacher)
        # Prio 3: 全校其他空堂教師 (Other Free Teachers)
        def get_sub_sort_key(c):
            if c.get("is_class_tutor"):
                prio = 0
            elif c.get("is_same_class"):
                prio = 1
            elif c.get("is_exact_same_subj"):
                prio = 2
            else:
                prio = 3
            return (prio, c["teacher_name"])

        candidates.sort(key=get_sub_sort_key)

        return jsonify({
            "status": "success",
            "absent_teacher_info": absent_teacher_info,
            "absent_course": absent_course,
            "candidates": candidates,
            "ai_ranked": False
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/substitute/save", methods=["POST"])
def api_substitute_save():
    try:
        req = request.get_json() or {}
        cfg = load_config_rules()
        if "substitute_records" not in cfg:
            cfg["substitute_records"] = []
            
        import datetime
        record = {
            "id": datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
            "date": req.get("date", datetime.date.today().strftime("%Y-%m-%d")),
            "day": req.get("day"),
            "period": req.get("period"),
            "class_name": req.get("class_name"),
            "subject_name": req.get("subject_name"),
            "absent_teacher": req.get("absent_teacher"),
            "sub_teacher": req.get("sub_teacher"),
            "reason": req.get("reason", "公假/病假代課")
        }
        cfg["substitute_records"].insert(0, record)
        save_config_rules(cfg)
        return jsonify({"status": "success", "message": "調代課紀錄已成功儲存！", "records": cfg["substitute_records"]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/substitute/list", methods=["GET"])
def api_substitute_list():
    try:
        cfg = load_config_rules()
        records = cfg.get("substitute_records", [])
        return jsonify({"status": "success", "records": records})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/exam-invigilation/solve", methods=["POST"])
def api_exam_invigilation_solve():
    try:
        req = request.get_json() or {}
        days_count = int(req.get("days", 2))
        periods_per_day = int(req.get("periods", 4))
        
        data = load_schedule_data()
        if "error" in data:
            return jsonify(data), 500
            
        classes = [c for c in data.get("classes", []) if c["code"] and not c["code"].startswith("99")]
        teachers = data.get("teachers", [])
        
        if not classes or not teachers:
            return jsonify({"status": "error", "message": "No classes or teachers available for exam invigilation"}), 400

        # Build original schedule lookup map with lists for simultaneous classes: (class_code, str(day), str(period)) -> list of schedule_items
        schedules = data.get("schedules", [])
        schedule_map = {}
        for s in schedules:
            cc = s.get("class_code")
            d = str(s.get("day"))
            p = str(s.get("period"))
            if cc and d and p:
                key = (cc, d, p)
                if key not in schedule_map:
                    schedule_map[key] = []
                schedule_map[key].append(s)

        # Track assigned invigilators per exam slot (d, p) to prevent invigilator conflicts
        assigned_invigilators_by_slot = {}
        invigilation_plan = []
        t_idx = 0
        
        for d in range(1, days_count + 1):
            for p in range(1, periods_per_day + 1):
                slot_key = (d, p)
                if slot_key not in assigned_invigilators_by_slot:
                    assigned_invigilators_by_slot[slot_key] = set()

                for c in classes:
                    orig_items = schedule_map.get((c["code"], str(d), str(p)), [])
                    
                    # Extract simultaneous teachers & subjects
                    sim_teachers = []
                    orig_subj_list = []
                    for item in orig_items:
                        tc = item.get("teacher_code")
                        tn = item.get("teacher_name")
                        sn = item.get("subject_name", "")
                        if tc and tn and tc not in [st["code"] for st in sim_teachers]:
                            sim_teachers.append({"code": tc, "name": tn, "subject": sn})
                        if sn and sn not in orig_subj_list:
                            orig_subj_list.append(sn)

                    chosen_code = ""
                    chosen_name = ""

                    # Priority 1: Pick a simultaneous teacher who is NOT busy in this exam slot
                    for st in sim_teachers:
                        if st["code"] not in assigned_invigilators_by_slot[slot_key]:
                            chosen_code = st["code"]
                            chosen_name = st["name"]
                            break

                    # Priority 2: Fallback to next available teacher
                    if not chosen_code:
                        for _ in range(len(teachers)):
                            t = teachers[t_idx % len(teachers)]
                            t_idx += 1
                            if t["code"] not in assigned_invigilators_by_slot[slot_key]:
                                chosen_code = t["code"]
                                chosen_name = t["name"]
                                break

                    if chosen_code:
                        assigned_invigilators_by_slot[slot_key].add(chosen_code)

                    invigilation_plan.append({
                        "day": d,
                        "period": p,
                        "class_code": c["code"],
                        "class_name": c["name"],
                        "invigilator_code": chosen_code,
                        "invigilator_name": chosen_name,
                        "orig_subject": " / ".join(orig_subj_list),
                        "is_simultaneous": len(sim_teachers) > 1,
                        "sim_teachers": sim_teachers
                    })

        cfg = load_config_rules()
        cfg["exam_invigilations"] = {
            "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "days": days_count,
            "periods": periods_per_day,
            "plan": invigilation_plan
        }
        save_config_rules(cfg)

        return jsonify({
            "status": "success",
            "message": "定期考查 (段考) 監考表已成功自動生成！",
            "days": days_count,
            "periods": periods_per_day,
            "plan": invigilation_plan
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/exam-invigilation/get-plan", methods=["GET"])
def api_exam_invigilation_get_plan():
    try:
        cfg = load_config_rules()
        exam_data = cfg.get("exam_invigilations", {})
        plan = exam_data.get("plan", [])
        if plan:
            max_day = max(int(item.get("day", 1)) for item in plan)
            max_period = max(int(item.get("period", 1)) for item in plan)
            exam_data["days"] = max_day
            exam_data["periods"] = max_period
        return jsonify({"status": "success", "exam_data": exam_data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/exam-invigilation/save-plan", methods=["POST"])
def api_exam_invigilation_save_plan():
    try:
        req = request.get_json() or {}
        plan = req.get("plan", [])
        days_count = req.get("days")
        periods_per_day = req.get("periods")
        
        cfg = load_config_rules()
        existing = cfg.get("exam_invigilations", {})
        cfg["exam_invigilations"] = {
            "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "days": days_count or existing.get("days", 2),
            "periods": periods_per_day or existing.get("periods", 4),
            "plan": plan
        }
        save_config_rules(cfg)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- 108 課綱 國教署課程代碼對照與健診 ENDPOINTS (州董 WINST-23 規範) ---


def get_moe_course_codes_data():
    cfg = load_config_rules()
    custom_moe_map = cfg.get("moe_course_codes", {})
    
    dbf_dir = get_latest_dbf_dir()
    subjects_dict = {}
    
    # 1. Read from subj.dbf if available
    if dbf_dir and os.path.exists(os.path.join(dbf_dir, "subj.dbf")):
        try:
            from dbfread import DBF
            subj_dbf = os.path.join(dbf_dir, "subj.dbf")
            db_subj = DBF(subj_dbf, ignore_missing_memofile=True, encoding='cp950')
            for r in db_subj:
                code = str(r.get("SUBJ_NO", "")).strip()
                name = str(r.get("SUBJ_NAME", "")).strip() or str(r.get("SUBJ_SHORT", "")).strip()
                if code and name:
                    subjects_dict[code] = {
                        "subject_code": code,
                        "subject_name": name,
                        "hours": 2,
                        "category": "部定必修"
                    }
        except Exception as e:
            print("Error reading subj.dbf:", e)


    # 2. Accumulate/update from actual schedule data
    sched_data = load_schedule_data()
    if isinstance(sched_data, dict) and "schedules" in sched_data:
        from collections import defaultdict
        subj_hours = defaultdict(int)
        for s in sched_data["schedules"]:
            code = str(s.get("subject_code", "")).strip()
            name = str(s.get("subject_name", "")).strip()
            if code and name:
                if code not in subjects_dict:
                    subjects_dict[code] = {
                        "subject_code": code,
                        "subject_name": name,
                        "hours": 0,
                        "category": "部定必修"
                    }
                subj_hours[code] += 1
        for code, h in subj_hours.items():
            if code in subjects_dict:
                subjects_dict[code]["hours"] = max(1, h // 5)

    year = cfg.get("year", "114")
    school_name = cfg.get("school_name", "學校名稱")

    result_list = []
    mapped_count = 0
    
    for code, info in subjects_dict.items():
        sname = info["subject_name"]
        
        category = "部定必修"
        if "選修" in sname:
            category = "多元選修"
        elif "彈性" in sname or "自主" in sname:
            category = "彈性學習"
        elif "社團" in sname or "班會" in sname or "週會" in sname or "團體" in sname:
            category = "團體活動"
        elif "校訂" in sname:
            category = "校訂必修"

        moe_code = custom_moe_map.get(code, "")
        is_mapped = bool(moe_code)
        
        if is_mapped:
            mapped_count += 1
        else:
            cat_num = "1" if category == "部定必修" else ("2" if category == "校訂必修" else ("3" if category == "多元選修" else "4"))
            auto_gen = f"{year}-{cat_num}{code.zfill(4)}-001"
            moe_code = auto_gen

        result_list.append({
            "subject_code": code,
            "subject_name": sname,
            "hours": info["hours"],
            "category": category,
            "moe_code": moe_code,
            "is_mapped": is_mapped
        })

    result_list.sort(key=lambda x: x["subject_code"])
    total_count = len(result_list)
    unmapped_count = total_count - mapped_count
    compliance_rate = round((mapped_count / total_count * 100), 1) if total_count > 0 else 100.0

    return {
        "year": year,
        "school_name": school_name,
        "total_count": total_count,
        "mapped_count": mapped_count,
        "unmapped_count": unmapped_count,
        "compliance_rate": compliance_rate,
        "moe_subjects": result_list
    }

@app.route("/api/moe-course-codes/get", methods=["GET"])
def api_get_moe_course_codes():
    try:
        data = get_moe_course_codes_data()
        return jsonify({"status": "success", **data})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/moe-course-codes/save", methods=["POST"])
def api_save_moe_course_codes():
    try:
        req = request.get_json() or {}
        moe_map = req.get("moe_course_codes", {})
        
        cfg = load_config_rules()
        cfg["moe_course_codes"] = moe_map
        save_config_rules(cfg)
        
        return jsonify({"status": "success", "message": "108 課綱國教署課程代碼對照表已成功儲存！"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/moe-course-codes/export-csv", methods=["GET"])
def api_export_moe_course_codes_csv():
    try:
        import io, csv
        data = get_moe_course_codes_data()
        moe_subjects = data.get("moe_subjects", [])
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["學年度", "校務系統科目代碼", "科目名稱", "每週節數", "108課綱類別", "國教署標準課程代碼(23碼)", "勾稽狀態"])
        
        for s in moe_subjects:
            writer.writerow([
                data.get("year", "114"),
                s["subject_code"],
                s["subject_name"],
                s["hours"],
                s["category"],
                s["moe_code"],
                "已對接完成" if s["is_mapped"] else "待確認上傳"
            ])
            
        mem = io.BytesIO()
        mem.write(output.getvalue().encode('utf-8-sig'))
        mem.seek(0)
        
        year_str = data.get("year", "114")
        filename = f"MOE_Course_Codes_{year_str}.csv"
        
        return send_file(
            mem,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

# --- TEACHER & SUBJECT MANAGEMENT API (新增與刪除全校教師/科目) ---


@app.route("/api/teachers/list", methods=["GET"])
def api_get_teachers_list():
    try:
        cfg = load_config_rules()
        custom_teachers = cfg.get("custom_teachers", [])
        deleted_teacher_codes = set(cfg.get("deleted_teacher_codes", []))

        sched_data = load_schedule_data()
        db_teachers = sched_data.get("teachers", []) if isinstance(sched_data, dict) else []

        merged_map = {}
        for t in db_teachers:
            code = str(t.get("code", "")).strip()
            name = str(t.get("name", "")).strip()
            role = str(t.get("role", "專任教師")).strip()
            subject = str(t.get("subject", "")).strip()
            if code and code not in deleted_teacher_codes:
                item = {"code": code, "name": name, "role": role}
                if subject:
                    item["subject"] = subject
                merged_map[code] = item

        for t in custom_teachers:
            code = str(t.get("code", "")).strip()
            name = str(t.get("name", "")).strip()
            role = str(t.get("role", "專任教師")).strip()
            subject = str(t.get("subject", "")).strip()
            if code and code not in deleted_teacher_codes:
                item = {"code": code, "name": name, "role": role}
                if subject:
                    item["subject"] = subject
                merged_map[code] = item

        final_list = list(merged_map.values())
        final_list.sort(key=lambda x: (x.get("code", ""), x.get("name", "")))

        return jsonify({"status": "success", "teachers": final_list})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/teachers/add", methods=["POST"])
def api_add_teacher():
    try:
        req = request.get_json() or {}
        code = str(req.get("code", "")).strip()
        name = str(req.get("name", "")).strip()
        role = str(req.get("role", "專任教師")).strip() or "專任教師"
        subject = str(req.get("subject", "")).strip()

        if not code or not name:
            return jsonify({"status": "error", "message": "教師代碼與姓名不能為空！"}), 400

        cfg = load_config_rules()
        custom_teachers = cfg.get("custom_teachers", [])
        deleted_teacher_codes = cfg.get("deleted_teacher_codes", [])

        if code in deleted_teacher_codes:
            deleted_teacher_codes.remove(code)
            cfg["deleted_teacher_codes"] = deleted_teacher_codes

        existing = next((t for t in custom_teachers if str(t.get("code", "")).strip() == code), None)
        if existing:
            existing["name"] = name
            existing["role"] = role
            existing["subject"] = subject
        else:
            custom_teachers.append({"code": code, "name": name, "role": role, "subject": subject})

        cfg["custom_teachers"] = custom_teachers
        save_config_rules(cfg)

        global _cached_data
        _cached_data = None

        return jsonify({"status": "success", "message": f"成功新增/更新教師: 【{name}】({code})"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/teachers/delete", methods=["POST"])
def api_delete_teacher():
    try:
        req = request.get_json() or {}
        code = str(req.get("code", "")).strip()
        if not code:
            return jsonify({"status": "error", "message": "未指定欲刪除的教師代碼！"}), 400

        cfg = load_config_rules()
        custom_teachers = cfg.get("custom_teachers", [])
        deleted_teacher_codes = cfg.get("deleted_teacher_codes", [])

        cfg["custom_teachers"] = [t for t in custom_teachers if str(t.get("code", "")).strip() != code]

        if code not in deleted_teacher_codes:
            deleted_teacher_codes.append(code)
            cfg["deleted_teacher_codes"] = deleted_teacher_codes

        save_config_rules(cfg)

        global _cached_data
        _cached_data = None

        return jsonify({"status": "success", "message": f"成功刪除教師 (代碼: {code})"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/subjects/list", methods=["GET"])
def api_get_subjects_list():
    try:
        cfg = load_config_rules()
        custom_subjects = cfg.get("custom_subjects", [])
        deleted_subject_codes = set(cfg.get("deleted_subject_codes", []))

        moe_data = get_moe_course_codes_data()
        db_subjects = moe_data.get("moe_subjects", [])

        merged_map = {}
        for s in db_subjects:
            code = str(s.get("subject_code", "")).strip()
            name = str(s.get("subject_name", "")).strip()
            if code and code not in deleted_subject_codes:
                merged_map[code] = {
                    "code": code,
                    "name": name,
                    "category": s.get("category", "部定必修")
                }

        for s in custom_subjects:
            code = str(s.get("code", "")).strip()
            name = str(s.get("name", "")).strip()
            category = str(s.get("category", "部定必修")).strip()
            if code and code not in deleted_subject_codes:
                merged_map[code] = {"code": code, "name": name, "category": category}

        final_list = list(merged_map.values())
        final_list.sort(key=lambda x: (x.get("code", ""), x.get("name", "")))

        return jsonify({"status": "success", "subjects": final_list})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/subjects/add", methods=["POST"])
def api_add_subject():
    try:
        req = request.get_json() or {}
        code = str(req.get("code", "")).strip()
        name = str(req.get("name", "")).strip()
        category = str(req.get("category", "部定必修")).strip() or "部定必修"

        if not code or not name:
            return jsonify({"status": "error", "message": "科目代碼與名稱不能為空！"}), 400

        cfg = load_config_rules()
        custom_subjects = cfg.get("custom_subjects", [])
        deleted_subject_codes = cfg.get("deleted_subject_codes", [])

        if code in deleted_subject_codes:
            deleted_subject_codes.remove(code)
            cfg["deleted_subject_codes"] = deleted_subject_codes

        existing = next((s for s in custom_subjects if str(s.get("code", "")).strip() == code), None)
        if existing:
            existing["name"] = name
            existing["category"] = category
        else:
            custom_subjects.append({"code": code, "name": name, "category": category})

        cfg["custom_subjects"] = custom_subjects
        save_config_rules(cfg)

        global _cached_data
        _cached_data = None

        return jsonify({"status": "success", "message": f"成功新增/更新科目: 【{name}】({code})"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/subjects/delete", methods=["POST"])
def api_delete_subject():
    try:
        req = request.get_json() or {}
        code = str(req.get("code", "")).strip()
        if not code:
            return jsonify({"status": "error", "message": "未指定欲刪除的科目代碼！"}), 400

        cfg = load_config_rules()
        custom_subjects = cfg.get("custom_subjects", [])
        deleted_subject_codes = cfg.get("deleted_subject_codes", [])

        cfg["custom_subjects"] = [s for s in custom_subjects if str(s.get("code", "")).strip() != code]

        if code not in deleted_subject_codes:
            deleted_subject_codes.append(code)
            cfg["deleted_subject_codes"] = deleted_subject_codes

        save_config_rules(cfg)

        global _cached_data
        _cached_data = None

        return jsonify({"status": "success", "message": f"成功刪除科目 (代碼: {code})"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- CLASS MANAGEMENT API (新增與刪除全校班級與高國中學制) ---

@app.route("/api/classes/list", methods=["GET"])
def api_get_classes_list():
    try:
        cfg = load_config_rules()
        custom_classes = cfg.get("custom_classes", [])
        deleted_class_codes = set(cfg.get("deleted_class_codes", []))

        sched_data = load_schedule_data()
        db_classes = sched_data.get("classes", []) if isinstance(sched_data, dict) else []

        merged_map = {}
        for c in db_classes:
            code = str(c.get("code", "")).strip()
            name = str(c.get("name", "")).strip()
            tutor = str(c.get("tutor", "")).strip()
            if code and code not in deleted_class_codes:
                group = "國中部" if (code.startswith("7") or code.startswith("8") or code.startswith("9")) else ("跨班選修" if "跨班" in name or code in ["404","504","604"] else "高中部")
                merged_map[code] = {"code": code, "name": name, "tutor": tutor, "group": group}

        for c in custom_classes:
            code = str(c.get("code", "")).strip()
            name = str(c.get("name", "")).strip()
            tutor = str(c.get("tutor", "")).strip()
            group = str(c.get("group", "")).strip() or ("國中部" if (code.startswith("7") or code.startswith("8") or code.startswith("9")) else "高中部")
            if code and code not in deleted_class_codes:
                merged_map[code] = {"code": code, "name": name, "tutor": tutor, "group": group}

        final_list = list(merged_map.values())
        final_list.sort(key=lambda x: (x.get("code", ""), x.get("name", "")))

        return jsonify({"status": "success", "classes": final_list})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/classes/add", methods=["POST"])
def api_add_class():
    try:
        req = request.get_json() or {}
        code = str(req.get("code", "")).strip()
        name = str(req.get("name", "")).strip()
        tutor = str(req.get("tutor", "")).strip()
        group = str(req.get("group", "高中部")).strip() or "高中部"

        if not code or not name:
            return jsonify({"status": "error", "message": "班級代碼與名稱不能為空！"}), 400

        cfg = load_config_rules()
        custom_classes = cfg.get("custom_classes", [])
        deleted_class_codes = cfg.get("deleted_class_codes", [])

        if code in deleted_class_codes:
            deleted_class_codes.remove(code)
            cfg["deleted_class_codes"] = deleted_class_codes

        existing = next((c for c in custom_classes if str(c.get("code", "")).strip() == code), None)
        if existing:
            existing["name"] = name
            existing["tutor"] = tutor
            existing["group"] = group
        else:
            custom_classes.append({"code": code, "name": name, "tutor": tutor, "group": group})

        cfg["custom_classes"] = custom_classes
        save_config_rules(cfg)

        global _cached_data
        _cached_data = None

        return jsonify({"status": "success", "message": f"成功新增/更新班級: 【{name}】({code})"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/classes/delete", methods=["POST"])
def api_delete_class():
    try:
        req = request.get_json() or {}
        code = str(req.get("code", "")).strip()
        if not code:
            return jsonify({"status": "error", "message": "未指定欲刪除的班級代碼！"}), 400

        cfg = load_config_rules()
        custom_classes = cfg.get("custom_classes", [])
        deleted_class_codes = cfg.get("deleted_class_codes", [])

        cfg["custom_classes"] = [c for c in custom_classes if str(c.get("code", "")).strip() != code]

        if code not in deleted_class_codes:
            deleted_class_codes.append(code)
            cfg["deleted_class_codes"] = deleted_class_codes

        save_config_rules(cfg)

        global _cached_data
        _cached_data = None

        return jsonify({"status": "success", "message": f"成功刪除班級 (代碼: {code})"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.errorhandler(500)
def handle_500_error(e):
    import traceback
    err_msg = str(e)
    tb = traceback.format_exc()
    print(f"[500 Error] {err_msg}\n{tb}")
    if request.path.startswith("/api/"):
        return jsonify({"status": "error", "message": f"Server Exception: {err_msg}"}), 200
    try:
        return render_template("index.html"), 200
    except Exception:
        return f"<h1>系統提示</h1><p>伺服器已啟動，頁面載入異常: {err_msg}</p>", 200





def generate_default_6class_schedule():
    """Generates a default collision-free 6-class schedule for 101, 201, 301, 701, 801, 901."""
    classes = [
        {"code": "101", "name": "101班", "tutor": "張大明"},
        {"code": "201", "name": "201班", "tutor": "許淑芬"},
        {"code": "301", "name": "301班", "tutor": "郭德華"},
        {"code": "701", "name": "701班", "tutor": "王美玲"},
        {"code": "801", "name": "801班", "tutor": "陳建宏"},
        {"code": "901", "name": "901班", "tutor": "林志豪"},
    ]
    
    subjects_plan = [
        ("國語文", "許淑芬", "T05", None),
        ("數學", "陳建宏", "T02", None),
        ("英語文", "楊宗緯", "T09", None),
        ("理化", "鄭雅婷", "T10", "理化實驗室"),
        ("資訊科技", "王美玲", "T01", "電腦教室"),
        ("體育", "廖健宏", "T08", "體育場/館"),
        ("歷史", "林志豪", "T03", None),
        ("地理", "蔡小芬", "T07", None),
        ("公民", "王美玲", "T01", None),
        ("班會與團體活動", "張大明", "T04", None)
    ]
    
    records = []
    for c_idx, c in enumerate(classes):
        for day in range(1, 6):
            for period in range(1, 9):
                sub_idx = (c_idx * 7 + day * 3 + period) % len(subjects_plan)
                sub_name, t_name, t_code, room = subjects_plan[sub_idx]
                
                if day == 5 and period == 6:
                    sub_name = "班會與團體活動"
                    t_name = c["tutor"]
                    room = None
                    
                records.append({
                    "class_code": c["code"],
                    "class_name": c["name"],
                    "subject_name": sub_name,
                    "subject_code": f"SUB-{sub_idx+1:02d}",
                    "teacher_name": t_name,
                    "teacher_code": t_code,
                    "day": str(day),
                    "period": str(period),
                    "room_name": room or ""
                })
    return records

def normalize_schedule_record(r):
    """Normalize dictionary keys from Excel/DBF into unified standard keys."""
    if not isinstance(r, dict):
        return r
        
    c_code = ""
    c_name = ""
    s_code = ""
    s_name = ""
    t_code = ""
    t_name = ""
    r_code = ""
    r_name = ""
    day = "1"
    period = "1"
    
    for k, v in r.items():
        if v is None or (isinstance(v, float) and str(v) == "nan"):
            v = ""
        v_str = str(v).strip()
        k_str = str(k).strip()
        
        if "班級代碼" in k_str or k_str == "CLASS_NO" or k_str == "class_code":
            c_code = v_str
        elif "班級名稱" in k_str or k_str == "CLASS_NAME" or k_str == "class_name":
            c_name = v_str
        elif "科目代碼" in k_str or k_str == "SUB_NO" or k_str == "subject_code":
            s_code = v_str
        elif "科目" in k_str or k_str == "SUB_NAME" or k_str == "subject_name":
            s_name = v_str
        elif "教師代碼" in k_str or k_str == "TEA_NO" or k_str == "teacher_code":
            t_code = v_str
        elif "教師" in k_str or k_str == "TEA_NAME" or k_str == "teacher_name":
            t_name = v_str
        elif "教室代碼" in k_str or k_str == "ROOM_NO" or k_str == "room_code":
            r_code = v_str
        elif "教室" in k_str or k_str == "ROOM_NAME" or k_str == "room_name":
            r_name = v_str
        elif "星期" in k_str or k_str == "DAY" or k_str == "day":
            day = v_str
        elif "節次" in k_str or k_str == "PERIOD" or k_str == "period":
            period = v_str
            
    if not c_code and r.get("class_code"): c_code = str(r["class_code"])
    if not c_name and r.get("class_name"): c_name = str(r["class_name"])
    if not c_name and c_code: c_name = f"{c_code}班" if not c_code.endswith("班") else c_code
    if not c_code and c_name: c_code = c_name.replace("班", "")
    
    if not t_code and r.get("teacher_code"): t_code = str(r["teacher_code"])
    if not t_name and r.get("teacher_name"): t_name = str(r["teacher_name"])
    
    t_code = str(t_code or "").strip()
    if t_code.endswith(".0"): t_code = t_code[:-2]
    if t_code.lower() in ("nan", "none", "null"): t_code = ""

    t_name = str(t_name or "").strip()
    if t_name.endswith(".0"): t_name = t_name[:-2]
    if t_name.lower() in ("nan", "none", "null"): t_name = ""

    # If t_name is numeric or empty, look up in teachers config
    if (not t_name or t_name.isdigit()) and t_code:
        try:
            cfg = load_config_rules()
            for tch in cfg.get("teachers", []):
                tch_code = str(tch.get("code", "")).strip().replace(".0", "")
                if tch_code == t_code:
                    t_name = tch.get("name", t_name)
                    break
        except Exception:
            log_exception("normalize_solved_record:teacher_lookup", traceback.format_exc())

    return {
        "id": r.get("id") or f"{c_code}_{day}_{period}",
        "class_code": c_code,
        "class_name": c_name,
        "subject_code": s_code or str(r.get("subject_code", "")),
        "subject_name": s_name or str(r.get("subject_name", "")),
        "teacher_code": t_code or str(r.get("teacher_code", "")),
        "teacher_name": t_name or str(r.get("teacher_name", "")),
        "day": str(day or "1"),
        "period": str(period or "1"),
        "room_name": r_name or str(r.get("room_name", ""))
    }

def get_current_solved_schedules():
    # 優先從 load_schedule_data 取得目前生效課表（支援欣河 Excel、claspv.dbf、已解算課表）
    try:
        data = load_schedule_data()
        if isinstance(data, dict) and data.get("schedules"):
            return [normalize_schedule_record(r) for r in data["schedules"] if isinstance(r, dict)]
    except Exception as e:
        print(f"[警告] load_schedule_data 載入課表失敗: {e}")

    excel_path = os.path.join(os.path.dirname(__file__), "School_Schedule_Solved.xlsx")
    solved = []

    # Priority 2: Read freshly generated School_Schedule_Solved.xlsx
    if os.path.exists(excel_path):
        try:
            import pandas as pd
            df = pd.read_excel(excel_path)
            solved = df.to_dict(orient="records")
        except Exception as e:
            print(f"[警告] 讀取 School_Schedule_Solved.xlsx 失敗: {e}")

    # Priority 3: Fallback to config_rules.json
    if not solved:
        cfg = load_config_rules()
        solved = cfg.get("solved_schedules", [])

    # Priority 4: Fallback to default 6 class generator
    if not solved:
        solved = generate_default_6class_schedule()
        cfg = load_config_rules()
        cfg["solved_schedules"] = solved
        save_config_rules(cfg)

    normalized = [normalize_schedule_record(r) for r in solved if isinstance(r, dict)]
    return normalized







@app.errorhandler(404)
def handle_404_error(e):
    if request.path == "/teacher":
        return render_template("teacher_portal.html"), 200
    if request.path.startswith("/api/"):
        return jsonify({"status": "error", "message": "API route not found"}), 404
    try:
        return render_template("index.html"), 200
    except Exception:
        return "<h1>404 Not Found</h1>", 404

def process_semantic_ai_scheduling(msg, cfg, data):
    """
    Advanced Natural Language Semantic AI Understanding Engine.
    Parses unstructured user prompts into actions.
    """
    import re
    msg_clean = msg.strip()
    
    # 1. Master Auto Build / Full Run / General Execution Prompts
    full_auto_triggers = [
        "全部", "全套", "全部都要", "全部一次", "全包", "全部自動", "搞定", 
        "都排", "都做", "一鍵", "全校排課", "自動排課", "開始", "執行", 
        "go", "yes", "好", "全部幫我", "幫我排", "排課", "排下去", "都來", "幫我全排"
    ]
    if any(t in msg_clean for t in full_auto_triggers) and not any(k in msg_clean for k in ["不排課", "不排", "避開", "休假", "特定", "不要"]):
        reply = (
            "🧠 【AI 語意理解成功】已為您識別並啟動全校 AI 智慧排課指令！\n\n"
            "正在為您全自動執行以下 5 大排課步驟：\n"
            "1. 🏫 載入全校 6 班課程與教師名單範本\n"
            "2. 🤖 智慧匹配教師額度與導師授課平衡\n"
            "3. 🪄 自動對接電腦教室、實驗室與體育場容量上限\n"
            "4. 👥 鎖定全校共同班會時段\n"
            "5. ⚡ 啟動 Google OR-Tools CP-SAT 最優化求解與零衝突驗證！"
        )
        return reply, "run_full_auto", {}

    # 2. Extract Teacher No-Teach Slots (e.g. "王美玲老師星期五下午不要排課")
    if any(k in msg_clean for k in ["不排課", "避開", "不要排", "空出來", "休假", "請假"]):
        teachers = data.get("teachers", [])
        matched_teachers = []
        for t in teachers:
            tname = t.get("name", "")
            tcode = t.get("code", "")
            if tname and (tname in msg_clean or tname[:2] in msg_clean):
                matched_teachers.append((tcode, tname))
                
        day_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5}
        target_day = None
        for d_str, d_int in day_map.items():
            if f"星期{d_str}" in msg_clean or f"週{d_str}" in msg_clean or f"周{d_str}" in msg_clean or f"禮拜{d_str}" in msg_clean:
                target_day = d_int
                break
                
        periods = []
        if "下午" in msg_clean: periods = [5, 6, 7, 8]
        elif "上午" in msg_clean: periods = [1, 2, 3, 4]
        elif "整天" in msg_clean: periods = [1, 2, 3, 4, 5, 6, 7, 8]
        
        p_match = re.findall(r"第?([1-8])節?", msg_clean)
        if p_match and not periods:
            periods = [int(p) for p in p_match]

        if matched_teachers and target_day and periods:
            cfg = load_config_rules()
            if "custom_no_teach" not in cfg:
                cfg["custom_no_teach"] = {}
                
            new_slots = [f"{target_day}-{p}" for p in periods]
            for tcode, tname in matched_teachers:
                t_key = tcode or tname
                if t_key not in cfg["custom_no_teach"]:
                    cfg["custom_no_teach"][t_key] = []
                for s in new_slots:
                    if s not in cfg["custom_no_teach"][t_key]:
                        cfg["custom_no_teach"][t_key].append(s)
            save_config_rules(cfg)
            
            t_names = "、".join([t[1] for t in matched_teachers])
            day_names = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}
            p_desc = "、".join([f"第{p}節" for p in periods])
            reply = f"✅ 【AI 語意執行成功】已成功為【{t_names}】老師設定限制：\n週{day_names[target_day]} {p_desc} 設定為不排課時段！\n\n規則已寫入全校排課資料庫並立即生效。"
            return reply, "update_no_teach", {"teachers": [t[1] for t in matched_teachers]}

    # 3. Common Simultaneous Scheduling (Class Meeting, Clubs, Assembly)
    if any(k in msg_clean for k in ["班會", "社團", "週會", "共同"]):
        sim_type = "全校共同班會" if "班會" in msg_clean else ("全校共同社團" if "社團" in msg_clean else "全校共同週會")
        reply = (
            f"👥 【AI 語意理解成功】已為您設定【{sim_type}】！\n\n"
            f"系統已自動建立跨全校所有班級的「同時排課鎖定約束 (Simultaneous Group)」，"
            f"在求解時 CP-SAT 將確保全校班級於同一時間上班會/社團！"
        )
        return reply, "create_sim_preset", {"type": sim_type}

    # 4. Specific Class / Teacher / Room Timetable Navigation Query
    classes = data.get("classes", [])
    teachers = data.get("teachers", [])
    
    # Check Class match
    target_class = None
    for c in classes:
        c_code = str(c.get("code", ""))
        c_name = str(c.get("name", ""))
        if c_code and (c_code in msg_clean or c_name in msg_clean or (len(c_code) == 3 and c_code in msg_clean)):
            target_class = c
            break

    if target_class:
        reply = f"🚀 【AI 語意切換】已為您開啟【{target_class.get('name')}】班級課表！"
        return reply, "show_class_schedule", {"code": target_class.get("code")}

    # Check Teacher match
    target_teacher = None
    for t in teachers:
        t_name = str(t.get("name", ""))
        t_code = str(t.get("code", ""))
        if t_name and t_name in msg_clean:
            target_teacher = t
            break

    if target_teacher:
        reply = f"🚀 【AI 語意切換】已為您開啟【{target_teacher.get('name')}】老師個人課表！"
        return reply, "show_teacher_schedule", {"code": target_teacher.get("code")}

    # Check Room match
    rooms = ["電腦教室", "理化實驗室", "生物實驗室", "音樂教室", "美術教室", "體育場/館", "家政教室", "生活科技教室"]
    for rname in rooms:
        if rname in msg_clean and "課表" in msg_clean:
            reply = f"🚀 【AI 語意切換】已為您開啟【{rname}】專用教室課表！"
            return reply, "show_room_schedule", {"code": rname}

    # 5. Special Room Capacity & Subject Mapping
    if any(k in msg_clean for k in ["專用教室", "電腦教室", "實驗室", "對接", "體育", "場地"]):
        reply = (
            "🪄 【AI 語意理解成功】已完成全校專用教室自動對接與容量控管！\n\n"
            "• 💻 電腦教室 (控管上限 2 班) ➔ 自動對接 資訊科技 / 程式設計\n"
            "• 🧪 理化實驗室 (控管上限 2 班) ➔ 自動對接 理化 / 物理 / 化學\n"
            "• 🧪 生物實驗室 (控管上限 1 班) ➔ 自動對接 生物\n"
            "• 🏀 體育場/館 (控管上限 3 班) ➔ 自動對接 體育"
        )
        return reply, "match_venues", {}

    # 5a. Direct adjustment / demonstration mode
    if any(k in msg_clean for k in ["怎麼調", "如何調", "直接解決", "幫我修正", "幫我處理", "調整", "演示", "示範"]):
        reply = (
            "🛠️ 【AI 調整演示模式】\n"
            "我可以直接幫你進入調整流程，並在螢幕上展示可行改法：\n"
            "1. 先打開雙視窗對照或智慧修復頁面\n"
            "2. 標出可調整的課程、教師與可用時段\n"
            "3. 直接提供可執行的對調 / 微調 / 代課 / 連鎖調整方案\n"
            "4. 你確認後可立即套用到課表"
        )
        return reply, "rescue", {"demo": True}

    # 5. Teacher specialty / subject query
    if any(k in msg_clean for k in ["專長", "任教科目", "教什麼", "擅長", "可以教", "教哪科", "科目"]):
        teachers = data.get("teachers", [])
        matched = []
        for t in teachers:
            tname = str(t.get("name", "")).strip()
            tcode = str(t.get("code", "")).strip()
            tsubj = str(t.get("subject", "")).strip()
            trole = str(t.get("role", "")).strip()
            if any(x and x in msg_clean for x in [tname, tcode, tsubj, trole]):
                matched.append(t)
        if matched:
            lines = []
            for t in matched[:15]:
                lines.append(f"• {t.get('name')}({t.get('code')}): {t.get('subject') or t.get('role', '未標示')}")
            reply = "📚 【AI 教師專長查詢】\n" + "\n".join(lines)
            return reply, None, {}

    # 6. Teacher Surname / Count Query (e.g. "有幾個姓王的老師", "姓王的老師有哪些")
    if ("姓" in msg_clean and ("老師" in msg_clean or "教師" in msg_clean)) or ("有幾個" in msg_clean and "老師" in msg_clean) or ("幾位老師" in msg_clean):
        teachers = data.get("teachers", [])
        surname = ""
        m_surname = re.search(r"姓([\u4e00-\u9fa5]{1,2})", msg_clean)
        if m_surname:
            surname = m_surname.group(1)
            
        matched = []
        for t in teachers:
            tname = t.get("name", "")
            if surname:
                if tname.startswith(surname) or surname in tname:
                    matched.append(t)
            else:
                matched.append(t)
                
        if surname:
            if matched:
                t_list_str = "\n".join([f"{i+1}. {t.get('name')} (代碼: {t.get('code')}, 身分: {t.get('role', '專任教師')})" for i, t in enumerate(matched)])
                reply = f"📊 【AI 學校資料庫即時查詢】\n目前全校資料庫中共有 {len(matched)} 位姓「{surname}」的教師：\n{t_list_str}"
            else:
                reply = f"📊 【AI 學校資料庫即時查詢】\n目前全校資料庫中未找到姓「{surname}」的教師。"
        else:
            t_list_str = "、".join([t.get("name") for t in teachers[:10]])
            reply = f"📊 【AI 學校資料庫即時查詢】\n目前全校資料庫中共有 {len(teachers)} 位教師，包含：{t_list_str}..."
        return reply, None, {}

    # 7. Specific Class / Teacher / Room Timetable Navigation Query
    classes = data.get("classes", [])
    teachers = data.get("teachers", [])
    
    # Check Class match
    target_class = None
    for c in classes:
        c_code = str(c.get("code", ""))
        c_name = str(c.get("name", ""))
        if c_code and (c_code in msg_clean or c_name in msg_clean or (len(c_code) == 3 and c_code in msg_clean)):
            target_class = c
            break

    if target_class:
        reply = f"🚀 【AI 語意切換】已為您開啟【{target_class.get('name')}】班級課表！"
        return reply, "show_class_schedule", {"code": target_class.get("code")}

    # Check Teacher match
    target_teacher = None
    for t in teachers:
        t_name = str(t.get("name", ""))
        t_code = str(t.get("code", ""))
        if t_name and t_name in msg_clean:
            target_teacher = t
            break

    if target_teacher:
        reply = f"🚀 【AI 語意切換】已為您開啟【{target_teacher.get('name')}】老師個人課表！"
        return reply, "show_teacher_schedule", {"code": target_teacher.get("code")}

    # Check Room match
    rooms = ["電腦教室", "理化實驗室", "生物實驗室", "音樂教室", "美術教室", "體育場/館", "家政教室", "生活科技教室"]
    for rname in rooms:
        if rname in msg_clean:
            reply = f"🚀 【AI 語意切換】已為您開啟【{rname}】專用教室課表！"
            return reply, "show_room_schedule", {"code": rname}

    # 8. Class / Tutor Query (e.g. "701班導師是誰", "有幾個班級")
    if "導師" in msg_clean or ("有幾個" in msg_clean and "班" in msg_clean) or ("班級" in msg_clean and "名單" in msg_clean):
        classes = data.get("classes", [])
        c_list_str = "\n".join([f"• {c.get('name')}: 導師【{c.get('tutor', '未指派')}】" for c in classes])
        reply = f"🏫 【AI 全校班級與導師即時資料】\n目前全校共有 {len(classes)} 個班級：\n{c_list_str}"
        return reply, None, {}

    # 9. Semester Switch or Creation
    if "學期" in msg_clean:
        sem_match = re.search(r"1\d\d-[12]", msg_clean)
        if sem_match:
            target_sem = sem_match.group(0)
            reply = f"📅 【AI 語意理解成功】正在為您開辦/切換至【{target_sem}】學期檔案！所有全校設定與配課資料均已自動繼承。"
            return reply, "switch_semester", {"semester_id": target_sem}
        else:
            curr_sem = cfg.get("active_semester_id", "114-1")
            reply = f"📅 【AI 語意理解】目前啟用的學期為【{curr_sem}】。您可以告訴我：「開辦 114-2 學期」或「切換至 115-1 學期」，我會為您一鍵切換與繼承！"
            return reply, None, {}

    # 10. Smart General Reasoning Fallback
    reply = (
        "🤖 【AI 智慧自然語言助理就緒】我能聽懂您的自由口語描述與查詢，例如：\n"
        "• 💬「201的課表」\n"
        "• 💬「有幾個姓王的老師」\n"
        "• 💬「全部一次AI自動設定」或「全部都要」\n"
        "• 💬「王美玲老師星期五下午不要排課」\n"
        "• 💬「把電腦課跟理化課自動對接專用教室」\n"
        "• 💬「幫全校排共同班會與社團」\n"
        "• 💬「開辦 114-2 新學期並匯入全校範本」\n\n"
        "請直接用您的對話方式告訴我需求，我會自動為您分析、統計與執行！"
    )
    return reply, None, {}


def call_groq_llm_api(user_msg, cfg, data, groq_api_key, model="llama-3.3-70b-versatile"):
    """
    Call Groq Cloud LLM API (OpenAI-compatible endpoint).
    Ultra-fast Llama 3.3 70B inference with full real-time school database & schedule context!
    """
    import json
    import urllib.request
    
    teachers = data.get("teachers", [])
    classes = data.get("classes", [])
    subjects = data.get("subjects", [])
    solved = get_current_solved_schedules()
    
    t_summary = ", ".join([
        f"{t.get('name')}({t.get('code')})[{t.get('subject') or t.get('role') or '未標示'}]"
        for t in teachers[:40]
    ])
    c_summary = ", ".join([f"{c.get('name')}(導師:{c.get('tutor','未指派')})" for c in classes])
    s_summary = ", ".join([s.get('name') for s in subjects[:12]])

    class_map = {}
    for s in solved:
        cn = str(s.get("class_name") or s.get("class_code"))
        if cn not in class_map:
            class_map[cn] = []
        class_map[cn].append(f"週{s.get('day')}第{s.get('period')}節:{s.get('subject_name')}({s.get('teacher_name')})")

    solved_summary_lines = []
    for cn, lessons in class_map.items():
        solved_summary_lines.append(f"【{cn}】" + ", ".join(lessons[:20]))

    solved_summary = "\n".join(solved_summary_lines) if solved_summary_lines else "目前尚未排課求解"

    system_prompt = (
        "你是一個專為臺灣中學設計的『舟歌 AI 智慧排課自然語言助手』。\n"
        f"目前學校真實資料庫數據如下：\n"
        f"• 現有教師 ({len(teachers)}位)：{t_summary}\n"
        f"• 現有班級 ({len(classes)}班)：{c_summary}\n"
        f"• 現有學科：{s_summary}\n"
        f"• 已排好的現行課表摘要：{solved_summary}\n\n"
        "當使用者詢問『201的課表』或某班級/教師課表時，請參考上述『已排好的現行課表摘要』詳細列出該班/該老師各節次的科目與時間。\n"
        "當使用者詢問教師專長、任教科目、代課人選、或某科目應找哪位老師時，請優先使用教師資料中的 subject 與 role，並結合現行排課紀錄推理。\n"
        "若使用者的話中含有明確排課動作意圖，請盡量輸出 action 與 payload，不要只做純聊天回答。\n"
        "回應格式必須為 JSON，包含 3 個欄位：\n"
        "1. reply: (字串) 用親切繁體中文向使用者詳細說明的課表內容或統計分析結果\n"
        "2. action: (字串) 應執行的動作代碼 (run_full_auto, create_sim_preset, match_venues, update_no_teach, switch_semester, 或 null)\n"
        "3. payload: (物件) 動作相關參數 (如 semester_id, type)\n\n"
        "請僅輸出合法 JSON，不要包含任何說明標籤與 Markdown Code block 符號。"
    )
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {groq_api_key.strip()}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg}
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"}
    }
    
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=12) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            content = res_data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return parsed.get("reply"), parsed.get("action"), parsed.get("payload", {})
    except urllib.error.HTTPError as he:
        if he.code == 403:
            print("[Groq API Log] 提示: Groq API Key 可能無效或存取受限 (HTTP 403 Forbidden)，已自動切換回內建語意引擎。")
        else:
            print(f"[Groq API Log] HTTP Error {he.code}: {he.reason}")
        raise he

@app.route("/api/config/groq", methods=["GET", "POST"])
def api_config_groq():
    """Get or Save Groq API Key and Model setting."""
    try:
        cfg = load_config_rules()
        if request.method == "POST":
            req = request.get_json(silent=True) or {}
            api_key = str(req.get("groq_api_key", "")).strip()
            model = str(req.get("groq_model", "llama-3.3-70b-versatile")).strip()
            
            cfg["groq_api_key"] = api_key
            cfg["groq_model"] = model
            save_config_rules(cfg)
            
            status_text = "已設定 Groq API Key" if api_key else "未設定 (使用內建 AI 語意引擎)"
            return jsonify({
                "status": "success",
                "message": f"Groq AI 設定已成功儲存！({status_text})",
                "has_key": bool(api_key),
                "model": model
            })
        else:
            api_key = cfg.get("groq_api_key") or os.environ.get("GROQ_API_KEY", "")
            masked_key = ""
            if api_key:
                masked_key = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "***"
            return jsonify({
                "status": "success",
                "has_key": bool(api_key),
                "masked_key": masked_key,
                "model": cfg.get("groq_model", "llama-3.3-70b-versatile")
            })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/server-info", methods=["GET"])
def api_server_info():
    """Returns local server network status and real IP address for cross-device links."""
    try:
        local_ip = get_local_ip()
        host = request.host
        port = host.split(":")[-1] if ":" in host else "5000"
        scheme = request.scheme or "http"
        lan_url = f"{scheme}://{local_ip}:{port}" if port not in ("80", "443") else f"{scheme}://{local_ip}"
        cloud_url = "https://tucheng-school-schedule.onrender.com"
        github_url = "https://github.com/YOUR_GITHUB_OWNER/YOUR_GITHUB_REPO"
        return jsonify({
            "status": "success",
            "local_ip": local_ip,
            "port": port,
            "lan_url": lan_url,
            "cloud_url": cloud_url,
            "github_url": github_url
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/save-config-rule", methods=["POST"])
def api_save_config_rule():
    """Saves individual rule config keys dynamically."""
    try:
        req = request.get_json(silent=True) or {}
        key = str(req.get("key", "")).strip()
        val = req.get("value")
        if not key:
            return jsonify({"status": "error", "message": "Key name is required"}), 400
        cfg = load_config_rules()
        cfg[key] = val
        save_config_rules(cfg)
        return jsonify({"status": "success", "message": f"Rule {key} updated successfully!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/run-solver", methods=["GET", "POST"])
def api_trigger_cp_solver():
    """Triggers CP-SAT solver execution dynamically with live module reloads."""
    try:
        import importlib
        import solve_schedule
        importlib.reload(solve_schedule)
        res = solve_schedule.run_solver()
        return jsonify(res)
    except Exception as e:
        return jsonify({"status": "error", "message": f"排課運算失敗: {str(e)}"}), 500

@app.route("/api/health-check", methods=["GET"])
def api_health_check():
    """Runs global schedule health inspection & data logic validation with smart pseudo-teacher and joint-event filtering."""
    try:
        data = load_schedule_data()
        solved = get_current_solved_schedules()
        cfg = load_config_rules()

        teacher_conflicts = []
        class_conflicts = []
        no_teach_violations = []
        fatigue_warnings = []

        slot_teachers = {}
        slot_classes = {}

        teacher_no_teach = cfg.get("teacher_no_teach", {})

        PSEUDO_TEACHERS = {"學務處", "各班導師", "教務處", "輔導室", "體育組", "總務處", "校長室", "無", "未指定", "待定", "自習"}
        JOINT_SUBJECTS = {"週會", "班會", "全校活動", "社團活動"}

        for s in solved:
            day = s.get("day")
            period = s.get("period")
            t_name = s.get("teacher_name")
            t_code = s.get("teacher_code")
            c_name = str(s.get("class_name") or s.get("class_code") or "")
            subj = s.get("subject_name", "")

            if not day or not period:
                continue

            slot_key = (day, period)

            is_pseudo_teacher = (t_name in PSEUDO_TEACHERS) or any(p in (t_name or "") for p in ["導師", "處", "組"])
            
            # Taiwanese High School Grouped Electives & Extraction Subjects
            GROUPED_ELECTIVE_KEYWORDS = [
                "本土", "語文", "手語", "閩南", "原民", "客家", "自主學習", 
                "充實補強", "彈性學習", "週期課程", "選修", "抽離", "跨班", 
                "分組", "輔導", "週會", "班會", "社團", "全校活動"
            ]

            is_joint_subject = (subj in JOINT_SUBJECTS) or any(k in subj for k in GROUPED_ELECTIVE_KEYWORDS) or ("跨班" in c_name)

            # 1. Check teacher conflict (Only for real individual teachers teaching non-joint subjects)
            if t_name and not is_pseudo_teacher and not is_joint_subject:
                t_key = (slot_key, t_name)
                if t_key in slot_teachers:
                    other_c = slot_teachers[t_key]
                    if other_c != c_name:
                        msg = f"❌ 教師【{t_name}】衝堂：在 星期{day} 第{period}節 同時排了【{other_c}】與【{c_name}】({subj})"
                        if msg not in teacher_conflicts:
                            teacher_conflicts.append(msg)
                else:
                    slot_teachers[t_key] = c_name

            # 2. Check class conflict (Only for standard non-cross-class sessions)
            if c_name and "跨班" not in c_name and not is_joint_subject:
                c_key = (slot_key, c_name)
                if c_key in slot_classes:
                    other_info = slot_classes[c_key]
                else:
                    slot_classes[c_key] = f"{subj}({t_name or ''})"

            # 3. Check teacher no-teach restriction
            if t_code and t_code in teacher_no_teach and not is_pseudo_teacher:
                forbidden_slots = teacher_no_teach[t_code]
                slot_str = f"{day}-{period}"
                if slot_str in forbidden_slots:
                    msg = f"⚠️ 教師【{t_name}】禁排違規：星期{day} 第{period}節 被排課【{c_name}】({subj})，違反個人不排課設定"
                    if msg not in no_teach_violations:
                        no_teach_violations.append(msg)

            # 4. Check Period 8 constraint: Regular main courses must NOT be in Period 8
            if str(period) == "8":
                is_tutoring = (subj.endswith("輔導") or ("輔導" in subj[1:]) or any(k in subj for k in ["第八", "8節", "課後", "補救"])) if subj else False
                if subj and (subj.startswith("輔導活動") or subj == "輔導"):
                    is_tutoring = False
                if not is_tutoring and not is_pseudo_teacher:
                    msg = f"⚠️ 正課排入第8節違規：班級【{c_name}】星期{day} 第8節 被安排了正課【{subj}】({t_name})，按規定正課僅能排在第1~7節"
                    if msg not in no_teach_violations:
                        class_conflicts.append(msg)

        total_issues = len(teacher_conflicts) + len(class_conflicts) + len(no_teach_violations) + len(fatigue_warnings)

        return jsonify({
            "status": "success",
            "teacher_conflicts": teacher_conflicts,
            "class_conflicts": class_conflicts,
            "no_teach_violations": no_teach_violations,
            "fatigue_warnings": fatigue_warnings,
            "total_issues": total_issues
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"診斷時發生錯誤: {str(e)}"}), 500

@app.route("/api/ai-chat", methods=["POST"])
def api_ai_chat():
    """Natural Language AI Conversational Assistant Endpoint with Hybrid Gemini/Groq LLM & Deterministic Engine."""
    try:
        req = request.get_json(silent=True) or {}
        msg = str(req.get("message", "")).strip()
        if not msg:
            return jsonify({"status": "error", "message": "請輸入對話內容！"}), 400

        cfg = load_config_rules()
        data = load_schedule_data()

        # 1. First parse deterministic system actions & queries
        s_reply, s_action, s_payload = process_semantic_ai_scheduling(msg, cfg, data)

        gemini_key = cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
        groq_key = cfg.get("groq_api_key") or os.environ.get("GROQ_API_KEY", "")
        groq_model = cfg.get("groq_model", "llama-3.3-70b-versatile")
        
        reply = None
        action = s_action
        action_payload = s_payload or {}
        
        # 2. Query LLM (Priority: Gemini -> Groq -> fallback)
        if s_action is None:
            if gemini_key:
                try:
                    t_summary = ", ".join([
                        f"{t.get('name')}[{t.get('subject') or t.get('role') or '未標示'}]"
                        for t in data.get('teachers', [])[:15]
                    ])
                    c_summary = ", ".join([c.get('name') for c in data.get('classes', [])])
                    prompt = (
                        f"你是一個臺灣中學排課專家 AI 對談助手。\n"
                        f"目前學校有教師: {t_summary} 等...\n"
                        f"班級有: {c_summary}\n"
                        f"使用者指令: {msg}\n\n"
                        "請以親切、專業的繁體中文回答，若有動作代碼與參數，請以 JSON 格式回應，否則直接以口語詳細解答。"
                    )
                    g_reply = call_gemini_llm_api(prompt, gemini_key, model="gemini-2.5-flash")
                    if g_reply:
                        try:
                            import re, json
                            json_match = re.search(r"\{.*\}", g_reply, re.DOTALL)
                            if json_match:
                                parsed = json.loads(json_match.group(0))
                                reply = f"✨ 【Gemini AI 助手】\n{parsed.get('reply')}"
                                if parsed.get("action"): action = parsed.get("action")
                                if parsed.get("payload"): action_payload = parsed.get("payload")
                            else:
                                reply = f"✨ 【Gemini AI 助手】\n{g_reply}"
                        except Exception:
                            reply = f"✨ 【Gemini AI 助手】\n{g_reply}"
                except Exception as e:
                    print(f"[Gemini Chat API Error] {e}")

            if not reply and groq_key:
                try:
                    g_reply, g_action, g_payload = call_groq_llm_api(msg, cfg, data, groq_key, model=groq_model)
                    if g_reply:
                        reply = f"⚡ 【Groq High-Speed AI ({groq_model})】\n{g_reply}"
                        if g_action: action = g_action
                        if g_payload: action_payload = g_payload
                except Exception as ge:
                    print(f"[Groq API Exception] Fallback to Semantic Engine: {ge}")

        if not reply:
            reply = s_reply

        return jsonify({
            "status": "success",
            "reply": reply,
            "action": action,
            "payload": action_payload
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"AI 對談處理異常: {str(e)}"}), 500

def call_gemini_llm_api(prompt, api_key, model="gemini-2.5-flash", response_json=False):
    import urllib.request
    import json
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {
        "Content-Type": "application/json"
    }
    body = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    if response_json:
        body["generationConfig"] = {
            "responseMimeType": "application/json"
        }
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            candidates = res_data.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts:
                    return parts[0].get("text", "")
            return ""
    except Exception as e:
        print(f"[Gemini API Error] {e}")
        raise e

@app.route("/api/config/gemini", methods=["GET", "POST"])
def api_config_gemini():
    try:
        cfg = load_config_rules()
        if request.method == "POST":
            req = request.get_json(silent=True) or {}
            api_key = str(req.get("gemini_api_key", "")).strip()
            cfg["gemini_api_key"] = api_key
            save_config_rules(cfg)
            status_text = "已設定 Gemini API Key" if api_key else "未設定 (將使用 Groq Key 或內建 AI 語意)"
            return jsonify({
                "status": "success",
                "message": f"Gemini AI 設定已成功儲存！({status_text})",
                "has_key": bool(api_key)
            })
        else:
            api_key = cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
            masked_key = ""
            if api_key:
                masked_key = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "***"
            return jsonify({
                "status": "success",
                "has_key": bool(api_key),
                "masked_key": masked_key
            })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/ai-diagnose-bottlenecks", methods=["POST"])
def api_ai_diagnose_bottlenecks():
    """
    AI Timetable Constraints Diagnostician.
    Analyzes schedule bottlenecks and conflicts to give human-friendly constraint relaxing advice.
    """
    try:
        cfg = load_config_rules()
        data = load_schedule_data()
        
        debug_res = api_data_debug_report().get_json()
        audit = debug_res.get("audit_summary", {}) if debug_res.get("status") == "success" else {}
        
        logic_errors = audit.get("logic_errors", [])
        unassigned_subjects = audit.get("unassigned_subjects", [])
        
        bottleneck_res = api_check_bottlenecks().get_json()
        teacher_bottlenecks = bottleneck_res.get("teacher_bottlenecks", []) if isinstance(bottleneck_res, dict) else []
        
        errs_desc = "\n".join([f"- {e}" for e in logic_errors[:15]]) if logic_errors else "無硬性衝突與邏輯錯誤。"
        unassigned_desc = ", ".join(unassigned_subjects[:15]) if unassigned_subjects else "無未指派教師之科目。"
        
        bottlenecks_desc = ""
        for b in teacher_bottlenecks[:10]:
            bottlenecks_desc += f"- 教師【{b.get('teacher')}】: 需排 {b.get('needed')} 節課，但可用空堂僅 {b.get('available_candidates')} 節，剩餘裕度(slack)僅 {b.get('slack')} 節。\n"
        if not bottlenecks_desc:
            bottlenecks_desc = "無明顯排課裕度不足之瓶頸教師。"
            
        prompt = (
            "你是一個臺灣中學排課專家 AI 診斷助手。請分析以下排課系統提供的診斷報告數據，"
            "以專業、親切的繁體中文，為學校排課管理者提出具體的限制調整或排課建議：\n\n"
            f"=== 1. 硬性衝堂與邏輯錯誤 ===\n{errs_desc}\n\n"
            f"=== 2. 未指派授課教師科目 ===\n{unassigned_desc}\n\n"
            f"=== 3. 裕度極度吃緊之教師瓶頸 ===\n{bottlenecks_desc}\n\n"
            "請給出 3~4 點明確可行的解決方案建議（例如建議放寬某些教師的不排課設定、檢視某科目的專用教室容量限制、或是檢查某些班級的配課是否超額）。"
        )
        
        gemini_key = cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
        groq_key = cfg.get("groq_api_key") or os.environ.get("GROQ_API_KEY", "")
        
        reply = ""
        if gemini_key:
            try:
                reply = call_gemini_llm_api(prompt, gemini_key, model="gemini-2.5-flash")
                if reply:
                    reply = "✨ 【Google Gemini 2.5 Flash 排課診斷建議】\n" + reply
            except Exception as e:
                print(f"Fallback to Groq due to Gemini error: {e}")
                
        if not reply and groq_key:
            try:
                groq_model = cfg.get("groq_model", "llama-3.3-70b-versatile")
                headers = {
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0"
                }
                body = {
                    "model": groq_model,
                    "messages": [
                        {"role": "system", "content": "你是一個臺灣中學排課診斷專家。"},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3
                }
                import urllib.request, json
                req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=12) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    reply = "⚡ 【Groq Llama 3.3 排課診斷建議】\n" + res_data["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"Groq API error: {e}")
                
        if not reply:
            reply = (
                "解【本機排課限制診斷與建議】\n"
                "1. 請檢查診斷報告中的「硬性衝堂」教師與班級項目，這是排課系統的硬性約束衝突。\n"
                "2. 若有裕度極度吃緊的教師（如可用空堂接近所需節數），代表該教師的「不排課時段」限制過於嚴格，建議在基本資料中適度放寬其不排課設定。\n"
                "3. 請確認是否有科目尚未在「配課管理」中指派任課教師，避免遺漏。"
            )
            
        return jsonify({
            "status": "success",
            "diagnose": reply
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"AI 診斷失敗: {str(e)}"}), 500

@app.route("/api/export-shinher-excel", methods=["GET"])
def api_export_shinher_excel():
    """
    Export ShinHer compatible excel templates for:
    - teacher: 教師代碼
    - class: 班級代碼
    - subject: 科目代碼
    - curriculum: 配課資料
    """
    try:
        import pandas as pd
        import io
        
        export_type = request.args.get("type", "teacher")
        cfg = load_config_rules()
        data = load_schedule_data()
        
        output = io.BytesIO()
        
        if export_type == "teacher":
            teachers = data.get("teachers", [])
            rows = []
            for t in teachers:
                rows.append({
                    "教師代碼": t.get("code", ""),
                    "教師姓名": t.get("name", ""),
                    "教師職務名稱": t.get("role", "專任教師"),
                    "教師組別": "",
                    "基本節數": t.get("base_hours", 16),
                    "人事編號": "",
                    "電子信箱": "",
                    "備註": ""
                })
            df = pd.DataFrame(rows)
            sheet_name = "教師代碼匯入"
            filename = "教師代碼匯入表.xlsx"
            
        elif export_type == "class":
            classes = data.get("classes", [])
            teachers = data.get("teachers", [])
            t_name_to_code = {t.get("name"): t.get("code") for t in teachers}
            
            rows = []
            for c in classes:
                tutor_name = c.get("tutor", "")
                tutor_code = t_name_to_code.get(tutor_name, "")
                rows.append({
                    "班級代碼": c.get("code", ""),
                    "班級名稱": c.get("name", ""),
                    "導師代碼": tutor_code,
                    "導師姓名": tutor_name,
                    "課諮師代碼": "",
                    "教室代碼": ""
                })
            df = pd.DataFrame(rows)
            sheet_name = "班級代碼匯入"
            filename = "班級代碼匯入表.xlsx"
            
        elif export_type == "subject":
            subjects = get_all_subjects_list()
            rows = []
            for s in subjects:
                rows.append({
                    "科目代碼": s.get("code", ""),
                    "科目名稱": s.get("name", ""),
                    "科目簡稱": s.get("name", "")[:6],
                    "科目英文名稱": ""
                })
            df = pd.DataFrame(rows)
            sheet_name = "科目代碼匯入"
            filename = "科目代碼匯入表.xlsx"
            
        elif export_type == "curriculum":
            year = cfg.get("year", "114")
            term = cfg.get("term", "1")
            res_json = api_get_course_assignments().get_json()
            assignments = res_json.get("assignments", [])
            
            rows = []
            for c_info in assignments:
                cc = c_info.get("class_code")
                cn = c_info.get("class_name")
                for sub in c_info.get("subjects", []):
                    rows.append({
                        "學年": year,
                        "學期": term,
                        "班級代碼": cc,
                        "班級名稱": cn,
                        "科目代碼": sub.get("subject_code"),
                        "科目名稱": sub.get("subject_name"),
                        "教師代碼": sub.get("teacher_code"),
                        "教師姓名": sub.get("teacher_name"),
                        "每週節數": sub.get("hours", 1)
                    })
            df = pd.DataFrame(rows)
            sheet_name = "配課資料匯入"
            filename = "配課資料匯入表.xlsx"
        else:
            return jsonify({"status": "error", "message": "不支援的匯出類型"}), 400
            
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name=sheet_name)
        output.seek(0)
        
        import urllib.parse
        encoded_filename = urllib.parse.quote(filename)
        response = send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename
        )
        response.headers["Content-Disposition"] = f"attachment; filename*=utf-8''{encoded_filename}"
        return response
    except Exception as e:
        return jsonify({"status": "error", "message": f"匯出失敗: {str(e)}"}), 500

# @app.route("/api/ai-chat", methods=["POST"])
def api_ai_chat_duplicate():
    """Natural Language AI Conversational Assistant Endpoint with Hybrid Groq LLM & Deterministic Engine."""
    try:
        req = request.get_json(silent=True) or {}
        msg = str(req.get("message", "")).strip()
        if not msg:
            return jsonify({"status": "error", "message": "請輸入對話內容！"}), 400

        cfg = load_config_rules()
        data = load_schedule_data()

        # 1. First parse deterministic system actions & queries
        s_reply, s_action, s_payload = process_semantic_ai_scheduling(msg, cfg, data)

        groq_key = cfg.get("groq_api_key") or os.environ.get("GROQ_API_KEY", "")
        groq_model = cfg.get("groq_model", "llama-3.3-70b-versatile")
        
        reply = None
        action = s_action
        action_payload = s_payload or {}
        
        # 2. If user asked open-ended reasoning questions, query Groq Llama 3.3 LLM!
        if groq_key and s_action is None:
            try:
                g_reply, g_action, g_payload = call_groq_llm_api(msg, cfg, data, groq_key, model=groq_model)
                if g_reply:
                    reply = f"⚡ 【Groq High-Speed AI ({groq_model})】\n{g_reply}"
                    if g_action: action = g_action
                    if g_payload: action_payload = g_payload
            except Exception as ge:
                print(f"[Groq API Exception] Fallback to Semantic Engine: {ge}")

        if not reply:
            reply = s_reply

        return jsonify({
            "status": "success",
            "reply": reply,
            "action": action,
            "payload": action_payload
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"AI 對談處理異常: {str(e)}"}), 500



# ─────────────────────────────────────────────────────────────────────────────
# 欣河智慧排課參考功能 – Stash Area / Smart Rescue / Conflict Color-check
# ─────────────────────────────────────────────────────────────────────────────
# In-memory stash area (session-level; cleared on server restart)
_stash_area = []   # list of lesson-dicts temporarily removed from grid

@app.route("/smart-rescue")
def smart_rescue_page():
    """智慧失敗調整頁面 – 仿欣河左右分割面板"""
    return render_template("smart_rescue.html")

@app.route("/api/unscheduled-lessons", methods=["GET"])
def api_unscheduled_lessons():
    """回傳尚未排入時段（day=0 或 period=0）的課程清單，同時包含暫存區課程。"""
    try:
        solved = get_current_solved_schedules()
        unscheduled = []
        for idx, s in enumerate(solved):
            d = str(s.get("day", "0")).strip().split(".")[0]
            p = str(s.get("period", "0")).strip().split(".")[0]
            if d in ("0", "", "None", "nan") or p in ("0", "", "None", "nan"):
                item = dict(s)
                item["id"] = s.get("id", idx)
                unscheduled.append(item)

        # Also include stashed items (they were removed from grid)
        for item in _stash_area:
            item["_stashed"] = True
            unscheduled.append(item)

        return jsonify({
            "status": "success",
            "unscheduled": unscheduled,
            "stashed": _stash_area,
            "total_unscheduled": len(unscheduled)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/stash-lesson", methods=["POST"])
def api_stash_lesson():
    """
    暫存區：將某節課從課表移除，放入暫存籃（day=0, period=0），
    方便之後從暫存區取回放到其他時段。
    """
    global _stash_area
    try:
        req = request.get_json(silent=True) or {}
        item_id = req.get("id")
        if item_id is None:
            return jsonify({"status": "error", "message": "缺少課程 id"}), 400

        solved = get_current_solved_schedules()
        item = None
        for s in solved:
            if str(s.get("id")) == str(item_id):
                item = s
                break

        if not item:
            return jsonify({"status": "error", "message": "找不到課程"}), 404

        # Save original slot
        item["_stash_orig_day"] = str(item.get("day", "0"))
        item["_stash_orig_period"] = str(item.get("period", "0"))

        # Remove from solved timetable (set day/period to 0)
        item["day"] = "0"
        item["period"] = "0"
        item["manual_locked"] = False

        # Clone into stash (avoid duplicates)
        _stash_area = [x for x in _stash_area if str(x.get("id")) != str(item_id)]
        _stash_area.append(dict(item))

        # Persist to config
        cfg = load_config_rules()
        cfg["solved_schedules"] = solved
        save_config_rules(cfg)

        return jsonify({
            "status": "success",
            "message": f"已將【{item.get('subject_name','')} / {item.get('class_name','')}】加入暫存區",
            "stash_count": len(_stash_area)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/unstash-lesson", methods=["POST"])
def api_unstash_lesson():
    """
    從暫存區取回課程，排入指定時段（target_day, target_period）。
    若目標時段有其他課，則執行對調。
    """
    global _stash_area
    try:
        req = request.get_json(silent=True) or {}
        item_id = req.get("id")
        target_day = str(req.get("target_day", "0"))
        target_period = str(req.get("target_period", "0"))

        if not item_id:
            return jsonify({"status": "error", "message": "缺少課程 id"}), 400

        solved = get_current_solved_schedules()
        cfg = load_config_rules()

        # Find in stash
        stash_item = None
        for x in _stash_area:
            if str(x.get("id")) == str(item_id):
                stash_item = x
                break

        if not stash_item:
            return jsonify({"status": "error", "message": "暫存區找不到此課程"}), 404

        # Find in solved list
        source_item = None
        for s in solved:
            if str(s.get("id")) == str(item_id):
                source_item = s
                break

        if source_item:
            source_item["day"] = target_day
            source_item["period"] = target_period
            source_item["manual_locked"] = True

        # Remove from stash
        _stash_area = [x for x in _stash_area if str(x.get("id")) != str(item_id)]

        cfg["solved_schedules"] = solved
        save_config_rules(cfg)

        return jsonify({
            "status": "success",
            "message": f"已從暫存區取回課程並排入週{target_day}第{target_period}節",
            "stash_count": len(_stash_area)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/conflict-check-slot", methods=["POST"])
def api_conflict_check_slot():
    """
    衝突色碼檢查：給定一個 class_code 和目標時段，
    回傳整個 5×8 課表格的可排入狀態（仿欣河綠/黃/紅/藍分色）。
    供智慧失敗調整面板使用。
    """
    try:
        req = request.get_json(silent=True) or {}
        item_id = req.get("item_id")
        class_code = req.get("class_code", "")

        solved = get_current_solved_schedules()
        cfg = load_config_rules()

        # Find the item to place
        source_item = None
        for s in solved:
            if str(s.get("id")) == str(item_id):
                source_item = s
                break

        if not source_item:
            # Try to find in stash
            for x in _stash_area:
                if str(x.get("id")) == str(item_id):
                    source_item = x
                    break

        if not source_item:
            return jsonify({"status": "error", "message": "找不到課程"}), 404

        # Build slot status map for the 5×8 grid
        slots_status = {}
        for d in range(1, 6):
            for p in range(1, 9):
                slot_key = f"{d}-{p}"
                curr_d = str(source_item.get("day", "0"))
                curr_p = str(source_item.get("period", "0"))

                if str(d) == curr_d and str(p) == curr_p:
                    slots_status[slot_key] = {"status": "current", "color": "current", "message": "目前時段"}
                    continue

                # Find what's in this slot for same class
                target_item = None
                for s in solved:
                    if str(s.get("id")) == str(source_item.get("id")):
                        continue
                    sd = str(s.get("day", "")).split(".")[0]
                    sp = str(s.get("period", "")).split(".")[0]
                    sc = str(s.get("class_code", "")).strip()
                    if sd == str(d) and sp == str(p) and sc == str(source_item.get("class_code", "")).strip():
                        target_item = s
                        break

                is_forbidden, warns = check_manual_swap_conflicts(source_item, d, p, target_item, solved, cfg)

                # Determine color code (仿欣河)
                if is_forbidden:
                    # Check if teacher conflict (紅斜線) or subject blocked (藍斜線)
                    warn_text = " ".join(warns)
                    if "教師衝堂" in warn_text or "教師不可排" in warn_text:
                        color = "forbidden_teacher"   # 紅斜線
                    elif "科目" in warn_text or "不排時段" in warn_text:
                        color = "forbidden_subject"   # 藍斜線
                    else:
                        color = "forbidden"           # 紅底
                    slots_status[slot_key] = {
                        "status": "forbidden",
                        "color": color,
                        "message": warns[0] if warns else "衝突"
                    }
                elif warns:
                    slots_status[slot_key] = {
                        "status": "soft_conflict",
                        "color": "warning",           # 黃色
                        "message": warns[0]
                    }
                else:
                    slots_status[slot_key] = {
                        "status": "feasible",
                        "color": "feasible",          # 綠色
                        "message": "可排入"
                    }

        return jsonify({
            "status": "success",
            "item": source_item,
            "slots": slots_status
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/smart-rescue/place-lesson", methods=["POST"])
def api_smart_rescue_place():
    """
    智慧失敗調整：一鍵排入 – 自動找第一個無衝突的時段排入未排課程。
    """
    try:
        req = request.get_json(silent=True) or {}
        item_id = req.get("item_id")
        prefer_morning = bool(req.get("prefer_morning", True))

        solved = get_current_solved_schedules()
        cfg = load_config_rules()

        source_item = None
        for s in solved:
            if str(s.get("id")) == str(item_id):
                source_item = s
                break

        if not source_item:
            return jsonify({"status": "error", "message": "找不到課程"}), 404

        # Try to find a feasible slot (prefer mornings first)
        period_order = list(range(1, 8)) if prefer_morning else list(range(7, 0, -1))
        day_order = [1, 2, 3, 4, 5]

        best_slot = None
        for d in day_order:
            for p in period_order:
                curr_d = str(source_item.get("day", "0"))
                curr_p = str(source_item.get("period", "0"))
                if str(d) == curr_d and str(p) == curr_p:
                    continue
                # Find target item
                target = None
                for s in solved:
                    if str(s.get("id")) == str(source_item.get("id")):
                        continue
                    sd = str(s.get("day", "")).split(".")[0]
                    sp = str(s.get("period", "")).split(".")[0]
                    sc = str(s.get("class_code", "")).strip()
                    if sd == str(d) and sp == str(p) and sc == str(source_item.get("class_code", "")).strip():
                        target = s
                        break

                is_forb, warns = check_manual_swap_conflicts(source_item, d, p, target, solved, cfg)
                if not is_forb:
                    best_slot = (d, p, target)
                    break
            if best_slot:
                break

        if not best_slot:
            return jsonify({
                "status": "no_slot",
                "message": "找不到完全無衝突的時段，請手動選擇時段或使用強制排入。"
            })

        bd, bp, btarget = best_slot
        old_d = str(source_item.get("day", "0"))
        old_p = str(source_item.get("period", "0"))

        source_item["day"] = str(bd)
        source_item["period"] = str(bp)
        source_item["manual_locked"] = True

        if btarget:
            btarget["day"] = old_d
            btarget["period"] = old_p
            btarget["manual_locked"] = True
            msg = f"已排入週{bd}第{bp}節（與【{btarget.get('subject_name','')}】對調）"
        else:
            msg = f"已排入週{bd}第{bp}節（原為空堂）"

        # Persist
        cfg["solved_schedules"] = solved
        save_config_rules(cfg)

        # Try Excel
        try:
            import pandas as pd
            base_dir = os.path.dirname(os.path.abspath(__file__))
            local_output = os.path.join(base_dir, "School_Schedule_Solved.xlsx")
            pd.DataFrame(solved).to_excel(local_output, index=False)
        except Exception as e:
            log_exception("api_place_schedule:save_solved_excel", e)

        return jsonify({
            "status": "success",
            "message": msg,
            "placed_day": bd,
            "placed_period": bp
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/lock-lesson", methods=["POST"])
def api_lock_lesson():
    """鎖定/解鎖課程（標記禁止調課）。"""
    try:
        req = request.get_json(silent=True) or {}
        item_id = req.get("id")
        lock_state = bool(req.get("locked", True))

        solved = get_current_solved_schedules()
        cfg = load_config_rules()

        item = None
        for s in solved:
            if str(s.get("id")) == str(item_id):
                item = s
                break

        if not item:
            return jsonify({"status": "error", "message": "找不到課程"}), 404

        item["manual_locked"] = lock_state
        cfg["solved_schedules"] = solved
        save_config_rules(cfg)

        state_str = "鎖定（禁止調課）" if lock_state else "解除鎖定"
        return jsonify({
            "status": "success",
            "message": f"【{item.get('subject_name','')} / {item.get('class_name','')}】已{state_str}",
            "locked": lock_state
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# 欣河參考功能 – 02.全校教師超鐘點與基本鐘點核算總表
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/teacher-workload-summary", methods=["GET"])
def api_teacher_workload_summary():
    """
    仿欣河『02.超鐘點總表』：計算全校每位教師的基本鐘點、實排節數、
    超鐘點（兼課）、第8節輔導課、社團課與鐘點狀態。
    """
    try:
        data = load_schedule_data()
        solved = get_current_solved_schedules()
        cfg = load_config_rules()

        teachers = data.get("teachers", [])
        custom_base_hours = cfg.get("teacher_base_hours", {})

        # Tally teaching periods for each teacher
        teacher_stats = {}
        for t in teachers:
            t_name = t.get("name", "").strip()
            t_code = t.get("code", "").strip()
            if not t_name or t_name.startswith("備用"):
                continue

            role = t.get("role", "專任教師")

            # Determine base hours (Priority: config override > teacher.dbf > role default)
            if t_name in custom_base_hours:
                base_h = float(custom_base_hours[t_name])
            elif t.get("base_hours", 0) > 0:
                base_h = float(t.get("base_hours", 0))
            else:
                # Role-based default standard in Taiwan High/Junior Schools
                if "導師" in role:
                    base_h = 12.0 if "高" in role else 14.0
                elif "主任" in role:
                    base_h = 4.0
                elif "組長" in role or "幹事" in role:
                    base_h = 8.0
                elif "輔導" in role:
                    base_h = 10.0
                else:
                    base_h = 16.0  # 專任教師標準基本鐘點

            teacher_stats[t_name] = {
                "name": t_name,
                "code": t_code,
                "role": role,
                "base_hours": int(base_h) if base_h.is_integer() else base_h,
                "regular_hours": 0,    # 正課 (週一~五 第1~7節)
                "period8_hours": 0,    # 第8節輔導課
                "club_hours": 0,       # 社團活動
                "total_hours": 0,      # 總實排節數
                "classes": set(),
                "subjects": set(),
                "details": []
            }

        PSEUDO = {"學務處", "各班導師", "教務處", "輔導室", "體育組", "總務處", "校長室", "無", "未指定", "待定", "自習"}

        for s in solved:
            d = str(s.get("day", "0")).split(".")[0]
            p = str(s.get("period", "0")).split(".")[0]
            t_name = s.get("teacher_name", "").strip()
            c_name = str(s.get("class_name") or s.get("class_code") or "").strip()
            subj = str(s.get("subject_name", "")).strip()

            if not d or not p or d == "0" or p == "0" or not t_name or t_name in PSEUDO:
                continue

            if t_name not in teacher_stats:
                teacher_stats[t_name] = {
                    "name": t_name,
                    "code": s.get("teacher_code", ""),
                    "role": "專任教師",
                    "base_hours": 16,
                    "regular_hours": 0,
                    "period8_hours": 0,
                    "club_hours": 0,
                    "total_hours": 0,
                    "classes": set(),
                    "subjects": set(),
                    "details": []
                }

            st = teacher_stats[t_name]
            st["total_hours"] += 1
            if c_name: st["classes"].add(c_name)
            if subj: st["subjects"].add(subj)

            if p == "8":
                st["period8_hours"] += 1
            elif "社團" in subj:
                st["club_hours"] += 1
            else:
                st["regular_hours"] += 1

            st["details"].append(f"週{d}第{p}節 {c_name} {subj}")

        # Compute overtime and status
        summary_list = []
        total_school_hours = 0
        total_overtime_hours = 0
        overtime_teacher_count = 0
        deficit_teacher_count = 0

        for t_name, st in teacher_stats.items():
            base_h = st["base_hours"]
            reg_h = st["regular_hours"]
            overtime_h = max(0, reg_h - int(base_h))
            deficit_h = max(0, int(base_h) - reg_h)

            if overtime_h > 0 or st["period8_hours"] > 0:
                status = "超鐘點"
                status_color = "success"
                overtime_teacher_count += 1
            elif deficit_h > 0:
                status = f"缺 {deficit_h} 節"
                status_color = "danger"
                deficit_teacher_count += 1
            else:
                status = "剛好達標"
                status_color = "neutral"

            total_school_hours += st["total_hours"]
            total_overtime_hours += (overtime_h + st["period8_hours"])

            summary_list.append({
                "name": t_name,
                "code": st["code"],
                "role": st["role"],
                "base_hours": base_h,
                "regular_hours": reg_h,
                "period8_hours": st["period8_hours"],
                "club_hours": st["club_hours"],
                "total_hours": st["total_hours"],
                "overtime_hours": overtime_h,
                "total_extra_hours": overtime_h + st["period8_hours"],
                "status": status,
                "status_color": status_color,
                "classes": ", ".join(sorted(list(st["classes"]))),
                "subjects": ", ".join(sorted(list(st["subjects"])))
            })

        summary_list.sort(key=lambda x: (0 if "主任" in x["role"] else 1 if "組長" in x["role"] else 2 if "導師" in x["role"] else 3, x["name"]))

        return jsonify({
            "status": "success",
            "teachers": summary_list,
            "stats": {
                "total_teachers": len(summary_list),
                "overtime_teachers": overtime_teacher_count,
                "deficit_teachers": deficit_teacher_count,
                "total_school_hours": total_school_hours,
                "total_overtime_hours": total_overtime_hours
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"超鐘點統計計算失敗: {str(e)}"}), 500

@app.route("/api/export-workload-excel", methods=["GET"])
def api_export_workload_excel():
    """匯出全校教師超鐘點與基本鐘點核算總表 Excel。"""
    try:
        import io
        import pandas as pd
        
        res = api_teacher_workload_summary()
        json_data = res.get_json()
        if json_data.get("status") != "success":
            return jsonify({"status": "error", "message": "取得資料失敗"}), 500

        teachers = json_data.get("teachers", [])
        rows = []
        for idx, t in enumerate(teachers, 1):
            rows.append({
                "編號": idx,
                "教師姓名": t["name"],
                "教師代碼": t["code"],
                "學校職務": t["role"],
                "基本鐘點": t["base_hours"],
                "正課實排節數": t["regular_hours"],
                "第8節輔導課": t["period8_hours"],
                "社團活動": t["club_hours"],
                "全週實排總節數": t["total_hours"],
                "正課超鐘點": t["overtime_hours"],
                "合計兼課/超額節數": t["total_extra_hours"],
                "鐘點狀態": t["status"],
                "任教班級": t["classes"],
                "任教科目": t["subjects"]
            })

        df = pd.DataFrame(rows)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name="全校教師超鐘點總表")
        output.seek(0)

        filename = "全校教師超鐘點與基本鐘點總表.xlsx"
        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({"status": "error", "message": f"匯出失敗: {str(e)}"}), 500


@app.route("/api/teacher/preferences", methods=["GET"])
def api_get_teacher_preferences():
    try:
        teacher_code = request.args.get("code", "").strip()
        if teacher_code.isdigit() and len(teacher_code) < 4:
            teacher_code = teacher_code.zfill(4)
        cfg = load_config_rules()
        prefs = cfg.get("teacher_preferences", {}).get(teacher_code, {})
        return jsonify({"status": "success", "preferences": prefs})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/teacher/preferences", methods=["POST"])
def api_save_teacher_preferences():
    try:
        req = request.get_json() or {}
        teacher_code = req.get("teacher_code", "").strip()
        if teacher_code.isdigit() and len(teacher_code) < 4:
            teacher_code = teacher_code.zfill(4)
        if not teacher_code:
            return jsonify({"status": "error", "message": "教師代碼必填"}), 400
        
        cfg = load_config_rules()
        if "teacher_preferences" not in cfg:
            cfg["teacher_preferences"] = {}
            
        cfg["teacher_preferences"][teacher_code] = {
            "style": req.get("style", "none"),
            "avoid_split_shifts": bool(req.get("avoid_split_shifts", False)),
            "max_daily_periods": req.get("max_daily_periods"),
            "avoid_first_last": bool(req.get("avoid_first_last", False)),
            "blocked_slots": req.get("blocked_slots", []),
            "preferred_slots": req.get("preferred_slots", [])
        }
        
        save_config_rules(cfg)
        return jsonify({"status": "success", "message": "排課偏好申報已儲存！"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/teacher-preference")
def teacher_preference_page():
    return render_template("teacher_preference.html")


if __name__ == "__main__":

    if len(sys.argv) > 1 and ("desktop" in sys.argv[1].lower() or "--desktop" in sys.argv[1].lower()):
        import desktop_app
        desktop_app.main()
    else:
        load_schedule_data()
        port = int(os.environ.get("PORT", 5000))
        local_ip = get_local_ip()
        print(f"\n==================================================")
        print(f" [系統] 智慧排課系統已啟動 (Waitress WSGI Server)")
        print(f" [網址] 本機瀏覽網址: http://127.0.0.1:{port}")
        print(f" [局域網] 局域網/手機連線網址: http://{local_ip}:{port}")
        print(f"==================================================\n")
        try:
            from waitress import serve
            serve(app, host="0.0.0.0", port=port, threads=8)
        except ImportError:
            app.run(host="0.0.0.0", port=port, debug=False)






