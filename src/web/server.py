import asyncio
import csv
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from aiohttp import web
import yaml

from src.web.resume_parser import parse_resume
from src.web.runner_manager import runner_manager

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
STATIC_DIR = Path(__file__).parent / "static"


def load_yaml(file_name: str) -> dict:
    path = CONFIG_DIR / file_name
    if not path.exists():
        example_path = CONFIG_DIR / f"{Path(file_name).stem}.example.yaml"
        if example_path.exists():
            try:
                import shutil
                shutil.copyfile(example_path, path)
                return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception:
                pass
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def save_yaml(file_name: str, data: dict):
    path = CONFIG_DIR / file_name
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


# ================== API HANDLERS ==================

async def handle_index(request):
    index_file = STATIC_DIR / "index.html"
    return web.FileResponse(index_file)


async def handle_get_status(request):
    sessions = runner_manager.check_cookie_session()
    applied_today = runner_manager.get_applications_today_count()
    profile = load_yaml("profile.yaml")

    resume_path_rel = profile.get("resume_path", "resume/resume.pdf")
    resume_path = ROOT_DIR / resume_path_rel
    resume_exists = resume_path.exists()
    resume_name = resume_path.name if resume_exists else None

    return web.json_response({
        "status": runner_manager.status,
        "current_task": runner_manager.current_task,
        "current_site": runner_manager.current_site,
        "stats": runner_manager.stats,
        "current_job": runner_manager.current_job,
        "naukri_logged_in": sessions.get("naukri", False),
        "linkedin_logged_in": sessions.get("linkedin", False),
        "applied_today": applied_today,
        "resume_name": resume_name,
        "resume_exists": resume_exists,
        "skills_count": len(profile.get("skills", [])),
    })


async def handle_resume_upload(request):
    reader = await request.multipart()
    resume_dir = DATA_DIR / "resumes"
    resume_dir.mkdir(parents=True, exist_ok=True)

    saved_path = None
    original_filename = ""

    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "resume":
            original_filename = part.filename or "resume.pdf"
            safe_name = f"resume_{int(time.time())}_{Path(original_filename).name}"
            target_path = resume_dir / safe_name
            with open(target_path, "wb") as f:
                while True:
                    chunk = await part.read_chunk()
                    if not chunk:
                        break
                    f.write(chunk)
            saved_path = target_path

    if not saved_path:
        return web.json_response({"success": False, "error": "No resume file uploaded"}, status=400)

    # Synchronize default fallback resume file: resume/resume.pdf
    default_resume = ROOT_DIR / "resume" / "resume.pdf"
    default_resume.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(saved_path, default_resume)
    except Exception as e:
        print(f"[server] Warning: Could not mirror resume.pdf: {e}")

    # Invalidate any cached parsed text so LLM and AnswerEngine reload the new document
    for txt_cache in DATA_DIR.glob("resume_*.txt"):
        try:
            txt_cache.unlink()
        except Exception:
            pass

    # Parse resume details
    parsed = parse_resume(saved_path)

    # Relative path from project root
    rel_path = saved_path.relative_to(ROOT_DIR).as_posix()

    # Update profile.yaml
    profile = load_yaml("profile.yaml")
    profile["resume_path"] = rel_path

    if not profile.get("personal"):
        profile["personal"] = {}
    if parsed["name"]:
        profile["personal"]["full_name"] = parsed["name"]
    if parsed["email"]:
        profile["personal"]["email"] = parsed["email"]
    if parsed["phone"]:
        profile["personal"]["phone"] = parsed["phone"]
    if parsed.get("location"):
        profile["personal"]["current_city"] = parsed["location"]
    if parsed["linkedin_url"] and not profile["personal"].get("linkedin_url"):
        profile["personal"]["linkedin_url"] = parsed["linkedin_url"]
    if parsed["github_url"] and not profile["personal"].get("github_url"):
        profile["personal"]["github_url"] = parsed["github_url"]

    # Merge or set skills
    existing_skills = profile.get("skills") or []
    merged_skills = list(dict.fromkeys(existing_skills + parsed["skills"]))
    profile["skills"] = merged_skills

    if not profile.get("experience"):
        profile["experience"] = {}
    if parsed["experience_years"] is not None:
        profile["experience"]["total_years"] = parsed["experience_years"]
    if parsed["education"]:
        profile["experience"]["highest_education"] = parsed["education"]
    if parsed.get("current_company"):
        profile["experience"]["current_company"] = parsed["current_company"]
    if parsed.get("current_title"):
        profile["experience"]["current_title"] = parsed["current_title"]

    save_yaml("profile.yaml", profile)

    # Also update search.yaml with suggested target roles and exact calculated experience
    search_cfg = load_yaml("search.yaml")
    if parsed["target_roles"]:
        new_queries = []
        for role in parsed["target_roles"]:
            new_queries.append({
                "keywords": role.lower(),
                "locations": [""],
                "experience": parsed["experience_years"] or 0
            })
        if "naukri" in search_cfg:
            search_cfg["naukri"]["queries"] = new_queries
            search_cfg["naukri"]["search_urls"] = []
        if "linkedin" in search_cfg:
            search_cfg["linkedin"]["queries"] = [
                {"keywords": role.lower(), "locations": ["India"]} for role in parsed["target_roles"][:4]
            ]
            search_cfg["linkedin"]["search_urls"] = []
        save_yaml("search.yaml", search_cfg)

    runner_manager.log(f"Active resume synchronized: {original_filename} (Experience: {parsed['experience_label']}, {len(parsed['skills'])} skills)")

    return web.json_response({
        "success": True,
        "filename": original_filename,
        "parsed": parsed,
        "message": f"Resume synchronized! Detected {parsed['experience_label']} with {len(parsed['skills'])} skills. Job search matrix aligned."
    })


