"""LinkedIn adapter (new 2026 jobs UI at /jobs/search-results/, with fallbacks for the classic UI).

Flow, all on the search page:
  search URL -> read job cards -> click a card -> details pane on the right ->
    * "Easy Apply": multi-step modal (rendered inside a shadow DOM) filled step by step by
      FormFiller; you see a full summary before "Submit application".
    * "Apply on company website" (a link): its URL is opened in a new tab and handed to src/ats.
  -> next card ... -> "Page 2" button -> ...

New UI class names are obfuscated, so selectors use componentkey / aria-label / role / text.
LinkedIn is strict about automation: keep daily_cap low (~15) and delays human.
"""
import re
from typing import Iterator
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PWTimeout

from src.core.browser import dump_debug, update_live_view
from src.core.forms import FormFiller
from src.core.models import Job, JobDetail, SkipJob
from src.core.review import console
from src.core.session import ApplySession
from src.sites.base import SiteAdapter

BASE = "https://www.linkedin.com"
DATE_POSTED = {"day": "r86400", "week": "r604800", "month": "r2592000"}

CARD_NEW = "div[role='button'][componentkey^='job-card-component-ref-'], .job-card-container, div[data-job-id]"
CARD_OLD = "[data-occludable-job-id], li[data-job-id], li.jobs-search-results__list-item, div.jobs-search-results-list__list-item"
SEL = {
    "external": "a[aria-label*='company website' i]:visible, "
                "button.jobs-apply-button:visible:not(:has-text('Easy Apply'))",
    "modal": "dialog[open], [data-testid='dialog']:visible, .jobs-easy-apply-modal:visible, [role='dialog']:visible",
    "error": ".artdeco-inline-feedback--error:visible, [role='alert']:visible",
    "description": "[data-testid='expandable-text-box'], #job-details, .jobs-description__content",
}
EASY_RE = re.compile(r"\bEasy Apply\b", re.I)
NEXT_RE = re.compile(r"^(next|continue|continue to next step)$", re.I)
REVIEW_RE = re.compile(r"^review( your application)?$", re.I)
SUBMIT_RE = re.compile(r"^submit( application)?$", re.I)
APPLIED_RE = re.compile(r"Applied \d+ \w+ ago|Application submitted|You applied", re.I)
CLOSED_RE = re.compile(r"No longer accepting applications", re.I)
SENT_RE = re.compile(r"application was sent|Application sent|application was submitted", re.I)

