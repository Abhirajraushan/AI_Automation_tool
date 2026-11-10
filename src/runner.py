import hashlib
from datetime import datetime
from pathlib import Path
import re
from collections import Counter
from urllib.parse import parse_qs, urlsplit

from rich.console import Console
from rich.markup import escape

from src.ats import apply_external, detect
from src.config import Settings
from src.core import llm as llm_mod
from src.core.answer_engine import AnswerEngine
from playwright.sync_api import Error as PlaywrightError

from src.core.browser import dump_debug, open_browser, update_live_view
from src.core.human import Human
from src.core.matcher import Matcher
from src.core.models import Job, JobDetail, QuitRun, SkipJob
from src.core.resume_parser import load_resume_text
from src.core.review import Reviewer
from src.core.session import ApplySession
from src.core.tracker import CSV_PATH, Tracker
from src.outreach.linkedin_outreach import LinkedInOutreach
from src.outreach.message import build_pitch, write_prep
from src.outreach.skills import find_skills
from src.sites.linkedin import LinkedInAdapter
from src.sites.mycareernet import MyCareernetAdapter, is_anonymous_company
from src.sites.naukri import NaukriAdapter
from src.sites.randstad import RandstadAdapter
from src.sites.teamlease import TeamLeaseAdapter

ADAPTERS = {"naukri": NaukriAdapter, "linkedin": LinkedInAdapter, "mycareernet": MyCareernetAdapter,
            "teamlease": TeamLeaseAdapter, "randstad": RandstadAdapter}
console = Console()


def _defaults(site: str, cfg: dict) -> dict:
    qs = cfg.get("queries") or []
    kws = [q["keywords"] for q in qs]
    if site == "linkedin" and not kws:
        kws = [parse_qs(urlsplit(u).query).get("keywords", [""])[0] for u in cfg.get("search_urls") or []]
    locs = (qs[0].get("locations") if qs else None) or []
    days = cfg.get("job_age_days") or {"day": 1, "week": 7, "month": 30}.get(cfg.get("date_posted"), 7)
    return {"keywords": [k for k in kws if k], "exp": (qs[0].get("experience") if qs else None) or 2,
            "locations": [l for l in locs if l], "days": days, "sort": cfg.get("sort_by_date", True)}


GENERIC_ROLE_WORDS = {"development", "developer", "engineer", "software", "senior", "junior", "sr", "jr",
                      "sde", "programmer", "lead", "jobs", "job", "remote", "intern", "associate", "application", "and", "or"}
STACK_ALIASES = {
    "golang": ["golang", "go"], "go": ["golang", "go"], "node": ["node", "nodejs", "node.js"],
    "react": ["react", "reactjs", "react.js"], "dotnet": [".net", "dotnet", "c#"],
    "net": [".net", "dotnet", "c#"], "js": ["javascript", "js"],
    "cybersecurity": ["cybersecurity", "cyber security", "infosec", "information security", "security analyst", "soc", "penetration", "appsec"],
    "security": ["security", "cyber", "infosec", "soc", "appsec", "devsecops"],
    "soc": ["soc", "security operations", "siem", "incident response"],
    "infosec": ["infosec", "information security", "cybersecurity"],
    "fullstack": ["full stack", "fullstack", "full-stack", "mern", "mean"],
    "full": ["full stack", "fullstack", "full-stack"],
    "stack": ["full stack", "fullstack", "full-stack"],
    "backend": ["backend", "back end", "back-end", "server-side"],
    "frontend": ["frontend", "front end", "front-end", "ui developer"],
    "devops": ["devops", "sre", "site reliability", "cloud engineer", "platform engineer"]
}


def stack_terms(keywords: str) -> list[str]:
    """'golang developer' -> ['golang', 'go'];  'java full stack developer' -> ['java']."""
    if any(not [w for w in re.findall(r"[a-z0-9+#.]+", k.lower()) if w not in GENERIC_ROLE_WORDS]
           for k in keywords.split(",") if k.strip()):
        return []        # a generic role like "backend development" is in the search: don't filter by stack
    words = [w for w in re.findall(r"[a-z0-9+#.]+", keywords.lower()) if w not in GENERIC_ROLE_WORDS]
    out = []
    for w in words:
        out += STACK_ALIASES.get(w.strip("."), [w])
    return out


SOFTWARE_ROLE = re.compile(
    r"\b(software|sde|swe|backend|back[- ]end|full[- ]?stack|programmer|developer|development engineer|"
    r"application engineer|platform engineer|member of technical staff|mts|java|golang|go|spring|microservices?|api|"
    r"security|cyber|infosec|soc|penetration|pentest|scada|vulnerability|appsec|devsecops)\b", re.I)
SECURITY_ROLE = re.compile(
    r"\b(security|cyber|infosec|soc|penetration|pentest|scada|vulnerability|appsec|devsecops)\b", re.I)
NOT_SOFTWARE_ROLE = re.compile(
    r"\b(test(er|ing)?|qa|quality|automation tester|embedded|firmware|hardware|vlsi|asic|rtl|validation|"
    r"verification|data (analyst|scientist)|analyst|analytics|support|sales|marketing|consultant|"
    r"trainer|training|faculty|teacher|instructor|tutor|professor|lecturer|"
    r"mechanical|electrical|civil|power|modem|camera|kernel|cpu|gpu|dsp|pmic|wlan|cad)\b", re.I)

