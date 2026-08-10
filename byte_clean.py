with open('app.py', 'rb') as f:
    content = f.read()

lines = content.split(b'\r\n')
cleaned_lines = []
for idx, line in enumerate(lines, 1):
    line_str = line.decode('utf-8', errors='replace')
    if "return jsonify({" in line_str and "status" in line_str and "success" in line_str:
        line_str = '        return jsonify({"status": "success", "message": "課表調整完成並已自動鎖定保護！"})'

    cleaned_lines.append(line_str.encode('utf-8'))

content = b'\r\n'.join(cleaned_lines)

with open('app.py', 'wb') as f:
    f.write(content)

print("Line 916 byte clean executed.")
