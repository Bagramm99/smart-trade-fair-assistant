"""
build_knowledge_base.py
───────────────────────
Scrapes the Ostfalia ISO-relevant web pages and the PDF content we already
have, cleans the text, and saves everything as plain .txt files that can
be embedded for RAG.

WHY THE ORIGINAL BROKE — two separate problems:

  Problem 1 — 403 outside campus network
    ostfalia.de blocks requests from non-university IPs.
    You must run this script from inside the campus network:
      • On a lab machine directly
      • Via SSH into a lab machine (ask professor for access)
      • Connected to the Ostfalia VPN
    Outside campus you get a 403, the scraper catches no error,
    and returns an almost-empty HTML shell → only the <h1> survives.

  Problem 2 — JavaScript-rendered content
    The Ostfalia CMS injects page content via JavaScript AFTER the
    initial HTML loads. requests+BeautifulSoup never executes JS —
    it only sees the empty shell, which is why you got exactly:
        "Wege ins Ausland"   ← just the h1, nothing else

  FIX: Use Selenium (headless Chrome) to load the page like a real
    browser, wait for JS to finish, then extract the rendered HTML.
    Falls back to requests+BS4 if Selenium is not available.

Run once from inside the campus network:
    pip install selenium requests beautifulsoup4
    python build_knowledge_base.py

Output:
    knowledge/raw_texts/   ← one .txt file per source
    knowledge/summary.json ← index of all files + metadata
"""

import os
import json
import time
import requests
from bs4 import BeautifulSoup

OUTPUT_DIR = "knowledge/raw_texts"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Realistic browser User-Agent — bare-bones strings get blocked
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# ── Selenium (JS-rendering) setup ─────────────────────────────────────────────

_driver = None

def _get_driver():
    """
    Launch headless Chrome once and reuse for all pages.
    Requires: pip install selenium
              Chrome or Chromium installed (available on Ostfalia lab machines).
    Returns None if Selenium/Chrome is not available → falls back to requests.
    """
    global _driver
    if _driver is not None:
        return _driver
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        opts = Options()
        opts.add_argument("--headless")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument(f"user-agent={HEADERS['User-Agent']}")

        _driver = webdriver.Chrome(options=opts)
        print("  [Selenium] Headless Chrome ready.\n")
        return _driver
    except Exception as e:
        print(f"  [Selenium] Not available: {e}")
        print("  [Selenium] Falling back to requests (may get incomplete content).\n")
        return None


def _close_driver():
    global _driver
    if _driver:
        _driver.quit()
        _driver = None


# ── Page fetching ─────────────────────────────────────────────────────────────

def fetch_rendered(url: str) -> str:
    """
    Fetch a URL using headless Chrome (executes JavaScript).
    Waits 3 seconds for JS to finish rendering before extracting HTML.
    This is the correct approach for modern CMS sites like Ostfalia.
    """
    driver = _get_driver()
    if driver is None:
        return fetch_static(url)

    try:
        driver.get(url)
        time.sleep(3)          # wait for JS to inject content into the DOM
        return driver.page_source
    except Exception as e:
        return f"[SELENIUM ERROR: {e}]"


