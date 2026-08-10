import os
import sys
from flask import Flask, jsonify, render_template, send_from_directory, send_file, request
from dbfread import DBF

app = Flask(__name__, static_folder="static", template_folder="templates")

# Path configuration
SEARCH_DIR = r"D:\土城高中"

# Global cache variables
_cached_data = None
_db_mtimes = {}

def get_latest_dbf_dir():
    """Finds the newest spv*.wdb directory inside SEARCH_DIR containing the DBF folder."""
    if not os.path.exists(SEARCH_DIR):
        local_dbf = os.path.join(os.path.dirname(__file__), "dbf_data")
        if os.path.isdir(local_dbf):
            return local_dbf
        return None
    
    candidates = []
    for name in os.listdir(SEARCH_DIR):
        path = os.path.join(SEARCH_DIR, name)
        if os.path.isdir(path) and name.lower().startswith("spv") and name.lower().endswith(".wdb"):
            dbf_path = os.path.join(path, "SPV2000", "SPV2000", "DBF")
            if os.path.isdir(dbf_path):
                candidates.append((path, dbf_path))
                
    if not candidates:
        return None
    
    candidates.sort(key=lambda x: os.path.basename(x[0]), reverse=True)
    return candidates[0][1]

def load_schedule_data():
    """Loads all schedule data from DBF files and caches it."""
    global _cached_data, _db_mtimes
    
    dbf_dir = get_latest_dbf_dir()
    if not dbf_dir:
        return {"error": "No SPV2000 DBF directory found in D:\\土城高中"}
    
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
        db_clatime = DBF(resolved_paths["clatime"], ignore_missing_memofile=True)
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
        db_class = DBF(resolved_paths["class"], ignore_missing_memofile=True)
        classes = []
        for r in db_class:
            classes.append({
                "code": r.get("CLASS_NO", "").strip(),
                "name": r.get("CLASS_NAME", "").strip(),
                "tutor": r.get("SHOW_TEA", "").strip() if r.get("SHOW_TEA") else ""
            })
        classes.sort(key=lambda x: x["code"])

        # 3. Parse teacher.dbf
        db_teacher = DBF(resolved_paths["teacher"], ignore_missing_memofile=True)
        teachers = []
        # Build code normalization map: short code (e.g. '28') -> full padded code (e.g. '0028')
        teacher_code_map = {}
        for r in db_teacher:
            t_name = r.get("TEACH_NAME", "").strip()
            full_code = r.get("TEACHER_NO", "").strip()
            if full_code:
                # Map both the stripped integer form and the full padded form to the canonical full_code
                teacher_code_map[str(int(full_code))] = full_code
                teacher_code_map[full_code] = full_code
            # Filter out backup or empty teachers
            if t_name and not t_name.startswith("備用"):
                teachers.append({
                    "code": full_code,
                    "name": t_name,
                    "role": r.get("TEACH_KINA", "").strip() if r.get("TEACH_KINA") else ""
                })
        teachers.sort(key=lambda x: x["name"])

        # 4. Load schedules (either from solved Excel or from claspv.dbf fallback)
        solved_excel = r"D:\土城高中\School_Schedule_Solved.xlsx"
        if not os.path.exists(solved_excel) or not os.path.exists(r"D:\土城高中"):
            solved_excel = os.path.join(os.path.dirname(__file__), "School_Schedule_Solved.xlsx")
            
        schedules = []
        classrooms = {}
        
        if os.path.exists(solved_excel):
            import pandas as pd
            df = pd.read_excel(solved_excel)
            df = df.fillna("")
            for idx, r in df.iterrows():
                class_code = str(r.get("班級代碼", "")).strip().split(".")[0]
                class_name = str(r.get("班級名稱", "")).strip()
                subject_code = str(r.get("科目代碼", "")).strip().split(".")[0]
                subject_name = str(r.get("科目名稱", "")).strip()
                
                teacher_code = str(r.get("教師代碼", "")).strip().split(".")[0]
                if teacher_code.replace(".0", "") == "nan" or teacher_code.lower() == "nan":
                    teacher_code = ""
                # Normalize teacher code to padded format matching teacher.dbf
                if teacher_code:
                    teacher_code = teacher_code_map.get(teacher_code, teacher_code)
                teacher_name = str(r.get("教師姓名", "")).strip()
                if teacher_name.lower() == "nan":
                    teacher_name = ""
                    
                room_name = str(r.get("教室名稱", "")).strip()
                if room_name.lower() == "nan":
                    room_name = ""
                room_code = room_name
                
                day = str(r.get("星期", "")).strip().split(".")[0]
                period = str(r.get("節次", "")).strip().split(".")[0]
                
                try:
                    week_mode = int(float(r.get("週別設定", 0)))
                except:
                    week_mode = 0
                    
                try:
                    ud = int(float(r.get("上下修", 0)))
                except:
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
            db_claspv = DBF(resolved_paths["claspv"], ignore_missing_memofile=True)
            for idx, r in enumerate(db_claspv):
                class_code = r.get("班級", "").strip()
                class_name = r.get("班級名稱", "").strip()
                subject_code = r.get("科目", "").strip()
                subject_name = r.get("科目名稱", "").strip()
                teacher_code = r.get("教師", "").strip()
                # Normalize to padded format matching teacher.dbf codes
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