ABSOLUTE_EXCLUDES = re.compile(
    r"\b(trainer|training|faculty|teacher|instructor|tutor|professor|lecturer|"
    r"data analyst|business analyst|financial analyst|marketing analyst|operations analyst|data analytics|"
    r"data scientist|data science|big data|hadoop|pyspark|databricks|snowflake|power bi|tableau|"
    r"ai engineer|ai / ml|ml engineer|machine learning|genai|prompt engineer|"
    r"sales|marketing|account manager|telecaller|bpo|data entry|technician|operator|"
    r"interior designer|graphic designer|content writer|recruiter|hr executive)\b",
    re.I
)

CITY_ALIASES = {
    "bengaluru": ["bengaluru", "bangalore", "blr", "electronic city", "whitefield"],
    "delhi": ["delhi", "noida", "gurgaon", "gurugram", "ncr", "faridabad", "ghaziabad"],
    "mumbai": ["mumbai", "navi mumbai", "thane"],
    "hyderabad": ["hyderabad", "secunderabad", "cyberabad", "hitec city"],
    "pune": ["pune", "hinjewadi", "magarpatta", "kharadi"],
    "chennai": ["chennai", "madras"],
    "remote": ["remote", "wfh", "work from home", "virtual", "anywhere in india"],
    "bhubaneswar": ["bhubaneswar", "cuttack", "odisha"],
    "kolkata": ["kolkata", "calcutta"],
    "ahmedabad": ["ahmedabad", "gandhinagar"],
    "chandigarh": ["chandigarh", "mohali", "panchkula"],
    "jaipur": ["jaipur", "rajasthan"],
    "kochi": ["kochi", "cochin", "kerala"],
    "indore": ["indore"],
    "lucknow": ["lucknow"]
}


def is_location_match(job_loc: str, allowed_locations: list[str], job_desc: str = "") -> bool:
    """Checks whether the job's location matches candidate's target locations or is Remote."""
    if not allowed_locations:
        return True

    clean_allowed = [l.strip().lower() for l in allowed_locations if l.strip()]
    if not clean_allowed or any(x in clean_allowed for x in ["anywhere", "all india", "india", "flexible", "all", ""]):
        return True

    target_tokens = set()
    for l in clean_allowed:
        target_tokens.add(l)
        for canon, aliases in CITY_ALIASES.items():
            if canon in l or any(a in l for a in aliases):
                target_tokens.update(aliases)
                target_tokens.add(canon)

    job_loc_clean = (job_loc or "").lower().replace("-", " ").replace("/", " ")
    desc_head = (job_desc[:500] or "").lower().replace("-", " ").replace("/", " ") if job_desc else ""

    # Check if job is Remote and user accepts Remote
    is_job_remote = any(k in job_loc_clean or k in desc_head for k in ["remote", "work from home", "wfh", "virtual", "anywhere in india"])
    if is_job_remote and any(k in target_tokens for k in ["remote", "wfh", "work from home", "virtual"]):
        return True

    # If job has an explicit city in job_loc, check against target tokens
    for tok in target_tokens:
        if tok in job_loc_clean:
            return True

    return False

EXCLUDE_TITLE = re.compile(
    r"\b(test(er|ing)?|qa|sdet\d*|quality assurance|guidewire|sap|salesforce|servicenow|mainframe|cobol|"
    r"pega|siebel|plm|enovia|data entry|bpo|voice process|sales|telecaller|technical support|"
    r"support engineer|desktop support|helpdesk)\b", re.I)


def excluded_title(title: str, extra: list[str] | None = None, wanted: str = "") -> bool:
    """Roles you didn't ask for (testers, trainers, data analysts, Guidewire/SAP, support, sales...) — skipped
    before opening the job."""
    if ABSOLUTE_EXCLUDES.search(title):
        return True
    hit = EXCLUDE_TITLE.search(title)
    if hit:
        hit_word = hit.group(0).lower()
        if hit_word in wanted.lower() or SECURITY_ROLE.search(title):
            hit = None
    if not hit and extra:
        hit = next((x for x in extra if x and re.search(rf"\b{re.escape(x)}\b", title, re.I)), None)
    return bool(hit)


def is_software_role(title: str) -> bool:
    """'Software Engineer', 'Java Developer', 'Backend Engineer', 'Security Engineer' yes;
    'Software Tester', 'Embedded Developer', 'Data Analyst', plain 'Engineer' no."""
    if ABSOLUTE_EXCLUDES.search(title):
        return False
    if SECURITY_ROLE.search(title):
        return True
    return bool(SOFTWARE_ROLE.search(title)) and not NOT_SOFTWARE_ROLE.search(title)


def on_stack(terms: list[str], text: str) -> bool:
    if not terms:
        return True
    low = text.lower()
    for t in terms:
        t_low = t.lower()
        if t_low in ("go", "golang"):
            if "Go" in find_skills(text) or "golang" in low or re.search(r"\bgo\b", low):
                return True
        elif re.search(rf"(?<![a-z0-9]){re.escape(t_low)}(?![a-z0-9#])", low):
            return True
        elif t_low in STACK_ALIASES:
            for alias in STACK_ALIASES[t_low]:
                if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9#])", low):
                    return True
    return False


