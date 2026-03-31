"""
build_knowledge_base.py
───────────────────────
Scrapes the Ostfalia ISO-relevant web pages and the PDF content we already
have, cleans the text, and saves everything as plain .txt files that can
be embedded for RAG.

Run once before the fair:
    python build_knowledge_base.py

Output:
    knowledge/raw_texts/   ← one .txt file per source
    knowledge/summary.json ← index of all files + metadata
"""

import os
import json
import time
import re
import requests
from bs4 import BeautifulSoup

OUTPUT_DIR = "knowledge/raw_texts"
os.makedirs(OUTPUT_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ISO-Fair-Bot/1.0; "
        "Student research project TU Braunschweig)"
    )
}

# ── Pages to scrape ────────────────────────────────────────────────────────────
PAGES = [
    {
        "key": "iso_main",
        "url": "https://www.ostfalia.de/hochschule/campus-einrichtungen/international-student-office",
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
        "url": "https://www.ostfalia.de/studieren/im-studium/international/studierende-aus-dem-ausland/dein-weg-an-die-ostfalia",
        "topic": "Step-by-step path for incoming international students",
    },
    {
        "key": "erasmus_outgoing",
        "url": "https://www.ostfalia.de/studieren/im-studium/international/wege-ins-ausland",
        "topic": "Erasmus+ and ways to study abroad as an Ostfalia student",
    },
    {
        "key": "language_courses",
        "url": "https://www.ostfalia.de/hochschule/campus-einrichtungen/sprachenzentrum",
        "topic": "Language courses at Sprachenzentrum",
    },
    {
        "key": "german_as_foreign_language",
        "url": "https://www.ostfalia.de/en/university/campus-facilities/language-centre/german-as-a-foreign-language",
        "topic": "German as a foreign language (DaF) courses for international students",
    },
    {
        "key": "sprachtandem",
        "url": "https://www.ostfalia.de/en/university/campus-facilities/language-centre/language-tandem",
        "topic": "Language tandem program — practice German with a native speaker",
    },
    {
        "key": "housing",
        "url": "https://www.ostfalia.de/studieren/studieninteressierte/wohnen",
        "topic": "Student housing and accommodation options",
    },
    {
        "key": "studierenden_service",
        "url": "https://www.ostfalia.de/hochschule/campus-einrichtungen/studierenden-service",
        "topic": "Student service office — general admin (redirect target for out-of-scope questions)",
    },
]

# TODO: Check URLS and get right URLS

# ── Manually authored content (from the PDF + what we know) ───────────────────
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


def clean_text(raw: str) -> str:
    """Remove nav menus, footers, cookie banners and excess whitespace."""
    # Remove extra blank lines
    lines = [l.strip() for l in raw.splitlines()]
    # Filter out very short lines that are likely nav items
    lines = [l for l in lines if len(l) > 3]
    # Collapse runs of blank lines
    cleaned = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                cleaned.append("")
            prev_blank = True
        else:
            cleaned.append(line)
            prev_blank = False
    return "\n".join(cleaned).strip()


def scrape_page(page: dict) -> str:
    """Fetch and extract main content from an Ostfalia page."""
    try:
        resp = requests.get(page["url"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return f"[SCRAPE ERROR: {e}]"

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove noise elements
    for tag in soup.select("nav, header, footer, .cookie-banner, script, style, .navigation, .breadcrumb"):
        tag.decompose()

    # Try to get main content area
    main = (
        soup.select_one("#inhalt") or
        soup.select_one("main") or
        soup.select_one("article") or
        soup.select_one(".content") or
        soup.body
    )

    text = main.get_text(separator="\n") if main else soup.get_text(separator="\n")
    return clean_text(text)


def save(key: str, topic: str, url: str, text: str):
    path = os.path.join(OUTPUT_DIR, f"{key}.txt")
    header = f"SOURCE: {url}\nTOPIC: {topic}\n{'='*60}\n\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + text)
    char_count = len(text)
    print(f"  ✓  {key}.txt  ({char_count:,} chars)")
    return {"key": key, "topic": topic, "url": url, "file": f"{key}.txt", "chars": char_count}


# ── Run ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Building ISO knowledge base...\n")
    index = []

    # 1. Scrape web pages
    print("── Web pages ──")
    for page in PAGES:
        print(f"  Fetching: {page['key']} ...")
        text = scrape_page(page)
        entry = save(page["key"], page["topic"], page["url"], text)
        index.append(entry)
        time.sleep(1.5)  # polite delay

    # 2. Write manual/PDF-derived texts
    print("\n── Manual / PDF-derived content ──")
    for item in MANUAL_TEXTS:
        entry = save(item["key"], item["topic"], "manual/pdf", item["text"])
        index.append(entry)

    # 3. Save index
    index_path = "knowledge/summary.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    total_chars = sum(e["chars"] for e in index)
    print(f"\nDone. {len(index)} files, {total_chars:,} total characters.")
    print(f"Index saved to: {index_path}")
    print("\nNext step: run embed_knowledge_base.py to generate the vector index.")
