"""
Skill Categorizer — open-source LLM edition
============================================
Fetches Wikipedia context for each skill, then categorizes it into a
Skill Bucket + Sub-Bucket using a FREE open-source LLM.

Two backend options (pick one in the CONFIG section below):

  A) Ollama  — runs 100 % locally, no API key needed.
               Install: https://ollama.com  → `ollama pull llama3`
               Supports: llama3, mistral, gemma2, phi3, qwen2, etc.

  B) Groq    — free cloud API (very fast), needs a free key from
               https://console.groq.com  (generous free tier).
               Supports: llama3-8b-8192, mixtral-8x7b-32768, gemma2-9b-it

Setup:
    pip install pandas openpyxl requests

    # For Groq only:
    pip install groq
    set GROQ_API_KEY=your_key_here        # Windows
    export GROQ_API_KEY=your_key_here     # Linux / Mac

Usage:
    python categorize_skills.py
"""

import os, json, re, time
import pandas as pd
import requests

# ── CONFIG — edit these two lines ────────────────────────────────────────────

INPUT_FILE  = r"C:\Users\ankit.rana\Downloads\skill_master_review.xlsx"
OUTPUT_FILE = r"C:\Users\ankit.rana\Downloads\skill_master_review_categorized_llama.xlsx"

# BACKEND: "ollama"  OR  "groq"
BACKEND = "ollama"

# Ollama settings (ignored when BACKEND="groq")
OLLAMA_URL   = "http://localhost:11434"   # default Ollama address
OLLAMA_MODEL = "llama3"                   # any model you've pulled

# Groq settings (ignored when BACKEND="ollama")
# Get a free key at https://console.groq.com
GROQ_MODEL   = "llama-3.1-8b-instant"          # fast & free on Groq
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# ── Taxonomy ──────────────────────────────────────────────────────────────────