async def handle_list_resumes(request):
    """List all resumes in data/resumes with metadata and active state."""
    profile = load_yaml("profile.yaml")
    active_rel = profile.get("resume_path", "")
    active_filename = Path(active_rel).name if active_rel else ""

    resume_dir = DATA_DIR / "resumes"
    resume_dir.mkdir(parents=True, exist_ok=True)

    items = []
    for f in sorted(resume_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True):
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d %b %Y, %H:%M")
        size_kb = round(f.stat().st_size / 1024, 1)
        is_active = (f.name == active_filename)
        display = f.name.replace("resume_", "")
        if "_" in display:
            display = display.split("_", 1)[-1]

        parsed = None
        try:
            parsed = parse_resume(f)
        except Exception:
            pass

        items.append({
            "filename": f.name,
            "display_name": display,
            "modified": mtime,
            "size_kb": size_kb,
            "is_active": is_active,
            "experience_years": parsed.get("experience_years", 2) if parsed else 2,
            "experience_label": parsed.get("experience_label", "2 Years of Experience") if parsed else "2 Years of Experience",
            "skills_count": len(parsed.get("skills", [])) if parsed else 0,
            "top_skills": (parsed.get("skills", [])[:6]) if parsed else [],
            "candidate_name": parsed.get("name", "") if parsed else ""
        })

    return web.json_response({
        "success": True,
        "resumes": items,
        "active_filename": active_filename
    })


