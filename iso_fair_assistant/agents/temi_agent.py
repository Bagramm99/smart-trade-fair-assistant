# agents/temi_agent.py
#
# Temi integration via TemiRest HTTP API (port 8080).
#
# REST endpoints (confirmed):
#   GET  /locations                          → list saved locations
#   POST /goto      text/plain {"text":"x"}  → navigate to saved location
#   POST /say       text/plain {"text":"x"}  → TTS
#   POST /img       text/plain {"image":"x"} → display image URL  ← key: "image" not "text"
#   POST /txt       text/plain {"text":"x"}  → display text
#
# Attempted (may work depending on TemiRest version):
#   POST /follow    text/plain {}            → follow nearest person
#   GET  /stop                               → stop current action

import json as _json
import logging
import socket
import subprocess
import sys
import time
import threading
from pathlib import Path
import requests
import config

log = logging.getLogger("temi")

TEMI_BASE_URL          = f"http://{config.TEMI_IP}:8080"
HTTP_CONNECT_TIMEOUT   = 3
HTTP_READ_TIMEOUT_SHORT = 8
HTTP_READ_TIMEOUT_GOTO = 45

# ── Low-level REST helpers ────────────────────────────────────────────────────

def _plain_post(path: str, payload: dict, read_timeout: int = HTTP_READ_TIMEOUT_SHORT):
    """POST with Content-Type: text/plain (required by most TemiRest endpoints)."""
    url = f"{TEMI_BASE_URL}{path}"
    try:
        resp = requests.post(
            url,
            data=_json.dumps(payload),
            headers={"Content-Type": "text/plain"},
            timeout=(HTTP_CONNECT_TIMEOUT, read_timeout),
        )
        return resp
    except Exception as e:
        log.warning("Temi POST %s failed: %s", url, e)
        return None


def _temi_get(path: str, read_timeout: int = HTTP_READ_TIMEOUT_SHORT):
    url = f"{TEMI_BASE_URL}{path}"
    try:
        return requests.get(url, timeout=(HTTP_CONNECT_TIMEOUT, read_timeout))
    except Exception as e:
        log.warning("Temi GET %s failed: %s", url, e)
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


def _temi_goto(location: str):
    known = _temi_locations()
    if known is not None and location not in known:
        log.error("Temi location '%s' not found. Available: %s", location, known)
        return False
    resp = _plain_post("/goto", {"text": location, "id": "iso"}, HTTP_READ_TIMEOUT_GOTO)
    if resp:
        log.info("Temi goto '%s' -> HTTP %s", location, resp.status_code)
    return resp is not None


def _temi_say(text: str, language: str = "english"):
    resp = _plain_post("/say", {"text": text, "language": language, "id": "iso"})
    if resp:
        log.info("Temi say -> HTTP %s", resp.status_code)


def _temi_show_image(image_url: str) -> bool:
    """
    Display an image on Temi's screen.
    KEY FIX: field is "image" (not "text"), Content-Type must be text/plain.
    """
    resp = _plain_post("/img", {"image": image_url, "id": "iso"})
    if resp is None:
        return False
    if resp.status_code < 400:
        log.info("Temi img -> HTTP %s | %s", resp.status_code, image_url)
        return True
    log.error("Temi img HTTP %s | body: %s", resp.status_code, (resp.text or "")[:200])
    return False


def _temi_follow() -> bool:
    """
    Try to activate Temi's built-in person-following mode.
    TemiRest may not expose this on all versions — returns True if accepted.
    """
    resp = _plain_post("/follow", {})
    if resp is None:
        return False
    if resp.status_code < 400:
        log.info("Temi follow mode activated (HTTP %s)", resp.status_code)
        return True
    log.warning("Temi /follow returned HTTP %s — not supported on this version", resp.status_code)
    return False


def _temi_stop():
    _temi_get("/stop")


# ── Image / navigation constants ──────────────────────────────────────────────

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
    "partner_universities": "Hi! I am Temi. Here is the full list of our partner universities. Feel free to take one!",
    "language_courses":     "Hi! I am Temi. Here is the Sprachenzentrum language course overview. Take one from my tray!",
    "housing":              "Hi! I am Temi. Here is the housing guide for exchange students. Please take one!",
    "health_insurance":     "Hi! I am Temi. Here is the health insurance information. Take a flyer from my tray!",
    "outgoing_process":     "Hi! I am Temi. Here are the steps to apply for a semester abroad. Please take one!",
    "europe_partners":      "Hi! I am Temi. Here are our Erasmus partners in Europe. Take a flyer!",
    "non_eu_partners":      "Hi! I am Temi. Here are our non-European partner universities. Please take a flyer!",
}
DELIVERY_DEFAULT = "Hi! I am Temi. Here is some information for you. Please take a flyer from my tray!"