def _naukri_terms(keywords: str) -> str:
    """Show Naukri's own suggestions for each typed keyword; pick by number (Enter = keep yours)."""
    from src.sites.naukri_suggest import suggest
    chosen = []
    for kw in [k.strip() for k in keywords.split(",") if k.strip()]:
        sugg = suggest(kw)
        if not sugg:
            chosen.append(kw)
            continue
        console.print(f"  Naukri terms for [bold]{escape(kw)}[/]: " + "  ".join(f"[cyan]{i}[/] {escape(x)}" for i, x in enumerate(sugg, 1)))
        raw = console.input(escape("    pick numbers (e.g. 1,2), Enter = keep yours > ")).strip()
        picks = [sugg[int(x) - 1] for x in re.findall(r"\d+", raw) if 0 < int(x) <= len(sugg)]
        chosen += picks or [kw]
    return ", ".join(dict.fromkeys(chosen))


def choose_search(site: str, settings: Settings, keywords=None, exp=None, location=None, days=None, ask=True):
    """Ask which stack / experience / location / freshness to search (or take them from CLI flags)
    and rewrite this run's search config. Nothing is saved to search.yaml."""
    if site in ("all", "both"):
        for s in ("linkedin", "naukri"):
            choose_search(s, settings, keywords, exp, location, days, ask=ask)
        return
    cfg = settings.search.setdefault(site, {})
    d = _defaults(site, cfg)
    if ask and keywords is None:
        console.rule(f"[bold]What should I search on {site}?[/] (Enter = keep default)")
        hint = (f"Enter = your {len(cfg['search_urls'])} saved links" if cfg.get("search_urls")
                else ", ".join(d["keywords"]))
        raw = console.input(escape(f"  Stack / role (comma for several) — or paste a {site} search link "
                                   f"[{hint}] > ")).strip()
        if not raw and cfg.get("search_urls"):
            console.print(f"  → using your {len(cfg['search_urls'])} saved {site} search links (search.yaml)")
            if site == "linkedin":
                easy_only = cfg.get("easy_apply_only", False)
                r2 = console.input(escape(f"  Easy Apply only? (n = also company-site jobs) [{'Y/n' if easy_only else 'y/N'}] > ")).strip().lower()
                cfg["easy_apply_only"] = easy_only if not r2 else r2.startswith("y")
            return
        if raw.startswith("http"):
            cfg["search_urls"], cfg["queries"] = [raw], []
            raw2 = console.input(escape(f"  Posted within days (1, 3, 7, 15, 30) [{d['days']}] > ")).strip()
            days = int(raw2) if raw2.isdigit() else d["days"]
            if site == "naukri":
                cfg["job_age_days"] = days
            console.print(f"  → using your link · last {days} day(s) · newest first")
            return
        keywords = raw or ", ".join(d["keywords"])
        if site == "naukri" and raw:
            keywords = _naukri_terms(keywords)
        raw = console.input(escape(f"  Experience in years [{d['exp']}] > ")).strip()
        exp = int(raw) if raw.isdigit() else d["exp"]
        raw = console.input(escape(f"  Locations (comma; '-' = anywhere) [{', '.join(d['locations']) or 'anywhere'}] > ")).strip()
        location = "" if raw == "-" else (raw or ", ".join(d["locations"]))
        raw = console.input(escape(f"  Posted within days (1, 3, 7, 15, 30) [{d['days']}] > ")).strip()
        days = int(raw) if raw.isdigit() else d["days"]
        raw = console.input(escape(f"  Newest first (sort by date)? [{'Y/n' if d['sort'] else 'y/N'}] > ")).strip().lower()
        sort = d["sort"] if not raw else raw.startswith("y")
        if site == "linkedin":
            easy_only = cfg.get("easy_apply_only", False)
            raw = console.input(escape(f"  Easy Apply only? (n = also company-site jobs) [{'Y/n' if easy_only else 'y/N'}] > ")).strip().lower()
            cfg["easy_apply_only"] = easy_only if not raw else raw.startswith("y")
    else:
        sort = d["sort"]
    kws = [k.strip() for k in (keywords if keywords is not None else ", ".join(d["keywords"])).split(",") if k.strip()]
    exp = d["exp"] if exp is None else exp
    locs = [l.strip() for l in (location if location is not None else ", ".join(d["locations"])).split(",") if l.strip()]
    days = d["days"] if days is None else days

    cfg["queries"] = [{"keywords": k, "locations": locs or [""], "experience": exp} for k in kws]
    cfg["search_urls"] = []
    cfg["sort_by_date"] = sort
    if site == "naukri":
        cfg["job_age_days"] = days
    else:
        cfg["date_posted"] = "day" if days <= 1 else "week" if days <= 7 else "month"
        cfg["experience_levels"] = [1, 2] if exp < 2 else [2, 3] if exp < 5 else [3, 4] if exp < 10 else [4, 5]
    console.print(f"  → {', '.join(kws)} · {exp} yrs · {', '.join(locs) or 'anywhere'} · last {days} day(s)"
                  f"{' · newest first' if sort else ''}")


