import os
import sys
import json
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
        local_dbf = os.path.join(os.path.dirname(__file__), "dbf_data")
        if os.path.isdir(local_dbf):
            return local_dbf
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
        classes.sort(key=lambda x: x["code"])

        # 3. Parse teacher.dbf
        db_teacher = DBF(resolved_paths["teacher"], ignore_missing_memofile=True, encoding='cp950')
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
            db_claspv = DBF(resolved_paths["claspv"], ignore_missing_memofile=True, encoding='cp950')
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
        excel_path = r"D:\土城高中\School_Schedule_Solved.xlsx"
        if not os.path.exists(excel_path):
            return jsonify({"status": "error", "message": "Solved file not found"})
        df = pd.read_excel(excel_path)
        
        # Load tables for validation
        dbf_dir = get_latest_dbf_dir()
        db_no_teach = list(DBF(os.path.join(dbf_dir, "no_teach.dbf"), ignore_missing_memofile=True, encoding='cp950'))
        db_no_sub = list(DBF(os.path.join(dbf_dir, "no_sub.dbf"), ignore_missing_memofile=True, encoding='cp950'))
        db_class = list(DBF(os.path.join(dbf_dir, "class.dbf"), ignore_missing_memofile=True, encoding='cp950'))
        
        virtual_class_codes = set()
        for r in db_class:
            if r.get("虛擬") or "跨班" in r.get("CLASS_NAME", ""):
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
        excel_path = r"D:\土城高中\School_Schedule_Solved.xlsx"
        if not os.path.exists(excel_path):
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
        claspv_base = list(DBF(os.path.join(dbf_dir, "claspv_base.dbf"), ignore_missing_memofile=True, encoding='cp950'))
        
        math_records = []
        for r in claspv_base:
            c = r.get("?剔?", "").strip()
            t = str(r.get("教師姓名", "")).strip() if not pd.isna(r.get("教師姓名")) else ""
            if c == '102' and s == '301':
                math_records.append({k: str(v) for k, v in r.items()})
                
        return jsonify(math_records)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/debug-teacher-slots")