CARDS_JS = """(sel) => [...document.querySelectorAll(sel)].map(c => {
  const rootCard = c.closest('li, [data-occludable-job-id], .jobs-search-results__list-item, .job-card-container') || c;
  const key = c.getAttribute('componentkey') || rootCard.getAttribute('componentkey') || '';
  let id = key.replace('job-card-component-ref-', '') 
           || c.getAttribute('data-occludable-job-id')
           || rootCard.getAttribute('data-occludable-job-id')
           || c.getAttribute('data-job-id')
           || rootCard.getAttribute('data-job-id');
  if (!id) {
    const link = rootCard.querySelector('a[href*="/jobs/view/"], a[data-job-id]') || c.querySelector('a[href*="/jobs/view/"], a[data-job-id]');
    if (link) {
      id = link.getAttribute('data-job-id') || (link.getAttribute('href') || '').match(/\\/jobs\\/view\\/([0-9]+)/)?.[1] || '';
    }
  }
  const dismiss = rootCard.querySelector('button[aria-label^="Dismiss"]');
  let title = dismiss ? dismiss.getAttribute('aria-label').replace(/^Dismiss\\s+/, '').replace(/\\s+job$/, '') : '';
  if (!title) {
    const titleEl = rootCard.querySelector('.job-card-list__title, a.job-card-container__link, strong, h3, a[href*="/jobs/view/"]');
    if (titleEl) title = (titleEl.innerText || '').trim();
  }

  let company = '';
  const compEl = rootCard.querySelector('.job-card-container__primary-description, .artdeco-entity-lockup__subtitle, [class*="company"]');
  if (compEl) company = (compEl.innerText || '').trim();

  let location = '';
  const locEl = rootCard.querySelector('.job-card-container__metadata-item, .artdeco-entity-lockup__caption, [class*="location"]');
  if (locEl) location = (locEl.innerText || '').trim();

  if (!company || !location) {
    const ps = [...rootCard.querySelectorAll('p, .artdeco-entity-lockup__subtitle, .artdeco-entity-lockup__caption, .job-card-container__primary-description')]
      .map(p => ((p.querySelector('span[aria-hidden="true"]') || p).innerText || '').trim()).filter(Boolean);
    if (!title && ps[0]) title = ps[0];
    const rest = ps.filter(t => t !== title);
    if (!company && rest[0]) company = rest[0];
    if (!location && rest[1]) location = rest[1];
  }
  
  const textC = c.innerText || '';
  const textRoot = rootCard.innerText || '';
  const combinedText = (textRoot + ' ' + textC).replace(/\\s+/g, ' ');
  
  const isEasy = /Easy Apply/i.test(combinedText);
  const footerState = rootCard.querySelector('.job-card-container__footer-job-state, [class*="footer-job-state"], [class*="applied"]');
  const checkIcon = rootCard.querySelector('li-icon[type*="check"], svg[data-test-app-aware-link], [aria-label*="applied" i]');
  const isApplied = /\\bApplied\\b|Application submitted|You applied|Applied \\d+/i.test(combinedText)
                    || (footerState && /applied/i.test(footerState.innerText || ''))
                    || !!checkIcon;

  return {
    id: String(id || ''),
    title: title || 'Job Posting',
    company: company || 'Company',
    location: location || '',
    easy: isEasy,
    applied: !!isApplied
  };
})"""


