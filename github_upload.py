"""Upload app.py to GitHub via REST API."""
import base64
import json
import urllib.request
import urllib.error

# Read the fixed file
with open("app.py", "rb") as f:
    content_bytes = f.read()

content_b64 = base64.b64encode(content_bytes).decode("ascii")

# GitHub API config - using the GitHub token from git credential if available
# The user needs to provide a token OR we use the stored credential
OWNER = "Albertyoung22"
REPO  = "TcSChed"
PATH  = "app.py"

# First, get the current file SHA (required for update)
api_url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{PATH}"

# Try to read GitHub token from git credential manager
import subprocess, sys

def get_github_token():
    """Try to get GitHub token from Windows Credential Manager."""
    try:
        result = subprocess.run(
            ["cmdkey", "/list:git:https://github.com"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("Credential found:", result.stdout[:100])
    except Exception as e:
        print("cmdkey error:", e)
    
    # Try git credential helper
    try:
        proc = subprocess.Popen(
            ["git", "credential", "fill"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        out, err = proc.communicate(input=b"protocol=https\nhost=github.com\n\n", timeout=5)
        for line in out.decode().splitlines():
            if line.startswith("password="):
                return line[9:].strip()
    except Exception as e:
        print("git credential error:", e)
    return None

token = get_github_token()
if not token:
    print("No GitHub token found. Please enter your GitHub Personal Access Token:")
    print("(You can create one at https://github.com/settings/tokens)")
    token = input("Token: ").strip()

if not token:
    print("ERROR: No token provided. Cannot upload.")
    sys.exit(1)

headers = {
    "Authorization": f"token {token}",
    "Content-Type": "application/json",
    "Accept": "application/vnd.github.v3+json"
}

# Get current file SHA
req = urllib.request.Request(api_url, headers=headers)
try:
    with urllib.request.urlopen(req) as resp:
        file_info = json.loads(resp.read())
        sha = file_info["sha"]
        print(f"Current file SHA: {sha[:10]}...")
except urllib.error.HTTPError as e:
    print(f"Error getting file: {e.code} {e.reason}")
    sha = None

# Upload the new content
payload = {
    "message": "fix: add cp950 encoding to all DBF calls for Linux/Render compatibility",
    "content": content_b64,
}
if sha:
    payload["sha"] = sha

data = json.dumps(payload).encode("utf-8")
req = urllib.request.Request(api_url, data=data, headers=headers, method="PUT")

try:
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
        print(f"SUCCESS! Commit: {result['commit']['sha'][:10]}")
        print(f"Message: {result['commit']['message']}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"ERROR: {e.code} {e.reason}")
    print(body[:500])