def api_debug_teacher_slots():
    try:
        dbf_dir = get_latest_dbf_dir()
        claspv_base = list(DBF(os.path.join(dbf_dir, "claspv_base.dbf"), ignore_missing_memofile=True, encoding='cp950'))
        no_teach = list(DBF(os.path.join(dbf_dir, "no_teach.dbf"), ignore_missing_memofile=True, encoding='cp950'))
        db_class = list(DBF(os.path.join(dbf_dir, "class.dbf"), ignore_missing_memofile=True, encoding='cp950'))
        
        virtual_class_codes = set()
        for r in db_class:
            if r.get("虛擬") or "跨班" in r.get("CLASS_NAME", ""):
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
              
        # Group dynamic items by teacher
        teacher_groups = {}
        for r in claspv_base:
            w = str(r.get("星期", "")).strip() if not pd.isna(r.get("星期")) else ""
            s = str(r.get("節次", "")).strip() if not pd.isna(r.get("節次")) else ""
            if not w and not s:
                t = r.get("教師", "").strip()
                if t:
                    if t not in teacher_groups:
                        teacher_groups[t] = []
                    teacher_groups[t].append(r)
                    
        # Check each teacher's dynamic items
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
                    "subject": r.get("科目名稱", "").strip(),
                    "candidates": candidates
                })
                
            t_name = t_items[0].get("教師名稱", "").strip()
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
        dbf_dir = get_latest_dbf_dir()
        claspv_base = list(DBF(os.path.join(dbf_dir, "claspv_base.dbf"), ignore_missing_memofile=True, encoding='cp950'))
        no_teach = list(DBF(os.path.join(dbf_dir, "no_teach.dbf"), ignore_missing_memofile=True, encoding='cp950'))
        db_class = list(DBF(os.path.join(dbf_dir, "class.dbf"), ignore_missing_memofile=True, encoding='cp950'))
        
        virtual_class_codes = set()
        for r in db_class:
            if r.get("虛擬") or "跨班" in r.get("CLASS_NAME", ""):
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
                        
        teacher_groups = {}
        for r in claspv_base:
            w = str(r.get("星期", "")).strip() if not pd.isna(r.get("星期")) else ""
            s = str(r.get("節次", "")).strip() if not pd.isna(r.get("節次")) else ""
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
            t_name = t_items[0].get("教師名稱", "").strip()
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
            
        source_d = int(item["day"])
        source_p = int(item["period"])
        t_code = item["teacher_code"]
        c_code = item["class_code"]
        s_code = item["subject_code"]
        
        # Check if source_item is part of a consecutive period on the same day
        is_consecutive = False
        consecutive_period = None
        for s in schedules:
            if s["id"] != item_id and s["class_code"] == c_code and s["subject_code"] == s_code and s["day"] == str(source_d):
                p_diff = abs(int(s["period"]) - source_p)
                if p_diff == 1:
                    is_consecutive = True
                    consecutive_period = int(s["period"])
                    break
        if is_consecutive:
            item["consecutive_hint"] = f"提示：此課與第 {consecutive_period} 節為連堂課程"

        dbf_dir = get_latest_dbf_dir()
        db_no_teach = list(DBF(os.path.join(dbf_dir, "no_teach.dbf"), ignore_missing_memofile=True, encoding='cp950'))
        db_no_sub = list(DBF(os.path.join(dbf_dir, "no_sub.dbf"), ignore_missing_memofile=True, encoding='cp950'))
        
        # Build lookup maps for no_teach and no_sub
        no_teach_map = {} # teacher_code -> set of (d, p)
        for rule in db_no_teach:
            tc = rule.get("TEACHER_NO", "").strip()
            if tc:
                if tc not in no_teach_map:
                    no_teach_map[tc] = set()
                sd = rule.get("START_DAY", 1)
                ed = rule.get("END_DAY", 1)
                ss = rule.get("START_SEC", 1)
                es = rule.get("END_SEC", 1)
                for d in range(sd, ed + 1):
                    for p in range(ss, es + 1):
                        no_teach_map[tc].add((d, p))

        no_sub_map = {} # (class_code, subject_code) -> set of (d, p)
        for rule in db_no_sub:
            cc = rule.get("CLASS_NO", "").strip()
            sc = rule.get("SUBJECT_NO", "").strip()
            if cc and sc:
                key = (cc, sc)
                if key not in no_sub_map:
                    no_sub_map[key] = set()
                sd = rule.get("START_DAY", 1)
                ed = rule.get("END_DAY", 1)
                ss = rule.get("START_SEC", 1)
                es = rule.get("END_SEC", 1)
                for d in range(sd, ed + 1):
                    for p in range(ss, es + 1):
                        no_sub_map[key].add((d, p))

        teacher_blocked = no_teach_map.get(t_code, set())
        class_sub_blocked = no_sub_map.get((c_code, s_code), set())

        slots_status = {}
        for d in range(1, 6):
            for p in range(1, 9):
                slot_key = f"{d}-{p}"
                
                if source_d == d and source_p == p:
                    slots_status[slot_key] = {"status": "current", "message": "目前時段"}
                    continue
                
                forbidden_reasons = []
                soft_reasons = []
                
                # 1. Check Source Item going to (d, p)
                if t_code:
                    for s in schedules:
                        if s["id"] != item_id and s["teacher_code"] == t_code and s["day"] == str(d) and s["period"] == str(p):
                            forbidden_reasons.append(f"教師衝堂：與 {s['class_name']} 班 {s['subject_name']} 衝堂")
                if c_code:
                    for s in schedules:
                        if s["id"] != item_id and s["class_code"] == c_code and s["day"] == str(d) and s["period"] == str(p):
                            forbidden_reasons.append(f"班級衝堂：與 {s['subject_name']} ({s['teacher_name']}) 衝堂")
                
                if (d, p) in teacher_blocked:
                    soft_reasons.append("本課教師在該時段不排課")
                if (d, p) in class_sub_blocked:
                    soft_reasons.append("本班級科目在該時段禁止排課")
                
                # 2. Two-way Swap Check: Target Item(s) at (d, p) moving back to (source_d, source_p)
                target_items = [s for s in schedules if s["id"] != item_id and s["day"] == str(d) and s["period"] == str(p) and (s["class_code"] == c_code or s["teacher_code"] == t_code)]
                for tgt in target_items:
                    tgt_t = tgt["teacher_code"]
                    tgt_c = tgt["class_code"]
                    tgt_s = tgt["subject_code"]
                    
                    if tgt_t:
                        for s in schedules:
                            if s["id"] != tgt["id"] and s["id"] != item_id and s["teacher_code"] == tgt_t and s["day"] == str(source_d) and s["period"] == str(source_p):
                                forbidden_reasons.append(f"對調衝堂：對調老師({tgt['teacher_name']})移至原時段與 {s['class_name']}衝堂")
                    if tgt_c and tgt_c != c_code:
                        for s in schedules:
                            if s["id"] != tgt["id"] and s["id"] != item_id and s["class_code"] == tgt_c and s["day"] == str(source_d) and s["period"] == str(source_p):
                                forbidden_reasons.append(f"對調衝堂：對調班級({tgt['class_name']})移至原時段衝堂")
                                
                    if (source_d, source_p) in no_teach_map.get(tgt_t, set()):
                        soft_reasons.append(f"對調警示：對調老師({tgt['teacher_name']})在原時段不排課")
                    if (source_d, source_p) in no_sub_map.get((tgt_c, tgt_s), set()):
                        soft_reasons.append(f"對調警示：對調科目({tgt['subject_name']})在原時段禁止排課")
                
                if forbidden_reasons:
                    slots_status[slot_key] = {
                        "status": "forbidden",
                        "message": " / ".join(forbidden_reasons)
                    }
                elif soft_reasons:
                    slots_status[slot_key] = {
                        "status": "soft_conflict",
                        "message": " / ".join(soft_reasons)
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

DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(__file__))
CONFIG_RULES_FILE = os.path.join(DATA_DIR, "config_rules.json")

