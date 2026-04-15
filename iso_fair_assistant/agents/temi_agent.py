# agents/temi_agent.py
#
# Temi integration via TemiRest HTTP API (port 8080).
#
# Confirmed REST endpoints:
#   GET  /locations                                    → list saved locations
#   POST /goto      {"text": "entrance"}               → navigate to location
#   POST /say       {"text": "...", "language": "en"}  → speak via TTS
#   POST /img       {"text": "http://..."}             → display image URL
#   POST /txt       {"text": "..."}                    → display text on screen

import logging
import time
import threading
import requests
import config

log = logging.getLogger("temi")

# ── Temi REST helpers ─────────────────────────────────────────────────────────

TEMI_BASE_URL = f"http://{config.TEMI_IP}:8080"


def _temi_goto(location: str):
    """Send Temi to a saved location via REST API."""
    try:
        resp = requests.post(
            f"{TEMI_BASE_URL}/goto",
            json={"text": location},
            timeout=5,
        )
        log.info("Temi goto '%s' → HTTP %s", location, resp.status_code)
    except Exception as e:
        log.warning("Temi goto failed: %s", e)


def _temi_say(text: str, language: str = "en"):
    """Tell Temi to speak via REST API."""
    try:
        resp = requests.post(
            f"{TEMI_BASE_URL}/say",
            json={"text": text, "language": language},
            timeout=5,
        )
        log.info("Temi say → HTTP %s", resp.status_code)
    except Exception as e:
        log.warning("Temi say failed: %s", e)


def _temi_show_image(image_url: str):
    """
    Tell Temi to display an image from a URL.
    Endpoint /img with {"text": url} — confirmed working (HTTP 500 is a
    server-side log issue but Temi fetches and displays the image correctly).
    """
    try:
        resp = requests.post(
            f"{TEMI_BASE_URL}/img",
            json={"text": image_url},
            timeout=5,
        )
        log.info("Temi img → HTTP %s | URL: %s", resp.status_code, image_url)
    except Exception as e:
        log.warning("Temi img failed: %s", e)


# ── Stub (used when pytemi is not installed) ──────────────────────────────────

class _TemiStub:
    def __init__(self, ip: str, port: int = 7070):
        print(f"[Temi] Stub connected ({ip}:{port})")

    def stop(self):
        print("[Temi] Stopped")


# ── Try real library, fall back to stub ───────────────────────────────────────

try:
    from pytemi import TemiRobot as _TemiBackend   # type: ignore
    log.info("pytemi library found — using real hardware.")
except ImportError:
    _TemiBackend = _TemiStub
    log.warning("pytemi not installed — using REST API directly.")


# ── Topic → image mapping ─────────────────────────────────────────────────────

TOPIC_IMAGES = {
    "default":               "iso_contact_card.png",
    "welcome":               "iso_contact_card.png",
    "erasmus":               "partner_world_map.png",
    "partner_universities":  "partner_world_map.png",
    "studying_abroad":       "partner_world_map.png",
    "outgoing_process":      "outgoing_process.png",
    "europe_partners":       "erasmus_europe.png",
    "new_erasmus_partners":  "erasmus_new.png",
    "non_eu_partners":       "non_eu_partners_1.png",
    "americas_asia":         "non_eu_partners_2.png",
    "language_courses":      "language_courses.png",
    "housing":               "housing_guide.png",
    "health_insurance":      "health_insurance.png",
    "redirect":              "campus_map.png",
    "farewell":              "iso_contact_card.png",
}

# ── Temi speech scripts per topic ─────────────────────────────────────────────

DELIVERY_SCRIPTS = {
    "erasmus":               "Hi! I am Temi. I have information about Erasmus and our partner universities. Please take a flyer from my tray!",
    "partner_universities":  "Hi! I am Temi. Here is the full list of our partner universities worldwide. Feel free to take one!",
    "language_courses":      "Hi! I am Temi. I have the Sprachenzentrum language course overview for you. Take a flyer from my tray!",
    "housing":               "Hi! I am Temi. Here is the housing guide for exchange students. Please take one from my tray!",
    "health_insurance":      "Hi! I am Temi. I have health insurance information for you. Take a flyer from my tray!",
    "outgoing_process":      "Hi! I am Temi. Here are the steps to apply for a semester abroad. Please take one!",
    "europe_partners":       "Hi! I am Temi. Here is the overview of our Erasmus partners in Europe. Take a flyer!",
    "non_eu_partners":       "Hi! I am Temi. Here are our non-European partner universities. Please take a flyer!",
}