async def handle_activate_resume(request):
    """Switch active resume and realign candidate profile and target roles."""
    data = await request.json()
    filename = data.get("filename")
    if not filename:
        return web.json_response({"error": "Filename is required"}, status=400)

    target_path = DATA_DIR / "resumes" / filename
    if not target_path.exists():
        return web.json_response({"error": "Resume file not found"}, status=404)

    rel_path = f"data/resumes/{filename}"
    parsed = parse_resume(target_path)

    # Invalidate cache text files
    for txt_cache in DATA_DIR.glob("resume_*.txt"):
        try:
            txt_cache.unlink()
        except Exception:
            pass

    # Mirror to resume/resume.pdf
    default_resume = ROOT_DIR / "resume" / "resume.pdf"
    default_resume.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(target_path, default_resume)
    except Exception:
        pass

    profile = load_yaml("profile.yaml")
    profile["resume_path"] = rel_path

    if not profile.get("personal"):
        profile["personal"] = {}
    if parsed.get("name"):
        profile["personal"]["full_name"] = parsed["name"]
    if parsed.get("email"):
        profile["personal"]["email"] = parsed["email"]
    if parsed.get("phone"):
        profile["personal"]["phone"] = parsed["phone"]
    if parsed.get("location"):
        profile["personal"]["current_city"] = parsed["location"]
    if parsed.get("linkedin_url"):
        profile["personal"]["linkedin_url"] = parsed["linkedin_url"]
    if parsed.get("github_url"):
        profile["personal"]["github_url"] = parsed["github_url"]

    profile["skills"] = parsed.get("skills", [])
    if not profile.get("experience"):
        profile["experience"] = {}

    exp_years = max(1, parsed.get("experience_years", 2) or 1)
    profile["experience"]["total_years"] = exp_years
    if parsed.get("education"):
        profile["experience"]["highest_education"] = parsed["education"]
    if parsed.get("current_company"):
        profile["experience"]["current_company"] = parsed["current_company"]
    if parsed.get("current_title"):
        profile["experience"]["current_title"] = parsed["current_title"]

    save_yaml("profile.yaml", profile)

    # Also update search.yaml
    search_cfg = load_yaml("search.yaml")
    if parsed.get("target_roles"):
        new_queries = []
        for role in parsed["target_roles"]:
            new_queries.append({
                "keywords": role.lower(),
                "locations": [""],
                "experience": exp_years
            })
        if "naukri" in search_cfg:
            search_cfg["naukri"]["queries"] = new_queries
            search_cfg["naukri"]["search_urls"] = []
        if "linkedin" in search_cfg:
            search_cfg["linkedin"]["queries"] = [
                {"keywords": role.lower(), "locations": ["India"]} for role in parsed["target_roles"][:4]
            ]
            search_cfg["linkedin"]["search_urls"] = []
        save_yaml("search.yaml", search_cfg)

    runner_manager.log(f"Active resume switched to: {filename} ({parsed.get('experience_label', '')})")
    return web.json_response({
        "success": True,
        "active_filename": filename,
        "parsed": parsed,
        "message": f"Active resume successfully switched to '{filename}'."
    })


async def handle_delete_resume(request):
    """Delete a resume file from history."""
    data = await request.json()
    filename = data.get("filename")
    profile = load_yaml("profile.yaml")
    active_rel = profile.get("resume_path", "")
    if filename == Path(active_rel).name:
        return web.json_response({"error": "Cannot delete currently active resume"}, status=400)

    target_path = DATA_DIR / "resumes" / filename
    if target_path.exists():
        target_path.unlink()
        return web.json_response({"success": True})
    return web.json_response({"error": "File not found"}, status=404)


