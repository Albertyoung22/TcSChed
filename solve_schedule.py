import os
import sys
import json
import pandas as pd
from dbfread import DBF
from ortools.sat.python import cp_model

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

def find_latest_dbf_dir():
    try:
        from app import get_latest_dbf_dir
        path = get_latest_dbf_dir()
        return path
    except Exception:
        pass
    return None

def run_solver():
    logs = []
    def log(msg):
        print(msg)
        logs.append(str(msg))
        
    dbf_dir = find_latest_dbf_dir()
    db_claspv_base = []
    db_no_teach = []
    db_no_sub = []
    db_class = []

    if dbf_dir and os.path.exists(dbf_dir):
        log(f"Reading database from: {dbf_dir}")
        try:
            db_claspv_base = list(DBF(os.path.join(dbf_dir, "claspv_base.dbf"), ignore_missing_memofile=True))
            db_no_teach = list(DBF(os.path.join(dbf_dir, "no_teach.dbf"), ignore_missing_memofile=True))
            db_no_sub = list(DBF(os.path.join(dbf_dir, "no_sub.dbf"), ignore_missing_memofile=True))
            db_class = list(DBF(os.path.join(dbf_dir, "class.dbf"), ignore_missing_memofile=True))
        except Exception as e:
            log(f"Warning reading DBF files: {e}")
    else:
        log("No external DBF database found. Running CP-SAT solver in Custom / AI-Assignments mode.")

    # Identify virtual classes
    virtual_class_codes = set()
    for r in db_class:
        is_virt = r.get("虛擬班")
        if isinstance(is_virt, str):
            is_virt = is_virt.strip().lower() == "true"
        elif not isinstance(is_virt, bool):
            is_virt = False
            
        if is_virt or "跨班" in r.get("CLASS_NAME", ""):
            virtual_class_codes.add(r.get("CLASS_NO", "").strip())
            
    if virtual_class_codes:
        log(f"Identified virtual class codes: {list(virtual_class_codes)}")

    # Load custom rules
    custom_rules = {}
    config_rules_file = os.path.join(os.path.dirname(__file__), "config_rules.json")
    if os.path.exists(config_rules_file):
        try:
            with open(config_rules_file, "r", encoding="utf-8") as f:
                custom_rules = json.load(f)
        except Exception as e:
            log(f"Warning loading config_rules.json: {e}")

    ca = custom_rules.get("custom_assignments", {})
    da = set(custom_rules.get("deleted_assignments", []))

    unique_units = {}
    raw_item_unit_map = {}

    if db_claspv_base:
        log(f"Loaded {len(db_claspv_base)} course items to schedule from DBF.")
        for idx, r in enumerate(db_claspv_base):
            cc = str(r.get("班級", "")).strip()
            cn = str(r.get("班級名稱", "")).strip()
            sc = str(r.get("科目", "")).strip()
            sn = str(r.get("科目名稱", "")).strip()
            tc = str(r.get("教師", "")).strip()
            tn = str(r.get("教師名稱", "")).strip()
            rc = str(r.get("教室", "")).strip()
            rn = str(r.get("教室名稱", "")).strip()

            ckey = f"{cc}|{sc}"
            if ckey in da and ckey not in ca:
                continue
            if ckey in ca:
                tc = ca[ckey].get("teacher_code", tc)
                tn = ca[ckey].get("teacher_name", tn)

            w = r.get("星期", "").strip()
            s = r.get("節次", "").strip()
            pre_d = int(w) if w else None
            pre_p = int(s) if s else None

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

            sim_group = str(r.get("同時群", "")).strip()
            desc = str(r.get("說明", "")).strip()

            unit_key = (cc, sc, arr, sub_idx)
            if unit_key not in unique_units:
                unique_units[unit_key] = {
                    "unit_id": len(unique_units),
                    "unit_key": unit_key,
                    "class_code": cc,
                    "class_name": cn,
                    "subject_code": sc,
                    "subject_name": sn,
                    "teachers": set(),
                    "teacher_names": set(),
                    "room_code": rc,
                    "room_name": rn,
                    "prefilled_day": pre_d,
                    "prefilled_period": pre_p,
                    "week_mode": week_mode,
                    "ud": ud,
                    "arr": arr,
                    "sub_idx": sub_idx,
                    "total_hours": total_hours,
                    "sim_group": sim_group,
                    "desc": desc,
                    "raw_records": []
                }

            u = unique_units[unit_key]
            if tc:
                u["teachers"].add(tc)
            if tn:
                u["teacher_names"].add(tn)
            if pre_d is not None and u["prefilled_day"] is None:
                u["prefilled_day"] = pre_d
                u["prefilled_period"] = pre_p

            u["raw_records"].append({
                "raw_idx": idx,
                "teacher_code": tc,
                "teacher_name": tn,
                "record": r
            })
            raw_item_unit_map[idx] = u
    else:
        log(f"Loaded {len(ca)} custom assignments for AI CP-SAT Timetable Solver.")
        idx = 0
        for ckey, assign in ca.items():
            cc = str(assign.get("class_code", "")).strip()
            cn = str(assign.get("class_name", cc)).strip()
            sc = str(assign.get("subject_code", "")).strip()
            sn = str(assign.get("subject_name", sc)).strip()
            tc = str(assign.get("teacher_code", "")).strip()
            tn = str(assign.get("teacher_name", tc)).strip()
            hours = int(assign.get("hours", 2))

            if not cc or not sc:
                continue

            for h in range(1, hours + 1):
                unit_key = (cc, sc, h, 1)
                unique_units[unit_key] = {
                    "unit_id": len(unique_units),
                    "unit_key": unit_key,
                    "class_code": cc,
                    "class_name": cn,
                    "subject_code": sc,
                    "subject_name": sn,
                    "teachers": {tc} if tc else set(),
                    "teacher_names": {tn} if tn else set(),
                    "room_code": "",
                    "room_name": "",
                    "prefilled_day": None,
                    "prefilled_period": None,
                    "week_mode": 0,
                    "ud": 0,
                    "arr": h,
                    "sub_idx": 1,
                    "total_hours": hours,
                    "sim_group": "",
                    "desc": "",
                    "raw_records": [{
                        "raw_idx": idx,
                        "teacher_code": tc,
                        "teacher_name": tn,
                        "record": {
                            "班級": cc, "班級名稱": cn,
                            "科目": sc, "科目名稱": sn,
                            "教師": tc, "教師名稱": tn
                        }
                    }]
                }
                idx += 1

    units_list = list(unique_units.values())
    log(f"Collapsed into {len(units_list)} unique lesson units for CP-SAT solver.")

    model = cp_model.CpModel()
    days = range(1, 6)
    periods = range(1, 9)

    x = {}
    day_vars = {}
    period_vars = {}

    for u in units_list:
        uid = u["unit_id"]
        day_vars[uid] = model.NewIntVar(1, 5, f'day_{uid}')
        period_vars[uid] = model.NewIntVar(1, 8, f'period_{uid}')
        for d in days:
            for p in periods:
                b_var = model.NewBoolVar(f'x_{uid}_{d}_{p}')
                x[uid, d, p] = b_var
        model.Add(day_vars[uid] == sum(d * x[uid, d, p] for d in days for p in periods))
        model.Add(period_vars[uid] == sum(p * x[uid, d, p] for d in days for p in periods))
        model.Add(sum(x[uid, d, p] for d in days for p in periods) == 1)

        # Only enforce prefilled_day/prefilled_period if explicitly marked as manual_locked!
        # Otherwise, allow CP-SAT solver to reschedule freely to honor all rules (simultaneous groups, no-teach, venue limits, etc.)
        if u.get("manual_locked") and u["prefilled_day"] is not None and u["prefilled_period"] is not None:
            model.Add(day_vars[uid] == u["prefilled_day"])
            model.Add(period_vars[uid] == u["prefilled_period"])

    # 1. Simultaneous Groups (同時群)
    sim_groups = {}
    for u in units_list:
        sg = u["sim_group"]
        if sg:
            sim_groups.setdefault(sg, []).append(u["unit_id"])

    for sg, uids in sim_groups.items():
        if len(uids) > 1:
            f_uid = uids[0]
            for o_uid in uids[1:]:
                model.Add(day_vars[f_uid] == day_vars[o_uid])
                model.Add(period_vars[f_uid] == period_vars[o_uid])

    # 2. Custom Simultaneous Groups (自訂同時上課/跨班分組)
    custom_sim_groups = custom_rules.get("custom_simultaneous_groups", [])
    for grp in custom_sim_groups:
        members = grp if isinstance(grp, list) else (grp.get("members", []) if isinstance(grp, dict) else [])
        fixed_day = grp.get("fixed_day") if isinstance(grp, dict) else None
        fixed_period = grp.get("fixed_period") if isinstance(grp, dict) else None
        
        matched_uids = []
        for target in members:
            if not isinstance(target, dict):
                continue
            t_cc = str(target.get("class_code", "")).strip()
            t_sc = str(target.get("subject_code", "")).strip()
            for u in units_list:
                if u["class_code"] == t_cc and u["subject_code"] == t_sc:
                    matched_uids.append(u["unit_id"])
        if matched_uids:
            if len(matched_uids) > 1:
                f_uid = matched_uids[0]
                for o_uid in matched_uids[1:]:
                    model.Add(day_vars[f_uid] == day_vars[o_uid])
                    model.Add(period_vars[f_uid] == period_vars[o_uid])
            if fixed_day is not None and fixed_period is not None and str(fixed_day).isdigit() and str(fixed_period).isdigit():
                fd = int(fixed_day)
                fp = int(fixed_period)
                for uid in matched_uids:
                    model.Add(day_vars[uid] == fd)
                    model.Add(period_vars[uid] == fp)

    # 3. Class Conflicts (班級不衝堂)
    cls_units = {}
    for u in units_list:
        cc = u["class_code"]
        if cc and cc not in virtual_class_codes:
            cls_units.setdefault(cc, []).append(u)

    for cc, ulist in cls_units.items():
        grp_reps = {}
        for u in ulist:
            if u["prefilled_day"] is not None and u["prefilled_period"] is not None:
                ckey = ("PRE", u["prefilled_day"], u["prefilled_period"])
            elif u["sim_group"]:
                ckey = ("SIM", u["sim_group"])
            else:
                ckey = ("UNIT", u["unit_id"])
            if ckey not in grp_reps:
                grp_reps[ckey] = u
        reps = list(grp_reps.values())
        for d in days:
            for p in periods:
                model.AddAtMostOne(x[u["unit_id"], d, p] for u in reps if u["week_mode"] in (0, 1))
                model.AddAtMostOne(x[u["unit_id"], d, p] for u in reps if u["week_mode"] in (0, 2))

    # 4. Teacher Conflicts (教師不衝堂 - 嚴格同一教師不可在同一時段任教多班)
    teacher_units = {}
    for u in units_list:
        for tc in u["teachers"]:
            if tc:
                teacher_units.setdefault(tc, []).append(u)

    for tc, ulist in teacher_units.items():
        # Collapse identical simultaneous units for the same teacher
        grp_reps = {}
        for u in ulist:
            if u["prefilled_day"] is not None and u["prefilled_period"] is not None:
                tkey = ("PRE", u["prefilled_day"], u["prefilled_period"])
            elif u["sim_group"]:
                tkey = ("SIM", u["sim_group"])
            else:
                tkey = ("UNIT", u["unit_id"])
            if tkey not in grp_reps:
                grp_reps[tkey] = u
        reps = list(grp_reps.values())
        
        # Enforce strict 1-course per slot for each teacher
        for d in days:
            for p in periods:
                model.AddAtMostOne(x[u["unit_id"], d, p] for u in reps if u["week_mode"] in (0, 1))
                model.AddAtMostOne(x[u["unit_id"], d, p] for u in reps if u["week_mode"] in (0, 2))

        # Enforce reasonable teacher daily max load (<= 8 periods per day)
        for d in days:
            model.Add(sum(x[u["unit_id"], d, p] for u in reps for p in periods) <= 8)


    # 5. Venue Capacity Constraints & Subject-to-Venue Mappings
    subject_venue_mappings = custom_rules.get("subject_venue_mappings", [])
    subj_room_map = {r.get("subject_code"): r.get("room_name") for r in subject_venue_mappings if r.get("subject_code") and r.get("room_name")}

    venue_capacities = custom_rules.get("venue_capacities", {})
    if venue_capacities or subj_room_map:
        room_units_map = {}
        for u in units_list:
            sc = u.get("subject_code", "").strip()
            rm = u.get("room_name", "").strip() or u.get("room_code", "").strip()
            if sc in subj_room_map:
                rm = subj_room_map[sc]
                u["room_name"] = rm
                u["room_code"] = rm
            if rm:
                room_units_map.setdefault(rm, []).append(u)

        for room_name, r_units in room_units_map.items():
            cap = venue_capacities.get(room_name)
            if cap and cap > 0:
                for d in days:
                    for p in periods:
                        model.Add(sum(x[u["unit_id"], d, p] for u in r_units) <= cap)


    # Weights and penalties
    weights = custom_rules.get("weights", {})
    w_spreading = int(weights.get("spreading_weight", 15))
    w_consecutive = int(weights.get("consecutive_weight", 600))
    w_no_teach = int(weights.get("no_teach_penalty", 300))
    w_no_sub = int(weights.get("no_sub_penalty", 300))
    w_morning_pref = int(weights.get("morning_pref_weight", 50))
    w_pe_noon = int(weights.get("pe_noon_penalty_weight", 100))

    # SOFT Constraints
    no_teach_violations = []
    no_sub_violations = []
    afternoon_penalties = []
    pe_noon_penalties = []

    core_subject_codes = {"101", "102", "103", "104", "105"}

    for u in units_list:
        uid = u["unit_id"]
        sc = u.get("subject_code", "")
        sn = u.get("subject_name", "")

        # Core Morning Preference
        if sc in core_subject_codes or any(kw in sn for kw in ["國文", "英文", "數學", "物理", "化學"]):
            for d in days:
                for p in [5, 6, 7, 8]:
                    afternoon_penalties.append(x[uid, d, p])

        # PE Noon Avoidance
        if sc == "901" or "體育" in sn:
            for d in days:
                for p in [4, 5]:
                    pe_noon_penalties.append(x[uid, d, p])

    # Teacher Unavailability
    for rule in db_no_teach:
        t_code = rule.get("TEACHER_NO", "").strip()
        sd = rule.get("START_DAY", 1)
        ed = rule.get("END_DAY", 5)
        ss = rule.get("START_SEC", 1)
        es = rule.get("END_SEC", 1)

        if t_code in teacher_units:
            for u in teacher_units[t_code]:
                for d in range(sd, ed + 1):
                    for p in range(ss, es + 1):
                        if d in days and p in periods:
                            no_teach_violations.append(x[u["unit_id"], d, p])

    custom_no_teach = custom_rules.get("custom_no_teach", {})
    for t_code, slots in custom_no_teach.items():
        if t_code in teacher_units:
            for u in teacher_units[t_code]:
                for slot in slots:
                    try:
                        d_str, p_str = slot.split("-")
                        d, p = int(d_str), int(p_str)
                        if d in days and p in periods:
                            no_teach_violations.append(x[u["unit_id"], d, p])
                    except ValueError:
                        pass

    # Subject Blocked Times
    for rule in db_no_sub:
        c_code = rule.get("CLASS_NO", "").strip()
        s_code = rule.get("SUBJ_NO", "").strip()
        sd = rule.get("START_DAY", 1)
        ed = rule.get("END_DAY", 5)
        ss = rule.get("START_SEC", 1)
        es = rule.get("END_SEC", 1)

        for u in units_list:
            if u["class_code"] == c_code and u["subject_code"] == s_code:
                for d in range(sd, ed + 1):
                    for p in range(ss, es + 1):
                        if d in days and p in periods:
                            no_sub_violations.append(x[u["unit_id"], d, p])

    custom_no_sub = custom_rules.get("custom_no_sub", {})
    for key_str, slots in custom_no_sub.items():
        try:
            c_code, s_code = key_str.split("|")
            for u in units_list:
                if u["class_code"] == c_code and u["subject_code"] == s_code:
                    for slot in slots:
                        d_str, p_str = slot.split("-")
                        d, p = int(d_str), int(p_str)
                        if d in days and p in periods:
                            no_sub_violations.append(x[u["unit_id"], d, p])
        except ValueError:
            pass

    # Spreading objective & Consecutive Subjects
    class_sub_units = {}
    for u in units_list:
        key = (u["class_code"], u["subject_code"])
        class_sub_units.setdefault(key, []).append(u)

    consec_subject_codes = set(custom_rules.get("consecutive_subjects", ["104", "105", "110"]))
    class_consec_list = custom_rules.get("class_consecutive_rules", [])
    class_consec_map = {(r.get("class_code"), r.get("subject_code")): int(r.get("length", 2)) for r in class_consec_list}

    for (c_code, s_code), u_list in class_sub_units.items():
        is_consec = s_code in consec_subject_codes or (c_code, s_code) in class_consec_map
        if is_consec and len(u_list) >= 2:
            # Pair adjacent units to be consecutive on the same day (e.g. P1-P2, P3-P4)
            u1, u2 = u_list[0], u_list[1]
            u1_id, u2_id = u1["unit_id"], u2["unit_id"]
            model.Add(day_vars[u1_id] == day_vars[u2_id])
            model.Add(period_vars[u2_id] == period_vars[u1_id] + 1)

    active_vars = []
    for key, u_list in class_sub_units.items():
        c_code, s_code = key
        if len(u_list) > 1:
            for d in days:
                active = model.NewBoolVar(f'active_{c_code}_{s_code}_{d}')
                active_vars.append(active)
                for u in u_list:
                    uid = u["unit_id"]
                    model.Add(active >= sum(x[uid, d, p] for p in periods))


    # Multi-Objective Function
    model.Maximize(
        w_spreading * sum(active_vars) -
        w_no_teach * sum(no_teach_violations) -
        w_no_sub * sum(no_sub_violations) -
        w_morning_pref * sum(afternoon_penalties) -
        w_pe_noon * sum(pe_noon_penalties)
    )

    log("Solving CSP Timetable Model using CP-SAT solver...")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        log(f"Solution FOUND! (Status: {solver.StatusName(status)})")

        solved_records = []
        for u in units_list:
            uid = u["unit_id"]
            sol_d = solver.Value(day_vars[uid])
            sol_p = solver.Value(period_vars[uid])

            for raw in u["raw_records"]:
                solved_records.append({
                    "班級代碼": u["class_code"],
                    "科目代碼": u["subject_code"],
                    "教師代碼": raw["teacher_code"],
                    "班級名稱": u["class_name"],
                    "科目名稱": u["subject_name"],
                    "教師姓名": raw["teacher_name"],
                    "教室名稱": u["room_name"],
                    "時間代碼": f"{sol_d}{sol_p}{u['week_mode']}{u['ud']}",
                    "星期": str(sol_d),
                    "節次": str(sol_p),
                    "週別設定": u["week_mode"],
                    "說明": u["desc"]
                })

        base_dir = os.path.dirname(__file__)
        if dbf_dir and "土城高中" in dbf_dir and os.path.exists(r"D:\土城高中"):
            output_path = r"D:\土城高中\School_Schedule_Solved.xlsx"
        else:
            output_path = os.path.join(base_dir, "School_Schedule_Solved.xlsx")

        df_out = pd.DataFrame(solved_records)
        df_out.to_excel(output_path, index=False)
        log(f"Successfully wrote solved schedule to: {output_path}")

        # Update config_rules.json with solved_schedules
        if os.path.exists(config_rules_file):
            try:
                with open(config_rules_file, "r", encoding="utf-8") as f:
                    cfg_to_update = json.load(f)
            except Exception:
                cfg_to_update = {}
        else:
            cfg_to_update = {}

        cfg_to_update["solved_schedules"] = solved_records
        with open(config_rules_file, "w", encoding="utf-8") as f:
            json.dump(cfg_to_update, f, ensure_ascii=False, indent=2)

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

if __name__ == "__main__":
    res = run_solver()
    print("Execution Finished:", res.get("status"))