SKILL_TAXONOMY = {
    "Programming & Development": [
        "Programming Languages", "Scripting Languages", "Web Development",
        "Mobile Development", "API Development", "Software Architecture",
        "Object-Oriented Programming", "Functional Programming",
        "Embedded & Systems Programming", "Game Development",
        "Compiler & Language Design",
    ],
    "Frameworks, Libraries & SDKs": [
        "Frontend Frameworks", "Backend Frameworks", "Mobile Frameworks",
        "AI/ML Libraries", "Data & Analytics Libraries", "Testing Frameworks",
        "Enterprise Frameworks", "Infrastructure & Automation Frameworks",
        "UI Component Libraries",
    ],
    "Data, AI & Analytics": [
        "Data Analysis", "Business Intelligence", "Data Engineering",
        "Machine Learning", "Deep Learning", "Generative AI & LLMs", "NLP",
        "Computer Vision", "Statistics & Mathematics", "Data Visualization",
        "Analytics Engineering",
    ],
    "Databases & Data Storage": [
        "Relational Databases", "NoSQL Databases", "Data Warehousing",
        "Data Modeling", "Query Optimization", "Database Administration",
        "Search & Vector Databases", "Caching & In-Memory",
        "Message Queues & Streaming",
    ],
    "Cloud, Infrastructure & DevOps": [
        "Cloud Platforms", "Containers", "Orchestration", "CI/CD",
        "Infrastructure as Code", "Site Reliability Engineering",
        "Monitoring & Observability", "System Administration", "Networking",
        "Storage & Backup", "Platform Engineering",
    ],
    "Cybersecurity & Risk": [
        "Network Security", "Application Security",
        "Identity & Access Management", "Threat Detection & Response",
        "Security Auditing", "Governance, Risk & Compliance (GRC)",
        "Cloud Security", "Cryptography", "Security Engineering",
    ],
    "Tools, Software & Platforms": [
        "Productivity & Office", "Collaboration Tools", "CRM Platforms",
        "ERP Systems", "Design & Creative Tools", "Development Tools",
        "Project & Issue Tracking", "HR & People Tools", "Marketing Platforms",
        "Finance & Accounting Tools", "Customer Support Tools",
        "Document & Knowledge Management", "Data & Analytics Tools",
    ],
    "Engineering & Technical Operations": [
        "Mechanical Engineering", "Electrical Engineering",
        "Civil & Structural Engineering", "Chemical Engineering",
        "Manufacturing & Production", "Industrial Automation",
        "Environmental Engineering", "Technical Maintenance",
        "Aerospace & Defense Engineering", "Telecommunications Engineering",
    ],
    "Product, Project & Program Management": [
        "Agile Methodologies", "Project Planning & Scheduling",
        "Stakeholder Management", "Product Management",
        "Program & Portfolio Management", "Risk Management",
        "Business Analysis", "Quality Management", "Change Management",
    ],
    "Leadership & People Management": [
        "Team Leadership", "Talent Acquisition", "Coaching & Mentoring",
        "Performance Management", "Organizational Development",
        "Workforce Planning", "Executive Leadership", "HR Generalist Skills",
        "Learning & Development",
    ],
    "Sales, Customer Success & Business Development": [
        "Sales Development", "Account Management", "Customer Success",
        "Business Development", "Enterprise Sales",
        "Revenue Operations (RevOps)", "Retail & E-Commerce Sales",
        "Inside Sales", "Negotiation",
    ],
    "Marketing, Content & Communications": [
        "Digital Marketing", "Social Media Marketing", "Content Marketing",
        "Brand Management", "Public Relations",
        "Copywriting & Technical Writing", "Product Marketing",
        "Growth Marketing", "Marketing Analytics", "Event Marketing",
        "Communications (Internal/External)",
    ],
    "Finance, Legal & Compliance": [
        "Accounting", "Financial Analysis",
        "FP&A (Financial Planning & Analysis)", "Investment & Capital Markets",
        "Tax", "Audit", "Legal", "Compliance", "Risk Management (Finance)",
        "Treasury",
    ],
    "Research, Analysis & Domain Expertise": [
        "Market Research", "Competitive Intelligence", "Business Analysis",
        "Strategy & Consulting", "Academic & Scientific Research",
        "Policy & Regulatory Research", "UX Research",
        "Geospatial & Environmental Analysis", "Social Science Research",
    ],
    "Professional & Interpersonal Skills": [
        "Communication", "Presentation & Public Speaking",
        "Critical Thinking & Problem Solving", "Collaboration & Teamwork",
        "Emotional Intelligence", "Adaptability & Learning Agility",
        "Time Management & Productivity", "Leadership & Influence",
        "Creativity & Innovation", "Negotiation & Conflict Resolution",
        "Decision Making",
    ],
    "Languages": [
        "European Languages", "Asian Languages",
        "Middle Eastern & African Languages", "Language Proficiency Levels",
        "Sign Languages",
    ],
    "Certifications": [
        "Project Management", "Cloud Certifications",
        "Cybersecurity Certifications", "Finance & Accounting Certifications",
        "Legal & Compliance Certifications", "Data & AI Certifications",
        "HR & People Certifications", "Quality & Process Certifications",
        "Healthcare Certifications", "Industry-Specific Certifications",
    ],
    "Methodologies & Frameworks": [
        "Process Improvement", "Innovation & Design",
        "IT Service Management", "Enterprise Architecture",
        "Software Development Methodologies", "Risk & Compliance Frameworks",
        "Sales & GTM Methodologies", "Consulting Frameworks",
        "Supply Chain Methodologies", "Sustainability Frameworks",
    ],
    "Industry Expertise": [
        "Technology & Software", "Financial Services",
        "Healthcare & Life Sciences", "Retail & Consumer",
        "Manufacturing & Industrial", "Energy & Utilities",
        "Telecommunications", "Media & Entertainment", "Education",
        "Government & Public Sector", "Real Estate & Construction",
        "Logistics, Supply Chain & Transportation", "Agriculture & Food",
        "Professional Services", "Hospitality & Travel",
    ],
    "Design, UX & Creative": [
        "UX/UI Design", "Visual & Graphic Design", "Product Design",
        "Motion & Video", "3D & Spatial Design", "Photography",
        "Content Creation",
    ],
    "Operations, Supply Chain & Procurement": [
        "Operations Management", "Supply Chain Management", "Procurement",
        "Logistics & Distribution", "Quality & Compliance (Operations)",
    ],
    "Healthcare & Clinical": [
        "Clinical Skills", "Healthcare Management", "Healthcare Technology",
        "Clinical Research & Trials", "Public Health",
    ],
}

TAXONOMY_TEXT = "\n".join(
    f"- {bucket}: {', '.join(subs)}"
    for bucket, subs in SKILL_TAXONOMY.items()
)

# ── Wikipedia helper ──────────────────────────────────────────────────────────

