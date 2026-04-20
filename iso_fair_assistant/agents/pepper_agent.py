# agents/pepper_agent.py

import logging
import threading
import time
from typing import TYPE_CHECKING

from pypepper import PepperRobot
import config

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger("pepper")


# ── Pepper mic capture (NAOqi ALAudioDevice) ──────────────────────────────────

class _AudioCapture:
    """
    qi module that receives raw PCM frames from ALAudioDevice.
    Registered with session.registerService() so NAOqi can call onAudioData.
    """
    def __init__(self):
        self._frames = []
        self._lock   = threading.Lock()

    def onAudioData(self, numChannels, numSamples, timestamp, buffer):
        """Called by ALAudioDevice for every audio frame (16kHz PCM int16)."""
        try:
            import numpy as _np
            arr = _np.frombuffer(bytearray(buffer), dtype=_np.int16)
            # Deinterleave: take front mic (channel 0)
            if numChannels > 1:
                arr = arr[::numChannels]
            arr = arr.astype(_np.float32) / 32768.0
            with self._lock:
                self._frames.append(arr)
        except Exception as e:
            log.debug("Audio frame error: %s", e)

    def get_audio(self):
        with self._lock:
            if not self._frames:
                return None
            import numpy as _np
            return _np.concatenate(self._frames)


def _capture_from_pepper(session, audio_service, duration: float) -> "np.ndarray | None":
    """
    Capture `duration` seconds of audio from Pepper's front mic.
    Returns float32 numpy array at 16kHz, or None on failure.
    """
    if audio_service is None:
        log.warning("ALAudioDevice not available — cannot capture from Pepper mic.")
        return None

    capture    = _AudioCapture()
    service_id = None
    try:
        service_id = session.registerService("ISO_Mic", capture)
        # 16000 Hz, front mic (channel 0), non-deinterleaved=0
        audio_service.setClientPreferences("ISO_Mic", 16000, 0, 0)
        audio_service.subscribe("ISO_Mic")
        time.sleep(duration)
    except Exception as e:
        log.error("Pepper mic capture error: %s", e)
        return None
    finally:
        try:
            audio_service.unsubscribe("ISO_Mic")
        except Exception:
            pass
        if service_id is not None:
            try:
                session.unregisterService(service_id)
            except Exception:
                pass

    return capture.get_audio()


# ── PepperAgent ────────────────────────────────────────────────────────────────