async def handle_sync_naukri_resume(request):
    """Directly synchronizes and uploads the active resume to candidate's Naukri Profile."""
    profile = load_yaml("profile.yaml")
    resume_path_rel = profile.get("resume_path")
    if not resume_path_rel:
        return web.json_response({"error": "No resume is currently active"}, status=400)

    resume_path = ROOT_DIR / resume_path_rel
    if not resume_path.exists():
        return web.json_response({"error": f"Resume file {resume_path.name} not found"}, status=404)

    try:
        from src.sites.naukri import NaukriAdapter
        from src.core.browser import open_browser
        from src.runner import Human

        search_cfg = load_yaml("search.yaml")
        human = Human(search_cfg.get("delays", {}))
        adapter = NaukriAdapter(search_cfg, human)

        runner_manager.log(f"Synchronizing active document '{resume_path.name}' to your official Naukri profile...")
        with open_browser(site="naukri") as page:
            adapter.ensure_logged_in(page)
            ok, msg = adapter.sync_resume_to_profile(page, resume_path)
            if ok:
                sync_cache_file = ROOT_DIR / "data" / "naukri_profile_resume.txt"
                try:
                    sync_cache_file.write_text(resume_path.name, "utf-8")
                except Exception:
                    pass
                runner_manager.log(f"Naukri Profile synced: {msg}")
                return web.json_response({"success": True, "message": msg})
            else:
                runner_manager.log(f"Naukri sync failed: {msg}")
                return web.json_response({"success": False, "error": msg}, status=500)
    except Exception as e:
        runner_manager.log(f"Naukri sync error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_get_naukri_insights(request):
    """Returns cached or active recruiter insights, active CV name, and application statuses."""
    insights_file = DATA_DIR / "naukri_insights.json"
    if insights_file.exists():
        try:
            data = json.loads(insights_file.read_text(encoding="utf-8"))
            return web.json_response(data)
        except Exception:
            pass

    sync_cache_file = DATA_DIR / "naukri_profile_resume.txt"
    last_synced = sync_cache_file.read_text("utf-8").strip() if sync_cache_file.exists() else "Active_Resume.pdf"
    prof = load_yaml("profile.yaml")
    skills_preview = ", ".join(prof.get("skills", ["Python", "Java", "SQL", "Docker", "REST APIs"])[:8])
    return web.json_response({
        "active_resume": last_synced,
        "resume_uploaded_date": time.strftime("Uploaded on %b %d, %Y"),
        "resume_role": prof.get("experience", {}).get("current_title", "Software Engineer"),
        "resume_skills": skills_preview,
        "total_applies": 0,
        "application_updates": 0,
        "recruiter_actions_count": 0,
        "recent_applications": [],
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")
    })


async def handle_fetch_naukri_insights(request):
    """Triggers browser automation to fetch live recruiter actions & active CV status from Naukri."""
    if runner_manager.status != "idle":
        return web.json_response({
            "success": False,
            "error": f"Browser engine is currently busy ({runner_manager.status}). Please wait until the current operation finishes."
        }, status=409)

    runner_manager.status = "fetching_telemetry"
    try:
        from src.sites.naukri import NaukriAdapter
        from src.core.browser import open_browser
        from src.runner import Human

        search_cfg = load_yaml("search.yaml")
        human = Human(search_cfg.get("delays", {}))
        adapter = NaukriAdapter(search_cfg, human)

        runner_manager.log("Fetching live recruiter actions and active resume status from Naukri...")
        loop = asyncio.get_event_loop()

        def _fetch_worker():
            with open_browser(site="naukri") as page:
                adapter.ensure_logged_in(page)
                return adapter.fetch_recruiter_insights(page)

        data = await loop.run_in_executor(None, _fetch_worker)
        insights_file = DATA_DIR / "naukri_insights.json"
        insights_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        runner_manager.log(f"Naukri telemetry updated: {data.get('recruiter_actions_count', 0)} actions, {data.get('total_applies', 0)} total applies.")
        return web.json_response({"success": True, "insights": data})
    except Exception as e:
        runner_manager.log(f"Error fetching Naukri insights: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)
    finally:
        runner_manager.status = "idle"


async def handle_get_profile(request):
    profile = load_yaml("profile.yaml")
    resume_path_rel = profile.get("resume_path", "resume/resume.pdf")
    resume_path = ROOT_DIR / resume_path_rel
    resume_exists = resume_path.exists()
    
    parsed_info = None
    if resume_exists:
        try:
            parsed_info = parse_resume(resume_path)
        except Exception as e:
            print(f"[server] Error parsing existing resume: {e}")

    # Enforce minimum experience baseline (never 0)
    if not profile.get("experience"):
        profile["experience"] = {}
    exp = profile["experience"]
    if not exp.get("total_years") or int(exp.get("total_years", 0)) < 1:
        exp["total_years"] = max(1, (parsed_info.get("experience_years", 2) if parsed_info else 2))

    return web.json_response({
        "profile": profile,
        "resume_exists": resume_exists,
        "resume_name": resume_path.name if resume_exists else None,
        "parsed": parsed_info
    })


async def handle_save_profile(request):
    data = await request.json()
    profile = load_yaml("profile.yaml")

    if "personal" in data:
        profile["personal"] = data["personal"]
    if "skills" in data:
        profile["skills"] = data["skills"]
    if "experience" in data:
        exp = data["experience"]
        if "total_years" in exp:
            exp["total_years"] = max(1, int(exp["total_years"] or 1))
        profile["experience"] = exp
    if "answers" in data:
        profile["answers"] = data["answers"]

    save_yaml("profile.yaml", profile)
    runner_manager.log("Profile configuration updated.")
    return web.json_response({"success": True})


async def handle_get_search(request):
    search_cfg = load_yaml("search.yaml")
    # Simplify for frontend
    naukri_q = search_cfg.get("naukri", {}).get("queries", [])
    keywords = [q.get("keywords") for q in naukri_q if q.get("keywords")]
    experience = naukri_q[0].get("experience", 0) if naukri_q else 0
    locations = naukri_q[0].get("locations", [""]) if naukri_q else [""]
    job_age = search_cfg.get("naukri", {}).get("job_age_days", 7)
    work_mode = search_cfg.get("work_mode", "all")
    strict_location = search_cfg.get("strict_location", True)
    strict_stack = search_cfg.get("filters", {}).get("strict_stack", True)
    skip_external = not search_cfg.get("external", {}).get("enabled", False)

    profile = load_yaml("profile.yaml")
    exp = profile.get("experience", {})

    return web.json_response({
        "keywords": keywords,
        "experience": experience,
        "locations": locations,
        "days": job_age,
        "work_mode": work_mode,
        "strict_location": strict_location,
        "strict_stack": strict_stack,
        "skip_external": skip_external,
        "current_ctc_lpa": exp.get("current_ctc_lpa", 0),
        "expected_ctc_lpa": exp.get("expected_ctc_lpa", 8),
        "notice_period_days": exp.get("notice_period_days", 0),
        "willing_to_relocate": exp.get("willing_to_relocate", True),
        "raw": search_cfg
    })


async def handle_save_search(request):
    data = await request.json()
    search_cfg = load_yaml("search.yaml")

    keywords_list = data.get("keywords", [])
    experience = int(data.get("experience", 0))
    locations = data.get("locations", [""])
    days = int(data.get("days", 7))
    work_mode = data.get("work_mode", "all")
    strict_location = bool(data.get("strict_location", True))

    queries = []
    for kw in keywords_list:
        if kw.strip():
            queries.append({
                "keywords": kw.strip().lower(),
                "locations": locations,
                "experience": experience
            })

    search_cfg["strict_location"] = strict_location
    search_cfg["work_mode"] = work_mode

    if "strict_stack" in data:
        if "filters" not in search_cfg:
            search_cfg["filters"] = {}
        search_cfg["filters"]["strict_stack"] = bool(data["strict_stack"])

    if "skip_external" in data:
        if "external" not in search_cfg:
            search_cfg["external"] = {}
        search_cfg["external"]["enabled"] = not bool(data["skip_external"])

    if "naukri" not in search_cfg:
        search_cfg["naukri"] = {}
    search_cfg["naukri"]["queries"] = queries
    search_cfg["naukri"]["search_urls"] = []
    search_cfg["naukri"]["job_age_days"] = days
    search_cfg["naukri"]["work_mode"] = work_mode

    if "linkedin" not in search_cfg:
        search_cfg["linkedin"] = {}
    search_cfg["linkedin"]["queries"] = [
        {"keywords": kw.strip().lower(), "locations": locations or ["India"]} for kw in keywords_list
    ]
    search_cfg["linkedin"]["search_urls"] = []
    search_cfg["linkedin"]["work_mode"] = work_mode

    save_yaml("search.yaml", search_cfg)

    # Also update screening answers in profile.yaml if provided
    profile = load_yaml("profile.yaml")
    if not profile.get("experience"):
        profile["experience"] = {}

    if "expected_ctc_lpa" in data:
        profile["experience"]["expected_ctc_lpa"] = float(data["expected_ctc_lpa"])
    if "current_ctc_lpa" in data:
        profile["experience"]["current_ctc_lpa"] = float(data["current_ctc_lpa"])
    if "notice_period_days" in data:
        profile["experience"]["notice_period_days"] = int(data["notice_period_days"])
    if "willing_to_relocate" in data:
        profile["experience"]["willing_to_relocate"] = bool(data["willing_to_relocate"])

    save_yaml("profile.yaml", profile)

    runner_manager.log(f"Job search matrix saved: Locations={locations}, WorkMode={work_mode}, StrictLoc={strict_location}, StrictStack={search_cfg.get('filters', {}).get('strict_stack', True)}, SkipExt={not search_cfg.get('external', {}).get('enabled', False)}")
    return web.json_response({"success": True})


async def handle_start_login(request):
    data = await request.json()
    site = data.get("site", "naukri")
    try:
        runner_manager.start_login(site)
        return web.json_response({"success": True, "message": f"Browser opened for {site.upper()} login"})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)


async def handle_confirm_login(request):
    runner_manager.confirm_login_input()
    return web.json_response({"success": True})


async def handle_start_apply(request):
    data = await request.json()
    site = data.get("site", "naukri")
    limit = int(data.get("limit", 25))
    auto = bool(data.get("auto", True))
    retry = bool(data.get("retry", True))
    dry_run = bool(data.get("dry_run", False))
    profile = data.get("profile")

    try:
        runner_manager.start_apply(
            site=site, limit=limit, auto=auto, retry=retry, dry_run=dry_run, profile=profile
        )
        return web.json_response({"success": True, "message": "Application runner started!"})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)