# Saved Temi locations — must be pre-mapped in the TemiRest app
LOCATION_VISITOR = "entrance"    # ~2m toward where visitors stand
LOCATION_HOME    = "home base"   # Temi's resting spot at the stand table
TRAVEL_WAIT_SEC  = 5             # wait for Temi to physically arrive
FLYER_WAIT_SEC   = 30            # time for visitor to take flyer

# Whether to try /follow before falling back to goto("entrance")
ATTEMPT_FOLLOW   = True


# ── TemiAgent ─────────────────────────────────────────────────────────────────

def _is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class TemiAgent:
    def __init__(self):
        self._tablet_server = None   # injected: agent.set_tablet_server(ts)
        self._server_started = False

    def set_tablet_server(self, tablet_server):
        """Inject the shared TabletServer (already started by main.py)."""
        self._tablet_server = tablet_server
        self._server_started = True

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            locations = _temi_locations()
            if not locations:
                log.error("Temi REST not ready at %s.", TEMI_BASE_URL)
                return False
            log.info("Temi ready. Locations: %s", locations)

            for loc in (LOCATION_VISITOR, LOCATION_HOME):
                if loc not in locations:
                    log.warning(
                        "Location '%s' not saved in Temi app! "
                        "Save it via TemiRest before the demo. Available: %s",
                        loc, locations,
                    )
            return True
        except Exception as e:
            log.error("Temi connection failed: %s", e)
            return False

    def disconnect(self):
        log.info("Temi disconnected.")

    # ── Main actions ───────────────────────────────────────────────────────────

    def deliver_flyer(self, topic: str) -> bool:
        """
        Show image immediately, then in a background thread:
          1. Try /follow (person-following mode) — if supported, Temi
             moves toward the nearest detected person automatically.
          2. If /follow not supported, go to saved 'entrance' position.
          3. Speak delivery line + refresh image.
          4. Wait 30s for visitor to take flyer.
          5. Return to 'home base'.
        """
        image_url = self._resolve_image(topic)
        speech    = DELIVERY_SCRIPTS.get(topic, DELIVERY_DEFAULT)

        log.info("Temi delivering flyer for '%s'", topic)

        # Show image immediately on screen
        if not _temi_show_image(image_url):
            log.warning("Temi screen unavailable for image display.")

        thread = threading.Thread(
            target=self._delivery_sequence,
            args=(speech, image_url),
            daemon=True,
        )
        thread.start()
        return True

    def _delivery_sequence(self, speech: str, image_url: str):
        """
        Step 1: Approach visitor.
        Try /follow first (Temi detects and approaches nearest person).
        If /follow is not supported, fall back to goto("entrance").
        """
        approached = False

        if ATTEMPT_FOLLOW:
            log.info("Temi → trying /follow to approach visitor ...")
            approached = _temi_follow()
            if approached:
                # Give Temi a moment to start moving and reach the person
                time.sleep(TRAVEL_WAIT_SEC + 2)
            else:
                log.info("Temi → /follow not supported, falling back to goto('%s')", LOCATION_VISITOR)

        if not approached:
            _temi_goto(LOCATION_VISITOR)
            time.sleep(TRAVEL_WAIT_SEC)

        # At visitor position: speak + show image
        _temi_say(speech)
        _temi_show_image(image_url)

        log.info("Temi → waiting %ds for visitor to take flyer ...", FLYER_WAIT_SEC)
        time.sleep(FLYER_WAIT_SEC)

        # Stop following / return home
        if approached:
            _temi_stop()
        log.info("Temi → returning to '%s'", LOCATION_HOME)
        _temi_goto(LOCATION_HOME)
        log.info("Temi → back at home base.")

    def show_topic_image(self, topic: str):
        """Update Temi's screen to match current conversation topic."""
        image_url = self._resolve_image(topic)
        if _temi_show_image(image_url):
            log.debug("Temi screen updated: %s", image_url)

    def show_welcome(self):
        self.show_topic_image("welcome")

    def show_farewell(self):
        self.show_topic_image("farewell")

    # ── Internal ───────────────────────────────────────────────────────────────

    def _resolve_image(self, topic: str) -> str:
        filename = TOPIC_IMAGES.get(topic, TOPIC_IMAGES["default"])
        if self._tablet_server:
            return self._tablet_server.url(f"/assets/temi_screens/{filename}")
        # Fallback if server not injected
        prefix = "/" + config.TEMI_ASSETS_URL_PREFIX.strip("/")
        return f"http://{config.LOCAL_IP}:{config.TABLET_SERVER_PORT}{prefix}/{filename}"