class PepperAgent:
    """
    Wraps PepperRobot with ISO stand-specific behaviour.
    Tablet display is controlled here via the TabletServer reference.
    """

    def __init__(self):
        self._robot: PepperRobot | None = None
        self._tablet_server = None   # injected after creation: agent.set_tablet_server(ts)

    def set_tablet_server(self, tablet_server):
        """Inject tablet server so Pepper can update its own display state."""
        self._tablet_server = tablet_server

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            log.info("Connecting to Pepper at %s ...", config.PEPPER_IP)
            self._robot = PepperRobot(config.PEPPER_IP, local_ip=config.LOCAL_IP)
            self._robot.wakeup()
            self._robot.go_to_posture("Stand")
            self._robot.set_volume(config.PEPPER_VOLUME)
            self._robot.configure_awareness(
                background_movement=True,
                speaking_movement=True,
            )
            self._robot.set_tracking_mode("Head")
            self._robot.led_reset()
            log.info("Pepper ready.")
            return True
        except Exception as e:
            log.error("Connection failed: %s", e)
            return False

    def disconnect(self):
        if self._robot:
            self._robot.led_reset()
            self._robot.rest()
            self._robot.close()
            log.info("Pepper disconnected.")

    # ── Tablet display ─────────────────────────────────────────────────────────

    def _set_tablet_state(self, state: str):
        """Update the interactive tablet page state."""
        if self._tablet_server:
            self._tablet_server.set_state(state)

    def show_tablet_page(self):
        """
        Load the interactive tablet page on Pepper's screen.
        Call once at startup — the page then updates itself via polling.
        """
        if self._robot and self._tablet_server:
            url = self._tablet_server.tablet_page_url()
            try:
                self._robot.tablet.loadUrl(url)
                self._robot.tablet.showWebview()
                log.info("Pepper tablet loaded: %s", url)
            except Exception as e:
                log.warning("Could not load tablet page: %s", e)

    # ── Speaking ───────────────────────────────────────────────────────────────

    def say(self, text: str, animated: bool = False):
        log.debug("Pepper says: %s", text)
        self._set_tablet_state("speaking")
        if self._robot:
            self._robot.say(text, language=config.PEPPER_LANGUAGE, animated=animated)
        else:
            print(f"[Pepper] {text}")
        self._set_tablet_state("idle")

    # ── Interactions ───────────────────────────────────────────────────────────

    def attract_visitors(self):
        self._set_leds_attract()
        self._set_tablet_state("idle")
        self._robot.play_animation("Wave")
        self.say(
            "Hello! Welcome to the International Student Office stand. "
            "We help exchange students and anyone interested in studying abroad. "
            "Come talk to me!",
            animated=True,
        )

    def greet_new_visitor(self):
        self._robot.play_animation("Bow")
        self._set_leds_friendly()
        self.say(
            "Hi there! I am Pepper, your guide at the International Student Office. "
            "I can answer questions about Erasmus, studying abroad, language courses, "
            "housing, and more. You can also tap the screen to choose a topic!",
            animated=True,
        )

    def greet_returning_visitor(self):
        self._robot.play_animation("Yes")
        self.say(
            "Welcome back! Happy to help again. What else can I do for you?",
            animated=True,
        )

    def redirect_out_of_scope(self, topic: str):
        self._robot.play_animation("No2")
        self.say(
            f"That's a good question about {topic}, but it falls outside "
            "what our office handles. For that, visit the "
            "Studierenden-Service office — they handle general student admin. "
            "Is there anything about international programmes I can help with?"
        )

    def announce_temi_handoff(self, flyer_topic: str):
        self._robot.head_yaw(20)
        self.say(
            f"Let me ask my colleague Temi to bring you the flyer about {flyer_topic}.",
            animated=True,
        )
        self._robot.head_yaw(0)

    def temi_returned(self):
        self.say(
            "Temi has your flyer ready. Do you have any other questions?",
            animated=True,
        )

    def farewell(self):
        self._robot.play_animation("Bow")
        self._set_leds_goodbye()
        self.say(
            "It was great talking with you! Good luck with your studies. "
            "Feel free to come back anytime or contact us at incoming-iso@ostfalia.de.",
            animated=True,
        )
        self._robot.led_reset()

    # ── Microphone (via Pepper's hardware mic) ─────────────────────────────────

    def listen_with_mic(self, duration: float = 7.0) -> "np.ndarray | None":
        """
        Capture audio from Pepper's front microphone for `duration` seconds.
        Returns a float32 numpy array at 16kHz suitable for Whisper.

        This uses NAOqi's ALAudioDevice — no laptop microphone needed.
        The visitor speaks to Pepper naturally and the audio is processed locally.
        """
        if not self._robot:
            return None
        self._set_tablet_state("listening")
        audio = _capture_from_pepper(
            self._robot.session,
            self._robot.audio,
            duration,
        )
        self._set_tablet_state("thinking")
        return audio

    # ── Perception ─────────────────────────────────────────────────────────────

    def detect_face(self) -> bool:
        """Returns True if at least one face is detected (short timeout)."""
        try:
            count = self._robot.wait_for_face(timeout=config.FACE_DETECT_TIMEOUT)
            return count > 0
        except TimeoutError:
            return False

    def scan_qr_code(self) -> str | None:
        """Wait for QR code scan. Returns visitor ID or None."""
        try:
            return self._robot.wait_for_qr(timeout=config.QR_SCAN_TIMEOUT)
        except TimeoutError:
            return None

    def listen_for_keyword(self, keywords: list[str]) -> str | None:
        """NAOqi keyword detection — use only for simple fallback confirmations."""
        try:
            return self._robot.wait_for_keyword(keywords, timeout=config.SPEECH_TIMEOUT)
        except TimeoutError:
            return None

    # ── Status ─────────────────────────────────────────────────────────────────

    def print_status(self):
        if not self._robot:
            print("[Pepper] Not connected.")
            return
        battery = self._robot.get_battery_level()
        name    = self._robot.get_robot_name()
        version = self._robot.get_system_version()
        print(f"[Pepper] {name} | NAOqi {version} | Battery {battery}%")

    # ── LED helpers ────────────────────────────────────────────────────────────

    def _set_leds_attract(self):
        self._robot.led_fade("FaceLeds", "cyan", 1.0)

    def _set_leds_friendly(self):
        self._robot.led_reset()

    def _set_leds_thinking(self):
        self._robot.led_fade("FaceLeds", "blue", 0.5)

    def _set_leds_goodbye(self):
        self._robot.led_fade("FaceLeds", "green", 1.0)

    def set_thinking_leds(self):
        self._set_leds_thinking()
        self._set_tablet_state("thinking")

    def set_speaking_leds(self):
        self._set_leds_friendly()
        self._set_tablet_state("speaking")