def fetch_static(url: str) -> str:
    """
    Fallback: plain requests. Works only if the site serves full HTML
    server-side AND you are on the campus network. For Ostfalia, this
    will usually only return the page title and navigation.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        return f"[SCRAPE ERROR: {e}]"


# ── Text extraction ────────────────────────────────────────────────────────────

# CSS selectors for elements that are pure noise (nav, menus, cookie banners)
NOISE_SELECTORS = [
    "nav", "header", "footer",
    ".cookie-banner", ".cookie-notice",
    "script", "style",
    ".navigation", ".breadcrumb",
    ".menu", ".sidebar",
    # Ostfalia-specific nav/menu classes
    ".nav-main", ".nav-meta", ".social-links",
]

def extract_text(html: str) -> str:
    """
    Parse rendered HTML, strip noise, extract main content text.
    Tries Ostfalia-specific content selectors before falling back to <body>.
    """
    if html.startswith("["):
        # Error message from fetch functions — pass through as-is
        return html

    soup = BeautifulSoup(html, "html.parser")

    # Remove noise
    for selector in NOISE_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()

    # Try content-area selectors in priority order
    # Ostfalia uses #inhalt as the main content anchor
    main = (
        soup.select_one("#inhalt")        or
        soup.select_one(".ce-bodytext")   or
        soup.select_one("main")           or
        soup.select_one("article")        or
        soup.select_one('[role="main"]')  or
        soup.select_one(".content")       or
        soup.body
    )

    raw = main.get_text(separator="\n") if main else soup.get_text(separator="\n")
    return clean_text(raw)


def clean_text(raw: str) -> str:
    """Collapse whitespace and remove lines that are clearly navigation leftovers."""
    lines = [l.strip() for l in raw.splitlines()]

    # Drop very short lines (single words / numbers) — usually nav remnants
    lines = [l for l in lines if len(l) > 4]

    # Collapse consecutive blank lines to one
    cleaned, prev_blank = [], False
    for line in lines:
        if not line:
            if not prev_blank:
                cleaned.append("")
            prev_blank = True
        else:
            cleaned.append(line)
            prev_blank = False

    return "\n".join(cleaned).strip()


# ── Save ───────────────────────────────────────────────────────────────────────

def save(key: str, topic: str, url: str, text: str) -> dict:
    path = os.path.join(OUTPUT_DIR, f"{key}.txt")
    header = f"SOURCE: {url}\nTOPIC: {topic}\n{'='*60}\n\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + text)
    char_count = len(text)
    status = "⚠ ERROR" if text.startswith("[") else "✓"
    print(f"  {status}  {key}.txt  ({char_count:,} chars)")
    return {"key": key, "topic": topic, "url": url, "file": f"{key}.txt", "chars": char_count}


# ── Pages to scrape ────────────────────────────────────────────────────────────

PAGES = [
    {
        "key": "iso_main",
        "url": "https://www.ostfalia.de/en/university/campus-facilities/international-student-office",
        "topic": "ISO overview, services, contact",
    },
    {
        "key": "iso_incoming",
        "url": "https://www.ostfalia.de/hochschule/campus-einrichtungen/international-student-office/incoming-students",
        "topic": "Incoming students, nomination, application process",
    },
    {
        "key": "iso_fyi_integration",
        "url": "https://www.ostfalia.de/en/studieren/im-studium/international/fyi-for-your-integration",
        "topic": "Integration support, first steps in Germany for international students",
    },
    {
        "key": "iso_incoming_path",
        "url": "https://www.ostfalia.de/en/studying/at-university/international/international-students-and-applicants-welcome-at-ostfalia/your-way-to-ostfalia",
        "topic": "Step-by-step path for incoming international students",
    },
    {
        "key": "erasmus_outgoing",
        "url": "https://www.ostfalia.de/en/studying/at-university/international/pathways-abroad",
        "topic": "Erasmus+ and ways to study abroad as an Ostfalia student",
    },
    {
        "key": "language_center",
        "url": "https://www.ostfalia.de/en/university/campus-facilities/language-centre",
        "topic": "Information at Sprachenzentrum",
    },
    {
        "key": "language_courses",
        "url": "https://www.ostfalia.de/en/university/campus-facilities/language-centre/language-course-offer",
        "topic": "Language courses at Sprachenzentrum",
    },
    {
        "key": "german_as_foreign_language",
        "url": "https://www.ostfalia.de/en/university/campus-facilities/language-centre/german-as-a-foreign-language",
        "topic": "German as a foreign language (DaF) information for international students",
    },
    {
        "key": "german_courses",
        "url": "https://www.ostfalia.de/en/university/campus-facilities/language-centre/german-as-a-foreign-language/german-courses-during-your-studies",
        "topic": "German as a foreign language (DaF) courses for international students",
    },
    {
        "key": "dsh_german_certificate",
        "url": "https://www.ostfalia.de/en/university/campus-facilities/language-centre/german-as-a-foreign-language/dsh-exam-and-preparation-course",
        "topic": "Information about the DSH german certificate for international students",
    },
    {
        "key": "intensive_german_courses",
        "url": "https://www.ostfalia.de/en/university/campus-facilities/language-centre/german-as-a-foreign-language/intensive-courses-during-the-lecture-free-period",
        "topic": "German as a foreign language (DaF) intensive courses during the summer for international students",
    },
    {
        "key": "intercultural_offers",
        "url": "https://www.ostfalia.de/en/university/campus-facilities/language-centre/intercultural-offers",
        "topic": "Intercultural offers at the university",
    },
    {
        "key": "sprachtandem",
        "url": "https://www.ostfalia.de/en/university/campus-facilities/language-centre/language-tandem",
        "topic": "Language tandem program — practice German with a native speaker",
    },
    {
        "key": "certificates",
        "url": "https://www.ostfalia.de/en/university/campus-facilities/language-centre/certificates-and-language-certificates",
        "topic": "Language tandem program — practice German with a native speaker",
    },
    {
        "key": "housing",
        "url": "https://www.ostfalia.de/en/studieren/studieninteressierte/living",
        "topic": "Student housing and accommodation options",
    },
    {
        "key": "studierenden_service",
        "url": "https://www.ostfalia.de/hochschule/campus-einrichtungen/studierenden-service",
        "topic": "Student service office — redirect target for out-of-scope questions",
    },
]

# ── Manually authored content (from PDF + known facts) ────────────────────────
# This content does NOT need scraping — it goes straight to the knowledge base.

MANUAL_TEXTS = [
    {
        "key": "partner_universities_informatik",
        "topic": "Partner universities worldwide for Informatik faculty — Erasmus and non-EU",
        "text": """
