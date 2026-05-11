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
import socket
import subprocess
import sys
import time
import threading
from pathlib import Path
import requests
import config

log = logging.getLogger("temi")

# ── Temi REST helpers ─────────────────────────────────────────────────────────

TEMI_BASE_URL = f"http://{config.TEMI_IP}:8080"
HTTP_CONNECT_TIMEOUT = 3
HTTP_READ_TIMEOUT_SHORT = 8
HTTP_READ_TIMEOUT_GOTO = 45

def _is_tcp_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """Best-effort local check whether host:port is listening."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _tablet_server_running(port: int) -> bool:
    """Check common hosts where the local server may be bound."""
    hosts = ["127.0.0.1", "localhost", config.LOCAL_IP]
    return any(_is_tcp_port_open(host, port) for host in hosts)


def _tablet_server_healthy(port: int) -> bool:
    """Check that the image server responds with an actual PNG, not just an open port."""
    sample_url = (
        f"http://{config.LOCAL_IP}:{port}"
        f"{config.TEMI_ASSETS_URL_PREFIX}/partner_world_map.png"
    )
    try:
        resp = requests.get(sample_url, timeout=(HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT_SHORT))
        return resp.status_code < 400 and resp.content.startswith(b"\x89PNG\r\n\x1a\n")
    except Exception:
        return False


def _temi_get(path: str, read_timeout: int = HTTP_READ_TIMEOUT_SHORT):
    """GET helper with consistent timeout and error logging."""
    url = f"{TEMI_BASE_URL}{path}"
    try:
        return requests.get(url, timeout=(HTTP_CONNECT_TIMEOUT, read_timeout))
    except Exception as e:
        log.warning("Temi GET %s failed: %s", url, e)
        return None


def _temi_post(path: str, payload: dict, read_timeout: int):
    """POST helper with consistent timeout and error logging."""
    url = f"{TEMI_BASE_URL}{path}"
    try:
        return requests.post(url, json=payload, timeout=(HTTP_CONNECT_TIMEOUT, read_timeout))
    except Exception as e:
        log.warning("Temi POST %s failed with payload %s: %s", url, payload, e)
        return None


def _temi_locations() -> list[str] | None:
    """Returns saved Temi locations, or None if unavailable."""
    resp = _temi_get("/locations")
    if resp is None:
        return None
    try:
        data = resp.json()
        if isinstance(data, list):
            return [str(x) for x in data]
        return None
    except Exception:
        return None


def _temi_goto(location: str):
    """Send Temi to a saved location via REST API."""
    known_locations = _temi_locations()
    if known_locations is not None and location not in known_locations:
        log.error(
            "Temi goto target '%s' not found. Available locations: %s",
            location,
            known_locations,
        )
        return

    resp = _temi_post("/goto", {"text": location}, read_timeout=HTTP_READ_TIMEOUT_GOTO)
    if resp is None:
        return
    log.info("Temi goto '%s' -> HTTP %s", location, resp.status_code)


def _temi_say(text: str, language: str = "en"):
    """Tell Temi to speak via REST API."""
    resp = _temi_post("/say", {"text": text, "language": language}, read_timeout=HTTP_READ_TIMEOUT_SHORT)
    if resp is None:
        return
    log.info("Temi say -> HTTP %s", resp.status_code)


def _temi_show_image(image_url: str) -> bool:
    """
    Tell Temi to display an image from a URL.

    FIX: The /img endpoint expects:
      - Content-Type: text/plain  (NOT application/json)
      - Payload key: "image"      (NOT "text")
    Previously we were sending json={"text": url} which caused the 500.
    pytemi/robot.py line 258 confirms the correct format.
    """
    import json as _json

    payload = {"image": image_url, "id": "iso-assistant"}
    url = f"{TEMI_BASE_URL}/img"

    try:
        resp = requests.post(
            url,
            data=_json.dumps(payload),
            headers={"Content-Type": "text/plain"},
            timeout=(HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT_SHORT),
        )
        if resp.status_code < 400:
            log.info("Temi img -> HTTP %s | url=%s", resp.status_code, image_url)
            return True

        log.error(
            "Temi img returned HTTP %s | body=%s | image_url=%s",
            resp.status_code,
            (resp.text or "")[:300],
            image_url,
        )
        return False
    except Exception as e:
        log.warning("Temi img POST failed: %s", e)
        return False


def _temi_show_text(text: str) -> bool:
    """Tell Temi to display text on the tablet screen."""
    import json as _json

    payload = {"text": text, "id": "iso-assistant"}
    url = f"{TEMI_BASE_URL}/txt"

    try:
        resp = requests.post(
            url,
            data=_json.dumps(payload),
            headers={"Content-Type": "text/plain"},
            timeout=(HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT_SHORT),
        )
        if resp.status_code < 400:
            log.info("Temi txt -> HTTP %s | text=%s", resp.status_code, text)
            return True

        log.error(
            "Temi txt returned HTTP %s | body=%s | text=%s",
            resp.status_code,
            (resp.text or "")[:300],
            text,
        )
        return False
    except Exception as e:
        log.warning("Temi txt POST failed: %s", e)
        return False


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
# Flyer front covers (displayed on Temi screen while delivering)
FLYER_COVERS = {
    "erasmus":               "flyer_erasmus_cover.png",
    "partner_universities":  "flyer_partners_cover.png",
    "language_courses":      "flyer_language_cover.png",
    "housing":               "flyer_housing_cover.png",
    "health_insurance":      "flyer_insurance_cover.png",
    "outgoing_process":      "flyer_outgoing_cover.png",
    "europe_partners":       "flyer_europe_cover.png",
    "non_eu_partners":       "flyer_non_eu_cover.png",
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

LOCATION_VISITOR = config.TEMI_START_LOCATION   # saved position near the visitor
LOCATION_HOME    = "dairy"  # Temi's starting position at the stand
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
        self._asset_server_proc: subprocess.Popen | None = None
        self._delivery_thread: threading.Thread | None = None
        self._delivery_ready_event = threading.Event()
        self._delivery_done_event = threading.Event()

    def _ensure_tablet_server(self):
        """Start local static server for Temi images if enabled and not running."""
        if not config.AUTO_START_TABLET_SERVER:
            return

        if _tablet_server_running(config.TABLET_SERVER_PORT) and _tablet_server_healthy(config.TABLET_SERVER_PORT):
            return

        if _tablet_server_running(config.TABLET_SERVER_PORT):
            log.warning("Tablet server port %s is open but not serving images; restarting.", config.TABLET_SERVER_PORT)
            if self._asset_server_proc and self._asset_server_proc.poll() is None:
                try:
                    self._asset_server_proc.terminate()
                    self._asset_server_proc.wait(timeout=2)
                except Exception:
                    try:
                        self._asset_server_proc.kill()
                    except Exception:
                        pass

        base_dir = Path(__file__).resolve().parents[1]
        cmd = [
            sys.executable,
            "-m",
            "http.server",
            str(config.TABLET_SERVER_PORT),
            "--bind",
            "0.0.0.0",
            "--directory",
            str(base_dir),
        ]
        try:
            self._asset_server_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            for _ in range(20):
                if _tablet_server_healthy(config.TABLET_SERVER_PORT):
                    log.info(
                        "Started local tablet server at http://%s:%s",
                        config.LOCAL_IP,
                        config.TABLET_SERVER_PORT,
                    )
                    return
                if self._asset_server_proc.poll() is not None:
                    break
                time.sleep(0.1)

            log.warning(
                "Local tablet server did not come up on port %s.",
                config.TABLET_SERVER_PORT,
            )
        except Exception as e:
            log.warning("Failed to start local tablet server: %s", e)

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            self._ensure_tablet_server()
            self._robot = _TemiBackend(config.TEMI_IP)
            locations = _temi_locations()
            if not locations:
                log.error("Temi REST not ready at %s (no locations response).", TEMI_BASE_URL)
                return False
            log.info("Temi ready. Locations available: %s", locations)
            log.info("Temi flyer start location: %s", LOCATION_VISITOR)
            # Move Temi to home base at startup
            _temi_goto(LOCATION_HOME)
            time.sleep(2)
            return True
        except Exception as e:
            log.error("Temi connection failed: %s", e)
            return False

    def get_locations(self) -> list[str]:
        """Return the saved Temi locations currently available on the robot."""
        locations = _temi_locations()
        return locations or []

    def preview_locations(self, pause_seconds: float = 2.0) -> list[str]:
        """
        Cycle through all saved locations so you can see the terminal log and
        decide which one to use as the start/end point.

        Returns the list of locations that were previewed.
        """
        locations = self.get_locations()
        if not locations:
            log.info("No Temi locations available to preview.")
            return []

        for location in locations:
            log.info("Previewing Temi location: %s", location)
            _temi_goto(location)
            time.sleep(pause_seconds)

        log.info("Finished previewing %d Temi locations.", len(locations))
        return locations

    def disconnect(self):
        if self._robot:
            try:
                self._robot.stop()
            except Exception:
                pass
            log.info("Temi disconnected.")

        if self._asset_server_proc and self._asset_server_proc.poll() is None:
            self._asset_server_proc.terminate()
            try:
                self._asset_server_proc.wait(timeout=2)
            except Exception:
                self._asset_server_proc.kill()
            log.info("Local tablet server stopped.")

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
        self._delivery_ready_event.clear()
        self._delivery_done_event.clear()

        # Show image immediately
        if not _temi_show_image(image_url):
            _temi_say("I cannot show the image on my screen right now, but I can still help you with the flyer.")

        # Navigate + speak in background thread
        thread = threading.Thread(
            target=self._delivery_sequence,
            args=(speech, image_url, topic),
            daemon=True,
        )
        thread.start()
        self._delivery_thread = thread
        return True

    def wait_for_delivery(self, timeout: float | None = None) -> bool:
        """Wait until the current flyer delivery thread finishes."""
        thread = self._delivery_thread
        if thread is None:
            return True
        thread.join(timeout=timeout)
        return not thread.is_alive()

    def wait_for_delivery_ready(self, timeout: float | None = None) -> bool:
        """Wait until Temi has arrived, spoken, and shown the flyer."""
        return self._delivery_ready_event.wait(timeout=timeout)

    def _delivery_sequence(self, speech: str, image_url: str, flyer_topic: str | None = None):
        """Background: goto entrance → wait → speak → display flyer cover → wait → goto home base."""
        log.info("Temi → navigating to '%s'", LOCATION_VISITOR)
        _temi_goto(LOCATION_VISITOR)

        # Wait for Temi to physically arrive
        time.sleep(TRAVEL_WAIT_SEC)

        # Speak and refresh image at visitor position
        _temi_say(speech)
        if not _temi_show_image(image_url):
            _temi_say("My screen is currently unavailable.")

        # Display flyer front cover if available
        if flyer_topic:
            flyer_cover_url = self._resolve_flyer_cover(flyer_topic)
            if flyer_cover_url:
                time.sleep(1)
                if _temi_show_image(flyer_cover_url):
                    log.info("Displaying flyer cover for: %s", flyer_topic)
                else:
                    log.warning("Failed to display flyer cover for: %s", flyer_topic)
                    _temi_show_text("Please grab a flyer.")
            else:
                log.warning("No flyer cover configured for: %s", flyer_topic)
                _temi_show_text("Please grab a flyer.")

        self._delivery_ready_event.set()
        log.info("Temi flyer handoff is ready for Pepper.")

        log.info("Temi → waiting %ds for visitor to take flyer ...", FLYER_WAIT_SEC)
        time.sleep(FLYER_WAIT_SEC)

        # Return to stand
        log.info("Temi → returning to '%s'", LOCATION_HOME)
        _temi_goto(LOCATION_HOME)
        log.info("Temi → back at home base.")
        self._delivery_done_event.set()

    def show_topic_image(self, topic: str):
        """Display topic image while Pepper speaks — no navigation."""
        image_url = self._resolve_image(topic)
        if _temi_show_image(image_url):
            log.debug("Temi screen updated: %s", image_url)
        else:
            log.warning("Temi screen not updated: %s", image_url)

    def show_welcome(self):
        """Display ISO contact card at stand startup."""
        self.show_topic_image("welcome")

    def show_farewell(self):
        self.show_topic_image("farewell")

    def clear_screen(self):
        """Clear Temi's screen after a session ends."""
        if self._robot is None:
            return
        try:
            if hasattr(self._robot, "clear_tablet"):
                self._robot.clear_tablet()
            elif hasattr(self._robot, "clear_screen"):
                self._robot.clear_screen()
        except Exception as e:
            log.debug("Temi clear screen failed: %s", e)

    def listen(self, timeout: int = 15) -> str | None:
        """
        Use Temi's built-in microphone and Android ASR for free-form speech.
        This is the primary conversation input — Temi is closer to the visitor
        than Pepper and has a better mic in a noisy fair environment.

        Calls pytemi's TemiRobot.listen() which POSTs to TemiRest /listen.
        Returns full transcript, or None if nothing heard / error.

        NOTE: self._robot must be a real TemiRobot (pytemi), not the stub.
        If pytemi is not installed, this returns None and the terminal
        fallback in main.py takes over.
        """
        if self._robot is None:
            log.warning("Temi not connected — cannot listen.")
            return None
        # Stub doesn't have .listen()
        if not hasattr(self._robot, "listen"):
            log.warning("Temi stub active — listen() not available.")
            return None
        try:
            transcript = self._robot.listen(
                prompt="",
                language="english",
                timeout=timeout,
            )
            if transcript and transcript.strip():
                log.info("Temi heard: %s", transcript.strip())
                return transcript.strip()
            log.debug("Temi listen returned empty transcript.")
            return None
        except Exception as e:
            log.warning("Temi listen failed: %s", e)
            return None

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _resolve_image(self, topic: str) -> str:
        """Returns HTTP URL reachable by Temi over Roboter-WLAN."""
        filename = TOPIC_IMAGES.get(topic, TOPIC_IMAGES["default"])
        prefix = "/" + config.TEMI_ASSETS_URL_PREFIX.strip("/")
        return (
            f"http://{config.LOCAL_IP}:{config.TABLET_SERVER_PORT}"
            f"{prefix}/{filename}"
        )

    def _resolve_flyer_cover(self, flyer_topic: str) -> str | None:
        """Returns HTTP URL for flyer front cover, or None if not available."""
        filename = FLYER_COVERS.get(flyer_topic)
        if not filename:
            return None
        asset_path = Path(__file__).resolve().parents[1] / config.TEMI_ASSETS_DIR / filename
        if not asset_path.exists():
            log.warning("Flyer cover asset missing: %s", asset_path)
            return None
        prefix = "/" + config.TEMI_ASSETS_URL_PREFIX.strip("/")
        return (
            f"http://{config.LOCAL_IP}:{config.TABLET_SERVER_PORT}"
            f"{prefix}/{filename}"
        )