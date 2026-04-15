from PIL import Image, ImageDraw, ImageFont
import os

OUTPUT_DIR = r"assets\temi_screens"
W, H = 800, 600
BG_COLOR = (0, 51, 102)
ACCENT_COLOR = (0, 153, 204)
TEXT_COLOR = (255, 255, 255)
FOOTER_COLOR = (0, 30, 60)

SCREENS = {
    "iso_contact_card": {"title": "International Student Office", "lines": ["  Am Exer 2, Room 008", "  incoming-iso@ostfalia.de", "  Veronique Bizien", "  www.ostfalia.de/iso", "", "  Office hours: Mon-Fri  10:00 - 12:00"], "footer": "Welcome to the ISO Stand!"},
    "partner_world_map": {"title": "Partner Universities Worldwide", "lines": ["  Europe         ->  40+ partners", "  Americas       ->  8 partners", "  Asia & Pacific ->  6 partners", "", "  Erasmus+, DAAD & bilateral agreements"], "footer": "Ask about a specific country!"},
    "outgoing_process": {"title": "How to Study Abroad", "lines": ["  1. Choose partner university", "  2. Apply via ISO (Oct/Apr deadline)", "  3. Get nominated by Ostfalia", "  4. Apply at host university", "  5. Prepare visa & insurance", "  6. Go abroad!"], "footer": "Come to the ISO office for personal advice"},
    "erasmus_europe": {"title": "Erasmus+ Partners in Europe", "lines": ["  France   Spain   Italy   Poland", "  Czechia  Portugal  Netherlands", "  Belgium  Greece  Romania  Hungary", "", "  Grant: 250-800 EUR/month + tuition waived"], "footer": "Erasmus+ grant covers living costs abroad"},
    "erasmus_new": {"title": "New Erasmus+ Partners 2025/26", "lines": ["  University of Ljubljana (Slovenia)", "  Vilnius Tech (Lithuania)", "  AGH University Krakow (Poland)", "", "  Applications open NOW for Winter 2025/26", "  Deadline: 15 October 2025"], "footer": "First come, first served - apply early!"},
    "non_eu_partners_1": {"title": "Non-EU Partners", "lines": ["  USA      ->  2 universities", "  Canada   ->  1 university", "  Brazil   ->  2 universities", "  Mexico   ->  1 university", "", "  Funding: DAAD scholarships available"], "footer": "Ask ISO about DAAD funding options"},
    "non_eu_partners_2": {"title": "Asia & Pacific Partners", "lines": ["  Japan    ->  2 universities", "  Korea    ->  1 university", "  China    ->  1 university", "  Australia ->  1 university", "  India    ->  1 university"], "footer": "Language courses available for preparation"},
    "language_courses": {"title": "Language Courses - Sprachenzentrum", "lines": ["  German   A1 - C1  (all semesters)", "  English  B1 - C1", "  French   A1 - B2", "  Spanish  A1 - B1", "", "  Registration: moodle.ostfalia.de"], "footer": "Free for all Ostfalia students!"},
    "housing_guide": {"title": "Housing for Exchange Students", "lines": ["  Studentenwerk dorms  (apply early!)", "  -> Wolfenbuettel & Braunschweig", "  -> 250 - 380 EUR/month", "", "  Registration: studentenwerk-br.de", "  Apply 4+ months before arrival"], "footer": "ISO helps with the application process"},
    "health_insurance": {"title": "Health Insurance", "lines": ["  Coming TO Germany:", "  -> Public insurance required", "  -> AOK / TK / Barmer (~110 EUR/month)", "", "  Going ABROAD from Germany:", "  -> DAAD travel insurance recommended"], "footer": "Ask ISO for the insurance checklist"},
    "campus_map": {"title": "Ostfalia Campus Wolfenbuettel", "lines": ["  ISO Office:  Am Exer 2, Room 008", "  Mensa:       Building A", "  Library:     Building B", "  IT Center:   Building C", "", "  Bus: Lines 420, 431 -> Ostfalia stop"], "footer": "Lost? Ask us - we know the campus!"},
}

def make_screen(filename, data):
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (W, 8)], fill=ACCENT_COLOR)
    try:
        font_title = ImageFont.truetype("arial.ttf", 34)
        font_body = ImageFont.truetype("arial.ttf", 26)
        font_footer = ImageFont.truetype("arial.ttf", 20)
    except OSError:
        font_title = font_body = font_footer = ImageFont.load_default()
    draw.text((40, 30), data["title"], font=font_title, fill=ACCENT_COLOR)
    draw.line([(40, 80), (W-40, 80)], fill=ACCENT_COLOR, width=2)
    y = 100
    for line in data["lines"]:
        draw.text((50, y), line, font=font_body, fill=TEXT_COLOR)
        y += 40
    draw.rectangle([(0, H-60), (W, H)], fill=FOOTER_COLOR)
    draw.line([(0, H-60), (W, H-60)], fill=ACCENT_COLOR, width=2)
    draw.text((40, H-44), data["footer"], font=font_footer, fill=ACCENT_COLOR)
    img.save(os.path.join(OUTPUT_DIR, filename + ".png"))
    print("OK: " + filename + ".png")

os.makedirs(OUTPUT_DIR, exist_ok=True)
for name, content in SCREENS.items():
    make_screen(name, content)
print("All done!")