PARTNER UNIVERSITIES — FACULTY OF INFORMATIK (OSTFALIA)
Source: Presentation by Véronique Bizien, 16.03.2026

ERASMUS PARTNERS (EUROPE):
France:
- Université Paris-Saclay / IUT Cachan (paris-saclay.fr)
- Université Versailles Saint Quentin UVSQ / ISTY
- Université de Toulouse / UPSSITECH / IRIT
- IMT Mines Alès (imt-mines-ales.fr)

Poland:
- Hipolit Cegielski State University of Applied Sciences – Gniezno (ans-gniezno.edu.pl)

Switzerland:
- Hochschule Luzern (hslu.ch)

Spain:
- Universidad de Granada (ugr.es)

Turkey:
- Istanbul Teknik Üniversitesi İTÜ (itu.edu.tr)

New ERASMUS (recently added):
- Finland: Tampere University of Applied Sciences (TAMK)
- Ireland: Munster Technological University (MTU), Cork
- Italy: Università Roma Tre
- Portugal: IPS – Instituto Politécnico de Setubal
- Czech Republic: Czech Technical University in Prague (CTU)

NON-EU PARTNERSHIPS (DAAD funding available):
Brazil:
- Universidade de Santa Cruz do Sul (UNISC)
- Universidade Federal de Santa Maria (UFSM)
- Universidade do Estado do Bahia (UNEB)

Japan:
- National Institute of Technology, Anan College (NIT Anan)

Jordan:
- German Jordanian University (GJU)

Canada:
- University of Manitoba (UM)

Morocco:
- Université Ibn Tofail (UIT)

Mexico:
- Universidad Popular Autónoma del Estado de Puebla (UPAEP)

South Korea:
- Hallym University

Taiwan:
- National Chung Cheng University (CCU)
- National Taiwan Normal University (NTNU)

Uruguay:
- Universidad Tecnológica del Uruguay (UTEC)