async def handle_stop_apply(request):
    runner_manager.stop()
    return web.json_response({"success": True, "message": "Stopped"})


async def handle_get_history(request):
    search_term = request.query.get("q", "").strip().lower()
    status_filter = request.query.get("status", "all")
    site_filter = request.query.get("site", "all")
    limit = int(request.query.get("limit", 100))

    db_path = DATA_DIR / "applications.db"
    if not db_path.exists():
        return web.json_response({"applications": [], "total": 0})

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    query = "SELECT site, job_id, title, company, location, status, score, updated_at, url, external_url FROM applications WHERE 1=1"
    params = []

    if status_filter in ("applied", "submitted"):
        query += " AND status IN ('applied', 'applied_manual')"
    elif status_filter in ("skipped", "filtered"):
        query += " AND status NOT IN ('applied', 'applied_manual')"

    if site_filter != "all":
        query += " AND site = ?"
        params.append(site_filter)

    if search_term:
        query += " AND (LOWER(company) LIKE ? OR LOWER(title) LIKE ?)"
        params.append(f"%{search_term}%")
        params.append(f"%{search_term}%")

    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    rows = cur.execute(query, params).fetchall()
    results = [dict(row) for row in rows]
    conn.close()

    return web.json_response({
        "applications": results,
        "total": len(results)
    })


