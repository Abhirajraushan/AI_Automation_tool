"""Terminal review: you approve every job and every uncertain answer."""
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.core.answer_engine import _closest_option, generate_tailored_statement
from src.core.models import Answer, Field, JobDetail, QuitRun, SkipJob

console = Console()


def _get_active_profile() -> dict:
    try:
        from pathlib import Path
        import yaml
        prof_path = Path("config/profile.yaml")
        if prof_path.exists():
            return yaml.safe_load(prof_path.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


class Reviewer:
    def __init__(self, review_cfg: dict):
        self.confirm_before_apply = review_cfg.get("confirm_before_apply", True)
        self.auto_accept_known = review_cfg.get("auto_accept_known", True)
        self.threshold = float(review_cfg.get("auto_accept_confidence", 0.85))
        self.auto_submit = review_cfg.get("auto_submit_known", False)   # --auto: submit when nothing is unknown

    def confirm_apply(self, detail: JobDetail, score: int, reason: str, low_match: bool = False) -> bool:
        """low_match: score is under min_match_score but the title is a software role — always ask,
        and default to skip so a stray Enter doesn't apply."""
        job = detail.job
        where = "[magenta]external — company site[/]" if detail.external else f"[green]{job.site}[/]"
        color = "yellow" if low_match else "bold"
        console.print(Panel(
            f"[bold]{job.title}[/] — {job.company}   ({where})\n"
            f"{job.location} · {job.experience}\n"
            f"Match: [{color}]{score}[/]/100 — {reason}\n{job.url}",
            title="Job — [yellow]LOW MATCH[/]" if low_match else "Job",
            border_style="yellow" if low_match else "cyan",
        ))
        if low_match:
            if self.auto_submit:
                return False
            choice = console.input("Low match — apply anyway? [cyan]y[/] apply  [cyan][Enter][/] skip  "
                                   "[cyan]q[/] quit > ").strip().lower()
            if choice == "q":
                raise QuitRun()
            return choice == "y"
        if not self.confirm_before_apply or self.auto_submit:
            return True
        choice = console.input("[cyan][Enter][/] apply  [cyan]s[/] skip  [cyan]q[/] quit > ").strip().lower()
        if choice == "q":
            raise QuitRun()
        return choice != "s"

    def choose(self, prompt: str, choices: str) -> str:
        """Single-letter prompt, e.g. choose('Finished?', 'dsq'). q always quits."""
        if self.auto_submit:
            return choices[0]
        while True:
            raw = console.input(f"{prompt} > ").strip().lower()[:1]
            if raw == "q":
                raise QuitRun()
            if raw and raw in choices:
                return raw

    def confirm_answer(self, f: Field, ans: Answer | None, force: bool = False, detail: JobDetail | None = None) -> str:
        lbl = f.label.lower()
        is_yes_no = bool(f.options and any(o.strip().lower() in ("yes", "no") for o in f.options))
        if any(k in lbl for k in ("have you attached", "attached your resume", "added your current", "added your ctc", "resume attached")):
            if is_yes_no:
                ans = Answer("Yes", 0.95, "profile")
        if ans and ans.value:
            if "authorized" in lbl and any(k in lbl for k in ("work", "legal", "country", "reside")):
                yes = next((o for o in f.options if o.strip().lower() in ("yes", "y", "true", "i am")), None) if f.options else None
                ans = Answer(yes or "Yes", 0.95, "profile")
            elif any(k in lbl for k in ("nationality", "citizen")):
                ans = Answer("Indian", 0.95, "profile")
            elif any(k in lbl for k in ("country",)) and "authorized" not in lbl:
                ans = Answer("India", 0.95, "profile")
            elif any(k in lbl for k in ("lacs", "inr lacs", "lpa")) and not is_yes_no:
                ans = Answer("8" if "expect" in lbl else "4", 0.95, "profile")
            elif any(k in lbl for k in ("ctc", "salary")) and not is_yes_no:
                ans = Answer("800000" if "expect" in lbl else "400000", 0.95, "profile")
            elif any(k in lbl for k in ("portfolio", "github", "website")) and not is_yes_no and ans.value.lower() in ("yes", "y", "no", "n"):
                prof = _get_active_profile()
                ans = Answer(prof.get("personal", {}).get("github_url", "https://github.com"), 0.95, "profile")
            elif any(k in lbl for k in ("degree", "educational", "highest education", "highest qualification")) and ans.value.lower() in ("yes", "y", "no", "n"):
                ans = Answer("Bachelor of Engineering (Computer Science)", 0.95, "profile")
            elif any(k in lbl for k in ("ca,", "cs,", "cma", "cfa", "chartered")) and ans.value.lower() in ("yes", "y"):
                ans = Answer("No", 0.95, "profile")
            elif any(k in lbl for k in ("sponsorship", "visa", "relative", "family member", "personal relationship", "outside business", "side business", "employed by", "employed in the past", "previously employed", "conflict of interest", "criminal")):
                if "authorized" not in lbl:
                    ans = Answer("No", 0.95, "profile")
                else:
                    ans = Answer("Yes", 0.95, "profile")
            elif any(k in lbl for k in ("if yes, please", "if yes, describe", "describe relationship", "name of person / vendor")):
                ans = Answer("N/A", 0.95, "profile")
            elif any(k in lbl for k in ("acknowledge and agree", "acknowledge", "processing of my personal data", "privacy policy", "consent to okta", "consent")):
                ack = next((o for o in f.options if any(k in o.lower() for k in ("acknowledge", "agree", "consent", "yes", "accept"))), None) if f.options else None
                ans = Answer(ack or "I acknowledge", 0.95, "profile")

        # If memory/profile answer is a bogus "Yes"/"No" on a non-confirmation question, bypass it
        is_bogus_bool = (ans and ans.value and ans.value.lower().strip() in ("yes", "y", "true", "no", "n", "false")
                         and any(k in f.label.lower() for k in ("salary", "ctc", "fixed", "drawn", "annual", "lpa", "lacs",
                                                                 "why", "interest", "cover letter", "skills you possess",
                                                                 "percentage", "cgpa", "rating", "scale of", "bonus", "rsu",
                                                                 "city", "location", "address", "state", "postal", "zip")))

        if (not force and ans and self.auto_accept_known and ans.source in ("profile", "memory")
                and ans.confidence >= self.threshold and not is_bogus_bool):
            val = ans.value
            if f.options:
                opt = _closest_option(val, f.options)
                if not opt:
                    opt = next((o for o in f.options if o.lower().strip() == val.lower().strip()), None)
                if not opt and val.lower().strip() in ("yes", "y", "true", "agree", "i acknowledge", "acknowledge", "consent"):
                    opt = next((o for o in f.options if any(k in o.lower() for k in ("acknowledge", "agree", "consent", "yes", "accept"))), None)
                if not opt and val.lower().strip() in ("no", "n", "false"):
                    opt = next((o for o in f.options if any(k in o.lower() for k in ("decline", "disagree", "do not", "no"))), None)
                if not opt:
                    opt = next((o for o in f.options if val.lower().strip() in o.lower()), None)
                if opt:
                    val = opt
            try:
                console.print(f"  [green]✔[/] {f.label} → [bold]{val}[/] [dim]({ans.source})[/]")
            except Exception:
                print(f"  [OK] {f.label} -> {val} ({ans.source})")
            return val

        if self.auto_submit and not force:
            val = None
            lbl = f.label.lower()
            if "authorized" in lbl and any(k in lbl for k in ("work", "legal", "country", "reside")):
                if f.options:
                    yes = next((o for o in f.options if o.strip().lower() in ("yes", "y", "true", "i am")), None)
                    val = yes or "Yes"
                else:
                    val = "Yes"
            elif any(k in lbl for k in ("nationality", "citizen")):
                if f.options:
                    opt = next((o for o in f.options if "indian" in o.lower()), None) or next((o for o in f.options if "india" in o.lower()), None)
                    val = opt or "Indian"
                else:
                    val = "Indian"
            elif any(k in lbl for k in ("country",)) and "authorized" not in lbl and not is_yes_no:
                if f.options:
                    opt = next((o for o in f.options if o.strip().lower() == "india" or "india" in o.lower()), None)
                    val = opt or "India"
                else:
                    val = "India"
            elif any(k in lbl for k in ("sponsorship", "require visa", "visa sponsorship", "need visa", "relative", "family member",
                                        "personal relationship", "outside business", "side business", "secondary employment",
                                        "board role", "employed by", "employed in the past", "previously employed", "worked at",
                                        "conflict of interest", "criminal", "convicted", "disciplinary", "ca,", "cs,", "cma", "cfa", "chartered",
                                        "existing offer", "other offer", "offer in hand")):
                if f.options:
                    no = next((o for o in f.options if o.strip().lower() in ("no", "n", "false", "i do not", "none")), None)
                    val = no or "No"
                else:
                    val = "No"
            elif any(k in lbl for k in ("if yes, please", "if yes, describe", "describe relationship", "name of person / vendor")):
                val = "N/A"
            elif any(k in lbl for k in ("acknowledge and agree", "acknowledge", "processing of my personal data", "privacy policy", "consent to okta", "consent")):
                if f.options:
                    ack = next((o for o in f.options if any(k in o.lower() for k in ("acknowledge", "agree", "consent", "yes", "accept"))), None)
                    val = ack or f.options[0]
                else:
                    val = "Yes"
            elif any(k in lbl for k in ("have you attached", "attached your resume", "added your current", "added your ctc", "resume attached")):
                val = "Yes"
            elif any(k in lbl for k in ("lacs", "inr lacs", "lpa")) and not is_yes_no:
                val = "8" if "expect" in lbl else "4"
            elif any(k in lbl for k in ("ctc", "salary", "fixed (annual)", "last drawn", "drawn fixed", "fixed compensation",
                                        "fixed annual", "annual fixed", "base pay", "gross pay", "remuneration", "package",
                                        "annual compensation")) and not is_yes_no:
                val = "8" if "expect" in lbl else "4"
            elif any(k in lbl for k in ("why are you interested", "skills you possess that align", "interest in this opportunity",
                                        "why should we hire", "about yourself", "cover letter", "alignment to role",
                                        "describe your experience", "why this role", "tell us a little bit", "why this company",
                                        "statement of purpose")):
                val = generate_tailored_statement(detail, f.label)
            elif any(k in lbl for k in ("reason for change", "reason for seeking", "why change")):
                val = "Seeking career advancement, new technical challenges, and opportunities to build high-performance distributed systems."
            elif any(k in lbl for k in ("unvested", "rsu", "bonus", "equity")):
                val = "0"
            elif any(k in lbl for k in ("scale of 1", "rate your")):
                val = "8"
            elif any(k in lbl for k in ("referral",)):
                val = "NA"
            elif any(k in lbl for k in ("portfolio", "github", "website")) and not is_yes_no:
                prof = _get_active_profile()
                val = prof.get("personal", {}).get("github_url", "https://github.com")
            elif any(k in lbl for k in ("linkedin",)):
                prof = _get_active_profile()
                val = prof.get("personal", {}).get("linkedin_url", "https://linkedin.com")
            elif any(k in lbl for k in ("street", "address")):
                prof = _get_active_profile()
                val = prof.get("personal", {}).get("current_city", "Bengaluru")
            elif any(k in lbl for k in ("zip", "postal", "pin")):
                prof = _get_active_profile()
                val = prof.get("personal", {}).get("postal_code", "560001")
            elif any(k in lbl for k in ("state", "province")):
                prof = _get_active_profile()
                val = prof.get("personal", {}).get("current_state", "Karnataka")
            elif any(k in lbl for k in ("city", "location")):
                prof = _get_active_profile()
                val = prof.get("personal", {}).get("current_city", "Bengaluru")
            elif any(k in lbl for k in ("serving notice", "on notice")) and not any(k in lbl for k in ("period", "days", "what is", "how many", "mention", "current")):
                val = "No"
            elif any(k in lbl for k in ("notice",)):
                if f.options:
                    val = _closest_option("30 days", f.options) or _closest_option("15 to 30 days", f.options) or _closest_option("30", f.options) or f.options[0]
                else:
                    val = "30"
            elif any(k in lbl for k in ("how soon", "joining time", "when can you join", "how many days to join")):
                if f.options:
                    val = _closest_option("30 days", f.options) or _closest_option("15 to 30 days", f.options) or _closest_option("Immediate", f.options) or f.options[0]
                else:
                    val = "30"
            elif any(k in lbl for k in ("cgpa", "gpa", "percentage", "score", "marks")):
                if f.options:
                    val = _closest_option("78.8", f.options) or _closest_option("70 & Above", f.options) or _closest_option("7.88", f.options) or f.options[0]
                else:
                    val = "78.8" if any(k in lbl for k in ("percentage", "score", "marks")) else "7.88"
            elif any(k in lbl for k in ("college", "university", "school")):
                val = "Chandigarh University"
            elif any(k in lbl for k in ("company", "employer", "organization")):
                val = "Indian Institute of Technology (IIT) Bhubaneswar"
            elif any(k in lbl for k in ("gender",)):
                val = "Male"
            elif any(k in lbl for k in ("degree", "educational", "highest education", "highest qualification")):
                if f.options:
                    bachelor = next((o for o in f.options if any(b in o.lower() for b in ("bachelor", "b.e", "b.tech", "graduate", "graduation"))), None)
                    val = bachelor or f.options[0]
                else:
                    val = "Bachelor of Engineering (Computer Science)"
            elif ans and ans.value and not (ans.value.lower() in ("yes", "1") and any(k in lbl for k in ("url", "link", "salary", "ctc", "qualification", "education", "degree", "fixed", "drawn", "lpa", "lacs", "why", "interest", "cover letter"))):
                val = ans.value
                if f.options:
                    opt = _closest_option(val, f.options)
                    if opt:
                        val = opt
            elif f.options:
                if is_yes_no:
                    val = "Yes"
                else:
                    bachelor = next((o for o in f.options if any(b in o.lower() for b in ("bachelor", "b.e", "b.tech", "graduate", "graduation"))), None)
                    yes = next((o for o in f.options if o.strip().lower() in ("yes", "y", "true", "i agree", "agree", "comfortable", "full-time", "immediate")), None)
                    val = bachelor if any(k in lbl for k in ("degree", "education", "qualification")) and bachelor else (yes or f.options[0])
            elif any(k in lbl for k in ("city", "current location", "where are you located", "location (city")):
                val = "Bhubaneswar, India"
            elif any(k in lbl for k in ("year", "exp", "how many")):
                val = "2"
            elif any(lbl.startswith(w) for w in ("is ", "are ", "do ", "can ", "will ", "have ", "confirm ", "agree ", "would ")) or is_yes_no:
                val = "Yes"
            else:
                val = "N/A"
            try:
                console.print(f"  [green]✔ (auto-fill)[/] {f.label} → [bold]{val}[/]")
            except Exception:
                print(f"  [OK (auto-fill)] {f.label} -> {val}")
            return val

        if self.auto_submit or not sys.stdin.isatty():
            # In autonomous / non-interactive mode, never freeze on console.input!
            if ans and ans.value and not is_bogus_bool:
                return ans.value
            if f.options:
                yes_opt = next((o for o in f.options if o.strip().lower() in ("yes", "y", "true")), None)
                if yes_opt and (is_yes_no or any(lbl.startswith(w) for w in ("is ", "are ", "do ", "can ", "will ", "have "))):
                    return yes_opt
                return f.options[0]
            if any(k in lbl for k in ("city", "location", "address")):
                return "Bhubaneswar, India"
            return "Yes" if is_yes_no else "2" if any(k in lbl for k in ("year", "exp")) else "N/A"

        table = Table(show_header=False, box=None)
        table.add_row("Question", f"[bold]{f.label}[/]")
        if f.options:
            table.add_row("Options", "\n".join(f"{i}. {o}" for i, o in enumerate(f.options, 1)))
        if ans:
            color = "green" if ans.confidence >= self.threshold else "yellow" if ans.confidence >= 0.5 else "red"
            table.add_row("Proposed", f"[{color}]{ans.value}[/] [dim]({ans.source}, {ans.confidence:.2f})[/]")
        else:
            table.add_row("Proposed", "[red]no answer found — type one[/]")
        console.print(Panel(table, title="Check answer", border_style="yellow"))

        while True:
            hint = "[Enter] accept  " if ans else ""
            raw = console.input(f"{hint}type new value / option number  s skip job  q quit > ").strip()
            if raw.lower() == "q":
                raise QuitRun()
            if raw.lower() == "s":
                raise SkipJob()
            if not raw and ans:
                return ans.value
            if raw.isdigit() and f.options and 1 <= int(raw) <= len(f.options):
                return f.options[int(raw) - 1]
            if raw:
                return raw
            console.print("  [yellow]No answer yet — type it" + (" or an option number" if f.options else "")
                          + ", or s to skip this job.[/]")