@app.route("/api/metadata")
def api_metadata():
    data = load_schedule_data()
    if "error" in data:
        return jsonify(data), 500
    
    return jsonify({
        "classes": data["classes"],
        "teachers": data["teachers"],
        "classrooms": data["classrooms"],
        "period_times": data["period_times"],
        "dbf_dir": data["dbf_dir"]
    })

@app.route("/api/schedule/class/<class_code>")
def api_schedule_class(class_code):
    data = load_schedule_data()
    if "error" in data:
        return jsonify(data), 500
        
    slots = [s for s in data["schedules"] if s["class_code"] == class_code]
    return jsonify(slots)

@app.route("/api/schedule/teacher/<teacher_code>")
def api_schedule_teacher(teacher_code):
    data = load_schedule_data()
    if "error" in data:
        return jsonify(data), 500
        
    slots = [s for s in data["schedules"] if s["teacher_code"] == teacher_code]
    return jsonify(slots)

@app.route("/api/schedule/room/<room_code>")
def api_schedule_room(room_code):
    data = load_schedule_data()
    if "error" in data:
        return jsonify(data), 500
        
    slots = [s for s in data["schedules"] if s["room_code"] == room_code]
    return jsonify(slots)

@app.route("/api/run-solver")
def api_run_solver():
    import solve_schedule
    # Force reload of solve_schedule module in case it was edited
    import importlib
    importlib.reload(solve_schedule)
    try:
        res = solve_schedule.run_solver()
        return jsonify(res)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/validate-solver")
