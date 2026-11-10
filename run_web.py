import os
import sys
import time
import socket
import subprocess
import threading
import webbrowser
from aiohttp import web
from src.web.server import create_app

PORT = 5000

def free_port(port: int = 5000):
    """
    Ensure port 5000 is strictly free and available.
    Terminates any stale/lingering process holding port 5000 so the server
    always binds cleanly without needing port hopping (e.g. 5001).
    """
    current_pid = os.getpid()
    if sys.platform == "win32":
        try:
            output = subprocess.check_output(
                f'netstat -ano | findstr :{port}',
                shell=True,
                text=True,
                stderr=subprocess.DEVNULL
            )
            killed_any = False
            for line in output.strip().splitlines():
                parts = line.split()
                if len(parts) >= 5 and "LISTENING" in parts:
                    pid_str = parts[-1]
                    if pid_str.isdigit():
                        pid = int(pid_str)
                        if pid != current_pid and pid != 0:
                            print(f"[PORT MANAGER] Freeing port {port}: terminating stale process PID {pid}...")
                            subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
                            killed_any = True
            if killed_any:
                time.sleep(1.0)
        except Exception:
            pass
    else:
        try:
            output = subprocess.check_output(["lsof", "-t", f"-i:{port}"], text=True, stderr=subprocess.DEVNULL)
            for pid_str in output.strip().splitlines():
                if pid_str.isdigit() and int(pid_str) != current_pid:
                    subprocess.run(["kill", "-9", pid_str], capture_output=True)
            time.sleep(0.5)
        except Exception:
            pass

def open_browser():
    time.sleep(1.2)
    url = f"http://localhost:{PORT}"
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"Could not automatically open browser: {e}")
        print(f"Please open your browser manually and go to: {url}")

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # Free port 5000 from any stale or orphaned instances
    free_port(PORT)

    print("=" * 68)
    print("🚀 RAUSHONIX AI — AUTONOMOUS CAREER & PLACEMENT SUITE")
    print("   Proprietary AI Architecture · Engineered by Abhiraj Raushan")
    print("=" * 68)
    print(f"👉 Local Web Dashboard running strictly at: http://localhost:{PORT}")
    print("👉 Default browser launching automatically...")
    print("=" * 68)
    print("NOTE: Keep this terminal window open while using Raushonix AI.")
    print("To terminate server: Press Ctrl + C.")
    print("=" * 68)

    # Automatically open browser
    threading.Thread(target=open_browser, daemon=True).start()

    app = create_app()
    web.run_app(app, host="127.0.0.1", port=PORT, print=False)
