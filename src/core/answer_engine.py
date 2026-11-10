"""Resolve a form question: profile.yaml -> answer memory -> LLM (with memory examples) -> you."""
import difflib
import re

import yaml

from src.core.llm import LLM, LLMUnavailable
from src.core.memory import GENERIC_EXP, AnswerMemory, keywords
from src.core.models import Answer, Field, JobDetail

SYSTEM = """You fill job application form questions on behalf of a candidate.
Rules:
- Answer ONLY from the candidate profile and resume provided. Never invent skills, employers or years.
- If options are given, "value" must be exactly one of the options (for checkbox kind: comma-separated options).
- Numeric questions (years, CTC, notice days): return just the number.
- Keep text answers short (one line) unless the question asks for a description.
- PAST ANSWERS are the candidate's own answers to earlier forms: follow them for the same or similar
  questions (same facts, same style). They override guesses.
- If the information is not in the profile/resume/past answers, give the most conservative honest
  answer and confidence below 0.5.
Return JSON: {"value": "<answer>", "confidence": <0..1>}"""


def _too_generic(key: str, label: str) -> bool:
    """'years of experience' must not answer 'Years of Rust experience'."""
    lk, kk = keywords(label), keywords(key)
    if not lk & {"year", "experience"}:
        return False
    return kk <= GENERIC_EXP and bool(lk - GENERIC_EXP - kk)