GITHUB_REPO = os.environ.get("GITHUB_REPO", "")     # e.g. "your_username/School_Schedule"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")   # Free GitHub Personal Access Token
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

def sync_to_github_cloud(filename, content_str, commit_message="Cloud Web UI Auto Save"):
    if not GITHUB_REPO or not GITHUB_TOKEN:
        return False
    def _bg_sync():
        try:
            import urllib.request, base64
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
            req_get = urllib.request.Request(url, headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "User-Agent": "Flask-Cloud-Sync"
            })
            sha = None
            try:
                with urllib.request.urlopen(req_get) as resp:
                    res_data = json.loads(resp.read().decode('utf-8'))
                    sha = res_data.get("sha")
            except Exception:
                pass

            encoded_content = base64.b64encode(content_str.encode('utf-8')).decode('utf-8')
            payload = {
                "message": commit_message,
                "content": encoded_content,
                "branch": GITHUB_BRANCH
            }
            if sha:
                payload["sha"] = sha

            req_put = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Content-Type": "application/json",
                "User-Agent": "Flask-Cloud-Sync"
            }, method="PUT")

            with urllib.request.urlopen(req_put) as resp:
                print(f"Cloud Auto-Sync {filename} to GitHub: SUCCESS")
        except Exception as e:
            print("GitHub Cloud Sync Error:", e)

    import threading
    threading.Thread(target=_bg_sync, daemon=True).start()

