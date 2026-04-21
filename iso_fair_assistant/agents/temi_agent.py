# agents/temi_agent.py

import json as _json
import logging
import socket
import sys
import time
import threading
from pathlib import Path
import requests
import config

log = logging.getLogger("temi")

TEMI_BASE_URL           = f"http://{config.TEMI_IP}:8080"
HTTP_CONNECT_TIMEOUT    = 3
HTTP_READ_TIMEOUT_SHORT = 10
HTTP_READ_TIMEOUT_GOTO  = 60   # goto blocks until Temi arrives

# ── REST helpers ──────────────────────────────────────────────────────────────

def _plain_post(path: str, payload: dict, read_timeout: int = HTTP_READ_TIMEOUT_SHORT):
    """POST with Content-Type: text/plain (required by TemiRest for most endpoints)."""
    url = f"{TEMI_BASE_URL}{path}"
    try:
        resp = requests.post(
            url,
            data=_json.dumps(payload),
            headers={"Content-Type": "text/plain"},
            timeout=(HTTP_CONNECT_TIMEOUT, read_timeout),
        )
        log.debug("POST %s → %s", path, resp.status_code)
        return resp
    except Exception as e:
        log.warning("POST %s failed: %s", path, e)
        return None


def _json_post(path: str, payload: dict, read_timeout: int = HTTP_READ_TIMEOUT_SHORT):
    """POST with Content-Type: application/json (used by /goto, /say per pytemi)."""
    url = f"{TEMI_BASE_URL}{path}"
    try:
        resp = requests.post(url, json=payload,
                             timeout=(HTTP_CONNECT_TIMEOUT, read_timeout))
        log.debug("POST(json) %s → %s", path, resp.status_code)
        return resp
    except Exception as e:
        log.warning("POST(json) %s failed: %s", path, e)
        return None


def _temi_get(path: str, timeout: int = HTTP_READ_TIMEOUT_SHORT):
    url = f"{TEMI_BASE_URL}{path}"
    try:
        return requests.get(url, timeout=(HTTP_CONNECT_TIMEOUT, timeout))
    except Exception as e:
        log.warning("GET %s failed: %s", path, e)
        return None


def _temi_locations() -> list[str] | None:
    resp = _temi_get("/locations")
    if resp is None:
        return None
    try:
        data = resp.json()
        return [str(x) for x in data] if isinstance(data, list) else None
    except Exception:
        return None


def _temi_goto(location: str) -> bool:
    """Navigate to a saved location. Blocks until Temi arrives (up to 60s)."""
    log.info("Temi → goto '%s'", location)
    # Try both content-types — different TemiRest versions vary
    resp = _json_post("/goto", {"text": location, "id": "iso"}, HTTP_READ_TIMEOUT_GOTO)
    if resp is None:
        # Fallback: try text/plain
        resp = _plain_post("/goto", {"text": location, "id": "iso"}, HTTP_READ_TIMEOUT_GOTO)
    if resp:
        log.info("Temi goto '%s' → HTTP %s", location, resp.status_code)
        return resp.status_code < 400
    return False


def _temi_say(text: str, language: str = "english") -> bool:
    """Temi speaks. Tries json first, then text/plain."""
    log.info("Temi say: %s", text[:60])
    resp = _json_post("/say", {"text": text, "language": language, "id": "iso"})
    if resp is None:
        resp = _plain_post("/say", {"text": text, "language": language, "id": "iso"})
    if resp:
        log.info("Temi say → HTTP %s", resp.status_code)
        return resp.status_code < 400
    return False


def _temi_show_image(image_url: str) -> bool:
    """Display image on Temi screen. Requires Content-Type: text/plain, key: 'image'."""
    resp = _plain_post("/img", {"image": image_url, "id": "iso"})
    if resp and resp.status_code < 400:
        log.info("Temi img → HTTP %s", resp.status_code)
        return True
    if resp:
        log.error("Temi img → HTTP %s | %s", resp.status_code, resp.text[:200])
    return False


# ── Topic → image mapping ──────────────────────────────────────────────────────

TOPIC_IMAGES = {
    "default":              "iso_contact_card.png",
    "welcome":              "iso_contact_card.png",
    "erasmus":              "partner_world_map.png",
    "partner_universities": "partner_world_map.png",
    "studying_abroad":      "partner_world_map.png",
    "outgoing_process":     "outgoing_process.png",
    "europe_partners":      "erasmus_europe.png",
    "new_erasmus_partners": "erasmus_new.png",
    "non_eu_partners":      "non_eu_partners_1.png",
    "americas_asia":        "non_eu_partners_2.png",
    "language_courses":     "language_courses.png",
    "housing":              "housing_guide.png",
    "health_insurance":     "health_insurance.png",
    "redirect":             "campus_map.png",
    "farewell":             "iso_contact_card.png",
}

