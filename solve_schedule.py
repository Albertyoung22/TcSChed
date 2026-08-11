import os
import sys
import pandas as pd
from dbfread import DBF
from ortools.sat.python import cp_model

sys.stdout.reconfigure(encoding='utf-8')

def find_latest_dbf_dir():
    search_dir = r"D:\土城高中"
    if not os.path.exists(search_dir):
        local_dbf = os.path.join(os.path.dirname(__file__), "dbf_data")
        if os.path.isdir(local_dbf):
            return local_dbf
        return None
    candidates = []
    for name in os.listdir(search_dir):
        path = os.path.join(search_dir, name)
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

def run_solver():
    logs = []
    def log(msg):
        print(msg)
        logs.append(str(msg))
        
    dbf_dir = find_latest_dbf_dir()
    if not dbf_dir:
        return {"status": "error", "message": "Could not find SPV2000 DBF directory in D:\\土城高中", "logs": logs}
        
    log(f"Reading database from: {dbf_dir}")
    
    try:
        # Load tables
        db_claspv_base = list(DBF(os.path.join(dbf_dir, "claspv_base.dbf"), ignore_missing_memofile=True))
        db_no_teach = list(DBF(os.path.join(dbf_dir, "no_teach.dbf"), ignore_missing_memofile=True))
        db_no_sub = list(DBF(os.path.join(dbf_dir, "no_sub.dbf"), ignore_missing_memofile=True))
        db_same_grp = list(DBF(os.path.join(dbf_dir, "same_grp.dbf"), ignore_missing_memofile=True))
        db_class = list(DBF(os.path.join(dbf_dir, "class.dbf"), ignore_missing_memofile=True))
    except Exception as e:
        return {"status": "error", "message": f"Failed to read DBF files: {str(e)}", "logs": logs}
    
    log(f"Loaded {len(db_claspv_base)} course items to schedule.")
    
    # Identify virtual classes
    virtual_class_codes = set()
    for r in db_class:
        is_virt = r.get("虛擬班")
        if isinstance(is_virt, str):
            is_virt = is_virt.strip().lower() == "true"
        elif isinstance(is_virt, bool):
            pass
        else:
            is_virt = False
            
        if is_virt or "跨班" in r.get("CLASS_NAME", ""):
            virtual_class_codes.add(r.get("CLASS_NO", "").strip())
            
    log(f"Identified virtual class codes: {list(virtual_class_codes)}")
            
    # Map teachers to each (class, subject, 排列, 細項)
    slot_teachers = {}
    for r in db_claspv_base:
        cc = r.get("班級", "").strip()
        sc = r.get("科目", "").strip()
        
        # Safely parse arr and sub
        arr_val = r.get("排列")
        arr = int(arr_val) if arr_val is not None and not pd.isna(arr_val) else 1
        sub_val = r.get("細項")
        sub = int(sub_val) if sub_val is not None and not pd.isna(sub_val) else 1
        
        t = r.get("教師", "").strip()
        if cc and sc:
            key = (cc, sc, arr, sub)
            if key not in slot_teachers:
                slot_teachers[key] = set()
            if t:
                slot_teachers[key].add(t)

    # Build model
    model = cp_model.CpModel()
    days = range(1, 6)      # Mon-Fri
    periods = range(1, 9)   # Periods 1-8
    
    # Convert claspv_base into list of items with index
    items = []
    for idx, r in enumerate(db_claspv_base):
        c_code = r.get("班級", "").strip()
        c_name = r.get("班級名稱", "").strip()
        s_code = r.get("科目", "").strip()
        s_name = r.get("科目名稱", "").strip()
        t_code = r.get("教師", "").strip()
        t_name = r.get("教師名稱", "").strip()
        r_code = r.get("教室", "").strip()
        r_name = r.get("教室名稱", "").strip()
        
        w = r.get("星期", "").strip()
        s = r.get("節次", "").strip()
        pre_d = int(w) if w else None
        pre_p = int(s) if s else None
        
        # Safely parse week_mode, ud, arr, sub_idx, total_hours
        wm_val = r.get("週別設定")
        week_mode = int(wm_val) if wm_val is not None and not pd.isna(wm_val) else 0
        
        ud_val = r.get("上下修")
        ud = int(ud_val) if ud_val is not None and not pd.isna(ud_val) else 0
        
        arr_val = r.get("排列")
        arr = int(arr_val) if arr_val is not None and not pd.isna(arr_val) else 1
        
        sub_val = r.get("細項")
        sub_idx = int(sub_val) if sub_val is not None and not pd.isna(sub_val) else 1
        
        tot_val = r.get("總節數")
        total_hours = int(tot_val) if tot_val is not None and not pd.isna(tot_val) else 1
        
        sim_group = r.get("同時群", "").strip()
        desc = r.get("說明", "").strip()
        
        # Get teachers tuple for this slot
        if c_code and s_code:
            teachers = tuple(sorted(list(slot_teachers[(c_code, s_code, arr, sub_idx)])))
        else:
            teachers = ()
            
        items.append({
            "idx": idx,
            "class_code": c_code,
            "class_name": c_name,
            "subject_code": s_code,
            "subject_name": s_name,
            "teacher_code": t_code,
            "teacher_name": t_name,
            "room_code": r_code,
            "room_name": r_name,
            "prefilled_day": pre_d,
            "prefilled_period": pre_p,
            "week_mode": week_mode,
            "ud": ud,
            "sim_group": sim_group,
            "arr": arr,
            "sub_idx": sub_idx,
            "desc": desc,
            "total_hours": total_hours,
            "teachers": teachers,
            "course_key": (c_code, s_code, t_code, arr),
            "lesson_slot_key": (c_code, s_code, arr, sub_idx, total_hours, week_mode),
            "cross_class_key": (s_code, arr, sub_idx, total_hours, week_mode, teachers) if len(teachers) > 1 else (c_code, s_code, arr, sub_idx, total_hours, week_mode)
        })

    # Apply custom course assignments override & deleted assignments filter
    config_rules_file = os.path.join(os.path.dirname(__file__), "config_rules.json")
    if os.path.exists(config_rules_file):
        try:
            import json
            with open(config_rules_file, "r", encoding="utf-8") as f:
                cf = json.load(f)
                ca = cf.get("custom_assignments", {})
                da = set(cf.get("deleted_assignments", []))
                
                filtered_items = []
                for item in items:
                    ckey = f"{item['class_code']}|{item['subject_code']}"
                    if ckey in da and ckey not in ca:
                        continue
                    if ckey in ca:
                        item["teacher_code"] = ca[ckey]["teacher_code"]
                        item["teacher_name"] = ca[ckey]["teacher_name"]
                        item["course_key"] = (item["class_code"], item["subject_code"], item["teacher_code"], item["arr"])
                    filtered_items.append(item)
                items = filtered_items
        except Exception as e:
            log(f"Warning loading custom_assignments: {e}")

    # Decision Variables
    x = {}
    day_vars = {}
    period_vars = {}
    
    for item in items:
        i = item["idx"]
        day_vars[i] = model.NewIntVar(1, 5, f'day_{i}')
        period_vars[i] = model.NewIntVar(1, 8, f'period_{i}')
        
        for d in days:
            for p in periods:
                x[i, d, p] = model.NewBoolVar(f'x_{i}_{d}_{p}')
                
        model.Add(day_vars[i] == sum(d * x[i, d, p] for d in days for p in periods))
        model.Add(period_vars[i] == sum(p * x[i, d, p] for d in days for p in periods))
        model.Add(sum(x[i, d, p] for d in days for p in periods) == 1)
        
        # Enforce prefilled locks
        if item["prefilled_day"] is not None and item["prefilled_period"] is not None:
            model.Add(day_vars[i] == item["prefilled_day"])
            model.Add(period_vars[i] == item["prefilled_period"])

    # 1. Simultaneous Groups (同時群)
    sim_groups_map = {}
    for item in items:
        sg = item["sim_group"]
        if sg:
            if sg not in sim_groups_map:
                sim_groups_map[sg] = []
            sim_groups_map[sg].append(item["idx"])
            
    for sg, idxs in sim_groups_map.items():
        if len(idxs) > 1:
            first_idx = idxs[0]
            for other_idx in idxs[1:]:
                model.Add(day_vars[first_idx] == day_vars[other_idx])
                model.Add(period_vars[first_idx] == period_vars[other_idx])

    # 2. Co-scheduled Split-Taught & Combined Lesson Slots
    co_sched_map = {}
    for item in items:
        cck = item["cross_class_key"]
        if cck[0] and (len(cck) == 6 or (len(cck) == 7 and cck[5])):
            if cck not in co_sched_map:
                co_sched_map[cck] = []
            co_sched_map[cck].append(item)
            
    for cck, slot_items in co_sched_map.items():
        if len(slot_items) > 1:
            first_item = slot_items[0]
            for other_item in slot_items[1:]:
                model.Add(day_vars[first_item["idx"]] == day_vars[other_item["idx"]])
                model.Add(period_vars[first_item["idx"]] == period_vars[other_item["idx"]])

    # 2.5 Custom Simultaneous Groups (自訂同時上課/分組教學/跨班排課)
    custom_sim_groups = custom_rules.get("custom_simultaneous_groups", [])
    for grp in custom_sim_groups:
        matched_idxs = []
        for target in grp:
            t_cc = str(target.get("class_code", "")).strip()
            t_sc = str(target.get("subject_code", "")).strip()
            for item in items:
                if item["class_code"] == t_cc and item["subject_code"] == t_sc:
                    matched_idxs.append(item["idx"])
        if len(matched_idxs) > 1:
            first_idx = matched_idxs[0]
            for other_idx in matched_idxs[1:]:
                model.Add(day_vars[first_idx] == day_vars[other_idx])
                model.Add(period_vars[first_idx] == period_vars[other_idx])

    # 3. Class Conflicts (班級不衝堂)
    class_items_map = {}
    for item in items:
        cc = item["class_code"]
        if cc:
            if cc not in class_items_map:
                class_items_map[cc] = []
            class_items_map[cc].append(item)
            
    for cc, cls_list in class_items_map.items():
        if cc in virtual_class_codes:
            continue
            
        prefilled_slots = {}
        for item in cls_list:
            if item["prefilled_day"] is not None:
                d = item["prefilled_day"]
                p = item["prefilled_period"]
                if (d, p) not in prefilled_slots:
                    prefilled_slots[(d, p)] = []
                prefilled_slots[(d, p)].append((item["week_mode"], item["cross_class_key"]))
                
        dynamic_cls_list = [item for item in cls_list if item["prefilled_day"] is None]
        
        # Group dynamic items by cross_class_key representative to allow co-scheduling
        reps = []
        seen_keys = set()
        for item in dynamic_cls_list:
            cck = item["cross_class_key"]
            if cck not in seen_keys:
                seen_keys.add(cck)
                reps.append(item)
                
        for d in days:
            for p in periods:
                pref_info = prefilled_slots.get((d, p), [])
                pref_weeks = [info[0] for info in pref_info]
                pref_keys = [info[1] for info in pref_info if info[1]]
                
                # If occupied by weekly prefilled
                if 0 in pref_weeks:
                    for item in reps:
                        if item["cross_class_key"] not in pref_keys:
                            model.Add(x[item["idx"], d, p] == 0)
                else:
                    if 1 in pref_weeks:
                        for item in reps:
                            if item["week_mode"] in (0, 1):
                                if item["cross_class_key"] not in pref_keys:
                                    model.Add(x[item["idx"], d, p] == 0)
                    else:
                        model.AddAtMostOne(x[item["idx"], d, p] for item in reps if item["week_mode"] in (0, 1))
                        
                    if 2 in pref_weeks:
                        for item in reps:
                            if item["week_mode"] in (0, 2):
                                if item["cross_class_key"] not in pref_keys:
                                    model.Add(x[item["idx"], d, p] == 0)
                    else:
                        model.AddAtMostOne(x[item["idx"], d, p] for item in reps if item["week_mode"] in (0, 2))

    # 4. Teacher Conflicts (教師不衝堂)
    teacher_items_map = {}
    for item in items:
        tc = item["teacher_code"]
        if tc:
            if tc not in teacher_items_map:
                teacher_items_map[tc] = []
            teacher_items_map[tc].append(item)
            
    for tc, t_list in teacher_items_map.items():
        prefilled_slots = {}
        for item in t_list:
            if item["prefilled_day"] is not None:
                d = item["prefilled_day"]
                p = item["prefilled_period"]
                if (d, p) not in prefilled_slots:
                    prefilled_slots[(d, p)] = []
                prefilled_slots[(d, p)].append((item["week_mode"], item["sim_group"], item["cross_class_key"]))
                
        dynamic_t_list = [item for item in t_list if item["prefilled_day"] is None]
        
        # Group dynamic items by sim_group or cross_class_key representative
        reps = []
        seen_sims = set()
        seen_keys = set()
        for item in dynamic_t_list:
            sg = item["sim_group"]
            cck = item["cross_class_key"]
            if sg:
                if sg not in seen_sims:
                    seen_sims.add(sg)
                    reps.append(item)
            elif cck and len(item["teachers"]) > 1: # Combined elective
                if cck not in seen_keys:
                    seen_keys.add(cck)
                    reps.append(item)
            else:
                reps.append(item)
                
        for d in days:
            for p in periods:
                pref_info = prefilled_slots.get((d, p), [])
                pref_weeks = [info[0] for info in pref_info]
                pref_sims = [info[1] for info in pref_info if info[1]]
                pref_keys = [info[2] for info in pref_info if info[2] and len(info[2]) == 6]
                
                if 0 in pref_weeks:
                    for item in reps:
                        is_allowed = (item["sim_group"] in pref_sims) or (item["cross_class_key"] in pref_keys)
                        if not is_allowed:
                            model.Add(x[item["idx"], d, p] == 0)
                else:
                    if 1 in pref_weeks:
                        for item in reps:
                            if item["week_mode"] in (0, 1):
                                is_allowed = (item["sim_group"] in pref_sims) or (item["cross_class_key"] in pref_keys)
                                if not is_allowed:
                                    model.Add(x[item["idx"], d, p] == 0)
                    else:
                        model.AddAtMostOne(x[item["idx"], d, p] for item in reps if item["week_mode"] in (0, 1))
                        
                    if 2 in pref_weeks:
                        for item in reps:
                            if item["week_mode"] in (0, 2):
                                is_allowed = (item["sim_group"] in pref_sims) or (item["cross_class_key"] in pref_keys)
                                if not is_allowed:
                                    model.Add(x[item["idx"], d, p] == 0)
                    else:
                        model.AddAtMostOne(x[item["idx"], d, p] for item in reps if item["week_mode"] in (0, 2))

    # NO CLASSROOM CONFLICTS ENFORCED

    # Setup class_sub_items map for spreading constraint
    class_sub_items = {}
    for item in items:
        key = (item["class_code"], item["subject_code"])
        if key not in class_sub_items:
            class_sub_items[key] = []
        class_sub_items[key].append(item)

    # 4. Venue Capacity Constraints (專用教室容納上限)
    venue_capacities = custom_rules.get("venue_capacities", {})
    if venue_capacities:
        room_items_map = {}
        for item in items:
            rm = item.get("room_name", "").strip() or item.get("room_code", "").strip()
            if rm:
                if rm not in room_items_map:
                    room_items_map[rm] = []
                room_items_map[rm].append(item)
                
        for room_name, r_items in room_items_map.items():
            cap = venue_capacities.get(room_name)
            if cap and cap > 0:
                for d in days:
                    for p in periods:
                        model.Add(sum(x[item["idx"], d, p] for item in r_items) <= cap)

    # Load dynamic config rules if present
    weights = custom_rules.get("weights", {})
    w_spreading = int(weights.get("spreading_weight", 15))
    w_consecutive = int(weights.get("consecutive_weight", 600))
    w_no_teach = int(weights.get("no_teach_penalty", 300))
    w_no_sub = int(weights.get("no_sub_penalty", 300))
    w_morning_pref = int(weights.get("morning_pref_weight", 50))
    w_pe_noon = int(weights.get("pe_noon_penalty_weight", 100))

    # SOFT Constraint: Morning Preference for Core Subjects (國文/英文/數學/物理/化學)
    core_subject_codes = {"101", "102", "103", "104", "105"}
    afternoon_penalties = []
    pe_noon_penalties = []
    
    for item in items:
        sc = item.get("subject_code", "").strip()
        sn = item.get("subject_name", "").strip()
        idx = item["idx"]
        
        # Morning Preference
        if sc in core_subject_codes or any(kw in sn for kw in ["國文", "英文", "數學", "物理", "化學"]):
            for d in days:
                for p in [5, 6, 7, 8]:
                    afternoon_penalties.append(x[idx, d, p])
                    
        # PE Noon Avoidance
        if sc == "901" or "體育" in sn:
            for d in days:
                for p in [4, 5]:
                    pe_noon_penalties.append(x[idx, d, p])

    # SOFT Constraint: Class/Subject Blocked Times (no_sub.dbf + custom)
    no_sub_violations = []
    for rule in db_no_sub:
        c_code = rule.get("CLASS_NO", "").strip()
        s_code = rule.get("SUBJECT_NO", "").strip()
        sd = rule.get("START_DAY", 1)
        ed = rule.get("END_DAY", 1)
        ss = rule.get("START_SEC", 1)
        es = rule.get("END_SEC", 1)
        
        key = (c_code, s_code)
        if key in class_sub_items:
            for item in class_sub_items[key]:
                for d in range(sd, ed + 1):
                    for p in range(ss, es + 1):
                        if d in days and p in periods:
                            no_sub_violations.append(x[item["idx"], d, p])

    custom_no_sub = custom_rules.get("custom_no_sub", {})
    for key_str, slots in custom_no_sub.items():
        parts = key_str.split("|")
        if len(parts) == 2:
            c_code, s_code = parts[0], parts[1]
            key = (c_code, s_code)
            if key in class_sub_items:
                for item in class_sub_items[key]:
                    for slot in slots:
                        try:
                            d_str, p_str = slot.split("-")
                            d, p = int(d_str), int(p_str)
                            if d in days and p in periods:
                                no_sub_violations.append(x[item["idx"], d, p])
                        except ValueError:
                            pass

    # SOFT Constraint: Teacher Unavailability (no_teach.dbf + custom)
    no_teach_violations = []
    for rule in db_no_teach:
        t_code = rule.get("TEACHER_NO", "").strip()
        sd = rule.get("START_DAY", 1)
        ed = rule.get("END_DAY", 1)
        ss = rule.get("START_SEC", 1)
        es = rule.get("END_SEC", 1)
        
        if t_code in teacher_items_map:
            for item in teacher_items_map[t_code]:
                for d in range(sd, ed + 1):
                    for p in range(ss, es + 1):
                        if d in days and p in periods:
                            no_teach_violations.append(x[item["idx"], d, p])

    custom_no_teach = custom_rules.get("custom_no_teach", {})
    for t_code, slots in custom_no_teach.items():
        if t_code in teacher_items_map:
            for item in teacher_items_map[t_code]:
                for slot in slots:
                    try:
                        d_str, p_str = slot.split("-")
                        d, p = int(d_str), int(p_str)
                        if d in days and p in periods:
                            no_teach_violations.append(x[item["idx"], d, p])
                    except ValueError:
                        pass

    # HARD Constraint: Teacher Max Consecutive Hours (欣河 排課條件2: 5.最多連堂數設定)
    max_consec_h = int(weights.get("max_consecutive_hours", 3))
    if max_consec_h > 0 and max_consec_h < 8:
        for t_code, t_items in teacher_items_map.items():
            if not t_code:
                continue
            for d in days:
                for start_p in range(1, 8 - max_consec_h + 1):
                    # Block start_p to start_p + max_consec_h (length max_consec_h + 1)
                    consec_block = range(start_p, start_p + max_consec_h + 1)
                    model.Add(sum(x[item["idx"], d, p] for item in t_items for p in consec_block if p in periods) <= max_consec_h)

    # HARD Constraint: Teacher Only-Teach Slots (欣河 排課條件1: 3.教師僅能排課時段)
    only_teach_map = custom_rules.get("only_teach_slots", {})
    for t_code, allowed_slots in only_teach_map.items():
        if t_code in teacher_items_map and allowed_slots:
            allowed_set = set(allowed_slots)
            for item in teacher_items_map[t_code]:
                for d in days:
                    for p in periods:
                        if f"{d}-{p}" not in allowed_set:
                            model.Add(x[item["idx"], d, p] == 0)

    # SOFT Constraint: Double Periods
    consecutive_subjects = set(custom_rules.get("consecutive_subjects", ["104", "105", "110"]))
    course_items_map = {}
    for item in items:
        key = item["course_key"]
        if key not in course_items_map:
            course_items_map[key] = []
        course_items_map[key].append(item)
        
    consecutive_vars = []
    valid_consec_slots = [(1, 2), (2, 3), (3, 4), (5, 6), (6, 7), (7, 8)]
    
    for key, c_list in course_items_map.items():
        if len(c_list) == 2:
            i = c_list[0]["idx"]
            j = c_list[1]["idx"]
            
            is_consec = model.NewBoolVar(f'is_consec_{i}_{j}')
            consecutive_vars.append(is_consec)
            
            slot_pair_vars = []
            for d in days:
                for p1, p2 in valid_consec_slots:
                    pair1 = model.NewBoolVar(f'pair1_{i}_{j}_{d}_{p1}')
                    model.Add(x[i, d, p1] + x[j, d, p2] == 2).OnlyEnforceIf(pair1)
                    model.Add(x[i, d, p1] + x[j, d, p2] <= 1).OnlyEnforceIf(pair1.Not())
                    slot_pair_vars.append(pair1)
                    
                    pair2 = model.NewBoolVar(f'pair2_{i}_{j}_{d}_{p1}')
                    model.Add(x[j, d, p1] + x[i, d, p2] == 2).OnlyEnforceIf(pair2)
                    model.Add(x[j, d, p1] + x[i, d, p2] <= 1).OnlyEnforceIf(pair2.Not())
                    slot_pair_vars.append(pair2)
            
            model.Add(is_consec == sum(slot_pair_vars))
            
            # If subject code is explicitly marked in consecutive_subjects, enforce mandatory double period constraint
            sub_code = c_list[0].get("subject_code", "")
            if sub_code in consecutive_subjects:
                model.Add(is_consec == 1)

    # SOFT Constraint: Spreading objective
    active_vars = []
    for key, c_list in class_sub_items.items():
        c_code, s_code = key
        if len(c_list) > 1:
            for d in days:
                active = model.NewBoolVar(f'active_{c_code}_{s_code}_{d}')
                active_vars.append(active)
                for item in c_list:
                    i = item["idx"]
                    model.Add(active >= sum(x[i, d, p] for p in periods))

    # Multi-Objective Function
    # Maximize: Spreading & Double consecutiveness, Penalize teacher, sub block & afternoon core / PE noon violations
    model.Maximize(
        w_spreading * sum(active_vars) +
        w_consecutive * sum(consecutive_vars) -
        w_no_teach * sum(no_teach_violations) -
        w_no_sub * sum(no_sub_violations) -
        w_morning_pref * sum(afternoon_penalties) -
        w_pe_noon * sum(pe_noon_penalties)
    )

    # Run Solver
    log("Solving CSP Timetable Model using CP-SAT solver...")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60.0
    status = solver.Solve(model)
    
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        log(f"Solution FOUND! (Status: {solver.StatusName(status)})")
        
        solved_records = []
        for item in items:
            i = item["idx"]
            sol_d = solver.Value(day_vars[i])
            sol_p = solver.Value(period_vars[i])
            
            solved_records.append({
                "班級代碼": item["class_code"],
                "科目代碼": item["subject_code"],
                "教師代碼": item["teacher_code"],
                "班級名稱": item["class_name"],
                "科目名稱": item["subject_name"],
                "教師姓名": item["teacher_name"],
                "教室名稱": item["room_name"],
                "時間代碼": f"{sol_d}{sol_p}{item['week_mode']}{item['ud']}",
                "星期": str(sol_d),
                "節次": str(sol_p),
                "週別設定": item["week_mode"],
                "說明": item["desc"]
            })
            
        # Write to Excel
        output_path = r"D:\土城高中\School_Schedule_Solved.xlsx"
        if not os.path.exists(r"D:\土城高中"):
            output_path = os.path.join(os.path.dirname(__file__), "School_Schedule_Solved.xlsx")
            
        df_out = pd.DataFrame(solved_records)
        df_out.to_excel(output_path, index=False)
        log(f"Successfully wrote solved schedule to: {output_path}")
        
        return {
            "status": "success", 
            "message": f"Solution found! Solver status: {solver.StatusName(status)}.",
            "logs": logs
        }
    else:
        log("Error: Could not find any feasible timetable solution matching all hard constraints!")
        return {
            "status": "error",
            "message": "Could not find any feasible timetable solution matching all hard constraints!",
            "logs": logs
        }
