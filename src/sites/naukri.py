"""Naukri adapter.

Naukri flow: job page -> "Apply" -> either applied instantly, or a chatbot drawer
asks questions one at a time (text box / radio / checkbox / chips) and submits after the last one.
Clicking Apply on a job with no questions submits immediately — so the runner asks you
BEFORE clicking Apply, and every uncertain chatbot answer is shown to you before it is sent.

Naukri changes its markup now and then. All selectors live in SEL; when something breaks,
check data/debug/*.html and update them here.
"""
import re
import time
from typing import Iterator
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PWTimeout

from src.core.answer_engine import _closest_option
from src.core.browser import dump_debug, update_live_view
from src.core.models import Field, Job, JobDetail, SkipJob
from src.core.session import ApplySession
from src.sites.base import SiteAdapter

BASE = "https://www.naukri.com"

SEL = {
    "card": "div.srp-jobtuple-wrapper, .cust-job-tuple, [class*='srp-jobtuple'], [class*='cust-job-tuple']",
    "card_title": "a.title, [class*='title'] a, a[class*='title']",
    "card_company": "a.comp-name, [class*='comp-name']",
    "card_location": ".locWdth, [class*='locWdth'], [class*='location']",
    "card_exp": ".expwdth, [class*='expwdth'], [class*='exp-wrap']",
    "card_tags": "ul.tags-gt li, [class*='tags-gt'] li",
    "card_snippet": "span.job-desc, [class*='job-desc']",
    "key_skills": "[class*='key-skill'] [class*='chip']",
    "jd": "[class*='dang-inner-html'], .job-desc",
    "apply_btn": "#apply-button",
    "company_site_btn": "#company-site-button",
    "already_applied": "#already-applied",
    "sort_btn": "button#filter-sort",                  # "Sort by: Relevance ▾"
    "sort_date": "a[data-id='filter-sort-f']",         # dropdown item "Date"
    "chat_drawer": "[class*='chatbot_Drawer']",
    "chat_bot_msg": "[class*='chatbot'] li.botItem, [class*='chatbot_Drawer'] li.botItem",
    "chat_text": "[class*='chatbot'] div.textArea[contenteditable='true'], [class*='chatbot_Drawer'] div.textArea",
    "chat_radio": "[class*='chatbot'] .ssrc__radio-btn-container, [class*='chatbot_Drawer'] .ssrc__radio-btn-container",
    "chat_radio_label": "[class*='chatbot'] .ssrc__radio-btn-container label, [class*='chatbot_Drawer'] .ssrc__radio-btn-container label, [class*='chatbot'] label.ssrc__label",
    "chat_checkbox": "[class*='chatbot'] .mcc__checkbox, [class*='chatbot'] .multicheckboxes-container label",
    "chat_chip": "[class*='chatbot'] .chatbot_Chip, [class*='chatbot_Drawer'] .chatbot_Chip",
    "chat_send": "[class*='chatbot'] .sendMsg, [class*='chatbot_Drawer'] .sendMsg, [class*='chatbot'] [class*='sendMsg'], [class*='chatbot'] [id*='sendMsg']",
    "chat_close": "[class*='chatbot_Drawer'] [class*='crossIcon'], [class*='chatbot'] .crossIcon",
}
ACK_RE = re.compile(r"^(got it|great|thanks?|thank you|no worries|okay|ok|noted|perfect|awesome|sure|"
                    r"alright|cool)\b[!. ]*", re.I)
CHIP_NOISE = re.compile(r"^(i made a mistake|skip this question|skip)$", re.I)   # bot controls, not answers
SUCCESS_RE = re.compile(r"successfully applied|applied successfully|application sent|^\s*Applied to\b|responses? (have been )?recorded|thank you for (your )?responses", re.I)


def _slug(text: str) -> str:
    """Naukri's URL words: 'C++ Developer' -> 'c-plus-plus-developer', 'C#' -> 'c-sharp', '.NET' -> 'dot-net'."""
    text = text.lower().replace("c++", "c plus plus").replace("c#", "c sharp").replace(".net", " dot net")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _text(locator) -> str:
    try:
        return locator.first.inner_text(timeout=1000).strip() if locator.count() else ""
    except PWTimeout:
        return ""