def api_validate_solver():
    import pandas as pd
    try:
        excel_path = r"D:\土城高中\School_Schedule_Solved.xlsx"
        if not os.path.exists(excel_path):
            return jsonify({"status": "error", "message": "Solved file not found"})
        df = pd.read_excel(excel_path)
        
        # Load tables for validation
        dbf_dir = get_latest_dbf_dir()
        db_no_teach = list(DBF(os.path.join(dbf_dir, "no_teach.dbf"), ignore_missing_memofile=True))
        db_no_sub = list(DBF(os.path.join(dbf_dir, "no_sub.dbf"), ignore_missing_memofile=True))
        db_class = list(DBF(os.path.join(dbf_dir, "class.dbf"), ignore_missing_memofile=True))
        
        virtual_class_codes = set()
        for r in db_class:
            if r.get("虛擬班") or "跨班" in r.get("CLASS_NAME", ""):
                virtual_class_codes.add(r.get("CLASS_NO", "").strip())
                
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
            t = str(r.get("教師代碼", "")).strip() if not pd.isna(r.get("教師代碼")) else ""
            c = str(r.get("班級代碼", "")).strip() if not pd.isna(r.get("班級代碼")) else ""
            wm_val = r.get("週別設定")
            wm = int(wm_val) if not pd.isna(wm_val) else 0
            desc = str(r.get("說明", "")).strip()
            if pd.isna(r.get("說明")):
                desc = ""
            
            if t and t != "nan":
                if t not in teacher_slots:
                    teacher_slots[t] = []
                for ext in teacher_slots[t]:
                    if ext["day"] == d and ext["period"] == p:
                        if wm == 0 or ext["week"] == 0 or wm == ext["week"]:
                            if desc == "(同時上課)" and ext["desc"] == "(同時上課)":
                                continue
                            detail.append(f"[Teacher Conflict]: Teacher {r.get('教師姓名')} ({t}) has overlapping classes in slot {d}-{p}!")
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
                            detail.append(f"[Class Conflict]: Class {r.get('班級名稱')} ({c}) has overlapping lessons in slot {d}-{p}! Sub: {r.get('科目名稱')} vs {ext['subject_name']}")
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
                    rule_t = rule['TEACHER_NO'].strip()
                    if rule_t == t_code:
                        if rule['START_DAY'] <= d <= rule['END_DAY'] and rule['START_SEC'] <= p <= rule['END_SEC']:
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
                    rule_c = rule['CLASS_NO'].strip()
                    rule_s = rule['SUBJECT_NO'].strip()
                    if rule_c == c_code and rule_s == s_code:
                        if rule['START_DAY'] <= d <= rule['END_DAY'] and rule['START_SEC'] <= p <= rule['END_SEC']:
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
        claspv_base = list(DBF(os.path.join(dbf_dir, "claspv_base.dbf"), ignore_missing_memofile=True))
        
        class_102_1_1 = []
        teach_0010_1_1 = []
        for r in claspv_base:
            c = r.get("班級", "").strip()
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
        excel_path = r"D:\土城高中\School_Schedule_Solved.xlsx"
        if not os.path.exists(excel_path):
            return jsonify({"status": "error", "message": "Solved file not found"})
        import pandas as pd
        df = pd.read_excel(excel_path)
        
        class_102_1_1 = []
        teach_0010_1_1 = []
        for idx, r in df.iterrows():
            c = str(r.get("班級代碼", "")).strip()
            t = str(r.get("教師代碼", "")).strip()
            d = str(r.get("星期", "")).strip()
            p = str(r.get("節次", "").strip() if isinstance(r.get("節次"), str) else str(int(r.get("節次"))) if not pd.isna(r.get("節次")) else "")
            
            # Convert values to strings for JSON serializability
            rec = {k: str(v) for k, v in r.items()}
            
            # Note: in pandas, numeric 1.0 gets read, so check '1' or '1.0'
            d_clean = str(int(float(d))) if d and d != "nan" else ""
            p_clean = str(int(float(p))) if p and p != "nan" else ""
            
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
        dbf_dir = get_latest_dbf_dir()
        claspv_base = list(DBF(os.path.join(dbf_dir, "claspv_base.dbf"), ignore_missing_memofile=True))
        
        math_records = []
        for r in claspv_base:
            c = r.get("班級", "").strip()
            s = r.get("科目", "").strip()
            if c == '102' and s == '301':
                math_records.append({k: str(v) for k, v in r.items()})
                
        return jsonify(math_records)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/debug-teacher-slots")
