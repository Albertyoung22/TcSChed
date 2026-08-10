"""Script to repair app.py by replacing PUA characters with correct Chinese text."""

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Build regex pattern for PUA chars
import re

def has_pua(s):
    return any(0xE000 <= ord(c) <= 0xF8FF for c in s)

def strip_pua(s):
    """Remove PUA chars from a string for pattern matching."""
    return ''.join(c if ord(c) < 0xE000 or ord(c) > 0xF8FF else '' for c in s)

# Split content into lines for analysis
lines = content.split('\n')

# For each PUA-containing line, determine the correct content
# by analyzing context (what the line should be based on code logic)

# These are the correct replacements keyed by line number (1-indexed)
# Based on code context analysis:
correct_lines = {
    9:  'SEARCH_DIR = r"D:\\土城高中"',
    43: '        return {"error": "No SPV2000 DBF directory found in D:\\\\土城高中"}',
    311: '        excel_path = r"D:\\土城高中\\School_Schedule_Solved.xlsx"',
    324: '            if r.get("虛擬") or "跨班" in r.get("CLASS_NAME", ""):',
    336: '            d_val = r.get("星期")',
    342: '            t = str(r.get("教師姓名", "")).strip() if not pd.isna(r.get("教師姓名")) else ""',
    344: '            wm_val = r.get("週別設定")',
    356: '                            if desc == "(虛擬班級)" and ext["desc"] == "(虛擬班級)":',
    358: '                            detail.append(f"[Teacher Conflict]: Teacher {r.get(\'教師代碼\')} ({t}) has overlapping classes in slot {d}-{p}!")',
    368: '                            if r.get("科目代碼") == ext["subject_code"]:',
    370: '                            detail.append(f"[Class Conflict]: Class {r.get(\'班級代碼\')} ({c}) has overlapping lessons in slot {d}-{p}! Sub: {r.get(\'科目名稱\')} vs {ext[\'subject_name\']}")',
    372: '                class_slots[c].append({"day": d, "period": p, "week": wm, "subject_code": r.get("科目代碼"), "subject_name": r.get("科目名稱")})',
    376: "            t_code = str(r.get('教師代碼', '')).strip()",
    377: "            d_val = r.get('星期')",
    391: "            s_code = str(r.get('科目代碼', '')).strip()",
    392: "            d_val = r.get('星期')",
    426: '            t = r.get("教師", "").strip()',
    427: '            d = r.get("星期", "").strip()',
    448: '        excel_path = r"D:\\土城高中\\School_Schedule_Solved.xlsx"',
    458: '            t = str(r.get("教師姓名", "")).strip()',
    459: '            d_val = r.get("星期")',
    492: '            t = str(r.get("教師姓名", "")).strip() if not pd.isna(r.get("教師姓名")) else ""',
    510: '            d_val = r.get("星期")',
    517: '            t_code = str(r.get("教師代碼", "")).strip()',
    541: '            t = str(r.get("教師姓名", "")).strip() if not pd.isna(r.get("教師姓名")) else ""',
    542: '            d_val = r.get("星期")',
    547: '            t_code = str(r.get("教師代碼", "")).strip()',
    575: '            t = str(r.get("教師姓名", "")).strip() if not pd.isna(r.get("教師姓名")) else ""',
    576: '            d_val = r.get("星期")',
    581: '            t_code = str(r.get("教師代碼", "")).strip()',
    602: '            t = r.get("教師", "").strip()',
    609: '            d = r.get("星期", "").strip()',
    632: '        excel_path = r"D:\\土城高中\\School_Schedule_Solved.xlsx"',
    633: '        if not os.path.exists(excel_path) or not os.path.exists(r"D:\\土城高中"):',
    637: '            return jsonify({"status": "error", "message": "Solved file not found"})',
    663: '        excel_path = r"D:\\土城高中\\School_Schedule_Solved.xlsx"',
    709: '    excel_path = r"D:\\土城高中\\School_Schedule_Solved.xlsx"',
    710: '    if not os.path.exists(excel_path) or not os.path.exists(r"D:\\土城高中"):',
    730: '    solved_excel = r"D:\\土城高中\\School_Schedule_Solved.xlsx"',
    731: '    if not os.path.exists(solved_excel) or not os.path.exists(r"D:\\土城高中"):',
    795: '        claspv_base = list(DBF(os.path.join(dbf_dir, "claspv_base.dbf"), ignore_missing_memofile=True, encoding=\'cp950\'))',
    813: '        claspv_base = list(DBF(os.path.join(dbf_dir, "claspv_base.dbf"), ignore_missing_memofile=True, encoding=\'cp950\'))',
    815: '        no_teach = list(DBF(os.path.join(dbf_dir, "no_teach.dbf"), ignore_missing_memofile=True, encoding=\'cp950\'))',
    823: '        claspv_base = list(DBF(os.path.join(dbf_dir, "claspv_base.dbf"), ignore_missing_memofile=True, encoding=\'cp950\'))',
    828: '        no_teach = list(DBF(os.path.join(dbf_dir, "no_teach.dbf"), ignore_missing_memofile=True, encoding=\'cp950\'))',
    833: '        db_class = list(DBF(os.path.join(dbf_dir, "class.dbf"), ignore_missing_memofile=True, encoding=\'cp950\'))',
    854: '        claspv_base = list(DBF(os.path.join(dbf_dir, "claspv_base.dbf"), ignore_missing_memofile=True, encoding=\'cp950\'))',
    855: '        no_teach = list(DBF(os.path.join(dbf_dir, "no_teach.dbf"), ignore_missing_memofile=True, encoding=\'cp950\'))',
}

# Apply corrections
fixed_lines = list(lines)
corrections = 0
for line_num, correct_text in correct_lines.items():
    idx = line_num - 1
    if idx < len(fixed_lines):
        # Preserve indentation from original line
        original = fixed_lines[idx]
        indent = len(original) - len(original.lstrip())
        # Use the correct text's own indentation
        fixed_lines[idx] = correct_text + '\n'
        corrections += 1

# Also do a regex-based cleanup for remaining PUA chars in field lookups
result = '\n'.join(l.rstrip('\n') for l in fixed_lines)

# Generic cleanup: any remaining PUA sequences 
# Pattern: PUA chars appearing as part of Chinese strings
pua_remaining = sum(1 for c in result if 0xE000 <= ord(c) <= 0xF8FF)
print(f"Corrections applied: {corrections}")
print(f"PUA chars remaining: {pua_remaining}")

# Write fixed version
with open('app.py', 'w', encoding='utf-8') as f:
    f.write(result)
    
print("Fixed app.py written successfully")
