import os
from contextlib import contextmanager
from datetime import datetime

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from pathlib import Path
from src.config import DATA_DIR

PROFILE_DIR = DATA_DIR / "chrome-profile"   # fallback profile


def get_profile_dir(site: str = "") -> Path:
    """Return dedicated, isolated browser profile directory for each hiring channel."""
    site_clean = (site or "").strip().lower()
    if "linkedin" in site_clean:
        target = DATA_DIR / "chrome-profile-linkedin"
    elif "naukri" in site_clean:
        target = DATA_DIR / "chrome-profile-naukri"
    else:
        target = DATA_DIR / "chrome-profile"
    target.mkdir(parents=True, exist_ok=True)
    # Clear orphaned locks to prevent Playwright lock hangs
    for lock_name in ("LOCK", "SingletonLock", "SingletonSocket", "SingletonCookie"):
        for base in (target, target / "Default"):
            lock_file = base / lock_name
            if lock_file.exists():
                try:
                    lock_file.unlink()
                except Exception:
                    pass
    return target


def kill_orphaned_profile_processes(profile_dir: Path):
    """Safely terminate orphaned browser child processes holding locks on this profile."""
    import sys
    import subprocess
    if sys.platform != "win32":
        return
    try:
        cmd = f'powershell -Command "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {{ $_.CommandLine -like \'*{profile_dir.name}*\' }} | Select-Object -ExpandProperty ProcessId"'
        out = subprocess.check_output(cmd, shell=True).decode()
        for p in out.split():
            p = p.strip()
            if p.isdigit() and int(p) != os.getpid():
                subprocess.run(f"taskkill /F /T /PID {p} 2>nul", shell=True)
    except Exception:
        pass


@contextmanager
def open_browser(site: str = ""):
    profile_dir = get_profile_dir(site)
    with sync_playwright() as pw:
        is_headless = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")
        opts = dict(
            user_data_dir=str(profile_dir),
            headless=is_headless,
            viewport=None,
            ignore_default_args=["--enable-automation"],
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
            ],
        )
        browser_channel = os.getenv("BROWSER_CHANNEL", "msedge").strip()
        browser_path = os.getenv("BROWSER_PATH", "").strip()   # any Chromium browser: Brave, Edge...

        def _launch():
            if browser_path:
                return pw.chromium.launch_persistent_context(executable_path=browser_path, **opts)
            elif browser_channel:
                try:
                    return pw.chromium.launch_persistent_context(channel=browser_channel, **opts)
                except PlaywrightError:
                    try:
                        return pw.chromium.launch_persistent_context(channel="chrome", **opts)
                    except PlaywrightError:
                        return pw.chromium.launch_persistent_context(**opts)
            else:
                try:
                    return pw.chromium.launch_persistent_context(channel="chrome", **opts)
                except PlaywrightError:
                    return pw.chromium.launch_persistent_context(**opts)

        try:
            ctx = _launch()
        except PlaywrightError as e:
            if "already in use" in str(e).lower() or "existing browser session" in str(e).lower():
                # Profile lock conflict: kill orphans for this profile and retry once
                kill_orphaned_profile_processes(profile_dir)
                import time
                time.sleep(1.2)
                for lock_name in ("LOCK", "SingletonLock", "SingletonSocket", "SingletonCookie"):
                    for base in (profile_dir, profile_dir / "Default"):
                        lf = base / lock_name
                        if lf.exists():
                            try:
                                lf.unlink()
                            except Exception:
                                pass
                ctx = _launch()
            else:
                raise
        ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.bring_to_front()
        except Exception:
            pass
        try:
            yield page
        finally:
            ctx.close()


def update_live_view(page):
    """Save quick viewport screenshot for real-time frontend monitoring."""
    try:
        preview = DATA_DIR / "live_preview.png"
        page.screenshot(path=str(preview), full_page=False)
    except Exception:
        pass


def dump_debug(page, tag: str):
    """Save screenshot + HTML when something unexpected happens, to fix selectors."""
    out = DATA_DIR / "debug"
    out.mkdir(exist_ok=True)
    stem = out / f"{datetime.now():%Y%m%d-%H%M%S}-{tag}"
    try:
        page.screenshot(path=f"{stem}.png", full_page=True)
        (stem.with_suffix(".html")).write_text(page.content(), encoding="utf-8")
        print(f"  [debug] saved {stem}.png/.html")
    except Exception:
        pass
