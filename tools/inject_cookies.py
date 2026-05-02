# this is a tool used to read the cookie from the clipboard or a file path(due to the input limitation of terminal)
# the instructions will be printed without any arguments in the input
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

username = os.getenv("DISCUZ_USERNAME", "bot_user")
domain = os.getenv("DISCUZ_BASE_URL", "https://localhost").rstrip("/")
host = domain.split("://")[-1].split("/")[0]  # remove parts before and including ://, then remove parts after and including /

output = Path(os.getenv("BOT_COOKIE_FILE", f"cookies/{username}.cookies.json"))
output.parent.mkdir(parents=True, exist_ok=True)  # automatically create the folder of cookies (though actually unneccesary)

use_clipboard = "--clipboard" in sys.argv
file_arg = next((a for a in sys.argv[1:] if not a.startswith("--")), None)

if use_clipboard:  # mode clipboard
    try:
        '''
        this is very likely going to induce failure on windows
        '''
        raw = subprocess.check_output(["pbpaste"], text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("⚠ Could not read clipboard. Try --file instead.")
        sys.exit(1)
elif file_arg:  # mode file path
    raw = Path(file_arg).read_text(encoding="utf-8").strip()
else:
    '''
    these instructions can be outdated and lead to failure
    I need to reminisce how did I get my current cookie...
    '''
    print(f"Site:       {domain}")
    print(f"Cookie file: {output}")
    print()
    print("=== Step 1: Log in manually in Chrome ===")
    print(f"  1. Open {domain}")
    print(f"  2. Log in as '{username}' (fill CAPTCHA)")
    print()
    print("=== Step 2: Export cookies ===")
    print("  Press F12 → Console → paste and run:")
    print()
    print("  copy(JSON.stringify(document.cookie.split('; ').map(function(c){")
    print("    var i = c.indexOf('=');")
    print(f"    return {{name:c.slice(0,i), value:c.slice(i+1), domain:'.{host}', path:'/'}};")
    print("  })));")
    print()
    print(f"=== Step 3: Run: python tools/inject_cookies.py --clipboard ===")
    sys.exit(0)

try:
    data = json.loads(raw)
except json.JSONDecodeError:
    print("⚠ Invalid JSON in clipboard. Did you run the Console command?")
    sys.exit(1)

parsed: list[dict] = []
if isinstance(data, list):
    parsed = [
        {
            "name": str(c.get("name", "")),
            "value": str(c.get("value", "")),
            "domain": c.get("domain", f".{host}"),
            "path": c.get("path", "/"),
        }
        for c in data if c.get("name")
    ]
elif isinstance(data, dict):
    parsed = [
        {"name": k, "value": v, "domain": f".{host}", "path": "/"}
        for k, v in data.items()
    ]

if not parsed:
    print("⚠ No cookies parsed.")
    sys.exit(1)

with open(output, "w", encoding="utf-8") as f:
    json.dump(parsed, f, ensure_ascii=False, indent=2)  # address Chinese, indent

print(f"✓ {len(parsed)} cookies saved to {output}")
print("Now run: python main.py")