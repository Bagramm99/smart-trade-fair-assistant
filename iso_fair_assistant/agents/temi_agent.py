# agents/temi_agent.py
#
# Temi integration. The pytemi library is not yet available (Linux x86 wheel).
# This file has a real interface and a stub that mirrors what pytemi will expose.
# Swap the stub class for `from pytemi import TemiRobot` when the library arrives.

import logging
import os
import config

log = logging.getLogger("temi")


# ── Stub (remove when pytemi is installed) ────────────────────────────────────

class _TemiStub:
    """Mirrors the expected pytemi interface. Prints actions instead of calling hardware."""

    class _TTS:
        def speak(self, text: str):
            print(f"[Temi TTS] {text}")

    class _Navigation:
        def go_to(self, location: str):
            print(f"[Temi NAV] Moving to '{location}'")

    class _Media:
        def show_image(self, url: str):
            print(f"[Temi SCREEN] Displaying URL: {url}")

    def __init__(self, ip: str, port: int = 7070):
        self.tts        = self._TTS()
        self.navigation = self._Navigation()
        self.media      = self._Media()
        print(f"[Temi] Stub connected ({ip}:{port})")

    def show_image(self, url: str):
        print(f"[Temi SCREEN] Displaying URL: {url}")

    def say(self, text: str):
        print(f"[Temi TTS] {text}")

    def follow_me(self):
        print("[Temi] Following visitor")

    def stop(self):
        print("[Temi] Stopped")


# ── Try real library, fall back to stub ───────────────────────────────────────

try:
    from pytemi import TemiRobot as _TemiBackend   # type: ignore
    log.info("pytemi library found — using real hardware.")
except ImportError:
    _TemiBackend = _TemiStub
    log.warning("pytemi not installed — using stub. Replace when library is available.")


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


class TemiAgent:
    """
    High-level controller for Temi.
    The orchestrator calls deliver_flyer() and show_topic_image().
    Everything else stays internal.
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
        Display the image for the topic and say the delivery line.
        Returns True on success. Called after Pepper asks for permission.
        """
        image_url = self._resolve_image(topic)
        speech    = self._delivery_speech(topic)

        log.info("Temi delivering flyer for topic '%s' → %s", topic, image_url)
        self._show_image(image_url)
        self._speak(speech)
        return True

    def show_topic_image(self, topic: str):
        """
        Display the image matching the current conversation topic
        while Pepper is speaking — no speech from Temi.
        """
        image_url = self._resolve_image(topic)
        self._show_image(image_url)
        log.debug("Temi screen updated: %s", image_url)

    def show_welcome(self):
        """Display the ISO contact card at stand startup."""
        self.show_topic_image("welcome")

    def show_farewell(self):
        self.show_topic_image("farewell")

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _resolve_image(self, topic: str) -> str:
        """
        Returns an HTTP URL that Temi can reach over the Roboter-WLAN.

        The Python HTTP server must be running on Windows (NOT WSL!):
            cd <project>/iso_fair_assistant
            python -m http.server 8082 --bind 172.30.36.107

        Temi then fetches:
            http://172.30.36.107:8082/assets/temi_screens/<filename>
        """
        filename = TOPIC_IMAGES.get(topic, TOPIC_IMAGES["default"])
        return f"http://{config.LOCAL_IP}:{config.TABLET_SERVER_PORT}/assets/temi_screens/{filename}"

    def _show_image(self, url: str):
        if self._robot:
            try:
                self._robot.show_image(url)
            except Exception as e:
                log.warning("Temi show_image failed (continuing): %s", e)

    def _speak(self, text: str):
        if self._robot:
            try:
                self._robot.say(text)
            except Exception as e:
                log.warning("Temi say failed (continuing): %s", e)

    def _delivery_speech(self, topic: str) -> str:
        """Returns a short Temi speech line for each flyer topic."""
        scripts = {
            "erasmus":              "Here is the Erasmus+ and partner university overview. Please take a flyer from my tray!",
            "partner_universities": "Here is the list of partner universities worldwide. Feel free to take one!",
            "language_courses":     "Here is the Sprachenzentrum course overview. Take a flyer from my tray!",
            "housing":              "Here is the housing guide for students. Please take one from my tray!",
            "health_insurance":     "Here is the health insurance information. Take a flyer from my tray!",
            "outgoing_process":     "Here are the steps to apply for a semester abroad. Please take one!",
        }
        return scripts.get(
            topic,
            "Here is some information for you. Please take a flyer from my tray!"
        )