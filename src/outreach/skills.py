"""Tech-skill vocabulary: find skills in a job description / resume, in order of appearance."""
import re

# display name -> regex alternatives (lowercase, matched on word-ish boundaries)
SKILLS: dict[str, list[str]] = {
    "Java": [r"java(?!\s*script)"], "Spring Boot": [r"spring\s*boot", r"spring"], "Go": [r"golang", r"\bgo\b(?=\s*(?:lang|developers?|engineers?|dev|backend|microservices?|services|programming|language|routines|modules|[,/|)\n]|$))",
                                                     r"(?<=[,/|(:]\s)go\b", r"(?<=[,/|(:])go\b"],
    "Python": [r"python"], "JavaScript": [r"javascript", r"\bjs\b", r"es6"], "TypeScript": [r"typescript"],
    "React": [r"react(?:\.?js)?"], "Angular": [r"angular"], "Node.js": [r"node(?:\.?js)?"], "C++": [r"c\+\+"],
    "C#": [r"c#", r"\.net"], "Kotlin": [r"kotlin"], "Scala": [r"\bscala\b"], "Rust": [r"\brust\b"],
    "Microservices": [r"micro-?services?"], "REST APIs": [r"rest(?:ful)?\s*apis?", r"\brest\b"],
    "GraphQL": [r"graphql"], "gRPC": [r"grpc"], "Kafka": [r"kafka"], "RabbitMQ": [r"rabbitmq"],
    "Redis": [r"redis"], "Elasticsearch": [r"elastic\s*search"], "SQL": [r"\bsql\b"],
    "MySQL": [r"mysql"], "PostgreSQL": [r"postgres(?:ql)?"], "Oracle": [r"oracle", r"pl/sql"],
    "MongoDB": [r"mongo(?:db)?"], "Cassandra": [r"cassandra"], "DynamoDB": [r"dynamo\s*db"],
    "AWS": [r"\baws\b", r"amazon web services"], "GCP": [r"\bgcp\b", r"google cloud"], "Azure": [r"azure"],
    "Docker": [r"docker"], "Kubernetes": [r"kubernetes", r"\bk8s\b"], "Jenkins": [r"jenkins"],
    "CI/CD": [r"ci\s*/\s*cd", r"continuous integration"], "Terraform": [r"terraform"], "Linux": [r"linux", r"unix"],
    "Git": [r"\bgit\b", r"github", r"gitlab"], "Hibernate": [r"hibernate", r"\bjpa\b"],
    "JUnit": [r"junit"], "Selenium": [r"selenium"], "Cucumber": [r"cucumber", r"\bbdd\b"], "TDD": [r"\btdd\b", r"test[- ]driven"],
    "System Design": [r"system design", r"distributed systems?", r"scalab(?:le|ility)"],
    "Data Structures & Algorithms": [r"data structures?", r"algorithms?", r"\bdsa\b"],
    "Multithreading": [r"multi-?threading", r"concurrency"], "Design Patterns": [r"design patterns?"],
    "OOP": [r"\boop\b", r"object[- ]oriented"], "Agile": [r"agile", r"scrum"],
    "WebSockets": [r"web\s*sockets?"], "HTML/CSS": [r"html", r"\bcss\b"], "Event-driven Architecture": [r"event[- ]driven"],
    "Caching": [r"caching"], "GenAI": [r"\bllms?\b", r"gen\s*ai", r"generative ai", r"openai", r"langchain"],
    "Machine Learning": [r"machine learning", r"\bml\b"], "A/B Testing": [r"a/b test"], "Feature Flags": [r"feature flags?"],
    "Spark": [r"\bspark\b"], "Airflow": [r"airflow"], "Prometheus/Grafana": [r"prometheus", r"grafana"],
    # Cybersecurity & Networks
    "Cybersecurity": [r"cyber\s*security", r"infosec", r"information\s*security"],
    "Penetration Testing": [r"penetration\s*test(?:ing)?", r"\bpentest(?:ing)?\b", r"\bvapt\b", r"ethical\s*hack(?:ing)?"],
    "SOC": [r"\bsoc\b", r"security\s*operations?\s*center"],
    "SIEM": [r"\bsiem\b", r"splunk", r"sentinel", r"qradar"],
    "OT Security": [r"ot\s*security", r"operational\s*technology\s*security", r"ics\s*security", r"industrial\s*control\s*systems?"],
    "SCADA": [r"\bscada\b"],
    "Cyber Range": [r"cyber\s*range"],
    "Threat Detection": [r"threat\s*detection", r"threat\s*intel(?:ligence)?", r"incident\s*response", r"\bdfir\b", r"digital\s*forensics"],
    "Network Security": [r"network\s*security", r"firewalls?", r"\bids\b", r"\bips\b"],
    "Application Security": [r"application\s*security", r"\bappsec\b", r"owasp", r"devsecops"],
    "Vulnerability Management": [r"vulnerability\s*(?:management|assessment|scanning)", r"nessus", r"qualys"],
    "Modbus": [r"modbus(?:\s*tcp)?"],
    "Wireshark": [r"wireshark"],
    "Burp Suite": [r"burp\s*suite", r"\bburp\b"],
    "Nmap": [r"\bnmap\b"],
    "Metasploit": [r"metasploit"],
    "RBAC / IAM": [r"\brbac\b", r"\biam\b", r"identity\s*(?:and|&)\s*access"],
    "Embedded / IoT Security": [r"\bzephyr\b", r"\brtos\b", r"\blora\b", r"\bble\b", r"iot\s*security"],
}
_COMPILED = {name: [re.compile(p, re.I) for p in pats] for name, pats in SKILLS.items()}


def find_skills(text: str) -> list[str]:
    """Skills mentioned in text, ordered by first appearance."""
    hits = []
    for name, pats in _COMPILED.items():
        pos = min((m.start() for p in pats if (m := p.search(text))), default=None)
        if pos is not None:
            hits.append((pos, name))
    return [name for _, name in sorted(hits)]