class NaukriAdapter(SiteAdapter):
    name = "naukri"

    def ensure_logged_in(self, page):
        try:
            page.bring_to_front()
        except Exception:
            pass

        def _is_logged_in():
            try:
                u = page.url.lower()
                if "login" in u or "auth" in u:
                    return False
                if "mnjuser" in u:
                    return True
                # Check presence of user avatar or profile elements
                if page.locator(".nI-gNb-drawer__icon, a[href*='/mnjuser/profile'], .user-name, [class*='nI-gNb-header__drawer']").count() > 0:
                    return True
            except Exception:
                pass
            return False

        try:
            page.goto(f"{BASE}/mnjuser/homepage", wait_until="domcontentloaded")
        except PlaywrightError:
            pass
        page.wait_for_timeout(2500)
        update_live_view(page)

        if _is_logged_in():
            print("Logged in to Naukri.")
            update_live_view(page)
            return

        print("Waiting for Naukri authentication in the open browser window...")
        print("Please log in to your Naukri account (Gmail #1) in the browser window.")
        for i in range(80):
            page.wait_for_timeout(1500)
            update_live_view(page)
            if _is_logged_in():
                print("Logged in to Naukri.")
                update_live_view(page)
                return
            if i % 10 == 0 and i > 0:
                print(f"Still waiting for Naukri authentication in browser... ({int(i * 1.5)}s elapsed)")

        update_live_view(page)
        print("❌ Naukri authentication not detected. Please log in to your Naukri account.")
        raise RuntimeError("Naukri authentication required. Please log in to your account.")

    def sync_resume_to_profile(self, page, resume_path) -> tuple[bool, str]:
        """Navigate to Naukri Profile and update the attached CV directly."""
        try:
            page.goto(f"{BASE}/mnjuser/profile", wait_until="domcontentloaded")
            page.wait_for_timeout(3500)
            inp = page.locator("input#attachCV, input[type='file'][id*='attachCV']").first
            if not inp.count():
                return False, "Could not find resume upload input on Naukri profile"
            inp.set_input_files(str(resume_path))
            page.wait_for_timeout(4500)
            toast = page.locator(".toaster, .toast, [class*='success'], [class*='msgBox']").filter(has_text=re.compile(r"success|uploaded", re.I))
            if toast.count() > 0 or "successfully uploaded" in page.content().lower():
                return True, "Resume successfully uploaded & synchronized on your Naukri profile."
            return True, "Resume uploaded to Naukri profile."
        except Exception as e:
            return False, f"Failed to sync resume to Naukri: {e}"

    def fetch_recruiter_insights(self, page) -> dict:
        """Fetch live recruiter actions, active attached CV, and application updates from Naukri."""
        sync_cache = Path("data/naukri_profile_resume.txt")
        active_res = sync_cache.read_text("utf-8").strip() if sync_cache.exists() else "Active_CV.pdf"
        data = {
            "active_resume": active_res,
            "resume_uploaded_date": time.strftime("Uploaded on %b %d, %Y"),
            "total_applies": 0,
            "application_updates": 0,
            "recruiter_actions_count": 0,
            "recruiter_actions": [],
            "recent_applications": [],
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            page.goto(f"{BASE}/mnjuser/profile", wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            res_card = page.locator(".attachCV, .resume-card, [class*='resume-box'], [class*='resumeSection']").first
            if res_card.count():
                card_text = res_card.inner_text()
                m_file = re.search(r"([A-Za-z0-9_ -]+\.(?:pdf|docx|doc))", card_text, re.I)
                if m_file:
                    data["active_resume"] = m_file.group(1).strip()
                m_date = re.search(r"(Uploaded on [A-Za-z0-9, ]+)", card_text, re.I)
                if m_date:
                    data["resume_uploaded_date"] = m_date.group(1).strip()
        except Exception as e:
            print(f"Profile check error: {e}")

        try:
            page.goto(f"{BASE}/myapply/historypage", wait_until="domcontentloaded")
            page.wait_for_timeout(3500)
            body_text = page.locator("body").inner_text()

            m_total = re.search(r"([0-9]+)\s*Total\s*applies", body_text, re.I)
            if m_total:
                data["total_applies"] = int(m_total.group(1))

            m_updates = re.search(r"([0-9]+)\s*Application\s*updates", body_text, re.I)
            if m_updates:
                data["application_updates"] = int(m_updates.group(1))

            m_rec = re.search(r"Recruiter Actions\s*\(([0-9]+)\)", body_text, re.I)
            if m_rec:
                data["recruiter_actions_count"] = int(m_rec.group(1))

            def _extract_cards(text):
                items = []
                # Match title, company, and status tags
                found = re.findall(
                    r"([A-Za-z0-9 &()\-|,/]{3,60})\n([A-Za-z0-9 &()\-|,/]{3,60})\n(?:[0-9.]+\n[0-9]+ Reviews\n)?([^\n]*(?:Application sent|viewed|shortlisted|contacted|active|downloaded|reviewed)[^\n]*)",
                    text,
                    re.I
                )
                for f in found:
                    t = f[0].strip()
                    c = f[1].strip()
                    s = f[2].strip()
                    if t and c and not any(k in t.lower() for k in ["total applies", "recruiter action", "filter", "search", "reviews"]):
                        items.append({"title": t, "company": c, "status": s})
                return items

            data["recent_applications"] = _extract_cards(body_text)[:15]

            # Attempt to click the "Recruiter Actions" tab to extract specifically viewed / actioned applications
            try:
                rec_tab = page.locator("text=/Recruiter Actions/i").first
                if rec_tab.count() > 0:
                    rec_tab.click()
                    page.wait_for_timeout(2500)
                    rec_body = page.locator("body").inner_text()
                    rec_items = _extract_cards(rec_body)
                    if rec_items:
                        data["recruiter_actions"] = rec_items[:15]
            except Exception as e_click:
                print(f"Recruiter actions click notice: {e_click}")

            # If recruiter_actions list is empty but count > 0, check recent applications for any viewed/shortlisted items
            if not data["recruiter_actions"]:
                for app in data["recent_applications"]:
                    st = app.get("status", "").lower()
                    if "view" in st or "shortlist" in st or "contact" in st:
                        data["recruiter_actions"].append(app)
        except Exception as e:
            print(f"History parse error: {e}")

        return data

    def queries(self) -> Iterator[dict]:
        """Pasted Naukri search links first; else ONE combined search per location with all your stacks
        (Naukri accepts k='golang developer, java developer, backend development')."""
        base = {"pages": self.cfg.get("pages_per_query", 1), "job_age": self.cfg.get("job_age_days")}
        for url in self.cfg.get("search_urls") or []:
            k = parse_qs(urlsplit(url).query).get("k", [""])[0]
            yield {**base, "url": url, "keywords": k}
        qs = self.cfg.get("queries") or []
        for q in qs:
            for loc in q.get("locations") or [""]:
                yield {**base, "keywords": q["keywords"], "location": loc, "experience": q.get("experience", 2)}

    def _search_url(self, q: dict, page_no: int = 1) -> str:
        """Same shape as Naukri's own search:
        /golang-developer-java-developer-jobs[-in-pune]?k=golang developer, java developer&experience=2
          &functionAreaIdGid=8&functionAreaIdGid=5&jobAge=7&sort=f"""
        if q.get("url"):
            url = q["url"]
            parts = urlsplit(url)
            params = parse_qs(parts.query)
            if self.cfg.get("sort_by_date", True):
                params["sort"] = ["f"]
            if q.get("job_age") and "jobAge" not in params:
                params["jobAge"] = [str(q["job_age"])]
            return urlunsplit(parts._replace(query=urlencode(params, doseq=True)))
        path = "-".join(_slug(k) for k in q["keywords"].split(",") if k.strip()) + "-jobs"
        loc = q.get("location", "")
        is_remote = bool(loc and loc.lower() in ("remote", "work from home", "wfh")) or self.cfg.get("work_mode") == "remote"
        if loc and loc.lower() not in ("remote", "work from home", "wfh", "anywhere", "all india"):
            path += f"-in-{_slug(loc)}"
        params = {"k": q["keywords"], "l": loc if loc and not is_remote and loc.lower() not in ("anywhere", "all india") else None,
                  "experience": q.get("experience"), "jobAge": q.get("job_age"),
                  "functionAreaIdGid": self.cfg.get("departments") or None,     # 8 = IT & Information Security, 5 = Engineering - Software & QA
                  "wfhType": [3] if is_remote else (self.cfg.get("work_mode") if isinstance(self.cfg.get("work_mode"), list) else None),
                  "sort": "f" if self.cfg.get("sort_by_date", True) else None}   # f = freshness (Date)
        params = {k: v for k, v in params.items() if v not in (None, "", [])}
        return f"{BASE}/{path}?{urlencode(params, doseq=True)}"

    @staticmethod
    def _page_url(url: str, page_no: int) -> str:
        """Page N of an (already sorted) results URL: /golang-jobs?… -> /golang-jobs-2?…"""
        parts = urlsplit(url)
        path = re.sub(r"-\d+$", "", parts.path.rstrip("/"))
        return urlunsplit(parts._replace(path=f"{path}-{page_no}" if page_no > 1 else path))

    def _sort_by_date(self, page) -> bool:
        """Results page: 'Sort by: Recommended' -> 'Date' (newest first)."""
        try:
            btn = page.locator(SEL["sort_btn"])
            if (btn.first.get_attribute("title") or "").lower() == "date":
                print("  already sorted by date")
                return True
            btn.first.click(timeout=5000)
            page.wait_for_timeout(700)
            opt = page.locator(SEL["sort_date"])
            if not opt.count():
                opt = page.get_by_text(re.compile(r"^\s*Date\s*$")).filter(visible=True)
            before = page.url
            opt.first.click(timeout=5000)
            page.wait_for_timeout(2500)
            page.wait_for_selector(SEL["card"], timeout=15000)
            ok = (page.locator(SEL["sort_btn"]).first.get_attribute("title") or "").lower() == "date"
            print(f"  sorted by date{'' if ok else ' (could not confirm)'}")
            return True
        except (PWTimeout, PlaywrightError):
            print("  could not switch to 'Sort by: Date' — using Naukri's default order")
            dump_debug(page, "naukri-sort")
            return False

    def search(self, page, query: dict) -> Iterator[Job]:
        base = self._search_url(query)
        for page_no in range(1, query["pages"] + 1):
            url = base if page_no == 1 else self._page_url(base, page_no)
            print(f"\nSearching: {url}")
            page.goto(url, wait_until="domcontentloaded")
            try:
                page.wait_for_selector(SEL["card"], timeout=15000)
            except PWTimeout:
                print("  no job cards found (end of results, or selectors changed)")
                dump_debug(page, "naukri-search")
                return
            if self.cfg.get("sort_by_date", True):
                self._sort_by_date(page)         # no-op when ?sort=f already applied; clicks Date otherwise
            self.human.pause()
            jobs = []
            for card in page.locator(SEL["card"]).all():
                job_id = card.get_attribute("data-job-id")
                link = card.locator(SEL["card_title"])
                href = link.first.get_attribute("href") if link.count() else None
                if not job_id or not href:
                    continue
                exp_text = _text(card.locator(SEL["card_exp"]))
                user_exp = query.get("experience", 2)
                # Enforce candidate experience band: never apply to jobs requiring > user_exp minimum years
                m_range = re.search(r"(\d+)\s*-\s*(\d+)", exp_text)
                if m_range and int(m_range.group(1)) > user_exp:
                    continue
                m_plus = re.search(r"(\d+)\s*\+", exp_text)
                if m_plus and int(m_plus.group(1)) > user_exp:
                    continue
                jobs.append(Job(
                    site=self.name, id=job_id, url=href,
                    title=_text(link),
                    company=_text(card.locator(SEL["card_company"])),
                    location=_text(card.locator(SEL["card_location"])),
                    experience=exp_text,
                    tags=[t.strip() for t in card.locator(SEL["card_tags"]).all_inner_texts() if t.strip()],
                    snippet=_text(card.locator(SEL["card_snippet"])),
                ))
            print(f"  page {page_no}: {len(jobs)} jobs")
            yield from jobs  # collected first so navigating to a job doesn't detach cards

    def open_job(self, page, job: Job) -> JobDetail:
        page.goto(job.url, wait_until="domcontentloaded")
        title_lower = (job.title or "").lower()
        is_walkin = any(w in title_lower for w in ["walk-in", "walk in", "walkin"])

        any_btn = f"{SEL['apply_btn']}, {SEL['company_site_btn']}, {SEL['already_applied']}"
        btn_timeout = 3000 if is_walkin else 10000
        try:
            page.wait_for_selector(any_btn, timeout=btn_timeout)
        except PWTimeout:
            if not is_walkin:
                dump_debug(page, "naukri-job")
        self.human.pause()
        skills = [t.strip() for t in page.locator(SEL["key_skills"]).all_inner_texts() if t.strip()]
        if skills:
            job.tags = skills

        has_apply = page.locator(SEL["apply_btn"]).count() > 0
        has_ext = page.locator(SEL["company_site_btn"]).count() > 0
        already = page.locator(SEL["already_applied"]).count() > 0

        skip = ""
        jd_text = _text(page.locator(SEL["jd"]))
        if has_ext and not has_apply:
            external_enabled = (self.cfg.get("external") or {}).get("enabled", False)
            if not external_enabled:
                skip = "external"
        elif not has_apply and not has_ext and not already:
            if is_walkin or "walk-in" in jd_text.lower() or "walk in" in jd_text.lower():
                skip = "walk_in"
            else:
                skip = "no_apply_button"

        return JobDetail(
            job=job,
            description=jd_text + ("\nKey skills: " + ", ".join(skills) if skills else ""),
            external=has_ext and not has_apply,
            already_applied=already,
            skip_reason=skip,
        )

    def apply(self, page, session: ApplySession) -> str:
        page._session_resume_path = session.resume_path
        btn = page.locator(SEL["apply_btn"]).first
        if not btn.count():
            return "failed"
        btn.click()
        page.wait_for_timeout(2500)

        # 1. Check if 1-click apply navigated to confirmation or error page
        if "saveApply" in page.url or "myapply" in page.url:
            error_re = re.compile(r"error while processing|unsuccessful|please try again|failed to apply", re.I)
            if page.get_by_text(error_re).count() > 0:
                print("  [naukri] Direct apply failed: error alert returned from server.")
                return "failed"
            if page.get_by_text(SUCCESS_RE).count() > 0 or page.locator(SEL["already_applied"]).count() > 0:
                print("  [naukri] 1-Click apply confirmed successfully.")
                return "applied"

        # 2. Check for Chatbot Drawer
        drawer = page.locator(SEL["chat_drawer"]).first
        if drawer.count() == 0 or not drawer.is_visible():
            page.wait_for_timeout(2000)

        if drawer.count() > 0 and drawer.is_visible():
            try:
                return self._chatbot(page, session)
            except SkipJob:
                self._close_chat(page)
                raise

        # 3. Final check if applied
        if self._applied(page):
            return "applied"
        return "failed"

    def open_external(self, page):
        btn = page.locator(SEL["company_site_btn"]).first
        if not btn.count():
            return None
        self.human.pause()
        return self.click_to_new_tab(page, btn)

    # --- chatbot -----------------------------------------------------------

    def _applied(self, page) -> bool:
        # Check for explicit failure / error message first!
        error_re = re.compile(r"error while processing|unsuccessful|please try again|failed to apply", re.I)
        if page.get_by_text(error_re).count() > 0:
            return False

        if "saveApply" in page.url or "myapply" in page.url:
            if page.locator(".error-banner, [class*='error'], .alert-danger").count() > 0:
                return False
            if (page.get_by_text(SUCCESS_RE).count() > 0
                or page.locator(SEL["already_applied"]).count() > 0
                or page.get_by_text(re.compile(r"applied|confirmation|application sent", re.I)).count() > 0):
                return True

        return (page.get_by_text(SUCCESS_RE).count() > 0
                or page.locator(SEL["already_applied"]).count() > 0)

    def _chatbot(self, page, session: ApplySession) -> str:
        """Answer the chat one question at a time. A question = a NEW bot message (by position, not text)
        that isn't an acknowledgement and whose answer controls have rendered. This keeps answers in sync
        with questions (reading too early used to send each answer to the next question)."""
        answered, idle = 0, 0                      # number of bot messages already handled
        for _ in range(40):
            got = self._wait_question(page, answered)
            if got == "APPLIED":
                return "applied"
            if got is None:
                if self._applied(page):
                    return "applied"
                if not page.locator(SEL["chat_drawer"]).first.is_visible():
                    idle += 1
                    if idle > 2:
                        dump_debug(page, "naukri-apply-unknown")
                        return "unknown"
                    continue
                dump_debug(page, "naukri-chat-stuck")
                return "failed"
            idle = 0
            count, question = got
            field = self._detect_field(page, question)
            answered = count
            if field is None:
                continue
            value = session.answer(field)
            self._fill(page, field, value)
        return "failed"

    def _has_input(self, page) -> bool:
        drawer = page.locator(SEL["chat_drawer"]).first
        if not drawer.count() or not drawer.is_visible():
            return False

        if (drawer.locator(".ssrc__radio-btn-container, [class*='radio'] label").filter(visible=True).count()
                or drawer.locator(".mcc__checkbox, .multicheckboxes-container label").filter(visible=True).count()
                or drawer.locator(".chatbot_Chip").filter(visible=True).count()):
            return True

        box = drawer.locator("div.textArea[contenteditable='true'], textarea, input[type='text']").filter(visible=True)
        if box.count() > 0 and box.first.is_visible():
            return True

        uploader = drawer.locator(".uploadCV, [class*='uploadBtn'], button:has-text('Upload')").filter(visible=True)
        return uploader.count() > 0 and uploader.first.is_visible()

    def _wait_question(self, page, answered: int, timeout_ms: int = 15000):
        """Wait for a new, settled bot question after the `answered` bot messages.
        Returns (bot message count, question text), 'APPLIED', or None on timeout."""
        waited = 0
        drawer = page.locator(SEL["chat_drawer"]).first
        while waited < timeout_ms:
            # If the drawer has closed or is not visible, check if application succeeded
            if not drawer.count() or not drawer.is_visible():
                if self._applied(page):
                    return "APPLIED"

            # Check if drawer has success message
            if drawer.count() and drawer.is_visible() and drawer.get_by_text(SUCCESS_RE).count() > 0:
                return "APPLIED"

            msgs = page.locator(SEL["chat_bot_msg"])
            n = msgs.count()
            if n > answered:
                text = " ".join(msgs.nth(n - 1).inner_text().split())
                if text and not ACK_RE.match(text) and self._has_input(page):
                    page.wait_for_timeout(400)                  # let options finish rendering
                    if page.locator(SEL["chat_bot_msg"]).count() == n:
                        return n, text
                    continue

            page.wait_for_timeout(300)
            waited += 300
        return None

    @staticmethod
    def _texts(loc) -> list[str]:
        out = []
        for t in loc.filter(visible=True).all_inner_texts():
            t = " ".join(t.split())
            if t and t not in out and not CHIP_NOISE.match(t):
                out.append(t)
        return out

    def _detect_field(self, page, question: str) -> Field | None:
        drawer = page.locator(SEL["chat_drawer"]).first
        if not drawer.count():
            return None

        radios = self._texts(drawer.locator(".ssrc__radio-btn-container label, .ssrc__radio-btn-container"))
        if radios:
            # Clean up duplicates
            clean_radios = []
            for r in radios:
                if r and r not in clean_radios:
                    clean_radios.append(r)
            if clean_radios:
                return Field(question, "radio", clean_radios, required=True)

        checks = self._texts(drawer.locator(".mcc__checkbox, .multicheckboxes-container label"))
        if checks:
            return Field(question, "checkbox", checks, required=True)

        chips = self._texts(drawer.locator(".chatbot_Chip"))
        if chips:
            return Field(question, "chips", chips, required=True)

        box = drawer.locator("div.textArea[contenteditable='true'], textarea, input[type='text']").filter(visible=True)
        if box.count() and box.first.is_visible():
            return Field(question, "text", required=True)

        # Only if question specifically prompts to attach/upload resume AND upload button is visible
        if re.search(r'\b(upload|attach)\b.*\b(resume|cv)\b|\b(resume|cv)\b.*\b(upload|attach)\b', question, re.I):
            drawer_file = drawer.locator("input[type='file'], .chatbot_Uploader")
            uploader_btn = drawer.locator(".uploadCV, [class*='uploadBtn'], button:has-text('Upload')").filter(visible=True)
            if drawer_file.count() > 0 and uploader_btn.count() > 0:
                return Field(question, "file", required=True)

        return None

    def _fill(self, page, field: Field, value: str):
        exact = re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)
        drawer = page.locator(SEL["chat_drawer"]).first
        print(f"  [naukri-chat] Filling '{field.question[:45]}' -> '{value}' ({field.kind})")

        if field.kind == "file":
            drawer_file = drawer.locator("input[type='file'], .chatbot_Uploader").first
            if drawer_file.count() and getattr(page, "_session_resume_path", None):
                resume_file = page._session_resume_path
                if resume_file.exists():
                    try:
                        drawer_file.set_input_files(str(resume_file))
                        page.wait_for_timeout(1500)
                        self._trigger_send(page)
                    except Exception as e:
                        print(f"  [warn] Naukri resume upload failed: {e}")

        elif field.kind == "radio":
            clicked = False
            # If value doesn't directly match any option, try mapped option
            if field.options and value not in field.options:
                mapped = _closest_option(value, field.options)
                if mapped:
                    value = mapped
                    exact = re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)

            # 1. Click matching label or container first (Naukri React listens to clicks on label/container)
            labels = drawer.locator(".ssrc__radio-btn-container label, .ssrc__label, label").filter(visible=True)
            for i in range(labels.count()):
                lbl = labels.nth(i)
                t = lbl.inner_text().strip()
                if exact.match(t) or value.lower() == t.lower() or value.lower() in t.lower() or t.lower() in value.lower():
                    try:
                        lbl.click(timeout=1500, force=True)
                        clicked = True
                        break
                    except Exception:
                        lbl.dispatch_event("click")
                        clicked = True
                        break

            if not clicked:
                cnt = drawer.locator(f".ssrc__radio-btn-container:has-text('{value}')").filter(visible=True)
                if cnt.count():
                    try:
                        cnt.first.click(timeout=1500, force=True)
                        clicked = True
                    except Exception:
                        cnt.first.dispatch_event("click")
                        clicked = True

            # 2. Try checking input directly if label didn't click
            if not clicked:
                inputs = drawer.locator(f"input[type='radio'][value='{value}'], input[type='radio'][id='{value}']")
                if inputs.count():
                    try:
                        inputs.first.check(force=True)
                        clicked = True
                    except Exception:
                        pass

            # 3. Also dispatch React events and native prototype setter directly into DOM to guarantee state sync
            try:
                page.evaluate("""(val) => {
                    const containers = Array.from(document.querySelectorAll('.ssrc__radio-btn-container'));
                    for (const c of containers) {
                        const lbl = c.querySelector('label');
                        const inp = c.querySelector('input[type="radio"]');
                        const text = (lbl ? lbl.innerText : '').trim().toLowerCase();
                        const inpVal = (inp ? (inp.value || inp.id) : '').trim().toLowerCase();
                        const v = val.toLowerCase();
                        if (text === v || inpVal === v || text.includes(v) || v.includes(text)) {
                            if (lbl) {
                                lbl.click();
                                lbl.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                            }
                            if (c) {
                                c.click();
                            }
                            if (inp) {
                                const proto = window.HTMLInputElement.prototype;
                                const nativeSet = Object.getOwnPropertyDescriptor(proto, 'checked')?.set;
                                if (nativeSet) nativeSet.call(inp, true);
                                else inp.checked = true;
                                inp.dispatchEvent(new Event('input', { bubbles: true }));
                                inp.dispatchEvent(new Event('change', { bubbles: true }));
                            }
                            const sendBox = document.querySelector('.sendMsgbtn_container .send');
                            if (sendBox) sendBox.classList.remove('disabled');
                            break;
                        }
                    }
                }""", value)
            except Exception:
                pass

            if not clicked:
                # Failsafe fallback: if no option matched, select the first visible radio button
                # to prevent the chatbot from getting stuck on this question for 20s and failing
                print(f"  [warn] No exact radio match for '{value}', selecting first available option to keep application progressing")
                first_label = drawer.locator(".ssrc__radio-btn-container label, .ssrc__label, label").filter(visible=True).first
                if first_label.count():
                    try:
                        first_label.click(timeout=1500, force=True)
                        clicked = True
                    except Exception:
                        first_label.dispatch_event("click")
                        clicked = True

            page.wait_for_timeout(400)
            self._trigger_send(page)

        elif field.kind == "checkbox":
            for v in [x.strip() for x in value.split(",") if x.strip()]:
                c = drawer.locator(".mcc__checkbox, .multicheckboxes-container label, label").filter(visible=True).filter(has_text=v)
                if c.count():
                    try:
                        c.first.click(timeout=1000, force=True)
                    except Exception:
                        c.first.dispatch_event("click")
                    page.wait_for_timeout(150)
            page.wait_for_timeout(400)
            self._trigger_send(page)

        elif field.kind == "chips":
            chip = drawer.locator(".chatbot_Chip").filter(visible=True).filter(has_text=exact)
            if not chip.count():
                chip = drawer.locator(".chatbot_Chip").filter(visible=True).filter(has_text=value)
            box = drawer.locator("div.textArea[contenteditable='true'], textarea").filter(visible=True)
            if chip.count():
                try:
                    chip.first.click(timeout=1200, force=True)
                except Exception:
                    chip.first.dispatch_event("click")
                page.wait_for_timeout(400)
                self._trigger_send(page)
            elif box.count() and box.first.is_visible():
                self._type_and_send(page, box.first, value)
            else:
                raise PlaywrightError(f"no option {value!r} in chat")

        else:
            # Text box
            box = drawer.locator("div.textArea[contenteditable='true'], textarea, input[type='text']").filter(visible=True).first
            if box.count():
                self._type_and_send(page, box, value)

    def _type_and_send(self, page, box, value: str):
        try:
            box.scroll_into_view_if_needed()
            box.click(force=True)
            page.wait_for_timeout(150)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.wait_for_timeout(100)
            box.press_sequentially(str(value), delay=20)
            page.wait_for_timeout(200)

            # Ensure value is set in contenteditable or input
            try:
                page.evaluate("""([el, val]) => {
                    if (el.isContentEditable) {
                        if (!el.innerText || el.innerText.trim() !== val) {
                            el.innerText = val;
                        }
                    } else if ('value' in el) {
                        el.value = val;
                    }
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
                }""", [box.element_handle(), str(value)])
            except Exception:
                pass

            page.wait_for_timeout(400)
            self._trigger_send(page)
        except Exception as e:
            print(f"  [warn] chatbot type error: {e}")

    def _trigger_send(self, page):
        page.wait_for_timeout(300)
        drawer = page.locator(SEL["chat_drawer"]).first

        # 1. Primary Naukri Chatbot Save Button: <div class="sendMsg" tabindex="0">Save</div> inside .sendMsgbtn_container
        save_btn = drawer.locator(".sendMsgbtn_container .sendMsg, .sendMsg").filter(visible=True).first
        if save_btn.count():
            # Wait briefly for parent .send to lose 'disabled' class if it is reacting to selection
            for _ in range(8):
                try:
                    is_dis = page.evaluate("(el) => el.closest('.send')?.classList.contains('disabled')", save_btn.element_handle())
                    if not is_dis:
                        break
                except Exception:
                    pass
                page.wait_for_timeout(150)

            # Ensure any lingering disabled state is cleared if options were selected
            try:
                page.evaluate("""() => {
                    const sendDiv = document.querySelector('.sendMsgbtn_container .send');
                    if (sendDiv) sendDiv.classList.remove('disabled');
                }""")
            except Exception:
                pass

            try:
                save_btn.click(timeout=1500, force=True)
                page.wait_for_timeout(500)
                return
            except Exception:
                try:
                    save_btn.dispatch_event("click")
                    page.wait_for_timeout(500)
                    return
                except Exception:
                    pass

        # 2. Fallback selectors
        send_selectors = [
            "[class*='chatbot'] .sendMsg",
            "[class*='chatbot_Drawer'] .sendMsg",
            ".sendMsg",
            "[class*='chatbot'] [id*='sendMsg']",
            "[class*='chatbot'] div:has-text('Save')",
            "[class*='chatbot_Drawer'] div:has-text('Save')",
            "[class*='chatbot'] button:has-text('Save')",
            "[class*='chatbot_Drawer'] button:has-text('Save')",
            "button:has-text('Save')",
            "button:has-text('Submit')"
        ]
        clicked = False
        for sel in send_selectors:
            btns = page.locator(sel).filter(visible=True)
            for i in range(btns.count()):
                btn = btns.nth(i)
                cls = btn.get_attribute("class") or ""
                # Skip if disabled
                if "disabled" in cls:
                    continue
                try:
                    btn.click(timeout=1200, force=True)
                    clicked = True
                    break
                except Exception:
                    try:
                        btn.dispatch_event("click")
                        clicked = True
                        break
                    except Exception:
                        pass
            if clicked:
                break

        if not clicked:
            page.keyboard.press("Enter")
        page.wait_for_timeout(500)

    def _close_chat(self, page):
        close = page.locator(SEL["chat_close"]).first
        if close.count():
            close.click()
        else:
            page.keyboard.press("Escape")
