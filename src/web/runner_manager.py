import asyncio
import os
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, List, Set

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"

ANSI_REGEX = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


class RunnerManager:
    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.status: str = "idle"  # "idle" | "running" | "logging_in" | "stopping"
        self.current_task: str | None = None  # "apply" | "login"
        self.current_site: str = "all"
        self.ws_clients: Set[Any] = set()
        self.logs: List[str] = []
        self.max_logs: int = 500
        self.stats: Dict[str, int] = {
            "total_checked": 0,
            "applied": 0,
            "skipped": 0,
            "failed": 0
        }
        self.current_job: Dict[str, Any] = {
            "title": "",
            "company": "",
            "location": "",
            "score": None,
            "status": "Waiting to start..."
        }
        self.login_thread: threading.Thread | None = None
        self.stop_requested: bool = False

    def add_ws(self, ws):
        self.ws_clients.add(ws)

    def remove_ws(self, ws):
        self.ws_clients.discard(ws)

    async def broadcast(self, message: Dict[str, Any]):
        dead = []
        for ws in list(self.ws_clients):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.ws_clients.discard(ws)

    def log(self, text: str):
        clean = ANSI_REGEX.sub('', text).strip()
        if not clean:
            return
        timestamp = time.strftime("%H:%M:%S")
        entry = f"[{timestamp}] {clean}"
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

        try:
            log_file = DATA_DIR / "runner.log"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass

        # Broadcast via event loop if active
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.broadcast({"type": "log", "text": entry}), loop
                )
        except Exception:
            pass

    def check_cookie_session(self) -> Dict[str, bool]:
        """Check if authenticated cookies exist for naukri and linkedin in their isolated profiles."""
        res = {"naukri": False, "linkedin": False}

        def _read_cookie_db(path):
            if not path.exists():
                return b""
            try:
                if sys.platform == "win32":
                    import ctypes
                    from ctypes import wintypes
                    k32 = ctypes.windll.kernel32
                    h = k32.CreateFileW(str(path), 0x80000000, 3, None, 3, 0, None)
                    if h != -1:
                        buf = ctypes.create_string_buffer(5000000)
                        br = wintypes.DWORD()
                        k32.ReadFile(h, buf, 5000000, ctypes.byref(br), None)
                        k32.CloseHandle(h)
                        return buf.raw[:br.value]
                return path.read_bytes()
            except Exception:
                return b""

        # Check Naukri dedicated profile, fallback to legacy
        naukri_db = DATA_DIR / "chrome-profile-naukri" / "Default" / "Network" / "Cookies"
        if not naukri_db.exists():
            naukri_db = DATA_DIR / "chrome-profile" / "Default" / "Network" / "Cookies"
        naukri_content = _read_cookie_db(naukri_db)
        res["naukri"] = b"naukri" in naukri_content and len(naukri_content) > 500

        # Check LinkedIn dedicated profile
        linkedin_db = DATA_DIR / "chrome-profile-linkedin" / "Default" / "Network" / "Cookies"
        linkedin_content = _read_cookie_db(linkedin_db)
        if not linkedin_content:
            # Fallback to shared legacy
            linkedin_db = DATA_DIR / "chrome-profile" / "Default" / "Network" / "Cookies"
            linkedin_content = _read_cookie_db(linkedin_db)
        res["linkedin"] = b"li_at" in linkedin_content

        return res

    def get_applications_today_count(self) -> int:
        db_path = DATA_DIR / "applications.db"
        if not db_path.exists():
            return 0
        try:
            conn = sqlite3.connect(db_path)
            today_str = time.strftime("%Y-%m-%d")
            count = conn.execute(
                "SELECT COUNT(*) FROM applications WHERE status IN ('applied', 'applied_manual') AND updated_at LIKE ?",
                (f"{today_str}%",)
            ).fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0

    def start_login(self, site: str):
        if self.status != "idle":
            raise RuntimeError("A task is already running. Please wait or stop it first.")

        self.status = "logging_in"
        self.current_task = "login"
        self.current_site = site
        self.log(f"Starting browser login for {site.upper()}...")
        self.log("Please log in to your account in the browser window that appears.")

        def run_login():
            proc = None
            try:
                # We invoke login script that monitors page URL
                cmd = [
                    sys.executable, "-u", "-m", "src.main", "login", "--site", site
                ]
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(ROOT_DIR),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    encoding="utf-8",
                    errors="replace"
                )
                self.process = proc

                for line in iter(proc.stdout.readline, ''):
                    if not line:
                        break
                    clean_line = ANSI_REGEX.sub('', line).strip()
                    self.log(clean_line)
                    if "Logged in to" in clean_line:
                        self.log(f"Success! {site.upper()} is logged in.")

                if proc:
                    proc.wait()
            except Exception as e:
                self.log(f"Login error: {e}")
            finally:
                self.status = "idle"
                self.current_task = None
                self.process = None
                auth = self.check_cookie_session()
                if auth.get(site):
                    self.log(f"✅ Verified: {site.upper()} session authenticated successfully.")
                else:
                    self.log(f"⚠️ Note: {site.upper()} was not verified as logged in. Click Re-authenticate anytime to log in.")
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            self.broadcast({"type": "status", "status": "idle"}), loop
                        )
                except Exception:
                    pass

        self.login_thread = threading.Thread(target=run_login, daemon=True)
        self.login_thread.start()

    def confirm_login_input(self):
        """Simulate pressing Enter in the login CLI prompt."""
        if self.process and self.process.stdin and self.status == "logging_in":
            try:
                self.process.stdin.write("\n")
                self.process.stdin.flush()
                self.log("Confirmation sent to browser.")
            except Exception as e:
                self.log(f"Error sending confirm: {e}")

    def start_apply(self, site: str = "naukri", limit: int = 25, auto: bool = True,
                    retry: bool = True, dry_run: bool = False, profile: str | None = None):
        if self.status != "idle":
            raise RuntimeError("Application runner is already running!")

        self.status = "running"
        self.current_task = "apply"
        self.current_site = site
        self.stop_requested = False
        self.stats = {"total_checked": 0, "applied": 0, "skipped": 0, "failed": 0}
        self.current_job = {"title": "", "company": "", "location": "", "score": None, "status": "Initializing search..."}

        cmd = [sys.executable, "-u", "-m", "src.main", "run", "--site", site, "--no-ask"]
        if limit:
            cmd.extend(["--limit", str(limit)])
        if auto:
            cmd.append("--auto")
        if retry:
            cmd.append("--retry")
        if dry_run:
            cmd.append("--dry-run")
        if profile:
            cmd.extend(["--profile", profile])

        self.log(f"Starting Auto-Apply: Site={site.upper()}, Limit={limit}, Auto={auto}, DryRun={dry_run}")

        def run_worker():
            proc = None
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(ROOT_DIR),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    encoding="utf-8",
                    errors="replace"
                )
                self.process = proc

                for line in iter(proc.stdout.readline, ''):
                    if not line:
                        break
                    clean_line = ANSI_REGEX.sub('', line).strip()
                    self.log(clean_line)
                    self._parse_output_line(clean_line)

                if proc:
                    proc.wait()
            except Exception as e:
                self.log(f"Runner error: {e}")
            finally:
                self.status = "idle"
                self.current_task = None
                self.process = None
                self.log("Auto-Apply process finished.")
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            self.broadcast({
                                "type": "status",
                                "status": "idle",
                                "stats": self.stats
                            }), loop
                        )
                except Exception:
                    pass

        t = threading.Thread(target=run_worker, daemon=True)
        t.start()

    def _parse_output_line(self, line: str):
        """Parse runner stdout to update real-time progress and job cards."""
        # Check for Applied count: e.g. "✔ [LINKEDIN] Applied so far: 3/5" or "✔ [NAUKRI] Applied so far: 4/5"
        app_match = re.search(r'Applied so far:\s*(\d+)/(\d+)', line, re.IGNORECASE)
        if app_match:
            self.stats["applied"] = int(app_match.group(1))

        # Check for Job Header: e.g. "1/50 · Microsoft — Backend Engineer"
        job_match = re.search(r'(\d+/\d+)\s*·\s*([^—–-]+)[—–-]\s*(.+)', line)
        if job_match:
            progress = job_match.group(1)
            company = job_match.group(2).strip()
            title = job_match.group(3).strip()
            self.stats["total_checked"] += 1
            self.current_job = {
                "progress": progress,
                "company": company,
                "title": title,
                "location": "",
                "score": None,
                "status": "Analyzing & Scoring..."
            }
            self._notify_job_update()
            return

        # Check for Panel Job Title: e.g. "Fullstack Developer — AI Governance (naukri)" or "Senior Software Engineer — Google (linkedin)"
        panel_match = re.search(r'^([A-Za-z0-9 +/._#-]{3,60})\s*[—–-]\s*([A-Za-z0-9 +/._&()#-]{2,60})\s*\((?:naukri|linkedin|external|company site)[^)]*\)', line)
        if panel_match:
            title = panel_match.group(1).strip()
            company = panel_match.group(2).strip()
            self.stats["total_checked"] += 1
            self.current_job = {
                "progress": f"{self.stats['total_checked']}",
                "company": company,
                "title": title,
                "location": "",
                "score": None,
                "status": "Evaluating Fit & Scoring..."
            }
            self._notify_job_update()
            return

        # Check for Match Score: e.g. "Match: 85%" or "score 75" or "[score 80]"
        score_match = re.search(r'(?:score|match)[:\s]+(\d+)', line, re.IGNORECASE)
        if score_match:
            score = int(score_match.group(1))
            self.current_job["score"] = score
            self._notify_job_update()

        # Check for Outcome: "→ applied via naukri" or "→ applied via linkedin"
        if "→ applied" in line.lower() or "applied successfully" in line.lower():
            self.current_job["status"] = "✅ Successfully Applied!"
            self._notify_job_update()
        elif "→ skipped" in line.lower() or "low match" in line.lower() or "off stack" in line.lower() or "not your role" in line.lower():
            self.stats["skipped"] += 1
            self.current_job["status"] = "⏭️ Skipped (Criteria mismatch)"
            self._notify_job_update()
        elif "failed" in line.lower() or "error applying" in line.lower():
            self.stats["failed"] += 1
            self.current_job["status"] = "⚠️ Application Failed"
            self._notify_job_update()

    def _notify_job_update(self):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.broadcast({
                        "type": "job_event",
                        "job": self.current_job,
                        "stats": self.stats
                    }), loop
                )
        except Exception:
            pass

    def stop(self):
        proc = self.process
        if not proc:
            self.status = "idle"
            return

        self.status = "stopping"
        self.log("Stopping runner process...")
        try:
            # If on Windows, kill process tree
            if sys.platform == "win32":
                subprocess.run(
                    f"taskkill /F /T /PID {proc.pid}",
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                proc.terminate()
        except Exception as e:
            self.log(f"Error while terminating: {e}")
        finally:
            self.status = "idle"
            self.current_task = None
            self.process = None
            self.log("Runner stopped.")


runner_manager = RunnerManager()