def login(site: str, settings: Settings):
    if site in ("all", "both"):
        for s in ("linkedin", "naukri"):
            login(s, settings)
        return
    adapter = ADAPTERS[site](settings.search, Human(settings.search.get("delays", {})))
    with open_browser(site=site) as page:
        adapter.ensure_logged_in(page)
        update_live_view(page)


def _daily_cap(limits: dict, site: str) -> int:
    return (limits.get("daily_cap_by_site") or {}).get(site, limits.get("daily_cap", 25))


class _LimitReached(Exception):
    pass


def run(site: str, settings: Settings, limit: int | None, dry_run: bool, auto: bool = False,
        retry: bool | None = None, now: bool = False):
    if site in ("all", "both"):
        sites_to_run = ["naukri", "linkedin"]
        applied_total = 0
        for s in sites_to_run:
            console.rule(f"[bold cyan]Starting applications on {s.upper()}[/]")
            try:
                s_applied = run(s, settings, limit, dry_run, auto=auto, retry=retry, now=now)
                if isinstance(s_applied, int):
                    applied_total += s_applied
            except QuitRun:
                console.print(f"[yellow]Run stopped by user during {s}.[/]")
                break
            except Exception as e:
                console.print(f"[bold red]Error running {s}: {e}[/]")
        return applied_total

    retry = auto if retry is None else retry            # --auto re-checks earlier skips unless --no-retry
    session_start = datetime.now().isoformat(timespec="seconds")
    human = Human(settings.search.get("delays", {}))
    adapter = ADAPTERS[site](settings.search, human)
    limits = settings.search.get("limits", {})
    external_on = (settings.search.get("external") or {}).get("enabled", False)
    tracker = Tracker()

    llm = llm_mod.from_env(settings.llm_provider)
    console.print(f"LLM: [bold]{f'{llm.provider} ({llm.model})' if llm else 'none — profile/cache answers only'}[/]")
    resume = load_resume_text(settings.resume_path)
    engine = AnswerEngine(settings.profile, resume, llm)
    matcher = Matcher(settings.profile, resume, llm)
    review_cfg = dict(settings.search.get("review", {}))
    if auto:
        review_cfg.update(confirm_before_apply=False, auto_submit_known=True)
        settings.outreach["ask_after_apply"] = False
        console.print("[bold green]AUTO mode[/]: applies without asking when every answer is known; unknown "
                      "questions still ask you; company sites that need you are done at the END of this run "
                      f"(same session){'; re-checking earlier skipped jobs' if retry else ''}.\n"
                      "  Afterwards: [cyan]python -m src.main outreach --pending 1[/]")
    reviewer = Reviewer(review_cfg)

    cap = _daily_cap(limits, site)
    applied_today = tracker.applied_today(site)
    remaining = cap - applied_today
    if limit:
        if remaining <= 0:
            console.print(f"[yellow]Daily cap ({cap}) was reached, but proceeding with user-specified limit of {limit}.[/]")
            remaining = limit
        else:
            remaining = min(remaining, limit)
    elif remaining <= 0 and not dry_run:
        console.print("Daily cap reached. Come back tomorrow.")
        return
    min_score = limits.get("min_match_score", 0)
    exclude_extra = (settings.search.get("filters") or {}).get("exclude_titles") or []
    ask_low = limits.get("ask_low_match_software", True)
    strict = bool((settings.search.get("filters") or {}).get("strict_stack", True))
    applied = 0

    with open_browser(site=site) as page:
        adapter.ensure_logged_in(page)
        update_live_view(page)
        if site == "naukri" and hasattr(adapter, "sync_resume_to_profile"):
            active_resume_file = Path(settings.resume_path).resolve()
            sync_cache_file = Path("data/naukri_profile_resume.txt")
            last_synced = sync_cache_file.read_text("utf-8").strip() if sync_cache_file.exists() else ""
            if last_synced != active_resume_file.name:
                console.print(f"[bold cyan]Auto-syncing active resume '{active_resume_file.name}' to official Naukri profile...[/]")
                ok, msg = adapter.sync_resume_to_profile(page, active_resume_file)
                if ok:
                    sync_cache_file.write_text(active_resume_file.name, "utf-8")
                    console.print(f"[bold green]✔ Naukri profile updated with: {active_resume_file.name}[/]")
                else:
                    console.print(f"[yellow]Auto-sync resume note: {msg}[/]")
        quit_early = False
        try:
            for query in adapter.queries():
                terms = stack_terms(query.get("keywords", ""))
                found = seen_before = 0
                counts = Counter()
                for job in adapter.search(page, query):
                    found += 1
                    if tracker.seen(job, retry=retry):
                        seen_before += 1
                        continue
                    if excluded_title(job.title, exclude_extra, query.get("keywords", "")):
                        console.print(f"  [dim]not your role: {job.title} — {job.company}[/]")
                        counts["not your role"] += 1
                        if not dry_run:
                            tracker.log(job, "off_stack", note="excluded title")
                        continue

                    # Location Filter Check on Search Card
                    target_locations = [l for l in (query.get("locations") or ([query.get("location")] if query.get("location") else [])) if l]
                    strict_loc = settings.search.get("strict_location", True)
                    if strict_loc and target_locations and job.location:
                        if not is_location_match(job.location, target_locations):
                            console.print(f"  [dim]location mismatch ({job.location}, wanted {', '.join(target_locations)}): {job.title} — {job.company}[/]")
                            counts["location mismatch"] += 1
                            if not dry_run:
                                tracker.log(job, "skipped", score=0, note=f"location mismatch: {job.location}")
                            continue

                    # cards show only ~5 tags -> judge the stack on the card only in strict mode
                    if strict and terms and job.tags and not on_stack(terms, " ".join([job.title, job.snippet, *job.tags])):
                        # If the job title itself is a software/security engineering role, open it to inspect full description
                        if not (is_software_role(job.title) or SECURITY_ROLE.search(job.title)):
                            console.print(f"  [dim]off stack (card): {job.title} — {job.company}  [{', '.join(job.tags[:5])}][/]")
                            counts["off stack"] += 1
                            if not dry_run:
                                tracker.log(job, "off_stack", note="card tags")
                            continue
                    try:
                        detail = adapter.open_job(page, job)
                        update_live_view(page)
                    except Exception as e:
                        console.print(f"  [yellow]could not open job {job.title}:[/] {e}")
                        counts["open_failed"] += 1
                        continue
                    skip = (detail.skip_reason or ("already_applied" if detail.already_applied else
                            "closed" if detail.closed else
                            "external" if detail.external and not external_on else None))
                    if skip:
                        console.print(f"  [dim]{skip}: {job.title} — {job.company}[/]")
                        counts[skip] += 1
                        if not dry_run:
                            tracker.log(job, skip, apply_via="external" if skip == "external" else "")
                        continue

                    # Deep Location Filter Check (verifies full description)
                    if strict_loc and target_locations and not is_location_match(job.location, target_locations, detail.description):
                        console.print(f"  [dim]location mismatch ({job.location or 'unspecified'}, wanted {', '.join(target_locations)}): {job.title} — {job.company}[/]")
                        counts["location mismatch"] += 1
                        if not dry_run:
                            tracker.log(job, "skipped", score=0, note=f"location mismatch: {job.location}")
                        continue

                    score, reason = matcher.score(detail)
                    if not on_stack(terms, f"{job.title}\n{' '.join(job.tags)}\n{detail.description}"):
                        # not the stack you searched — still apply if it fits your resume (strict_stack: false)
                        if strict or score < min_score or not is_software_role(job.title):
                            console.print(f"  [dim]off stack ({'/'.join(terms)} not mentioned, match {score}): "
                                          f"{job.title} — {job.company}[/]")
                            counts["off stack"] += 1
                            if not dry_run:
                                tracker.log(job, "off_stack", score, note=f"wanted {'/'.join(terms)}")
                            continue
                        reason = f"no {'/'.join(terms)}, but fits your skills — {reason}"
                    kind = "external" if detail.external else site
                    if detail.external and not (settings.search.get("external") or {}).get("enabled", True):
                        console.print(f"  [dim]Skipped External Job (external applications disabled): {job.title} — {job.company}[/]")
                        tracker.log(job, "skipped", score, "external disabled")
                        continue
                    low = score < min_score
                    if low:
                        console.print(f"  [dim]Skipped Low Match ({score}/100 < {min_score}): {job.title} — {job.company} ({reason})[/]")
                        counts["low match"] += 1
                        if not dry_run:
                            tracker.log(job, "low_match", score, reason)
                        continue
                    if dry_run:
                        console.print(f"  [green]would {'ask (low match)' if low else 'apply'}[/] {score} [{kind}]: "
                                      f"{job.title} — {job.company}")
                        continue

                    if not reviewer.confirm_apply(detail, score, reason, low_match=low):
                        tracker.log(job, "low_match" if low else "skipped", score, reason if low else "")
                        continue

                    session = ApplySession(detail, engine, reviewer, human, settings.resume_path)
                    try:
                        status, via, ext_url = _apply_one(adapter, page, session, site, now)
                    except SkipJob:
                        continue
                    except Exception as e:
                        console.print(f"  [yellow]error applying to {job.title}:[/] {e}")
                        status, via, ext_url = "failed", site, ""
                    tracker.log(job, status, score, apply_via=via, external_url=ext_url)
                    console.print(f"  → [bold]{status}[/] via {via}")
                    if status.startswith("applied") and settings.outreach.get("ask_after_apply"):
                        referral(page, settings, job.company, job.title, detail.description, resume, reviewer,
                                 human, tracker, company_hint=detail.company_url, job_url=job.url)
                    if status.startswith("applied"):
                        applied += 1
                        console.print(f"  [bold green]✔ [{site.upper()}] Applied so far: {applied}/{remaining} (Total Today: {tracker.applied_today()})[/]")
                        if applied >= remaining:
                            console.print(f"🎉 Reached application limit ({applied} applied).")
                            raise _LimitReached()
                    human.between_jobs()
                console.print(f"  [bold]search summary:[/] {found} found · {seen_before} already in history"
                              f" · {found - seen_before} checked now"
                              + ("" if retry or not seen_before else
                                 "   (re-check skipped/low-match ones with [cyan]--retry[/])"))
                if counts:
                    console.print("  skipped: " + " · ".join(f"{n} {why}" for why, n in counts.most_common()))
                if found and counts["off stack"] + counts["not your role"] >= 0.8 * (found - seen_before):
                    console.print("  [yellow]tip:[/] few jobs for this stack — Naukri pads results with generic ones. "
                                  "Search several stacks (e.g. [cyan]golang developer, java developer, backend developer[/]), "
                                  "use 15/30 days, or set filters.strict_stack: false in search.yaml")
        except _LimitReached:
            pass
        except QuitRun:
            console.print("Stopped by you.")
            quit_early = True
            raise
        if auto and not dry_run and not quit_early:
            applied += _work_queue(page, settings, engine, human, tracker, since=session_start)
        console.print(f"Applied on {site.upper()} this run: [bold]{applied}[/]   History CSV: {CSV_PATH}")
        return applied