DELIVERY_DEFAULT = (
    "Hi! I am Temi, your information assistant. "
    "Here is some information for you. Please take a flyer from my tray!"
)

# ── Navigation constants ──────────────────────────────────────────────────────

LOCATION_VISITOR = "entrance"   # saved position ~2 meters toward visitor
LOCATION_HOME    = "home base"  # Temi's starting position at the stand
TRAVEL_WAIT_SEC  = 5            # seconds to wait for Temi to arrive
FLYER_WAIT_SEC   = 30           # seconds Temi waits at visitor position


class TemiAgent:
    """
    High-level controller for Temi.
    Uses TemiRest HTTP API directly — no pytemi library needed.
    The orchestrator calls deliver_flyer() and show_topic_image().
    """

    def __init__(self):
        self._robot = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            self._robot = _TemiBackend(config.TEMI_IP)
            log.info("Temi ready.")
            return True
        except Exception as e:
            log.error("Temi connection failed: %s", e)
            return False

    def disconnect(self):
        if self._robot:
            try:
                self._robot.stop()
            except Exception:
                pass
            log.info("Temi disconnected.")

    # ── Main actions called by orchestrator ────────────────────────────────────

    def deliver_flyer(self, topic: str) -> bool:
        """
        Full flyer delivery sequence (runs in background thread):
          1. Show topic image immediately
          2. Drive to 'entrance' (~2 meters toward visitor)
          3. Wait for arrival (5s)
          4. Speak topic info aloud
          5. Wait 30s so visitor can take flyer
          6. Return to 'home base'
        Returns True immediately — navigation runs in background.
        """
        image_url = self._resolve_image(topic)
        speech    = DELIVERY_SCRIPTS.get(topic, DELIVERY_DEFAULT)

        log.info("Temi starting flyer delivery for topic '%s'", topic)

        # Show image immediately
        _temi_show_image(image_url)

        # Navigate + speak in background thread
        thread = threading.Thread(
            target=self._delivery_sequence,
            args=(speech, image_url),
            daemon=True,
        )
        thread.start()
        return True

    def _delivery_sequence(self, speech: str, image_url: str):
        """Background: goto entrance → wait → speak → wait 30s → goto home base."""
        log.info("Temi → navigating to '%s'", LOCATION_VISITOR)
        _temi_goto(LOCATION_VISITOR)

        # Wait for Temi to physically arrive
        time.sleep(TRAVEL_WAIT_SEC)

        # Speak and refresh image at visitor position
        _temi_say(speech)
        _temi_show_image(image_url)

        log.info("Temi → waiting %ds for visitor to take flyer ...", FLYER_WAIT_SEC)
        time.sleep(FLYER_WAIT_SEC)

        # Return to stand
        log.info("Temi → returning to '%s'", LOCATION_HOME)
        _temi_goto(LOCATION_HOME)
        log.info("Temi → back at home base.")

    def show_topic_image(self, topic: str):
        """Display topic image while Pepper speaks — no navigation."""
        image_url = self._resolve_image(topic)
        _temi_show_image(image_url)
        log.debug("Temi screen updated: %s", image_url)

    def show_welcome(self):
        """Display ISO contact card at stand startup."""
        self.show_topic_image("welcome")

    def show_farewell(self):
        self.show_topic_image("farewell")

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _resolve_image(self, topic: str) -> str:
        """Returns HTTP URL reachable by Temi over Roboter-WLAN."""
        filename = TOPIC_IMAGES.get(topic, TOPIC_IMAGES["default"])
        return (
            f"http://{config.LOCAL_IP}:{config.TABLET_SERVER_PORT}"
            f"/assets/temi_screens/{filename}"
        )