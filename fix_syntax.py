with open('app.py', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

replaces = [
    ("r.get('蝭€甈?)", "r.get('節次')"),
    ('r.get("蝭€甈?)', 'r.get("節次")'),
    ("r.get('?剔?隞?Ⅳ', '')", "r.get('班級代碼', '')"),
    ("r.get('?剔?隞?Ⅳ')", "r.get('班級代碼')"),
    ('r.get("?剔?隞?Ⅳ", "")', 'r.get("班級代碼", "")'),
    ('r.get("?剔?隞?Ⅳ")', 'r.get("班級代碼")'),
    ("r.get('?葦憪?', '')", "r.get('教師姓名', '')"),
    ("r.get('?葦憪?')", "r.get('教師姓名')"),
    ('r.get("?葦憪?", "")', 'r.get("教師姓名", "")'),
    ('r.get("?葦憪?")', 'r.get("教師姓名")'),
    ("r.get('??')", "r.get('星期')"),
    ('r.get("??")', 'r.get("星期")'),
    ("r.get('?葦隞?Ⅳ', '')", "r.get('教師代碼', '')"),
    ("r.get('?葦隞?Ⅳ')", "r.get('教師代碼')"),
    ('r.get("?葦隞?Ⅳ", "")', 'r.get("教師代碼", "")'),
    ('r.get("?葦隞?Ⅳ")', 'r.get("教師代碼")'),
    ("r.get('?葦', '')", "r.get('教師', '')"),
    ("r.get('?葦')", "r.get('教師')"),
    ("r.get('?恕', '')", "r.get('教室', '')"),
    ("r.get('?恕')", "r.get('教室')"),
    ("r.get('?剔?', '')", "r.get('班級', '')"),
    ("r.get('?剔?')", "r.get('班級')"),
]

for b, g in replaces:
    content = content.replace(b, g)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Fix script applied successfully.")