def referral(page, settings: Settings, company: str, role: str, job_text: str, resume: str,
             reviewer: Reviewer, human: Human, tracker: Tracker, company_hint: str = "", job_url: str = "",
             ask: bool = True) -> int:
    """Write prep notes, then (after your OK) message people at the company on LinkedIn."""
    cfg = settings.outreach
    if not cfg.get("enabled"):
        return 0
    if is_anonymous_company(company):
        console.print(f"  [dim]referral skipped: company is hidden ({company!r}). If you know it: "
                      f"python -m src.main outreach --company \"<name>\" --role \"{role}\"[/]")
        return 0
    pitch = build_pitch(cfg, role, company, job_text, resume)
    prep = write_prep(pitch, role, company, job_text, job_url)
    console.print(f"  prep notes: {prep}   [dim]skills used: {', '.join(pitch.matched)}[/]")
    if ask:
        if reviewer.choose(f"Message people at [bold]{company}[/] for a referral? [cyan]y[/]/[cyan]n[/]", "yn") == "n":
            return 0
    if company_hint and "/company/" not in company_hint:
        company_hint = ""
    if not company_hint:
        typed = console.input(f"Company name to search on LinkedIn [{company}] > ").strip()
        company = typed or company
    me = re.search(r"/in/([^/?#]+)", settings.profile.get("personal", {}).get("linkedin_url", "") or "")
    out = LinkedInOutreach(cfg, reviewer, human, tracker, me.group(1) if me else "")
    tab = page.context.new_page()
    try:
        return out.run_batch(tab, company, role, pitch, company_hint)
    finally:
        tab.close()
        page.bring_to_front()