async def handle_export_csv(request):
    csv_path = DATA_DIR / "applications.csv"
    if not csv_path.exists():
        return web.Response(text="No applications recorded yet.", status=404)
    return web.FileResponse(
        csv_path,
        headers={"Content-Disposition": 'attachment; filename="job_applications.csv"'}
    )


async def handle_reset_session(request):
    try:
        # Check if site target was specified: "naukri", "linkedin", or "all"
        target_site = "all"
        if request.can_read_body:
            try:
                data = await request.json()
                if isinstance(data, dict):
                    target_site = str(data.get("site", "all")).lower().strip()
            except Exception:
                pass
        if not target_site or target_site == "all":
            query_site = request.query.get("site")
            if query_site:
                target_site = query_site.lower().strip()

        # Kill browsers cleanly
        if sys.platform == "win32":
            subprocess.run("taskkill /f /im msedge.exe 2>nul & taskkill /f /im chrome.exe 2>nul", shell=True, capture_output=True)
        time.sleep(1)

        cleared = []
        if target_site in ("naukri", "all"):
            p_naukri = DATA_DIR / "chrome-profile-naukri"
            if p_naukri.exists():
                shutil.rmtree(p_naukri, ignore_errors=True)
                cleared.append("Naukri")
        if target_site in ("linkedin", "all"):
            p_linkedin = DATA_DIR / "chrome-profile-linkedin"
            if p_linkedin.exists():
                shutil.rmtree(p_linkedin, ignore_errors=True)
                cleared.append("LinkedIn")
        if target_site == "all":
            p_generic = DATA_DIR / "chrome-profile"
            if p_generic.exists():
                shutil.rmtree(p_generic, ignore_errors=True)
                cleared.append("Legacy Shared Profile")

        msg = f"Purged saved session for: {', '.join(cleared)}." if cleared else "No stored session profile found to purge."
        runner_manager.log(f"Session purge: {msg}")
        return web.json_response({"success": True, "message": msg, "cleared": cleared})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


