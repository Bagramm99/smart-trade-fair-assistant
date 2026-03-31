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
        def show_image(self, path: str):
            print(f"[Temi SCREEN] Displaying: {os.path.basename(path)}")

    def __init__(self, ip: str, port: int = 7070):
        self.tts        = self._TTS()
        self.navigation = self._Navigation()
        self.media      = self._Media()
        print(f"[Temi] Stub connected ({ip}:{port})")

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
# Maps LLM-identified topics to PNG filenames in assets/temi_screens/.
# Add entries here as new slide exports become available.

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
            self._robot.stop()
            log.info("Temi disconnected.")

    # ── Main actions called by orchestrator ────────────────────────────────────

    def deliver_flyer(self, topic: str) -> bool:
        """
        Display the image for the topic and say the delivery line.
        Returns True on success. Called after Pepper asks for permission.
        """
        image_path = self._resolve_image(topic)
        speech     = self._delivery_speech(topic)

        log.info("Temi delivering flyer for topic: %s", topic)
        self._show_image(image_path)
        self._speak(speech)
        return True

    def show_topic_image(self, topic: str):
        """
        Display the image matching the current conversation topic
        while Pepper is speaking — no speech from Temi.
        Called at the start of each new topic to keep the screen relevant.
        """
        image_path = self._resolve_image(topic)
        self._show_image(image_path)
        log.debug("Temi screen updated: %s", image_path)

    def show_welcome(self):
        """Display the ISO contact card at stand startup."""
        self.show_topic_image("welcome")

    def show_farewell(self):
        self.show_topic_image("farewell")

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _resolve_image(self, topic: str) -> str:
        filename = TOPIC_IMAGES.get(topic, TOPIC_IMAGES["default"])
        return os.path.join(config.TEMI_ASSETS_DIR, filename)

    def _show_image(self, path: str):
        if self._robot:
            self._robot.media.show_image(path)

    def _speak(self, text: str):
        if self._robot:
            self._robot.tts.speak(text)

    def _delivery_speech(self, topic: str) -> str:
        """Returns a short Temi speech line for each flyer topic."""
        scripts = {
            "erasmus":            "Here is the Erasmus+ and partner university overview. Please take a flyer from my tray!",
            "partner_universities":"Here is the list of partner universities worldwide. Feel free to take one!",
            "language_courses":   "Here is the Sprachenzentrum course overview. Take a flyer from my tray!",
            "housing":            "Here is the housing guide for students. Please take one from my tray!",
            "health_insurance":   "Here is the health insurance information. Take a flyer from my tray!",
            "outgoing_process":   "Here are the steps to apply for a semester abroad. Please take one!",
        }
        return scripts.get(
            topic,
            "Here is some information for you. Please take a flyer from my tray!"
        )