def outreach(settings: Settings, companies: list[str] | None, role: str, pending_days: int | None,
             job_url: str = "", people: list[str] | None = None, job_id: str = "", targets_file: str = ""):
    """Standalone: `outreach --company A B C [--role R]`, `outreach --pending 7`, `outreach --person URL`."""
    company = companies[0] if companies else None
    human = Human(settings.search.get("delays", {}))
    tracker = Tracker()
    reviewer = Reviewer(settings.search.get("review", {}))
    resume = load_resume_text(settings.resume_path)
    if people:
        return _contact_people(settings, people, company or "", role, job_url, human, tracker, reviewer, resume)
    default_role = role or settings.outreach.get("default_role", "Software Engineer")
    if companies:
        targets = [{"company": c, "job_id": job_id, "job_url": job_url, "role": default_role} for c in companies]
        return _contact_companies(settings, targets, human, tracker, reviewer, resume)
    if targets_file:
        return _contact_companies(settings, parse_targets_file(targets_file, default_role), human, tracker,
                                  reviewer, resume)
    if pending_days is None:
        targets = ask_targets(default_role)
        if targets:
            _contact_companies(settings, targets, human, tracker, reviewer, resume)
        return
    targets = [(c, t, u, s) for c, t, u, s in tracker.pending_outreach(pending_days or 7)]
    if not targets:
        console.print("Nothing to do: no applied jobs without outreach in that window.")
        return
    with open_browser() as page:
        LinkedInAdapter(settings.search, human).ensure_logged_in(page)
        try:
            for comp, title, url, site in targets:
                console.rule(f"[bold]{comp}[/] — {title}")
                job_text, hint = "", ""
                if url:
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)
                    job_text = page.locator("body").inner_text()[:8000]
                    link = page.locator("main a[href*='/company/']:visible").first
                    hint = (link.get_attribute("href") or "") if site == "linkedin" and link.count() else ""
                referral(page, settings, comp, title, job_text, resume, reviewer, human, tracker,
                         company_hint=hint, job_url=url, ask=True)
        except QuitRun:
            console.print("Stopped by you.")
    console.print(f"Outreach log: data/outreach.csv")