USA:
- University of Wisconsin Parkside (UWP)

HOW TO APPLY FOR OUTGOING EXCHANGE:
1. Contact the Auslandsbeauftragter, Internationalisierungs-Coach, or faculty patron
2. Submit your application via ISO (International Student Office)
3. Apply for financial support: Erasmus+ grant or DAAD PROMOS scholarship
4. Select your courses abroad
5. Talk to PAV to arrange credit recognition
6. Adapt your Learning Agreement
7. Consider a language course at the Sprachenzentrum first

CONTACTS FOR OUTGOING STUDENTS:
- Prof. R. Gerndt: r.gerndt@ostfalia.de (Room 135)
- Véronique Bizien: v.bizien@ostfalia.de (Room 008)
- PAVI: pavi@ostfalia.de (Room 028)
- ISO outgoing: a-s.garau@ostfalia.de
""".strip()
    },
    {
        "key": "iso_contacts_and_redirect",
        "topic": "ISO contact details and redirect rules for out-of-scope questions",
        "text": """
ISO CONTACT INFORMATION:
- Email (incoming students): incoming-iso@ostfalia.de
- In-person: Véronique Bizien, Am Exer 2, Raum 008
- ISO outgoing / scholarships: a-s.garau@ostfalia.de

WHAT THE ISO HANDLES:
- Incoming exchange students (all application and enrollment questions)
- Erasmus+ outgoing applications and partner university selection
- DAAD PROMOS scholarships for non-EU exchange
- Learning Agreements and credit recognition coordination
- Integration support for international students (FYI program)
- Language tandem and intercultural offerings (in cooperation with Sprachenzentrum)

WHAT THE ISO DOES NOT HANDLE (redirect these questions):
- General enrollment / first semester admin → Studierenden-Service or Immatrikulationsbüro
- Semester fees and re-enrollment → Studierenden-Service
- Exam registration and grading → Prüfungsamt of the relevant faculty
- Library access → Bibliothek
- IT accounts and student portal → Rechenzentrum
- General course questions → faculty office of the student's program

REDIRECT CONTACT:
Studierenden-Service: ostfalia.de/hochschule/campus-einrichtungen/studierenden-service
""".strip()
    }
]


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Building ISO knowledge base...\n")
    print("NOTE: Run this from inside the Ostfalia campus network (lab machine or VPN).\n")
    index = []

    # 1. Scrape web pages with JS rendering
    print("── Web pages (using Selenium + headless Chrome) ──")
    for page in PAGES:
        print(f"  Fetching: {page['key']} ...")
        html = fetch_rendered(page["url"])
        text = extract_text(html)

        # Warn if we got suspiciously little content
        if len(text) < 200 and not text.startswith("["):
            print(f"  ⚠  Only {len(text)} chars — page may not have rendered fully.")
            print(f"     Check that you are on the campus network and Chrome is installed.")

        entry = save(page["key"], page["topic"], page["url"], text)
        index.append(entry)
        time.sleep(2)   # polite delay between pages

    _close_driver()

    # 2. Write manual/PDF-derived texts (no scraping needed)
    print("\n── Manual / PDF-derived content ──")
    for item in MANUAL_TEXTS:
        entry = save(item["key"], item["topic"], "manual/pdf", item["text"])
        index.append(entry)

    # 3. Save index
    index_path = "knowledge/summary.json"
    os.makedirs("knowledge", exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    total_chars = sum(e["chars"] for e in index)
    print(f"\nDone. {len(index)} files, {total_chars:,} total characters.")
    print(f"Index saved to: {index_path}")

    # Report any pages that failed or returned too little
    short = [e for e in index if e["chars"] < 200]
    if short:
        print(f"\n⚠  {len(short)} page(s) returned very little content:")
        for e in short:
            print(f"   - {e['key']} ({e['chars']} chars) — check URL and network access")

    print("\nNext step: python embed_knowledge_base.py")