class LinkedInAdapter(SiteAdapter):
    name = "linkedin"

    def ensure_logged_in(self, page):
        try:
            page.bring_to_front()
        except Exception:
            pass

        def _is_logged_in():
            try:
                u = page.url.lower()
                # If on explicit unauthenticated landing or login page
                if any(x in u for x in ["/login", "/authwall", "/checkpoint/challenge", "/signup"]):
                    return False
                if any(x in u for x in ["/feed", "/mynetwork", "/in/", "/jobs"]):
                    # Verify global navigation or user profile elements exist
                    if page.locator("nav.global-nav, #global-nav, .global-nav__me, button[aria-label*='Me'], a[href*='/in/'], [data-control-name='nav.settings_signout']").count() > 0:
                        return True
                    # If on feed or jobs without login forms
                    if page.locator("input#username, input#session_key, form.login__form, form.join-form").count() == 0:
                        return True
            except Exception:
                pass
            return False

        try:
            if not ("/feed" in page.url or "/in/" in page.url or "/jobs" in page.url):
                page.goto(f"{BASE}/feed/", wait_until="domcontentloaded")
        except PlaywrightError:
            pass
        page.wait_for_timeout(2500)
        update_live_view(page)

        if _is_logged_in():
            print("Logged in to LinkedIn.")
            update_live_view(page)
            return

        print("Waiting for LinkedIn authentication in the open browser window...")
        print("Please log in to your LinkedIn account in the browser window. The dashboard live mirror is updating.")
        for i in range(80):
            page.wait_for_timeout(1500)
            update_live_view(page)
            if _is_logged_in():
                print("Logged in to LinkedIn.")
                update_live_view(page)
                return
            if i % 10 == 0 and i > 0:
                print(f"Still waiting for LinkedIn authentication in browser... ({int(i * 1.5)}s elapsed)")

        update_live_view(page)
        print("❌ LinkedIn authentication not detected. Please log in to LinkedIn first.")
        raise RuntimeError("LinkedIn authentication required. Please log in to your account.")

    # --- search ----------------------------------------------------------------

    def queries(self) -> Iterator[dict]:
        for url in self.cfg.get("search_urls") or []:
            yield {"url": url}
        for q in self.cfg.get("queries") or []:
            for loc in q.get("locations") or [""]:
                yield {"url": self._search_url(q["keywords"], loc), "keywords": q["keywords"]}

    def _search_url(self, keywords: str, location: str) -> str:
        params = {"keywords": keywords}
        if location:
            if location.lower() in ("remote", "work from home", "wfh"):
                params["f_WT"] = "2"
                params["location"] = "India"
            elif location.lower() not in ("anywhere", "all india"):
                params["location"] = location

        work_mode = str(self.cfg.get("work_mode", "")).lower()
        if "remote" in work_mode:
            params["f_WT"] = "2"
        elif "hybrid" in work_mode:
            params["f_WT"] = "3"
        elif "onsite" in work_mode or "on_site" in work_mode:
            params["f_WT"] = "1"

        if self.cfg.get("date_posted") in DATE_POSTED:
            params["f_TPR"] = DATE_POSTED[self.cfg["date_posted"]]
        if self.cfg.get("experience_levels"):
            params["f_E"] = ",".join(str(x) for x in self.cfg["experience_levels"])
        if self.cfg.get("easy_apply_only", False):
            params["f_AL"] = "true"
        # Target full-time engineering employment
        emp_type = self.cfg.get("employment_type", "full_time")
        if emp_type in ("full_time", "F"):
            params["f_JT"] = "F"
        if self.cfg.get("sort_by_date", True):
            params["sortBy"] = "DD"          # most recent first
        return f"{BASE}/jobs/search-results/?{urlencode(params)}"

    TRACKING = {"currentJobId", "eBP", "refId", "trackingId", "origin", "referralSearchId", "geoId_ref"}

    def clean_url(self, url: str) -> str:
        """Pasted LinkedIn link -> drop tracking params; add entry-level filter (f_E), full-time (f_JT),
        easy apply (f_AL), and newest-first sort when the link doesn't set them."""
        parts = urlsplit(url)
        params = {k: v for k, v in parse_qs(parts.query).items() if k not in self.TRACKING}
        if "f_E" not in params and self.cfg.get("experience_levels"):
            params["f_E"] = [",".join(str(x) for x in self.cfg["experience_levels"])]
        if self.cfg.get("sort_by_date", True) and "sortBy" not in params:
            params["sortBy"] = ["DD"]
        if self.cfg.get("easy_apply_only") and "f_AL" not in params:
            params["f_AL"] = ["true"]
        if "f_JT" not in params:
            params["f_JT"] = ["F"]
        return urlunsplit(parts._replace(query=urlencode(params, doseq=True)))

    def search(self, page, query: dict) -> Iterator[Job]:
        url = self.clean_url(query["url"])
        print(f"\nSearching: {url}")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        update_live_view(page)
        self.search_url = url
        easy_only = self.cfg.get("easy_apply_only", False)
        for page_no in range(1, self.cfg.get("pages_per_query", 1) + 1):
            if page_no > 1 and not self._goto_page(page, page_no):
                return
            try:
                page.wait_for_selector(f"{CARD_NEW}, {CARD_OLD}", timeout=15000)
            except PWTimeout:
                print("  no job cards found (end of results, or selectors changed)")
                dump_debug(page, "linkedin-search")
                update_live_view(page)
                return
            self._scroll_results(page)
            update_live_view(page)
            sel = CARD_NEW if page.locator(CARD_NEW).count() else CARD_OLD
            cards, seen = [], set()
            for c in page.evaluate(CARDS_JS, sel):
                if c["id"] and c["id"] not in seen:
                    seen.add(c["id"])
                    cards.append(c)
            print(f"  page {page_no}: {len(cards)} jobs "
                  f"({sum(c['easy'] for c in cards)} Easy Apply, {sum(c['applied'] for c in cards)} already applied)")
            for c in cards:
                if c["applied"]:
                    print(f"  [fast-skip] already applied on LinkedIn: {c['title']} — {c['company']}")
                    continue
                if easy_only and not c["easy"]:
                    continue
                yield Job(site=self.name, id=c["id"], url=f"{BASE}/jobs/view/{c['id']}/",
                          title=c["title"], company=c["company"], location=c["location"])

    def _goto_page(self, page, page_no: int) -> bool:
        btn = page.locator(f"button[aria-label='Page {page_no}']").first
        if not btn.count():
            return False
        self.human.pause()
        btn.click()
        page.wait_for_timeout(3000)
        update_live_view(page)
        return True

    def _scroll_results(self, page):
        """The results list lazy-loads cards as it scrolls; scroll its container to the bottom."""
        page.evaluate("""async (sel) => {
            let el = document.querySelector(sel);
            while (el && el.scrollHeight <= el.clientHeight + 5) el = el.parentElement;
            if (!el) return;
            for (let y = 0; y <= el.scrollHeight; y += 350) {
                el.scrollTop = y;
                await new Promise(r => setTimeout(r, 200 + Math.random() * 200));
            }
            el.scrollTop = 0;
        }""", f"{CARD_NEW}, {CARD_OLD}")

    # --- job details -------------------------------------------------------------

    def _easy_btn(self, page):
        # 1. Primary Easy Apply button in top card / details pane
        btn = page.locator(".jobs-apply-button:visible, button.jobs-apply-button:visible, .jobs-s-apply:visible button, button[data-job-id]:has-text('Easy Apply')")
        if btn.count():
            return btn.first
        # 2. Inside details container
        details = page.locator(".jobs-search__job-details, .job-view-layout, [data-view-name*='job-details'], .jobs-details, div.job-details-jobs-unified-top-card__container--two-pane, main")
        if details.count():
            b = (details.locator("button:visible, a:visible").filter(has_text=EASY_RE)
                 .or_(details.locator("button[aria-label*='Easy Apply' i]:visible")))
            if b.count():
                return b.first
        # 3. Visible button with Easy Apply, excluding top search bar filter pills
        return (page.locator("button:visible:not([class*='pill']):not([id*='pill']):not([role*='tab'])")
                .filter(has_text=EASY_RE)
                .or_(page.locator("button[aria-label*='Easy Apply' i]:visible:not([class*='pill']):not([id*='pill'])"))
                .first)

    def open_job(self, page, job: Job) -> JobDetail:
        if page.locator("dialog[open], [data-testid='dialog']:visible, .jobs-easy-apply-modal:visible, [role='dialog']:visible").count():
            self._discard(page)

        # 1. Locate the specific card for THIS job ID (never match other cards!)
        selectors = [
            f"div[componentkey='job-card-component-ref-{job.id}']",
            f"div[role='button'][componentkey='job-card-component-ref-{job.id}']",
            f"[data-job-id='{job.id}']",
            f"[data-occludable-job-id='{job.id}']",
            f"li[data-job-id='{job.id}']",
            f"a[href*='/jobs/view/{job.id}']",
            f"a[data-job-id='{job.id}']",
            f".job-card-container:has(a[href*='{job.id}'])",
            f"li:has(a[href*='{job.id}'])",
        ]
        card = page.locator(", ".join(selectors)).first

        clicked = False
        if card.count():
            try:
                # Find clickable element (title link, button, or card)
                clickable = card.locator("a[href*='/jobs/view/'], a.job-card-container__link, div[role='button'], .job-card-list__title, h3, strong").first
                target = clickable if clickable.count() else card
                target.scroll_into_view_if_needed(timeout=3000)
                self.human.pause()
                target.click(timeout=4000)
                clicked = True
            except Exception:
                try:
                    card.click(force=True, timeout=4000)
                    clicked = True
                except Exception:
                    pass

        if not clicked:
            # Try scrolling into view and clicking via JavaScript
            try:
                clicked = page.evaluate("""(jobId) => {
                    const el = document.querySelector(`[componentkey*="${jobId}"], [data-job-id="${jobId}"], [data-occludable-job-id="${jobId}"], a[href*="/jobs/view/${jobId}"]`);
                    if (el) {
                        el.scrollIntoView({block: 'center', behavior: 'instant'});
                        const clickEl = el.querySelector('a, div[role="button"]') || el;
                        clickEl.click();
                        return true;
                    }
                    return false;
                }""", job.id)
            except Exception:
                pass

        if not clicked:
            # Fallback direct URL navigation
            sep = "&" if "?" in self.search_url else "?"
            page.goto(f"{self.search_url}{sep}currentJobId={job.id}", wait_until="domcontentloaded")

        page.wait_for_timeout(2000)
        update_live_view(page)

        # 2. Wait for details pane to update
        details = page.locator(".jobs-search__job-details, .job-view-layout, [data-view-name*='job-details'], .jobs-details, div.job-details-jobs-unified-top-card__container--two-pane, main").first
        easy = self._easy_btn(page)
        external = page.locator(SEL["external"]).first
        applied_signal = details.locator("text=/Applied \\d+ \\w+ ago|Application submitted|You applied/i") if details.count() else page.locator("non_existent")

        try:
            easy.or_(external).or_(applied_signal).first.wait_for(timeout=6000)
        except PWTimeout:
            pass

        desc = page.locator(SEL["description"]).first
        description = desc.inner_text(timeout=2000).strip() if desc.count() else ""
        is_easy = easy.count() > 0
        company_link = page.locator("main a[href*='/company/']:visible").first

        # 3. Check already_applied STRICTLY within details container
        is_already_applied = False
        if not is_easy and details.count() > 0:
            is_already_applied = details.locator("text=/Applied \\d+ \\w+ ago|Application submitted|You applied/i").count() > 0

        is_closed = not is_easy and not external.count() and details.count() > 0 and details.locator("text=/No longer accepting applications/i").count() > 0

        return JobDetail(
            company_url=company_link.get_attribute("href") or "" if company_link.count() else "",
            job=job,
            description=description,
            external=not is_easy and external.count() > 0,
            already_applied=is_already_applied,
            closed=is_closed,
        )

    def open_external(self, page):
        link = page.locator(SEL["external"]).first
        if not link.count():
            return None
        href = link.get_attribute("href")
        if href:                      # new UI: a plain link — open it ourselves, no popups/dialogs
            new = page.context.new_page()
            new.goto(urljoin(BASE, href), wait_until="domcontentloaded")
            return new
        self.human.pause()            # classic UI: a button that opens a new tab
        return self.click_to_new_tab(page, link, timeout=8000)

    # --- Easy Apply ----------------------------------------------------------------

    def _modal(self, page):
        m = page.locator("div.jobs-easy-apply-modal:visible, div[role='dialog']:visible, dialog[open]:visible, [data-testid='dialog']:visible")
        steps = page.get_by_role("button", name=re.compile(
            f"{NEXT_RE.pattern}|{REVIEW_RE.pattern}|{SUBMIT_RE.pattern}", re.I))
        filtered = m.filter(has=steps)
        if filtered.count():
            return filtered.last
        return m.last

    def apply(self, page, session: ApplySession) -> str:
        btn = self._easy_btn(page)
        if not btn.count():
            return "failed"
        self.human.pause()
        try:
            btn.scroll_into_view_if_needed(timeout=3000)
            btn.click()
        except Exception:
            btn.click(force=True)
        modal = self._modal(page)
        try:
            modal.wait_for(timeout=10000)
            update_live_view(page)
        except PWTimeout:
            dump_debug(page, "linkedin-nomodal")
            self._discard(page)
            return "failed"
        try:
            status = self._easy_apply(page, modal, session)
            if status != "applied":
                self._discard(page)
            return status
        except SkipJob:
            self._discard(page)
            raise
        except Exception as e:
            dump_debug(page, "linkedin-apply-exc")
            self._discard(page)
            return "failed"

    def _step_button(self, modal, pattern):
        b = modal.get_by_role("button", name=pattern).filter(visible=True)
        if b.count():
            return b.first
        b2 = modal.locator("button:visible, footer button:visible").filter(has_text=pattern)
        if b2.count():
            return b2.first
        return None

    def _easy_apply(self, page, modal, session: ApplySession) -> str:
        filler = FormFiller(session, upload="always", all_required=True)
        answered: dict[str, object] = {}     # label -> Control, across all steps (for final summary)
        had_errors, same_step_errors = False, 0
        job = session.detail.job

        for _ in range(15):
            page.wait_for_timeout(1000)
            update_live_view(page)
            for _wait in range(4):
                if not modal.locator(".artdeco-loader, .loading, svg[class*='loader'], svg[class*='loading']").count():
                    break
                page.wait_for_timeout(1000)

            self._unfollow(modal)            # never auto-follow the company
            for c in filler.fill(modal, force_invalid=had_errors):
                answered[c.field.label] = c

            update_live_view(page)

            submit = self._step_button(modal, SUBMIT_RE)
            if submit:
                update_live_view(page)
                status = filler.review_and_submit(
                    modal, list(answered.values()), submit,
                    success=lambda: page.get_by_text(SENT_RE).count() > 0 or not modal.is_visible(),
                    title=f"LinkedIn Easy Apply: {job.title} — {job.company}",
                    editable=False,      # earlier steps are no longer on screen
                )
                update_live_view(page)
                self._close_done_dialog(page)
                return status

            nxt = None
            for _try in range(3):
                nxt = self._step_button(modal, REVIEW_RE) or self._step_button(modal, NEXT_RE)
                if nxt:
                    break
                page.wait_for_timeout(1500)

            if not nxt:
                dump_debug(page, "linkedin-nostep")
                self._discard(page)
                return "failed"
            self.human.pause()
            try:
                nxt.click()
            except Exception:
                nxt.click(force=True)
            page.wait_for_timeout(1500)
            update_live_view(page)

            had_errors = modal.locator(SEL["error"]).count() > 0
            if had_errors:
                err_msgs = [e.inner_text().strip() for e in modal.locator(SEL["error"]).all() if e.inner_text().strip()]
                if err_msgs:
                    console.print(f"  [yellow]Step validation error:[/] {'; '.join(err_msgs[:2])}")
            same_step_errors = same_step_errors + 1 if had_errors else 0
            if same_step_errors >= 2:
                dump_debug(page, "linkedin-step-errors")
                if getattr(session.reviewer, "auto_submit", False):
                    console.print(f"  [yellow]Step rejected twice in auto mode. Skipping {job.title} to maintain velocity.[/]")
                    self._discard(page)
                    return "failed"
                choice = session.reviewer.choose(
                    "[yellow]LinkedIn still rejects this step.[/] Fix the red fields in the browser, then "
                    "[cyan]c[/] continue  [cyan]s[/] skip job", "cs")
                if choice == "s":
                    raise SkipJob()
                same_step_errors, had_errors = 0, False
        self._discard(page)
        return "failed"

    def _unfollow(self, modal):
        box = modal.get_by_label(re.compile(r"^follow", re.I))
        try:
            if box.count() and box.first.is_visible() and box.first.is_checked():
                box.first.uncheck(force=True, timeout=2000)
        except PlaywrightError:
            box.first.evaluate("e => e.click()")

    def _close_done_dialog(self, page):
        page.wait_for_timeout(1500)
        done = page.get_by_role("button", name=re.compile(r"^(dismiss|done|not now)$", re.I)).filter(visible=True)
        if done.count():
            try:
                done.first.click()
            except Exception:
                pass

    def _discard(self, page):
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass
        d = page.locator("button[aria-label*='dismiss' i]:visible, button[aria-label*='close' i]:visible, button[data-test-modal-close-btn]:visible, button.artdeco-modal__dismiss:visible, button[data-test-dialog-close-btn]:visible")
        if d.count():
            try:
                d.first.click(timeout=2000)
                page.wait_for_timeout(500)
            except Exception:
                pass
        confirm = page.locator("button[data-control-name='discard_application_confirm_btn']:visible, button:visible").filter(has_text=re.compile(r"^discard$", re.I))
        if confirm.count():
            try:
                confirm.first.click(timeout=2000)
                page.wait_for_timeout(500)
            except Exception:
                pass
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        console.print("  [dim]application discarded/closed[/]")