def ask_targets(default_role: str) -> list[dict]:
    """Interactive: company, job ID, job link, role — repeat until Enter on company."""
    console.rule("[bold]Referral outreach[/] — Enter on 'Company name' to start sending")
    targets = []
    while True:
        company = console.input(f"\n[bold]Company name[/] {'(Enter = start)' if targets else ''} > ").strip()
        if not company:
            break
        job_id = console.input("  Job ID (Enter if none) > ").strip()
        job_url = console.input("  Job link (Enter if none) > ").strip()
        role = console.input(f"  Role [{default_role}] > ").strip() or default_role
        targets.append({"company": company, "job_id": job_id, "job_url": job_url, "role": role})
        console.print(f"  [green]added[/] {company} · {role}" + (f" · Job ID {job_id}" if job_id else "")
                      + (" · link" if job_url else ""))
    return targets


def parse_targets_file(path: str, default_role: str) -> list[dict]:
    """companies.txt — one per line:  Company | job id | job link | role   (only Company is required)."""
    out = []
    for line in open(path):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [x.strip() for x in line.split("|")] + ["", "", ""]
        out.append({"company": parts[0], "job_id": parts[1], "job_url": parts[2], "role": parts[3] or default_role})
    return out


def _contact_companies(settings, targets: list[dict], human, tracker, reviewer, resume):
    """For each target find eng leaders + recruiters/HR, approve once per company, send all."""
    cfg = settings.outreach
    me = re.search(r"/in/([^/?#]+)", settings.profile.get("personal", {}).get("linkedin_url", "") or "")
    out = LinkedInOutreach(cfg, reviewer, human, tracker, me.group(1) if me else "")
    total = 0
    with open_browser(site="linkedin") as page:
        LinkedInAdapter(settings.search, human).ensure_logged_in(page)
        try:
            for i, t in enumerate(targets, 1):
                comp, role, job_id, job_url = t["company"], t["role"], t.get("job_id", ""), t.get("job_url", "")
                console.rule(f"[bold]{i}/{len(targets)} · {comp}[/] — {role}" + (f" (Job ID {job_id})" if job_id else ""))
                job_text, hint = "", ""
                if job_url:
                    page.goto(job_url, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)
                    job_text = page.locator("body").inner_text()[:8000]
                    link = page.locator("main a[href*='/company/']:visible").first
                    hint = (link.get_attribute("href") or "") if "linkedin.com" in job_url and link.count() else ""
                applied = bool(job_id or job_url)
                pitch = build_pitch(cfg, role, comp, job_text, resume, general=not applied, job_id=job_id)
                if job_text:
                    console.print(f"  prep notes: {write_prep(pitch, role, comp, job_text, job_url)}")
                total += out.run_batch(page, comp, role, pitch, hint)
                if out.tracker.outreach_today() >= cfg.get("daily_cap", 20):
                    console.print("[yellow]Daily cap reached — stopping.[/]")
                    break
        except QuitRun:
            console.print("Stopped by you.")
    console.print(f"Sent {total} connection notes. Log: data/outreach.csv")


