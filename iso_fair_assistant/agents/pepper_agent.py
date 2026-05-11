# agents/pepper_agent.py
#
# Uses the real pypepper API methods discovered in the professor's test file.
# Every method here maps directly to a real robot.xxx() call.

import logging
import threading
from pypepper import PepperRobot
import config
from tablet_server import questions_for_topic

log = logging.getLogger("pepper")

class PepperAgent:
    """
    Wraps PepperRobot with ISO-specific behaviour.
    All low-level robot calls stay in this file — the orchestrator
    only calls the high-level methods below.
    """

    def __init__(self):
        self._robot: PepperRobot | None = None
        self._is_speaking: bool = False  # True while say() is active — gates mic input

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
            self._robot.set_tracking_mode("Head")  # head follows people, body stays still
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

    # ── Speaking ───────────────────────────────────────────────────────────────

    def say(self, text: str, animated: bool = False):
        """Speak out loud. Sets _is_speaking=True while active so main.py
        can pause the mic and avoid capturing Pepper's own voice."""
        log.debug("Pepper says: %s", text)
        self._is_speaking = True
        try:
            if self._robot:
                self._robot.say(text, language=config.PEPPER_LANGUAGE, animated=animated)
            else:
                print(f"[Pepper] {text}")
        finally:
            self._is_speaking = False

    @property
    def is_speaking(self) -> bool:
        """True while Pepper is currently talking. Check before starting mic capture."""
        return self._is_speaking

    # ── Stand-level interactions ───────────────────────────────────────────────

    # Rotating short attract messages — varied so they don't feel repetitive
    _ATTRACT_MESSAGES = [
        "Hello! Wave at me or tap my screen to get started!",
        "Hi there! Come closer — tap my screen or just say hello.",
        "Welcome! Ask me about Erasmus, housing, or studying abroad!",
    ]
    _attract_index: int = 0

    def attract_visitors(self):
        """
        Rotate short attract messages so the stand doesn't feel static.
        Each message suggests a different way to start the interaction.
        """
        self._set_leds_attract()
        self._robot.play_animation("Wave")
        msg = self._ATTRACT_MESSAGES[self._attract_index % len(self._ATTRACT_MESSAGES)]
        self.__class__._attract_index += 1
        self.say(msg, animated=True)

    def greet_new_visitor(self):
        """Greeting kept short — pilot study showed long greetings delay the conversation."""
        self._robot.play_animation("Bow")
        self._set_leds_friendly()
        self.say(
            "Hi! I'm Pepper, your ISO guide. Ask me about Erasmus, housing, language courses, or studying abroad!",
            animated=True,
        )

    def greet_returning_visitor(self):
        """Shorter greeting for someone who already spoke to the stand today."""
        self._robot.play_animation("Yes")
        self.say(
            "Welcome back! Happy to help again. What else can I do for you?",
            animated=True,
        )

    def redirect_out_of_scope(self, topic: str):
        """
        Politely redirect questions the ISO cannot answer.
        Called by the orchestrator when the LLM flags an out-of-scope question.
        """
        self._robot.play_animation("No2")
        self.say(
            f"That's a good question about {topic}, but that falls outside "
            "what our office handles. For that, I'd recommend visiting the "
            "Studierenden-Service office — they handle all general student "
            "administration. Is there anything about international programs "
            "I can help you with instead?"
        )

    def announce_temi_handoff(self, flyer_topic: str):
        """Tell the visitor that Temi is bringing a flyer."""
        self._robot.head_yaw(20)   # glance toward Temi
        self.say(
            f"Let me ask my colleague Temi to bring you the flyer about {flyer_topic}.",
            animated=True,
        )
        self._robot.head_yaw(0)

    def temi_returned(self):
        """Resume conversation after Temi has delivered the flyer."""
        self.say("Temi has your flyer ready.", animated=True)

    def farewell(self):
        """Close the conversation."""
        self._robot.play_animation("Bow")
        self._set_leds_goodbye()
        self.say(
            "Great talking with you! Grab a flyer from Temi's tray, and feel free to come back. See you!",
            animated=True,
        )
        self._robot.led_reset()

    # ── Perception ─────────────────────────────────────────────────────────────

    def detect_face(self) -> bool:
        """
        Returns True if at least one face is detected.
        Uses the blocking wait_for_face with a short timeout.
        """
        try:
            count = self._robot.wait_for_face(timeout=config.FACE_DETECT_TIMEOUT)
            return count > 0
        except TimeoutError:
            return False

    def scan_qr_code(self) -> str | None:
        """
        Wait for the visitor to show their session QR code.
        Returns the visitor ID string, or None on timeout.
        """
        self.say("If you have a visitor ID from today, please show the QR code to my camera.")
        try:
            data = self._robot.wait_for_qr(timeout=config.QR_SCAN_TIMEOUT)
            return data
        except TimeoutError:
            return None

    def listen_for_speech(
        self,
        keywords: list[str],
        timeout: float | None = None,
        threshold: float | None = None,
    ) -> str | None:
        """
        Listen for one of a set of keywords (e.g. yes/no confirmations).
        Returns the heard keyword or None on timeout.
        """
        if not self._robot:
            return None
        try:
            word = self._robot.wait_for_keyword(
                keywords,
                timeout=timeout if timeout is not None else config.SPEECH_TIMEOUT,
                threshold=threshold if threshold is not None else config.SPEECH_KEYWORD_THRESHOLD,
            )
            return word
        except TimeoutError:
            return None

    def wait_for_any_touch(self) -> str | None:
        """Block until the visitor touches any sensor. Returns sensor name."""
        try:
            return self._robot.wait_for_touch(buttons=None, timeout=config.SESSION_IDLE_TIMEOUT)
        except TimeoutError:
            return None

    def get_tablet_input(self, timeout: float = None) -> str | None:
        """Return the next button press from Pepper's tablet page."""
        if not self._robot:
            return None
        try:
            return self._robot.get_tablet_touch(timeout=timeout)
        except Exception as e:
            log.debug("Tablet input error: %s", e)
            return None

    def set_tablet_state(self, state: str) -> bool:
        if self._robot:
            return self._robot.set_tablet_state(state)
        return False

    def set_tablet_questions(self, questions: list[str]) -> bool:
        if self._robot:
            return self._robot.set_tablet_questions(questions)
        return False

    def set_tablet_questions_for_topic(self, topic: str) -> bool:
        if self._robot:
            return self._robot.set_tablet_questions(questions_for_topic(topic))
        return False

    def wait_for_start_touch(self, timeout: float = 8.0) -> bool:
        """
        Wait for either the Pepper tablet start button or any body touch sensor.

        Returns True if a start signal was detected before timeout, otherwise False.
        """
        if not self._robot:
            return False

        touched = threading.Event()

        def _wait_tablet_touch():
            try:
                if self._robot.wait_for_tablet_touch(timeout=timeout):
                    touched.set()
            except TimeoutError:
                pass
            except Exception as e:
                log.debug("Tablet touch wait error: %s", e)

        def _wait_body_touch():
            try:
                sensor = self._robot.wait_for_touch(buttons=None, timeout=timeout)
                if sensor:
                    touched.set()
            except TimeoutError:
                pass
            except Exception as e:
                log.debug("Body touch wait error: %s", e)

        tablet_touch_thread = threading.Thread(target=_wait_tablet_touch, daemon=True)
        body_touch_thread = threading.Thread(target=_wait_body_touch, daemon=True)
        tablet_touch_thread.start()
        body_touch_thread.start()

        return touched.wait(timeout=timeout)

    # ── Tablet ─────────────────────────────────────────────────────────────────

    def show_tablet_text(self, text: str):
        """Display text on Pepper's chest tablet."""
        if self._robot:
            self._robot.show_text(text)

    def show_tablet_image(self, url_or_path: str):
        """Display an image on Pepper's chest tablet."""
        if self._robot:
            self._robot.show_image(url_or_path)

    def clear_tablet(self):
        if self._robot:
            self._robot.clear_tablet()

    # ── Status ─────────────────────────────────────────────────────────────────

    def print_status(self):
        if not self._robot:
            print("[Pepper] Not connected.")
            return
        battery = self._robot.get_battery_level()
        name    = self._robot.get_robot_name()
        version = self._robot.get_system_version()
        print(f"[Pepper] {name} | NAOqi {version} | Battery {battery}%")

    # ── Internal LED helpers ───────────────────────────────────────────────────

    def _set_leds_attract(self):
        """Cyan pulsing eyes to attract attention from a distance."""
        self._robot.led_fade("FaceLeds", "cyan", 1.0)

    def _set_leds_friendly(self):
        """White eyes during normal conversation."""
        self._robot.led_reset()

    def _set_leds_thinking(self):
        """Blue eyes while the LLM is generating a response."""
        self._robot.led_fade("FaceLeds", "blue", 0.5)

    def _set_leds_goodbye(self):
        """Green eyes during farewell."""
        self._robot.led_fade("FaceLeds", "green", 1.0)

    def set_thinking_leds(self):
        """Called by orchestrator while waiting for LLM response."""
        self._set_leds_thinking()

    def set_speaking_leds(self):
        """Called by orchestrator when Pepper starts speaking."""
        self._set_leds_friendly()

    # ── Tablet splash ──────────────────────────────────────────────────────────

    def show_splash(self, wait_for_tap: bool = False, timeout: float = 8.0) -> bool:
        """
        Show a welcome / tap-to-start message on Pepper's chest tablet.
        Uses pypepper's built-in TabletServer (started automatically because
        local_ip is passed to PepperRobot in connect()).
        Font size is 60px — readable at stand distance.

        If wait_for_tap is True, this blocks briefly and returns whether a tap
        (tablet or body touch) was detected.
        """
        if not self._robot:
            return False

        self._robot.show_tablet_home()
        self._robot.set_tablet_questions(questions_for_topic("welcome"))
        self._robot.set_tablet_state("splash")

        if not wait_for_tap:
            return True
        return self.wait_for_start_touch(timeout=timeout)

    # ── Tracking mode helpers ──────────────────────────────────────────────────

    def set_body_tracking(self):
        """
        Switch to WholeBody tracking — Pepper turns its whole body toward
        a detected person. Call this when a visitor arrives.
        """
        if self._robot:
            self._robot.set_tracking_mode("WholeBody")

    def set_head_tracking(self):
        """
        Switch back to Head-only tracking — body stays still, head follows.
        Call this during attract mode between sessions.
        """
        if self._robot:
            self._robot.set_tracking_mode("Head")