def api_debug_teacher_slots():
    try:
        dbf_dir = get_latest_dbf_dir()
        claspv_base = list(DBF(os.path.join(dbf_dir, "claspv_base.dbf"), ignore_missing_memofile=True))
        no_teach = list(DBF(os.path.join(dbf_dir, "no_teach.dbf"), ignore_missing_memofile=True))
        db_class = list(DBF(os.path.join(dbf_dir, "class.dbf"), ignore_missing_memofile=True))
        
        virtual_class_codes = set()
        for r in db_class:
            if r.get("虛擬班") or "跨班" in r.get("CLASS_NAME", ""):
                virtual_class_codes.add(r.get("CLASS_NO", "").strip())
                
        # Prefilled slots for classes
        class_prefilled = {}
        for r in claspv_base:
            c = r.get("班級", "").strip()
            d = r.get("星期", "").strip()
            p = r.get("節次", "").strip()
            if c and d and p:
                if c not in class_prefilled:
                    class_prefilled[c] = set()
                class_prefilled[c].add((int(d), int(p)))
                
        # Blocked slots for teachers
        teacher_blocked = {}
        for rule in no_teach:
            t = rule['TEACHER_NO'].strip()
            if t:
                if t not in teacher_blocked:
                    teacher_blocked[t] = set()
                sd = rule['START_DAY']
                ed = rule['END_DAY']
                ss = rule['START_SEC']
                es = rule['END_SEC']
                for d in range(sd, ed + 1):
                    for p in range(ss, es + 1):
                        teacher_blocked[t].add((d, p))
                        
        # Check each teacher's dynamic items
        teacher_report = []
        for t_code in sorted(list(set(r.get("教師", "").strip() for r in claspv_base if r.get("教師", "").strip()))):
            t_items = [r for r in claspv_base if r.get("教師", "").strip() == t_code and (not r.get("星期", "").strip() or not r.get("節次", "").strip())]
            if not t_items:
                continue
                
            # Group by sim_group or cross_class_key (representative) to get unique dynamic slots needed
            unique_dynamic_needed = len(set(r.get("同時群", "").strip() if r.get("同時群", "").strip() else r.get("班級", "").strip() + "_" + r.get("科目", "").strip() for r in t_items))
            
            # Find which slots are available for the teacher
            t_blocked = teacher_blocked.get(t_code, set())
            
            # Find the union of class blocked slots for the classes this teacher teaches
            classes_taught = set(r.get("班級", "").strip() for r in t_items if r.get("班級", "").strip())
            
            # Find slots where at least one of the classes taught is prefilled (busy)
            # Wait, if a teacher teaches multiple classes (not combined), then for a specific lesson, 
            # only THAT class needs to be free.
            # But if the teacher only has a few available slots, and those slots are busy for the classes she teaches:
            # Let's count how many slots in the 5x8 grid are:
            # 1. Not blocked for the teacher
            # 2. Not prefilled for the class of the lesson
            # For each lesson (item), count its candidate slots
            item_candidate_slots = []
            for r in t_items:
                c = r.get("班級", "").strip()
                # If virtual class, it is always free
                c_pref = class_prefilled.get(c, set()) if c not in virtual_class_codes else set()
                
                candidates = 0
                for d in range(1, 6):
                    for p in range(1, 9):
                        if (d, p) not in t_blocked and (d, p) not in c_pref:
                            candidates += 1
                item_candidate_slots.append({
                    "sub": r.get("科目名稱", "").strip(),
                    "class": r.get("班級名稱", "").strip(),
                    "candidates": candidates
                })
                
            teacher_report.append({
                "teacher": t_items[0].get("教師名稱", "").strip(),
                "code": t_code,
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
        dbf_dir = get_latest_dbf_dir()
        claspv_base = list(DBF(os.path.join(dbf_dir, "claspv_base.dbf"), ignore_missing_memofile=True))
        no_teach = list(DBF(os.path.join(dbf_dir, "no_teach.dbf"), ignore_missing_memofile=True))
        db_class = list(DBF(os.path.join(dbf_dir, "class.dbf"), ignore_missing_memofile=True))
        
        virtual_class_codes = set()
        for r in db_class:
            if r.get("虛擬班") or "跨班" in r.get("CLASS_NAME", ""):
                virtual_class_codes.add(r.get("CLASS_NO", "").strip())
                
        # Prefilled slots for classes
        class_prefilled = {}
        for r in claspv_base:
            c = r.get("班級", "").strip()
            d = r.get("星期", "").strip()
            p = r.get("節次", "").strip()
            if c and d and p:
                if c not in class_prefilled:
                    class_prefilled[c] = set()
                class_prefilled[c].add((int(d), int(p)))
                
        # Blocked slots for teachers
        teacher_blocked = {}
        for rule in no_teach:
            t = rule['TEACHER_NO'].strip()
            if t:
                if t not in teacher_blocked:
                    teacher_blocked[t] = set()
                sd = rule['START_DAY']
                ed = rule['END_DAY']
                ss = rule['START_SEC']
                es = rule['END_SEC']
                for d in range(sd, ed + 1):
                    for p in range(ss, es + 1):
                        teacher_blocked[t].add((d, p))
                        
        teacher_bottlenecks = []
        for t_code in sorted(list(set(r.get("教師", "").strip() for r in claspv_base if r.get("教師", "").strip()))):
            t_items = [r for r in claspv_base if r.get("教師", "").strip() == t_code and (not r.get("星期", "").strip() or not r.get("節次", "").strip())]
            if not t_items:
                continue
                
            unique_dynamic_needed = len(set(r.get("同時群", "").strip() if r.get("同時群", "").strip() else r.get("班級", "").strip() + "_" + r.get("科目", "").strip() for r in t_items))
            t_blocked = teacher_blocked.get(t_code, set())
            
            # Find the intersection of candidate slots for all items of this teacher
            # If a teacher has multiple dynamic items, they must be scheduled at DIFFERENT times (teacher conflicts).
            # So the total number of unique candidate slots available for the teacher's dynamic items 
            # must be at least the number of unique dynamic slots needed!
            # What are the unique candidate slots for the teacher?
            # Any slot (d, p) that is:
            # - Not blocked for the teacher
            # - And for AT LEAST ONE of the items of this teacher, the class is not prefilled.
            # Wait, if a teacher teaches class C1 and C2, a slot is a candidate for C1 if C1 is free, and for C2 if C2 is free.
            # So the slot is a candidate for the teacher if she can schedule *some* lesson there.
            # But the total number of available slots for the teacher's lessons is the union of candidate slots across all her lessons.
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
            
            t_name = t_items[0].get("教師名稱", "").strip()
            
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
        claspv_base = list(DBF(os.path.join(dbf_dir, "claspv_base.dbf"), ignore_missing_memofile=True))
        
        records = []
        for r in claspv_base:
            c = r.get("班級", "").strip()
            if c == '401':
                records.append({k: str(v) for k, v in r.items()})
                
        return jsonify(records)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/debug-class")
def api_debug_class():
    try:
        dbf_dir = get_latest_dbf_dir()
        db_class = list(DBF(os.path.join(dbf_dir, "class.dbf"), ignore_missing_memofile=True))
        records = [{k: str(v) for k, v in r.items()} for r in db_class]
        return jsonify(records)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/check-file-time")
def api_check_file_time():
    try:
        excel_path = r"D:\土城高中\School_Schedule_Solved.xlsx"
        if not os.path.exists(excel_path) or not os.path.exists(r"D:\土城高中"):
            excel_path = os.path.join(os.path.dirname(__file__), "School_Schedule_Solved.xlsx")
            
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
        excel_path = r"D:\土城高中\School_Schedule_Solved.xlsx"
        if not os.path.exists(excel_path) or not os.path.exists(r"D:\土城高中"):
            excel_path = os.path.join(os.path.dirname(__file__), "School_Schedule_Solved.xlsx")
            
        if not os.path.exists(excel_path):
            return jsonify({"status": "error", "message": "Solved schedule file not found. Please run the solver first."}), 404
            
        return send_file(excel_path, as_attachment=True, download_name="School_Schedule_Solved.xlsx")
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/check-swap-slots/<int:item_id>")
def api_check_swap_slots(item_id):
    try:
        data = load_schedule_data()
        if "error" in data:
            return jsonify(data), 500
            
        schedules = data["schedules"]
        item = None
        for s in schedules:
            if s["id"] == item_id:
                item = s
                break
                
        if not item:
            return jsonify({"status": "error", "message": "Course item not found"}), 404
            
        dbf_dir = get_latest_dbf_dir()
        db_no_teach = list(DBF(os.path.join(dbf_dir, "no_teach.dbf"), ignore_missing_memofile=True))
        db_no_sub = list(DBF(os.path.join(dbf_dir, "no_sub.dbf"), ignore_missing_memofile=True))
        
        teacher_blocked = set()
        t_code = item["teacher_code"]
        if t_code:
            for rule in db_no_teach:
                if rule.get("TEACHER_NO", "").strip() == t_code:
                    sd = rule.get("START_DAY", 1)
                    ed = rule.get("END_DAY", 1)
                    ss = rule.get("START_SEC", 1)
                    es = rule.get("END_SEC", 1)
                    for d in range(sd, ed + 1):
                        for p in range(ss, es + 1):
                            teacher_blocked.add((d, p))
                            
        class_sub_blocked = set()
        c_code = item["class_code"]
        s_code = item["subject_code"]
        if c_code and s_code:
            for rule in db_no_sub:
                if rule.get("CLASS_NO", "").strip() == c_code and rule.get("SUBJECT_NO", "").strip() == s_code:
                    sd = rule.get("START_DAY", 1)
                    ed = rule.get("END_DAY", 1)
                    ss = rule.get("START_SEC", 1)
                    es = rule.get("END_SEC", 1)
                    for d in range(sd, ed + 1):
                        for p in range(ss, es + 1):
                            class_sub_blocked.add((d, p))
                            
        slots_status = {}
        for d in range(1, 6):
            for p in range(1, 9):
                slot_key = f"{d}-{p}"
                
                if item["day"] == str(d) and item["period"] == str(p):
                    slots_status[slot_key] = {"status": "current", "message": "目前時段"}
                    continue
                    
                t_conflicts = []
                if t_code:
                    for s in schedules:
                        if s["id"] != item_id and s["teacher_code"] == t_code and s["day"] == str(d) and s["period"] == str(p):
                            t_conflicts.append(s)
                            
                c_conflicts = []
                if c_code:
                    for s in schedules:
                        if s["id"] != item_id and s["class_code"] == c_code and s["day"] == str(d) and s["period"] == str(p):
                            c_conflicts.append(s)
                            
                if t_conflicts or c_conflicts:
                    reasons = []
                    for s in t_conflicts:
                        reasons.append(f"教師衝堂：與 {s['class_name']} 班 {s['subject_name']} 衝堂")
                    for s in c_conflicts:
                        reasons.append(f"班級衝堂：與 {s['subject_name']} ({s['teacher_name']}) 衝堂")
                    slots_status[slot_key] = {
                        "status": "forbidden",
                        "message": " / ".join(reasons)
                    }
                elif (d, p) in teacher_blocked:
                    slots_status[slot_key] = {
                        "status": "soft_conflict",
                        "message": "教師不排課時段"
                    }
                elif (d, p) in class_sub_blocked:
                    slots_status[slot_key] = {
                        "status": "soft_conflict",
                        "message": "科目禁止排課時段"
                    }
                else:
                    slots_status[slot_key] = {
                        "status": "feasible",
                        "message": "完全可行"
                    }
                    
        return jsonify({
            "item": item,
            "slots": slots_status
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/execute-swap", methods=["POST"])
def api_execute_swap():
    try:
        req_data = request.get_json()
        source_id = int(req_data.get("source_id"))
        target_day = req_data.get("target_day")
        target_period = req_data.get("target_period")
        target_id = req_data.get("target_id")
        if target_id is not None:
            target_id = int(target_id)
            
        solved_excel = r"D:\土城高中\School_Schedule_Solved.xlsx"
        if not os.path.exists(solved_excel) or not os.path.exists(r"D:\土城高中"):
            solved_excel = os.path.join(os.path.dirname(__file__), "School_Schedule_Solved.xlsx")
            
        if not os.path.exists(solved_excel):
            data = load_schedule_data()
            if "error" in data:
                return jsonify(data), 500
            import pandas as pd
            records = []
            for s in data["schedules"]:
                records.append({
                    "班級代碼": s["class_code"],
                    "科目代碼": s["subject_code"],
                    "教師代碼": s["teacher_code"],
                    "班級名稱": s["class_name"],
                    "科目名稱": s["subject_name"],
                    "教師姓名": s["teacher_name"],
                    "教室名稱": s["room_name"],
                    "時間代碼": f"{s['day']}{s['period']}{s['week_mode']}{s['ud']}",
                    "星期": int(s["day"]),
                    "節次": int(s["period"]),
                    "週別設定": s["week_mode"],
                    "說明": ""
                })
            df = pd.DataFrame(records)
            df.to_excel(solved_excel, index=False)
            
        import pandas as pd
        df = pd.read_excel(solved_excel)
        df = df.fillna("")
        
        if source_id < 0 or source_id >= len(df):
            return jsonify({"status": "error", "message": "Source item index out of bounds"}), 400
            
        if target_id is not None:
            if target_id < 0 or target_id >= len(df):
                return jsonify({"status": "error", "message": "Target item index out of bounds"}), 400
                
            day_a = df.loc[source_id, "星期"]
            period_a = df.loc[source_id, "節次"]
            
            df.loc[source_id, "星期"] = df.loc[target_id, "星期"]
            df.loc[source_id, "節次"] = df.loc[target_id, "節次"]
            df.loc[source_id, "時間代碼"] = f"{df.loc[target_id, '星期']}{df.loc[target_id, '節次']}{df.loc[source_id, '週別設定']}0"
            df.loc[source_id, "說明"] = "手排課 (鎖定)"
            
            df.loc[target_id, "星期"] = day_a
            df.loc[target_id, "節次"] = period_a
            df.loc[target_id, "時間代碼"] = f"{day_a}{period_a}{df.loc[target_id, '週別設定']}0"
            df.loc[target_id, "說明"] = "手排課 (鎖定)"
        else:
            df.loc[source_id, "星期"] = int(target_day)
            df.loc[source_id, "節次"] = int(target_period)
            df.loc[source_id, "時間代碼"] = f"{target_day}{target_period}{df.loc[source_id, '週別設定']}0"
            df.loc[source_id, "說明"] = "手排課 (鎖定)"
            
        df.to_excel(solved_excel, index=False)
        
        global _cached_data
        _cached_data = None
        
        return jsonify({"status": "success", "message": "課表調整完成並已自動鎖定保護！"})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    load_schedule_data()
    app.run(host="127.0.0.1", port=5000, debug=True)