def load_config_rules():
    if os.path.exists(CONFIG_RULES_FILE):
        try:
            with open(CONFIG_RULES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
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
        except Exception:
            pass
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

def save_config_rules(data):
    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    with open(CONFIG_RULES_FILE, "w", encoding="utf-8") as f:
        f.write(json_str)
    sync_to_github_cloud("config_rules.json", json_str, "Cloud Web UI Auto Save config_rules.json")

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

@app.route("/api/config-rules", methods=["GET"])
def api_get_config_rules():
    try:
        cfg = load_config_rules()
        dbf_dir = get_latest_dbf_dir()
        
        db_no_teach = list(DBF(os.path.join(dbf_dir, "no_teach.dbf"), ignore_missing_memofile=True, encoding='cp950'))
        db_no_sub = list(DBF(os.path.join(dbf_dir, "no_sub.dbf"), ignore_missing_memofile=True, encoding='cp950'))
        
        # Build teacher blocked map from DBF
        dbf_no_teach = {}
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
                            
        # Build class-subject blocked map from DBF
        dbf_no_sub = {}
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
        req = request.get_json()
        tc = req.get("teacher_code")
        slots = req.get("slots", []) # list of "d-p"
        if not tc:
            return jsonify({"status": "error", "message": "Teacher code is required"}), 400
            
        cfg = load_config_rules()
        if "custom_no_teach" not in cfg:
            cfg["custom_no_teach"] = {}
        cfg["custom_no_teach"][tc] = slots
        save_config_rules(cfg)
        return jsonify({"status": "success", "message": f"教師 {tc} 不排課設定已儲存！"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/config-rules/save-no-sub", methods=["POST"])
def api_save_no_sub():
    try:
        req = request.get_json()
        cc = req.get("class_code")
        sc = req.get("subject_code")
        slots = req.get("slots", []) # list of "d-p"
        if not cc or not sc:
            return jsonify({"status": "error", "message": "Class and Subject code are required"}), 400
            
        key = f"{cc}|{sc}"
        cfg = load_config_rules()
        if "custom_no_sub" not in cfg:
            cfg["custom_no_sub"] = {}
        cfg["custom_no_sub"][key] = slots
        save_config_rules(cfg)
        return jsonify({"status": "success", "message": f"班級 {cc} 科目 {sc} 限制時段已儲存！"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/course-assignments", methods=["GET"])
def api_get_course_assignments():
    try:
        data = load_schedule_data()
        if "error" in data:
            return jsonify(data), 500
        
        cfg = load_config_rules()
        custom_assign = cfg.get("custom_assignments", {})

        # Group by class_code
        assignments = {}
        for s in data["schedules"]:
            cc = s["class_code"]
            if not cc:
                continue
            if cc not in assignments:
                assignments[cc] = {
                    "class_code": cc,
                    "class_name": s["class_name"],
                    "subjects": {}
                }
            sc = s["subject_code"]
            key = f"{sc}"
            
            override_key = f"{cc}|{sc}"
            assigned_t_code = s["teacher_code"]
            assigned_t_name = s["teacher_name"]
            if override_key in custom_assign:
                assigned_t_code = custom_assign[override_key].get("teacher_code", assigned_t_code)
                assigned_t_name = custom_assign[override_key].get("teacher_name", assigned_t_name)

            if key not in assignments[cc]["subjects"]:
                assignments[cc]["subjects"][key] = {
                    "subject_code": sc,
                    "subject_name": s["subject_name"],
                    "teacher_code": assigned_t_code,
                    "teacher_name": assigned_t_name,
                    "hours": 1
                }
            else:
                assignments[cc]["subjects"][key]["hours"] += 1

        # Apply custom hours override if specified
        for cc, info in assignments.items():
            for sub in info["subjects"].values():
                okey = f"{cc}|{sub['subject_code']}"
                if okey in custom_assign and "hours" in custom_assign[okey]:
                    sub["hours"] = int(custom_assign[okey]["hours"])

        # Convert subjects dict to list
        res_class = []
        for cc, info in assignments.items():
            res_class.append({
                "class_code": cc,
                "class_name": info["class_name"],
                "subjects": list(info["subjects"].values())
            })
            
        # Group by teacher_code
        t_assignments = {}
        for s in data["schedules"]:
            tc = s["teacher_code"]
            if not tc:
                continue
            if tc not in t_assignments:
                t_assignments[tc] = {
                    "teacher_code": tc,
                    "teacher_name": s["teacher_name"],
                    "total_hours": 0,
                    "courses": {}
                }
            sc = s["subject_code"]
            cc = s["class_code"]
            key = f"{cc}|{sc}"

            h = 1
            okey = f"{cc}|{sc}"
            if okey in custom_assign and "hours" in custom_assign[okey]:
                h = int(custom_assign[okey]["hours"])

            if key not in t_assignments[tc]["courses"]:
                t_assignments[tc]["courses"][key] = {
                    "class_code": cc,
                    "class_name": s["class_name"],
                    "subject_code": sc,
                    "subject_name": s["subject_name"],
                    "hours": 1
                }
            else:
                t_assignments[tc]["courses"][key]["hours"] += 1

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

        # Recalculate teacher total hours with overrides
        for tc, info in t_assignments.items():
            tot = 0
            for c in info["courses"].values():
                okey = f"{c['class_code']}|{c['subject_code']}"
                if okey in custom_assign and "hours" in custom_assign[okey]:
                    c["hours"] = int(custom_assign[okey]["hours"])
                tot += c["hours"]
            info["total_hours"] = tot

        res_teacher = []
        for tc, info in sorted(t_assignments.items(), key=lambda x: x[1]["teacher_name"]):
            res_teacher.append({
                "teacher_code": tc,
                "teacher_name": info["teacher_name"],
                "total_hours": info["total_hours"],
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
                pass

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
        solved_excel = r"D:\土城高中\School_Schedule_Solved.xlsx"
        if os.path.exists(solved_excel):
            try:
                os.remove(solved_excel)
            except Exception:
                pass
        local_excel = os.path.join(os.path.dirname(__file__), "School_Schedule_Solved.xlsx")
        if os.path.exists(local_excel):
            try:
                os.remove(local_excel)
            except Exception:
                pass
        
        global _cached_data
        _cached_data = None
        
        return jsonify({"status": "success", "message": "全校課表已成功清零！已回復至初始排課需求狀態，即刻可啟動全新 AI 排課。"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

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
        return jsonify({"status": "success", "message": "AI 排課權重與偏好參數已成功儲存！"})
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
        except Exception:
            pass
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
            except Exception:
                pass
                
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
def api_get_venue_capacities():
    try:
        cfg = load_config_rules()
        caps = cfg.get("venue_capacities", {
            "電腦教室": 2,
            "理化實驗室": 1,
            "音樂教室": 1,
            "體育場": 3
        })
        consec_subs = cfg.get("consecutive_subjects", ["104", "105", "110"])
        return jsonify({"status": "success", "venue_capacities": caps, "consecutive_subjects": consec_subs})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/save-venue-capacities", methods=["POST"])
def api_save_venue_capacities():
    try:
        req = request.get_json() or {}
        caps = req.get("venue_capacities", {})
        consec_subs = req.get("consecutive_subjects", [])
        
        cfg = load_config_rules()
        cfg["venue_capacities"] = caps
        cfg["consecutive_subjects"] = consec_subs
        save_config_rules(cfg)
        return jsonify({"status": "success", "message": "專用教室容納上限與強制連堂規則已成功儲存！"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/substitute/recommend", methods=["POST"])
def api_substitute_recommend():
    try:
        req = request.get_json() or {}
        absent_tcode = req.get("teacher_code", "").strip()
        day = str(req.get("day", "1")).strip()
        period = str(req.get("period", "1")).strip()
        
        data = load_schedule_data()
        if "error" in data:
            return jsonify(data), 500
            
        schedules = data.get("schedules", [])
        teachers = data.get("teachers", [])

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
        target_subject = absent_course.get("subject_name", "") if absent_course else ""

        for t in teachers:
            t_code = t["code"]
            if t_code == absent_tcode:
                continue
                
            # Check if teacher is busy
            if t_code in busy_teachers:
                continue
                
            # Check if slot is blocked in no_teach
            blocked_slots = no_teach_map.get(t_code, [])
            if f"{day}-{period}" in blocked_slots:
                continue

            # Check matching department/subject score
            same_subject_bonus = False
            for s in schedules:
                if s["teacher_code"] == t_code and target_subject and target_subject in s.get("subject_name", ""):
                    same_subject_bonus = True
                    break

            candidates.append({
                "teacher_code": t_code,
                "teacher_name": t["name"],
                "role": t.get("role", ""),
                "is_same_domain": same_subject_bonus
            })

        candidates.sort(key=lambda x: (not x["is_same_domain"], x["teacher_name"]))

        return jsonify({
            "status": "success",
            "absent_course": absent_course,
            "candidates": candidates
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

        # Run simple balanced assignment
        invigilation_plan = []
        t_idx = 0
        
        for d in range(1, days_count + 1):
            for p in range(1, periods_per_day + 1):
                for c in classes:
                    t = teachers[t_idx % len(teachers)]
                    t_idx += 1
                    invigilation_plan.append({
                        "day": d,
                        "period": p,
                        "class_code": c["code"],
                        "class_name": c["name"],
                        "invigilator_code": t["code"],
                        "invigilator_name": t["name"]
                    })

        cfg = load_config_rules()
        cfg["exam_invigilations"] = {
            "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "plan": invigilation_plan
        }
        save_config_rules(cfg)

        return jsonify({
            "status": "success",
            "message": "定期考查 (段考) 監考表已成功自動生成！",
            "plan": invigilation_plan
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    load_schedule_data()
    app.run(host="127.0.0.1", port=5000, debug=True)