DELIVERY_SCRIPTS = {
    "erasmus":              "Hi! I am Temi. Here is the Erasmus and partner universities flyer. Please take one from my tray!",
    "partner_universities": "Hi! I am Temi. Here is the list of our partner universities worldwide. Feel free to take one!",
    "language_courses":     "Hi! I am Temi. Here is the Sprachenzentrum language courses overview. Take one from my tray!",
    "housing":              "Hi! I am Temi. Here is the housing guide for exchange students. Please take one!",
    "health_insurance":     "Hi! I am Temi. Here is the health insurance information. Take a flyer from my tray!",
    "outgoing_process":     "Hi! I am Temi. Here are the steps to apply for a semester abroad. Please take one!",
    "europe_partners":      "Hi! I am Temi. Here are our Erasmus partners in Europe. Take a flyer!",
    "non_eu_partners":      "Hi! I am Temi. Here are our non-European partner universities. Please take one!",
}
DELIVERY_DEFAULT = "Hi! I am Temi. Here is some information for you. Please take a flyer from my tray!"

# Navigation — must match names saved in TemiRest app exactly
LOCATION_VISITOR = "entrance"
LOCATION_HOME    = "home base"
TRAVEL_WAIT_SEC  = 3    # extra wait after goto returns
FLYER_WAIT_SEC   = 25   # time for visitor to take flyer


# ── TemiAgent ─────────────────────────────────────────────────────────────────

class TemiAgent:
    def __init__(self):
        self._tablet_server = None

    def set_tablet_server(self, ts):
        self._tablet_server = ts

    def connect(self) -> bool:
        locations = _temi_locations()
        if locations is None:
            log.error("Cannot reach Temi REST at %s. Is TemiRest app open?", TEMI_BASE_URL)
            return False
        log.info("Temi connected. Locations: %s", locations)
        for loc in (LOCATION_VISITOR, LOCATION_HOME):
            if loc not in locations:
                log.warning(
                    "Location '%s' NOT found in Temi app! "
                    "Save it in TemiRest before the demo. Available: %s",
                    loc, locations,
                )
        return True

    def disconnect(self):
        log.info("Temi disconnected.")

    # ── Actions ───────────────────────────────────────────────────────────────

    def deliver_flyer(self, topic: str) -> bool:
        """
        Show image immediately, then in a daemon thread:
          goto entrance → speak → show image → wait → goto home base.
        Returns immediately — never blocks the main thread.
        """
        image_url = self._resolve_image(topic)
        speech    = DELIVERY_SCRIPTS.get(topic, DELIVERY_DEFAULT)

        log.info("deliver_flyer('%s') starting ...", topic)

        # Show image on Temi screen immediately
        _temi_show_image(image_url)

        # All navigation + speech in background — never blocks caller
        def _run():
            try:
                log.info("Temi thread: going to '%s'", LOCATION_VISITOR)
                _temi_goto(LOCATION_VISITOR)
                time.sleep(TRAVEL_WAIT_SEC)

                log.info("Temi thread: speaking delivery line")
                _temi_say(speech)
                _temi_show_image(image_url)

                log.info("Temi thread: waiting %ds", FLYER_WAIT_SEC)
                time.sleep(FLYER_WAIT_SEC)

                log.info("Temi thread: returning to '%s'", LOCATION_HOME)
                _temi_goto(LOCATION_HOME)
                log.info("Temi thread: done.")
            except Exception as e:
                log.error("Temi delivery thread crashed: %s", e, exc_info=True)

        t = threading.Thread(target=_run, daemon=True, name="temi-delivery")
        t.start()
        log.info("Temi delivery thread started (id=%s)", t.ident)
        return True

    def show_topic_image(self, topic: str):
        url = self._resolve_image(topic)
        _temi_show_image(url)

    def show_welcome(self):
        self.show_topic_image("welcome")

    def show_farewell(self):
        self.show_topic_image("farewell")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _resolve_image(self, topic: str) -> str:
        filename = TOPIC_IMAGES.get(topic, TOPIC_IMAGES["default"])
        if self._tablet_server:
            return self._tablet_server.url(f"/assets/temi_screens/{filename}")
        prefix = "/" + config.TEMI_ASSETS_URL_PREFIX.strip("/")
        return f"http://{config.LOCAL_IP}:{config.TABLET_SERVER_PORT}{prefix}/{filename}"