# ================== WEBSOCKET HANDLER ==================

async def handle_websocket(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    runner_manager.add_ws(ws)
    # Send initial welcome state
    await ws.send_json({
        "type": "init",
        "status": runner_manager.status,
        "current_task": runner_manager.current_task,
        "stats": runner_manager.stats,
        "current_job": runner_manager.current_job,
        "logs": runner_manager.logs[-50:]
    })

    try:
        async for msg in ws:
            pass
    finally:
        runner_manager.remove_ws(ws)

    return ws


async def handle_live_preview(request):
    preview_file = DATA_DIR / "live_preview.png"
    if not preview_file.exists():
        return web.Response(status=404)
    return web.FileResponse(preview_file, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


def create_app() -> web.Application:
    app = web.Application()

    # Route definitions
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/status", handle_get_status)
    app.router.add_get("/api/live-preview", handle_live_preview)
    app.router.add_get("/api/resumes", handle_list_resumes)
    app.router.add_post("/api/resumes/activate", handle_activate_resume)
    app.router.add_post("/api/resumes/delete", handle_delete_resume)
    app.router.add_post("/api/naukri/sync_resume", handle_sync_naukri_resume)
    app.router.add_get("/api/naukri/insights", handle_get_naukri_insights)
    app.router.add_post("/api/naukri/insights/fetch", handle_fetch_naukri_insights)
    app.router.add_post("/api/resume/upload", handle_resume_upload)
    app.router.add_get("/api/profile", handle_get_profile)
    app.router.add_post("/api/profile", handle_save_profile)
    app.router.add_get("/api/search", handle_get_search)
    app.router.add_post("/api/search", handle_save_search)
    app.router.add_post("/api/login", handle_start_login)
    app.router.add_post("/api/login/confirm", handle_confirm_login)
    app.router.add_post("/api/apply/start", handle_start_apply)
    app.router.add_post("/api/apply/stop", handle_stop_apply)
    app.router.add_get("/api/history", handle_get_history)
    app.router.add_get("/api/export", handle_export_csv)
    app.router.add_post("/api/reset-session", handle_reset_session)
    app.router.add_get("/ws/live", handle_websocket)

    # Static files
    app.router.add_static("/static", STATIC_DIR)

    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"==================================================")
    print(f"🚀 RAUSHONIX AI — Autonomous Placement Engine running!")
    print(f"👉 Open in your browser: http://localhost:{port}")
    print(f"==================================================")
    app = create_app()
    web.run_app(app, host="127.0.0.1", port=port)