def _words(text: str) -> set[str]:
    return set(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


def _numeric_option(value: str, options: list[str]) -> str | None:
    """'2' -> '1-3 years' / '2+ years' / 'Less than 3'; '30' -> '15-30 days'; '7.88' / '75' -> '70 & Above'."""
    try:
        v = float(value.strip().split()[0])
    except (ValueError, IndexError):
        return None
    if v == 0:
        no_exp = next((o for o in options if any(k in o.lower() for k in ("no experience", "none", "fresher", "0 years"))), None)
        if no_exp:
            return no_exp

    cand_values = [v]
    if 0 < v <= 10:
        has_large = any(any(float(n) > 10 for n in re.findall(r"\d+(?:\.\d+)?", opt)) for opt in options)
        if has_large:
            cand_values.extend([v * 9.5, v * 10.0])

    for val in cand_values:
        for opt in options:
            nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", opt)]
            low = opt.lower()
            if len(nums) >= 2 and (nums[0] <= val <= nums[1] or nums[1] <= val <= nums[0]):
                return opt
            if len(nums) == 1:
                n = nums[0]
                if ("+" in opt or "more" in low or "above" in low or "over" in low or ">=" in opt or ">" in opt) and val >= n:
                    return opt
                elif ("less" in low or "under" in low or "below" in low or "<" in opt) and val < n:
                    return opt
                elif val == n:
                    return opt
    return None


YES_TERMS = {"true", "1", "yes", "checked", "agree", "y", "i agree", "i acknowledge", "acknowledge", "consent", "i consent", "accept", "i accept", "sure", "ok", "okay", "of course"}
NO_TERMS = {"false", "0", "no", "n", "disagree", "i disagree", "decline", "do not agree", "nope", "never", "not really", "na", "n/a"}


def _closest_option(value: str, options: list[str]) -> str | None:
    if not options:
        return value
    v = value.strip().lower().rstrip(".!")
    for opt in options:
        if opt.strip().lower() == v:
            return opt
    if v in YES_TERMS:
        yes = next((o for o in options if o.strip().lower() == "yes"), None)
        if yes:
            return yes
        ack = next((o for o in options if any(k in o.strip().lower() for k in ("acknowledge", "agree", "consent", "accept", "yes", "relocate all", "willing to relocate"))), None)
        if ack:
            return ack
    if v in NO_TERMS:
        no = next((o for o in options if o.strip().lower() == "no"), None)
        if no:
            return no
        dec = next((o for o in options if any(k in o.strip().lower() for k in ("decline", "disagree", "do not", "no", "not willing"))), None)
        if dec:
            return dec
    numeric = _numeric_option(value, options)
    if numeric:
        return numeric
    match = difflib.get_close_matches(value, options, n=1, cutoff=0.6)
    if match:
        return match[0]
    vw = {w[:6] for w in re.findall(r"[a-z]{4,}", value.lower())}   # "Bachelor of Engineering" ~ "Bachelor's Degree"
    hits = [o for o in options if vw & {w[:6] for w in re.findall(r"[a-z]{4,}", o.lower())}]
    return hits[0] if len(hits) == 1 else None


# built-in profile keys that also appear inside unrelated questions ("Name of your college",
# "Why this company?") — they only answer short field labels
AMBIGUOUS_BUILTIN = {"name", "company", "organization", "location", "city", "website", "portfolio",
                     "job title", "current title", "current employer", "full name", "country"}


def generate_tailored_statement(detail: JobDetail | None = None, label: str = "") -> str:
    """Generate a dynamic, professional statement of interest / cover note tailored to the specific job & company."""
    title = (detail.job.title if detail and detail.job else "").strip() or "Software Engineer"
    company = (detail.job.company if detail and detail.job else "").strip()
    desc = ((detail.description if detail else "") or "").lower()
    comp_clause = f" at {company}" if company and not any(k in company.lower() for k in ("client", "leading", "confidential", "hiring", "consultancy")) else ""
    low_title = title.lower()

    # 1. Cybersecurity, SOC, SIEM, DLP, InfoSec, Security Operations
    if any(k in low_title or k in desc for k in ("security", "soc", "siem", "dlp", "infosec", "cyber", "threat", "vulnerability", "incident")):
        return (
            f"I am very excited to apply for the {title} role{comp_clause}. "
            "As a Software Developer (Cybersecurity & Systems) at IIT Bhubaneswar, I have hands-on experience in DLP policy design, "
            "Elastic SIEM alert triage, network packet analysis (Wireshark, TCP/IP, Nmap), and secure Linux platform engineering. "
            "My background in threat detection, Python/Go automation, and incident response directly aligns with your requirements to protect mission-critical environments."
        )

    # 2. Golang / Go Developer
    if any(k in low_title for k in ("go", "golang")) or "golang" in desc:
        return (
            f"I am excited to apply for the {title} position{comp_clause}. "
            "I bring strong backend engineering experience developing high-concurrency microservices and RESTful APIs in Go (Golang) and Python, "
            "integrated with PostgreSQL and Docker. Having architected secure platforms and automated services at IIT Bhubaneswar, "
            "I write clean, idiomatic Go code and focus on building reliable, scalable distributed architectures."
        )

    # 3. Python Developer / AI / Machine Learning / Data Analyst
    if any(k in low_title for k in ("python", "machine learning", "ml", "ai", "data analyst")) or ("python" in desc and "java" not in low_title):
        return (
            f"I am enthusiastic about the {title} opportunity{comp_clause}. "
            "My engineering background centers on backend service development, API integrations, and automation using Python, SQL, and modern frameworks, "
            "backed by hands-on experience in Docker containerization, AWS, and Linux environments. "
            "I am keen to leverage my technical foundation and problem-solving skills to build robust, high-performance systems for your team."
        )

    # 4. Data Engineer / Platform Engineer / DevOps / Cloud / SRE / Systems
    if any(k in low_title for k in ("data engineer", "platform", "devops", "cloud", "sre", "infrastructure", "systems")):
        return (
            f"I am excited to apply for the {title} role{comp_clause}. "
            "With hands-on experience designing containerized platform architectures (Docker, AWS), managing relational databases (PostgreSQL/SQL), "
            "building RESTful APIs, and automating operational workflows at IIT Bhubaneswar, "
            "I bring a strong foundation in platform reliability, security, and pipeline performance to support your engineering infrastructure."
        )

    # 5. General Software Developer / Software Engineer / Backend / Full Stack
    return (
        f"I am very keen to join{comp_clause} as a {title}. "
        "With 2 years of engineering experience focused on backend architecture, RESTful API design, and database systems (PostgreSQL/SQL) "
        "using Python, Go, and Java, I have built secure, scalable applications at IIT Bhubaneswar. "
        "I am eager to contribute clean code, quick learning agility, and reliable engineering solutions to your team."
    )


class AnswerEngine:
    def __init__(self, profile: dict, resume_text: str, llm: LLM | None):
        self.profile = profile
        self.resume_text = resume_text[:12000]
        self._resume_lc = resume_text.lower()
        self.llm = llm
        self.memory = AnswerMemory()

    def resolve(self, f: Field, detail: JobDetail, use_llm: bool = True) -> Answer | None:
        lbl = f.label.lower()

        # Strict language knowledge check: candidate knows English & Hindi only
        KNOWN_LANGUAGES = {"english", "hindi"}
        NON_KNOWN_LANGUAGES = {
            "kannada", "tamil", "telugu", "malayalam", "marathi", "bengali",
            "gujarati", "punjabi", "odia", "oriya", "assamese", "urdu",
            "german", "french", "spanish", "japanese", "mandarin", "chinese", "russian"
        }
        words_in_lbl = set(re.findall(r"[a-z]+", lbl))
        if words_in_lbl & NON_KNOWN_LANGUAGES:
            no_opt = next((o for o in f.options if o.strip().lower() in ("no", "none", "cannot speak", "cannot read / write", "not proficient", "0", "not fluent", "basic", "n")), "No")
            return Answer(no_opt, 0.99, "profile")
        if words_in_lbl & KNOWN_LANGUAGES and any(k in words_in_lbl for k in ("speak", "understand", "read", "write", "language", "proficient", "fluent", "communication", "level", "know", "known")):
            yes_opt = next((o for o in f.options if o.strip().lower() in ("yes", "fluent", "professional", "proficient", "native", "expert", "y")), "Yes")
            return Answer(yes_opt, 0.99, "profile")
        if any(k in words_in_lbl for k in ("language", "languages")):
            if f.kind == "checkbox" and f.options:
                chosen = [o for o in f.options if any(lang in o.lower() for lang in ("english", "hindi"))]
                if chosen:
                    return Answer(", ".join(chosen), 0.99, "profile")

        # Dynamic statement of interest / cover letter / skills alignment
        if any(k in lbl for k in ("why are you interested", "skills you possess that align",
                                  "interest in this opportunity", "why should we hire",
                                  "about yourself", "cover letter", "alignment to role",
                                  "why this role", "tell us a little bit", "why this company",
                                  "statement of purpose")):
            statement = generate_tailored_statement(detail, f.label)
            return Answer(statement, 0.98, "tailored")

        mem = self._from_memory(f)
        if mem and mem.confidence >= 0.9:
            val = mem.value
            # Normalize text values when field asks specifically for pure digits (days, LPA, years)
            if f.kind == "text" and not f.options:
                if re.search(r'\b(in days|days)\b', f.label, re.I) and 'days' in val.lower():
                    m_d = re.search(r'\b(\d+)\b', val)
                    if m_d:
                        return Answer(m_d.group(1), mem.confidence, mem.source)
                if re.search(r'\b(in lpa|in lacs|in lakhs|lpa|lacs|lakhs)\b', f.label, re.I):
                    if val in ("400000", "4,00,000", "400000.00"):
                        return Answer("4", mem.confidence, mem.source)
                    if val in ("800000", "8,00,000", "800000.00"):
                        return Answer("8", mem.confidence, mem.source)
            return mem              # your latest answer to this exact question wins
        ans = self._from_profile(f) or self._from_skill_years(f)
        if ans:
            return ans
        llm = self._from_llm(f, detail) if use_llm else None
        if mem and (not llm or llm.confidence < mem.confidence):
            return mem              # close (not exact) memory match: proposed, you confirm
        return llm

    def profile_answer(self, f: Field) -> Answer | None:
        return self._from_profile(f)

    def remember(self, f: Field, value: str, source: str = "user"):
        self.memory.add(f.label, value, f.kind, f.options, source)

    def _builtin_answers(self) -> dict:
        """Standard contact fields derived from profile.personal / experience."""
        p = self.profile.get("personal") or {}
        e = self.profile.get("experience") or {}
        name = (p.get("full_name") or "").split()
        return {
            "name": p.get("full_name"), "full name": p.get("full_name"),
            "first name": name[0] if name else "", "last name": name[-1] if len(name) > 1 else "",
            "given name": name[0] if name else "", "family name": name[-1] if len(name) > 1 else "",
            "surname": name[-1] if len(name) > 1 else "",
            "email": p.get("email"), "phone": p.get("phone"), "mobile": p.get("phone"),
            "phone number": p.get("phone"), "mobile phone number": p.get("phone"),
            "linkedin": p.get("linkedin_url"), "linkedin profile": p.get("linkedin_url"),
            "github": p.get("github_url"), "website": p.get("github_url"), "portfolio": p.get("github_url"),
            "city": p.get("current_city"), "location": p.get("current_city"),
            "street": p.get("street") or "Bhubaneswar",
            "street address": p.get("street") or "Bhubaneswar",
            "address": p.get("address") or "Bhubaneswar, Odisha",
            "state": p.get("state") or "Odisha",
            "province": p.get("state") or "Odisha",
            "state/province": p.get("state") or "Odisha",
            "zip": p.get("zip_code") or "752050",
            "zip code": p.get("zip_code") or "752050",
            "postal code": p.get("zip_code") or "752050",
            "zip/postal code": p.get("zip_code") or "752050",
            "pincode": p.get("zip_code") or "752050",
            "pin code": p.get("zip_code") or "752050",
            "country": "India",
            "nationality": "Indian",
            "citizenship": "Indian",
            "citizen": "Indian",
            "country of citizenship": "India",
            "current company": e.get("current_company"), "company": e.get("current_company"),
            "current employer": e.get("current_company"), "organization": e.get("current_company"),
            "current title": e.get("current_title"), "job title": e.get("current_title"),
            "designation": e.get("current_title") or "Software Developer",
            "current designation": e.get("current_title") or "Software Developer",
            "current role": e.get("current_title") or "Software Developer",
            "current job title": e.get("current_title") or "Software Developer",
            "current ctc": "400000", "expected ctc": "800000",
            "current salary": "400000", "expected salary": "800000",
            "current ctc in lacs": "4", "expected ctc in lacs": "8",
            "current salary in lacs": "4", "expected salary in lacs": "8",
            "current ctc in lpa": "4", "expected ctc in lpa": "8",
            "current salary in lpa": "4", "expected salary in lpa": "8",
            "ctc in lacs": "4", "salary in lacs": "4",
            "inr lacs": "4",
            "current fixed compensation": "400000",
            "current/last drawn fixed (annual)": "400000",
            "current/last drawn fixed": "400000",
            "last drawn fixed": "400000",
            "drawn fixed": "400000",
            "fixed (annual)": "400000",
            "fixed annual": "400000",
            "annual fixed": "400000",
            "fixed compensation": "400000",
            "fixed salary": "400000",
            "last drawn salary": "400000",
            "last drawn": "400000",
            "base salary": "400000",
            "gross salary": "400000",
            "annual compensation": "400000",
            "annual salary": "400000",
            "unvested options": "0", "rsu": "0", "bonuses": "0", "bonus": "0",
            "notice period": "30", "notice period days": "30",
            "notice period in days": str(e.get("notice_period_days") or 30),
            "current notice period": str(e.get("notice_period_days") or 30),
            "notice period": str(e.get("notice_period_days") or 30),
            "how soon can you join": "30",
            "how soon you join": "30 days",
            "earliest available joining date": "15122026",
            "college": "Chandigarh University", "university": "Chandigarh University",
            "school": "Chandigarh University",
            "degree": e.get("highest_education") or "B.E. Computer Science",
            "highest education": e.get("highest_education") or "B.E. Computer Science — Chandigarh University",
            "highest educational qualification": e.get("highest_education") or "B.E. Computer Science — Chandigarh University",
            "highest qualification": e.get("highest_education") or "B.E. Computer Science — Chandigarh University",
            "educational qualification": e.get("highest_education") or "B.E. Computer Science — Chandigarh University",
            "qualification": e.get("highest_education") or "B.E. Computer Science — Chandigarh University",
            "professional qualification": "No",
            "ca": "No", "cma": "No", "cfa": "No",
            "percentage": "78.8",
            "percentage obtained": "78.8",
            "percentage in highest qualification": "78.8",
            "percentage you obtained in your highest educational qualification": "78.8",
            "percentage marks": "78.8",
            "highest qualification percentage": "78.8",
            "aggregate percentage": "78.8",
            "cgpa": "7.88", "gpa": "7.88",
            "offer in hand": "No", "any offer in hand": "No", "existing offer": "No",
            "reason for job change": "Seeking career advancement, new technical challenges, and opportunities to build scalable systems.",
            "reason for change": "Seeking career advancement, new technical challenges, and opportunities to build scalable systems.",
            "why are you interested": "I am a Software Engineer with 2 years of experience specializing in backend systems, RESTful APIs, Python, Go, Java, and cloud platforms. I am eager to apply my skills to drive impactful engineering results.",
            "skills you possess that align": "Backend engineering with Python, Go, Java, REST APIs, PostgreSQL, AWS, and Docker.",
            "cover letter": "I am a Software Engineer with 2 years of experience in backend development, distributed systems, and cloud infrastructure. I am excited to apply my engineering skills to deliver high-impact results for your team.",
            "summary": "Software Engineer with 2 years of experience specializing in backend architectures, microservices, REST APIs, and cloud deployments (AWS/Docker).",
            "headline": "Software Engineer | Backend Developer | Go | Python | Java",
            "rate your proficiency": "8",
            "scale of 1 to 10": "8",
            "referral": "NA",
            "sponsorship": "No", "visa sponsorship": "No", "require sponsorship": "No",
            "require visa": "No", "require visa sponsorship": "No",
            "authorized to work": "Yes", "legally authorized": "Yes", "legally authorized to work": "Yes",
            "relatives": "No", "family members": "No", "personal relationships": "No",
            "outside business": "No", "side businesses": "No", "side business": "No",
            "employed in the past": "No", "previously employed": "No", "previously worked": "No",
            "conflict of interest": "No", "criminal": "No", "disciplinary": "No",
            "serving notice": "No", "on notice": "No",
            "total experience": str(e.get("total_years") or 2),
            "total work experience": str(e.get("total_years") or 2),
            "overall experience": str(e.get("total_years") or 2),
            "years of experience": str(e.get("total_years") or 2),
            "experience in years": str(e.get("total_years") or 2),
            "relevant experience": str(e.get("total_years") or 2),
            "relocate": "Yes", "ready to relocate": "Yes", "willing to relocate": "Yes",
            "open to relocate": "Yes", "living in or ready to relocate": "Yes",
            "are you currently living in or ready to relocate": "Yes",
            "relocation": "Yes", "willing to travel": "Yes",
            "work from office": "Yes", "comfortable working from office": "Yes",
            "comfortable working from the office": "Yes", "work from the office": "Yes",
            "five days a week": "Yes", "5 days a week": "Yes", "comfortable with 5 days": "Yes",
            "comfortable with hybrid": "Yes", "hybrid work": "Yes", "hybrid mode": "Yes",
            "immediate joiner": "Yes", "can you join immediately": "Yes", "ready to join immediately": "Yes",
            "notice period in days": str(e.get("notice_period_days") or 30),
            "current notice period": str(e.get("notice_period_days") or 30),
            "notice period": str(e.get("notice_period_days") or 30),
            "how soon can you join": "30",
            "rotational shift": "Yes", "night shift": "Yes", "shifts": "Yes",
            # LinkedIn Easy Apply screening questions
            "background check": "Yes", "undergo a background check": "Yes",
            "willing to undergo a background check": "Yes", "background verification": "Yes",
            "drug test": "Yes", "drug screening": "Yes",
            "valid passport": "Yes", "passport": "Yes",
            "security clearance": "No", "have security clearance": "No",
            "driver license": "Yes", "driver's license": "Yes", "driving license": "Yes",
            "commute": "Yes", "comfortable commuting": "Yes",
            "comfortable commuting to this job's location": "Yes",
            "comfortable with the commute": "Yes",
            "onsite": "Yes", "on-site": "Yes", "comfortable working on-site": "Yes",
            "full-time": "Yes", "full time": "Yes",
            "bachelor": "Yes", "bachelor's": "Yes", "bachelors": "Yes",
            "completed bachelor": "Yes", "completed your bachelor": "Yes",
            "completed your bachelors": "Yes", "completed bachelor degree": "Yes",
            "have you completed your bachelor": "Yes",
            "have you completed the following level of education": "Yes",
            "gender": "Male",
            "veteran": "No", "protected veteran": "I am not a protected veteran",
            "disability": "No, I do not have a disability",
            "require visa": "No", "require sponsorship": "No", "visa sponsorship": "No",
            "authorized to work in india": "Yes", "authorized to work in the country": "Yes",
            "are you legally authorized to work in india": "Yes",
            "are you legally authorized to work": "Yes",
            "current location": p.get("current_city") or "Bhubaneswar",
            "preferred location": "Bhubaneswar / Open to Relocate",
        }

    def _from_profile(self, f: Field) -> Answer | None:
        label_words = _words(f.label)
        best = None
        builtin = self._builtin_answers()
        answers = {**builtin, **(self.profile.get("answers") or {})}
        short_label = len(re.findall(r"[a-z]+", f.label.lower())) <= 3   # "Company", "Current company name"
        for key, value in answers.items():
            if value in ("", None):
                continue
            if key in AMBIGUOUS_BUILTIN and key not in (self.profile.get("answers") or {}) and not short_label:
                continue        # "company" must not answer "Why do you want to work at a fintech company?"
            rank = (len(_words(key)), len(key))  # most specific key wins
            if (_words(key) <= label_words and not _too_generic(key, f.label)
                    and (best is None or rank > best[0])):
                best = (rank, str(value))
        if not best:
            return None
        value = _closest_option(best[1], f.options)
        return Answer(value, 0.95, "profile") if value else None

    def _from_skill_years(self, f: Field) -> Answer | None:
        """'Years of experience with X?' -> experience.skill_years when X is on the resume / skills list.
        'Do you have experience with X?' (Yes/No) -> Yes for the same skills."""
        exp = self.profile.get("experience") or {}
        years = exp.get("skill_years") or exp.get("total_years") or 2
        lk = keywords(f.label)
        if "experience" not in lk and "year" not in lk:
            return None
        skills = lk - GENERIC_EXP - {"hands", "handson", "exposure", "using", "knowledge", "working", "worked"}
        if not skills:
            return None                     # "total years of experience" -> profile / memory
        known = {w.lower() for s in self.profile.get("skills") or [] for w in re.findall(r"[a-z0-9+#]+", s.lower())}
        on_resume = [w for w in skills if w in known or any(w == k or w in k or k in w for k in known) or re.search(rf"(?<![a-z]){re.escape(w)}s?(?![a-z])", self._resume_lc)]
        yes = next((o for o in f.options if o.strip().lower() == "yes"), None)
        no = next((o for o in f.options if o.strip().lower() == "no"), None)

        m_yr = re.search(r"(\d+)\+?\s*years?", f.label.lower())
        if m_yr and yes and no:
            req_years = int(m_yr.group(1))
            cand_years = int(exp.get("total_years") or 2)
            if req_years > cand_years:
                return Answer(no, 0.95, "profile")
            if on_resume:
                return Answer(yes, 0.95, "profile")

        if on_resume:
            value = yes if yes and "year" not in lk else _closest_option(str(years), f.options)
            return Answer(value, 0.95, "profile") if value else None
        unknown = exp.get("unknown_skill_years", "0")
        if str(unknown).lower() == "ask":
            unknown = "0"
        value = no if no and "year" not in lk else _closest_option(str(unknown), f.options)
        return Answer(value, 0.9, "profile") if value else None

    def _from_memory(self, f: Field) -> Answer | None:
        entry, score = self.memory.find(f.label)
        if not entry or score < 0.65:
            return None
        value = _closest_option(entry.answer, f.options) if f.kind != "checkbox" else entry.answer
        if not value:
            return None
        self.memory.used(entry)
        # exact match -> auto-fill; close match -> shown to you with the remembered question
        return Answer(value, 0.9 if score >= 0.9 else round(0.5 + score * 0.3, 2),
                      "memory" if score >= 0.9 else f"memory~ “{entry.question[:50]}”")

    def _from_llm(self, f: Field, detail: JobDetail) -> Answer | None:
        if not self.llm:
            return None
        profile = {k: v for k, v in self.profile.items() if k != "answers"}
        past = "\n".join(f"Q: {e.question}\nA: {e.answer}" for e in self.memory.similar(f.label))
        user = (
            f"CANDIDATE PROFILE:\n{yaml.safe_dump(profile, sort_keys=False)}\n"
            f"RESUME:\n{self.resume_text}\n\n"
            f"PAST ANSWERS:\n{past or '(none yet)'}\n\n"
            f"JOB: {detail.job.title} at {detail.job.company}\n\n"
            f"QUESTION: {f.label}\nKIND: {f.kind}\nOPTIONS: {f.options or 'free text'}"
        )
        try:
            data = self.llm.json(SYSTEM, user)
        except LLMUnavailable:
            return None
        except Exception as e:
            print(f"  [llm error] {e}")
            return None
        value = str(data.get("value", "")).strip()
        confidence = float(data.get("confidence", 0) or 0)
        if f.kind != "checkbox":
            mapped = _closest_option(value, f.options)
            if mapped is None:
                return Answer(value, 0.0, "llm")
            value = mapped
        return Answer(value, confidence, "llm") if value else None