def _contact_people(settings, urls, company, role, job_url, human, tracker, reviewer, resume):
    """outreach --person URL ...: skip the search, contact these profiles with a JD-tailored note."""
    from src.outreach.linkedin_outreach import Person
    with open_browser(site="linkedin") as page:
        LinkedInAdapter(settings.search, human).ensure_logged_in(page)
        job_text = ""
        if job_url:
            page.goto(job_url, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            job_text = page.locator("body").inner_text()[:8000]
        pitch = build_pitch(settings.outreach, role, company, job_text, resume)
        console.print(f"  prep notes: {write_prep(pitch, role, company, job_text, job_url)}")
        out = LinkedInOutreach(settings.outreach, reviewer, human, tracker)
        try:
            for url in urls:
                url = url.split("?")[0]
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
                name = page.locator("main h1").first.inner_text().strip() if page.locator("main h1").count() else ""
                try:
                    status, kind = out.contact(page, Person(name, url, ""), pitch)
                except PlaywrightError as e:
                    dump_debug(page, "outreach-error")
                    console.print(f"[red]browser error:[/] {str(e).splitlines()[0][:150]}")
                    status, kind = "failed", "invite"
                tracker.log_outreach(company, role, name, url, kind, status)
                console.print(f"  {name or url} → [bold]{status}[/] ({kind})")
        except QuitRun:
            console.print("Stopped by you.")


def _apply_one(adapter, page, session: ApplySession, site: str, now: bool = False) -> tuple[str, str, str]:
    """Returns (status, apply_via, external_url)."""
    if not session.detail.external:
        try:
            return adapter.apply(page, session), f"{site}_easy" if site == "linkedin" else site, ""
        except SkipJob:
            return "abandoned", site, ""
        except Exception as e:
            console.print(f"  [yellow]apply error:[/] {e}")
            return "failed", f"{site}_easy" if site == "linkedin" else site, ""

    ext = adapter.open_external(page)
    if ext is None:
        return "failed", "external", ""
    ext_url = ext.url
    if session.reviewer.auto_submit and not now:      # --now: handle company sites immediately instead
        try:
            ext.wait_for_load_state("domcontentloaded")
            ext.wait_for_timeout(2500)
            handler = detect(ext)
            if handler.name in ("generic", "workday"):          # needs you: queue, keep the run moving
                ext_url = ext.url
                if ext is not page:
                    ext.close()
                    page.bring_to_front()
                console.print(f"  [yellow]queued[/] ({handler.name} site needs you) — opens at the end of this run "
                              f"(or use --now to do it immediately)")
                return "queued", handler.name, ext_url
        except Exception as e:
            console.print(f"  [yellow]external check failed:[/] {e}")
    try:
        status, via = apply_external(ext, session)
        ext_url = ext.url
    except SkipJob:
        status, via = "abandoned", "external"
    except Exception as e:
        console.print(f"  [yellow]external apply failed:[/] {e}")
        status, via = "failed", "external"
    finally:
        if ext is not page:
            try:
                ext.close()
            except Exception:
                pass
            try:
                page.bring_to_front()
            except Exception:
                pass
    return status, via, ext_url


def apply_links(urls: list[str], settings: Settings):
    """Apply to job links you give (Workday, Greenhouse, Lever, any careers page)."""
    human = Human(settings.search.get("delays", {}))
    tracker = Tracker()
    llm = llm_mod.from_env(settings.llm_provider)
    console.print(f"LLM: [bold]{f'{llm.provider} ({llm.model})' if llm else 'none — profile/cache answers only'}[/]")
    engine = AnswerEngine(settings.profile, load_resume_text(settings.resume_path), llm)
    reviewer = Reviewer(settings.search.get("review", {}))

    with open_browser() as page:
        for i, url in enumerate(urls, 1):
            console.rule(f"[bold]Link {i}/{len(urls)}[/]")
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            header = page.locator("[data-automation-id='jobPostingHeader'], h1").filter(visible=True)
            host = urlsplit(url).hostname or ""
            job = Job(site="direct", id=hashlib.md5(url.encode()).hexdigest()[:12], url=url,
                      title=(header.first.inner_text().strip() if header.count() else page.title())[:120],
                      company=host.split(".")[0])
            detail = JobDetail(job, description=page.locator("body").inner_text()[:6000], external=True)
            session = ApplySession(detail, engine, reviewer, human, settings.resume_path)
            try:
                status, via = apply_external(page, session)
            except SkipJob:
                status, via = "abandoned", "direct"
            except QuitRun:
                console.print("Stopped by you.")
                break
            tracker.log(job, status, apply_via=via, external_url=page.url)
            console.print(f"  → [bold]{status}[/] via {via}")
            if status.startswith("applied") and settings.outreach.get("ask_after_apply"):
                try:
                    referral(page, settings, job.company, job.title, detail.description, engine.resume_text,
                             reviewer, human, tracker, job_url=url)
                except QuitRun:
                    break
    console.print(f"History CSV: {CSV_PATH}")


def _work_queue(page, settings: Settings, engine, human, tracker, since: str = "") -> int:
    """Company-site jobs queued (unknown sites / Workday logins): fill what's known, you finish,
    the tool learns. since = only rows queued at/after this timestamp (this session). Returns applied."""
    rows = tracker.db.execute(
        "SELECT site, job_id, title, company, url, external_url, location FROM applications "
        "WHERE status='queued' AND updated_at >= ? ORDER BY updated_at", (since,)).fetchall()
    if not rows:
        return 0
    reviewer = Reviewer({**settings.search.get("review", {}), "auto_submit_known": False})
    console.rule(f"[bold magenta]{len(rows)} company-site jobs that need you[/] — s = skip one, q = stop (rest stay queued)")
    applied = 0
    for i, (site, job_id, title, company, url, ext_url, loc) in enumerate(rows, 1):
        console.rule(f"[bold]{i}/{len(rows)} · {company}[/] — {title}")
        job = Job(site=site, id=job_id, title=title, company=company, url=url, location=loc or "")
        page.goto(ext_url or url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        detail = JobDetail(job, description=page.locator("body").inner_text()[:6000], external=True)
        session = ApplySession(detail, engine, reviewer, human, settings.resume_path)
        try:
            status, via = apply_external(page, session)
        except SkipJob:
            status, via = "skipped", "external"
        except QuitRun:
            console.print("Stopped — remaining jobs stay in the queue (python -m src.main apply --queued).")
            break
        tracker.log(job, status, apply_via=via, external_url=page.url)
        console.print(f"  → [bold]{status}[/] via {via}")
        applied += status.startswith("applied")
    return applied


def apply_queued(settings: Settings):
    """`apply --queued`: every queued company-site job, any session."""
    tracker = Tracker()
    if not tracker.db.execute("SELECT 1 FROM applications WHERE status='queued'").fetchone():
        console.print("Queue is empty.")
        return
    human = Human(settings.search.get("delays", {}))
    engine = AnswerEngine(settings.profile, load_resume_text(settings.resume_path),
                          llm_mod.from_env(settings.llm_provider))
    with open_browser() as page:
        _work_queue(page, settings, engine, human, tracker)


def report():
    tracker = Tracker()
    for site, status, n in tracker.summary():
        console.print(f"{site:9} {status:16} {n}")
    console.print("\nRecent:")
    for row in tracker.recent():
        console.print("  " + " | ".join("" if v is None else str(v) for v in row))


def export(applied_only: bool):
    n = Tracker().export_csv(applied_only=applied_only)
    console.print(f"Wrote {n} rows to {CSV_PATH}")