def fetch_wikipedia_summary(skill_name: str, max_chars: int = 400) -> str:
    headers = {"User-Agent": "SkillCategorizer/1.0"}
    url = ("https://en.wikipedia.org/api/rest_v1/page/summary/"
           + requests.utils.quote(skill_name))
    try:
        r = requests.get(url, timeout=10, headers=headers)
        if r.status_code == 200:
            return r.json().get("extract", "")[:max_chars]
        # Fall back to search
        sr = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search",
                    "srsearch": skill_name, "srlimit": 1, "format": "json"},
            timeout=10, headers=headers,
        )
        if sr.status_code == 200:
            hits = sr.json().get("query", {}).get("search", [])
            if hits:
                return fetch_wikipedia_summary(hits[0]["title"], max_chars)
    except Exception:
        pass
    return ""

# ── LLM backends ──────────────────────────────────────────────────────────────

def _build_prompt(skill: str, context: str, related: list[str]) -> str:
    related_str = ", ".join(related) if related else "N/A"
    return f"""You are a skill taxonomy expert. Categorize the skill below into exactly one Skill Bucket and one Skill Sub-Bucket from the taxonomy.

Skill: {skill}
Wikipedia context: {context or "No context available."}
Related skills (from resumes): {related_str}

Taxonomy (Bucket → Sub-Buckets):
{TAXONOMY_TEXT}

Rules:
1. Pick the single best-fitting Bucket and Sub-Bucket.
2. Return ONLY a raw JSON object — no markdown, no explanation.
3. Keys must be exactly "skill_bucket" and "skill_sub_bucket".

Example: {{"skill_bucket": "Tools, Software & Platforms", "skill_sub_bucket": "Productivity & Office"}}"""


def call_ollama(prompt: str) -> dict:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",          # Ollama native JSON mode
        "options": {"temperature": 0},
    }
    r = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=120)
    r.raise_for_status()
    text = r.json()["response"].strip()
    text = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


def call_groq(prompt: str) -> dict:
    from groq import Groq
    client = Groq(api_key=GROQ_API_KEY)
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},   # JSON mode
        max_tokens=200,
    )
    text = resp.choices[0].message.content.strip()
    text = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


def categorize(skill: str, context: str, related: list[str]) -> dict:
    prompt = _build_prompt(skill, context, related)
    if BACKEND == "groq":
        return call_groq(prompt)
    return call_ollama(prompt)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Quick backend sanity check
    if BACKEND == "ollama":
        try:
            r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
            models = [m["name"] for m in r.json().get("models", [])]
            print(f"Ollama running. Available models: {models or '(none pulled yet)'}")
            if not any(OLLAMA_MODEL in m for m in models):
                print(f"  ⚠  Model '{OLLAMA_MODEL}' not found. "
                      f"Run:  ollama pull {OLLAMA_MODEL}")
        except Exception:
            print("⚠  Ollama not reachable at", OLLAMA_URL,
                  "\n   Install from https://ollama.com and run: ollama pull", OLLAMA_MODEL)
    elif BACKEND == "groq":
        if not GROQ_API_KEY:
            raise ValueError("Set GROQ_API_KEY env var. Get a free key at https://console.groq.com")
        print(f"Using Groq backend → model: {GROQ_MODEL}")

    print(f"\nReading: {INPUT_FILE}")
    df = pd.read_excel(INPUT_FILE)

    name_col = next(c for c in df.columns if c.lower() == "name")
    top_cols  = [c for c in df.columns if re.match(r"top_\d+", c, re.I)]

    buckets, sub_buckets, contexts = [], [], []

    for idx, row in df.iterrows():
        skill   = str(row[name_col]).strip()
        related = [str(row[c]) for c in top_cols if pd.notna(row.get(c))]

        print(f"  [{idx+1}/{len(df)}] {skill}", end=" … ", flush=True)

        wiki = fetch_wikipedia_summary(skill)
        time.sleep(0.3)

        try:
            result     = categorize(skill, wiki, related)
            bucket     = result.get("skill_bucket", "Unknown")
            sub_bucket = result.get("skill_sub_bucket", "Unknown")
        except Exception as e:
            print(f"ERROR: {e}")
            bucket, sub_bucket = "Unknown", "Unknown"

        buckets.append(bucket)
        sub_buckets.append(sub_bucket)
        contexts.append(wiki[:200] if wiki else "")
        print(f"{bucket} → {sub_bucket}")

    df["skill_bucket"]     = buckets
    df["skill_sub_bucket"] = sub_buckets
    df["wiki_context"]     = contexts

    df.to_excel(OUTPUT_FILE, index=False)
    print(f"\nDone! Saved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
