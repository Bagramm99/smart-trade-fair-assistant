import json
import logging
import math
import os
import time
import urllib.parse
from typing import Callable, List, Optional

import qi

from ._animations import ANIMATIONS, resolve_animation, is_behavior, BEHAVIOR_PREFIX
from ._events import EventManager
from .server import TabletServer

logger = logging.getLogger("pypepper")

class PepperRobot:
    def __init__(
            self,
            ip: str,
            port: int = 9559,
            local_ip: str = None,
            tablet_server_port: int = 8080,
            local_image_dir: str = None):
        
        self.ip = ip
        self.port = port
        self.local_ip= local_ip
        self.local_image_dir = local_image_dir

        # qi application and session
        self.app = qi.Application(["pypepper", f"--qi-url=tcp://{ip}:{port}"])
        try:
            self.app.start()
        except RuntimeError as e:
            raise ConnectionError(
                f"Cannot connect to Pepper robot at {ip}:{port}. "
                f"Please verify:\n"
                f"  1. Pepper is powered on and connected to the network\n"
                f"  2. The IP address '{ip}' is correct\n"
                f"  3. This machine and Pepper are on the same subnet\n"
                f"  4. No firewall is blocking port {port}\n"
                f"Original error: {e}"
            ) from e
        self.session = self.app.session

        # naoqi service proxies (existing)
        self.tts = None
        self.animated_speech = None
        self.tablet = None
        self.motion = None
        self.posture = None
        self.leds = None

        # naoqi service proxies (new)
        self.animation_player = None
        self.awareness = None
        self.audio = None
        self.battery = None
        self.behavior = None
        self.memory = None
        self.navigation = None
        self.speech_recognition_service = None
        self.face_detection_service = None
        self.barcode = None
        self.system = None
        self.life = None
        self.video = None

        # internal state
        self._tablet_server = None
        self._event_manager = None

        self._connect()

        if local_ip:
            self._tablet_server = TabletServer(local_ip, tablet_server_port, local_image_dir)

    # ===============================================================================================
    # Connection to Pepper
    # ===============================================================================================

    def _connect(self):
        try:
            # Core services (required)
            self.tts = self.session.service("ALTextToSpeech")
            self.animated_speech = self.session.service("ALAnimatedSpeech")
            self.tablet = self.session.service("ALTabletService")
            self.motion = self.session.service("ALMotion")
            self.posture = self.session.service("ALRobotPosture")
            self.leds = self.session.service("ALLeds")
            self.memory = self.session.service("ALMemory")

            # Extended services (optional - some may not be available on virtual robots)
            self.animation_player = self._get_service("ALAnimationPlayer")
            self.awareness = self._get_service("ALBasicAwareness")
            self.audio = self._get_service("ALAudioDevice")
            self.battery = self._get_service("ALBattery")
            self.behavior = self._get_service("ALBehaviorManager")
            self.navigation = self._get_service("ALNavigation")
            self.speech_recognition_service = self._get_service("ALSpeechRecognition")
            self.face_detection_service = self._get_service("ALFaceDetection")
            self.barcode = self._get_service("ALBarcodeReader")
            self.system = self._get_service("ALSystem")
            self.life = self._get_service("ALAutonomousLife")
            self.video = self._get_service("ALVideoDevice")

            self.tts.setLanguage("English")

            # Enable event listening from robot - without this, ALMemory event
            # subscriptions will not receive data.
            self.session.listen("tcp://0.0.0.0:0")

            # Initialize event manager
            self._event_manager = EventManager(self.memory, self.session)

            print(f"Connected to Pepper at {self.ip}:{self.port}")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to pepper at {self.ip}:{self.port}: {e}")

    def _get_service(self, name: str):
        """Get a NAOqi service, returning None if unavailable."""
        try:
            return self.session.service(name)
        except Exception:
            logger.warning(f"Service {name} not available on this robot")
            return None

    def _require_service(self, service, name: str):
        """Raise RuntimeError if a service is not available."""
        if service is None:
            raise RuntimeError(f"{name} service is not available on this robot")
        
    def _require_tablet_server(self):
        if not self._tablet_server:
            raise RuntimeError(
                "local_ip is required to use built-in tablet server."
                "Pass it when creating PepperRobot: PepperRobot(ip, local_ip='192.168.x.x')"
            )
        
    
    # ===============================================================================================
    # Speech Methods
    # ===============================================================================================

    def say(self, text: str, language: str = "English", animated: bool = False) -> bool:
        """ Make pepper say something.

        Returns:
            True if speech completed successfully.
        """
        self.tts.setLanguage(language.capitalize())

        if animated:
            self.animated_speech.say(text)
        else:
            self.tts.say(text)

        time.sleep(0.2)
        return True

    def set_volume(self, volume: float) -> bool:
        """ Set tts volume (0.0 - 1.0).

        Returns:
            True if volume was set successfully.
        """
        self.tts.setVolume(volume)
        return True

    # ===============================================================================================
    # Display Methods
    # ===============================================================================================

    def show_image(self, url: str) -> bool:
        """
        Display an image on pepper's tablet.
        Pepper's tablet browser fetches the image directly.

        Returns:
            True if image was displayed successfully.
        """
        if not self.tablet.showImage(url):
            raise ValueError(f"Pepper could not load image from URL: {url}")
        return True

    def show_local_image(self, filepath: str) -> bool:
        """
        Display a local image on pepper's tablet.
        The image is served via the built-in HTTP server.
        Requires local_ip to be set.

        Args:
            filepath: Path to the image file. If local_image_dir is set, this can be just the file name.

        Returns:
            True if image was displayed successfully.
        """

        self._require_tablet_server()
        filename = os.path.basename(filepath)
        url = self._tablet_server.url(f"/image/{filename}")
        if not self.tablet.showImage(url):
            raise ValueError(f"Pepper could not load local image from filepath: {filepath}")
        return True


    def show_text(self, text: str) -> bool:
        """
        Display text on pepper's tablet.
        Requires local_ip to be set.

        Returns:
            True if text was displayed successfully.
        """
        self._require_tablet_server()
        text = urllib.parse.quote(text, safe="")
        url = self._tablet_server.url(f"/text?content={text}")
        self.tablet.loadUrl(url)
        self.tablet.showWebview()
        return True

    def show_website(self, url: str) -> bool:
        """
        Display a website on Pepper's tablet.

        Returns:
            True if website was loaded successfully.
        """
        self.tablet.loadUrl(url)
        self.tablet.showWebview()
        return True

    def tablet_url(self, path: str = "/") -> str:
        """Return a URL on Pepper's built-in tablet server."""
        self._require_tablet_server()
        return self._tablet_server.url(path)

    def set_tablet_state(self, state: str) -> bool:
        """Set the state exposed to the Pepper tablet page."""
        self._require_tablet_server()
        self._tablet_server.set_state(state)
        return True

    def set_tablet_questions(self, questions: list[str]) -> bool:
        """Set the visible button set on the Pepper tablet page."""
        self._require_tablet_server()
        self._tablet_server.set_questions(questions)
        return True

    def show_tablet_home(self) -> bool:
        """Show the built-in Pepper start page on the tablet."""
        return self.show_website(self.tablet_url("/"))

    def get_tablet_touch(self, timeout: float = None) -> str | None:
        """Read the next button press from the Pepper tablet page."""
        self._require_tablet_server()
        return self._tablet_server.get_touch_input(timeout=timeout)

    def wait_for_tablet_touch(self, timeout: float = None) -> str | None:
        """Block until the tablet start button is pressed."""
        self._require_tablet_server()
        return self._tablet_server.wait_for_touch(timeout=timeout)

    def clear_tablet(self) -> bool:
        """
        Clear the tablet.

        Returns:
            True if tablet was cleared successfully.
        """
        if self._tablet_server:
            self.tablet.loadUrl(self._tablet_server.url("/clear"))
            self.tablet.showWebview()
        else:
            self.tablet.hideWebview()
        return True

    
    def wait(self, secs: float):
        """
        Stops Pepper for certain amount of time.
        """
        time.sleep(secs)

    # ===============================================================================================
    # Motion & Navigation Methods
    # ===============================================================================================

    def move_to(self, x: float, y: float) -> bool:
        """Navigate Pepper to position (x, y) relative to current position.

        Uses ALNavigation.navigateTo(). Blocks until navigation completes.

        Args:
            x: Forward distance in meters (positive = forward).
            y: Lateral distance in meters (positive = left).

        Returns:
            True if navigation completed successfully.
        """
        self._require_service(self.navigation, "ALNavigation")
        future = self.navigation.navigateTo(x, y, _async=True)
        future.value()
        return True

    def move_along(self, x: float, y: float, theta: float, duration: float) -> bool:
        """Move Pepper with velocity for a specified duration.

        Uses ALMotion.moveToward() then stops after duration seconds.

        Args:
            x: Forward velocity (-1.0 to 1.0).
            y: Lateral velocity (-1.0 to 1.0).
            theta: Rotational velocity (-1.0 to 1.0).
            duration: Duration in seconds.

        Returns:
            True if movement completed successfully.
        """
        self.motion.moveToward(x, y, theta)
        time.sleep(duration)
        self.motion.stopMove()
        return True

    def hand_open(self, hand: str = "Both") -> bool:
        """Open Pepper's hand(s).

        Args:
            hand: "LHand", "RHand", or "Both".

        Returns:
            True if hand(s) opened successfully.
        """
        if hand == "Both":
            self.motion.openHand("LHand")
            self.motion.openHand("RHand")
        else:
            self.motion.openHand(hand)
        return True

    def hand_close(self, hand: str = "Both") -> bool:
        """Close Pepper's hand(s).

        Args:
            hand: "LHand", "RHand", or "Both".

        Returns:
            True if hand(s) closed successfully.
        """
        if hand == "Both":
            self.motion.closeHand("LHand")
            self.motion.closeHand("RHand")
        else:
            self.motion.closeHand(hand)
        return True

    def head_pitch(self, angle: float, duration: float = 2.0) -> bool:
        """Set Pepper's head pitch (up/down nod).

        Args:
            angle: Angle in degrees. Negative = up, Positive = down.
                   Range approximately -40 to +36 degrees.
            duration: Time in seconds to reach the angle.

        Returns:
            True if head movement completed successfully.
        """
        self.motion.angleInterpolation(
            "HeadPitch", math.radians(angle), duration, True
        )
        return True

    def head_yaw(self, angle: float, duration: float = 2.0) -> bool:
        """Set Pepper's head yaw (left/right turn).

        Args:
            angle: Angle in degrees. Positive = left, Negative = right.
                   Range approximately -119 to +119 degrees.
            duration: Time in seconds to reach the angle.

        Returns:
            True if head movement completed successfully.
        """
        self.motion.angleInterpolation(
            "HeadYaw", math.radians(angle), duration, True
        )
        return True

    def rest(self) -> bool:
        """Put Pepper into rest position (motors off, relaxed posture).

        Blocks until the rest position is reached.

        Returns:
            True if rest position reached successfully.
        """
        future = self.motion.rest(_async=True)
        future.value()
        return True

    def wakeup(self) -> bool:
        """Wake Pepper up from rest position.

        Blocks until the wakeup posture is reached.

        Returns:
            True if wakeup completed successfully.
        """
        future = self.motion.wakeUp(_async=True)
        future.value()
        return True

    def go_to_posture(self, posture_name: str, speed: float = 0.5) -> bool:
        """Move Pepper to a named posture.

        Args:
            posture_name: One of "Stand", "StandInit", "StandZero",
                          "Sit", "Crouch", "LyingBelly", "LyingBack".
            speed: Speed from 0.0 (slow) to 1.0 (fast).

        Returns:
            True if posture reached successfully.
        """
        future = self.posture.goToPosture(posture_name, speed, _async=True)
        future.value()
        return True

    # ===============================================================================================
    # Animation Methods
    # ===============================================================================================

    def play_animation(self, name: str, return_to_stand: bool = True) -> bool:
        """Play a named animation or raw animation path.

        Accepts either a friendly name (e.g., "Wave", "Bow") or a raw
        NAOqi animation path (e.g., "animations/Stand/Gestures/Hey_3").

        After the animation completes, Pepper returns to Stand posture by
        default (matching middleware behavior).

        Args:
            name: Animation name or path. Use get_available_animations()
                  to see friendly names.
            return_to_stand: If True, go to "Stand" posture after animation.

        Returns:
            True if animation completed successfully.

        Raises:
            ValueError: If name is not a recognized animation.
        """
        path = resolve_animation(name)

        if is_behavior(path):
            self._require_service(self.behavior, "ALBehaviorManager")
            if not self.behavior.isBehaviorInstalled(path):
                raise ValueError(f"Behavior '{path}' is not installed on the robot.")
            future = self.behavior.runBehavior(path, _async=True)
            future.value()
        else:
            self._require_service(self.animation_player, "ALAnimationPlayer")
            future = self.animation_player.run(path, _async=True)
            future.value()

        if return_to_stand:
            self.go_to_posture("Stand", 0.5)
        return True

    def get_available_animations(self) -> list:
        """Return list of available friendly animation names.

        Returns:
            List of string names that can be passed to play_animation().
        """
        return list(ANIMATIONS.keys())

    # ===============================================================================================
    # LED Methods
    # ===============================================================================================

    def led_on(self, group: str = "AllLeds") -> bool:
        """Turn on an LED group to full white.

        Args:
            group: LED group name. Options: "AllLeds", "BrainLeds",
                   "ChestLeds", "EarLeds", "FaceLeds", "FeetLeds",
                   "LeftEarLeds", "RightEarLeds", "LeftFaceLeds",
                   "RightFaceLeds".

        Returns:
            True if LEDs turned on successfully.
        """
        self.leds.on(group)
        return True

    def led_off(self, group: str = "AllLeds") -> bool:
        """Turn off an LED group.

        Args:
            group: LED group name (same options as led_on).

        Returns:
            True if LEDs turned off successfully.
        """
        self.leds.off(group)
        return True

    def led_fade(self, group: str, color: str, duration: float = 0.5) -> bool:
        """Fade an LED group to a named color.

        Args:
            group: LED group name (same options as led_on).
            color: Color name string (e.g., "red", "green", "blue",
                   "white", "yellow", "cyan", "magenta").
            duration: Fade time in seconds.

        Returns:
            True if LED fade completed successfully.
        """
        self.leds.fadeRGB(group, color, float(duration))
        return True

    def led_reset(self) -> bool:
        """Reset all LEDs to white (default state).

        Returns:
            True if LEDs reset successfully.
        """
        self.leds.on("AllLeds")
        self.leds.fadeRGB("AllLeds", "white", 0.0)
        return True

    # ===============================================================================================
    # System Information Methods
    # ===============================================================================================

    def get_battery_level(self) -> int:
        """Get current battery charge percentage.

        Returns:
            Battery level as integer (0-100).
        """
        self._require_service(self.battery, "ALBattery")
        return self.battery.getBatteryCharge()

    def get_robot_name(self) -> str:
        """Get the robot's configured name.

        Returns:
            Robot name string.
        """
        self._require_service(self.system, "ALSystem")
        return self.system.robotName()

    def get_system_version(self) -> str:
        """Get the NAOqi system version.

        Returns:
            Version string.
        """
        self._require_service(self.system, "ALSystem")
        return self.system.systemVersion()

    def get_temperature(self, sensor: str = "KneePitch") -> float:
        """Get temperature of a specific joint/sensor.

        Args:
            sensor: Joint sensor name. Common values:
                    "KneePitch", "HipPitch", "HipRoll",
                    "HeadPitch", "HeadYaw", "LShoulderPitch".

        Returns:
            Temperature in degrees Celsius.
        """
        return self.memory.getData(
            f"Device/SubDeviceList/{sensor}/Temperature/Sensor/Value"
        )

    def get_volume(self) -> int:
        """Get the current system output volume.

        Returns:
            Volume level (0-100).
        """
        self._require_service(self.audio, "ALAudioDevice")
        return self.audio.getOutputVolume()

    def set_system_volume(self, volume: int) -> bool:
        """Set the system-wide output volume.

        Args:
            volume: Volume level from 0 to 100.

        Returns:
            True if volume was set successfully.
        """
        self._require_service(self.audio, "ALAudioDevice")
        volume = max(1, min(100, int(volume)))
        self.audio.setOutputVolume(volume)
        return True

    def shutdown(self) -> bool:
        """Shut down the Pepper robot.

        Returns:
            True if shutdown command was sent successfully.
        """
        self._require_service(self.system, "ALSystem")
        self.system.shutdown()
        return True

    def reboot(self) -> bool:
        """Reboot the Pepper robot.

        Returns:
            True if reboot command was sent successfully.
        """
        self._require_service(self.system, "ALSystem")
        self.system.reboot()
        return True

    # ===============================================================================================
    # Awareness / Autonomous Life Methods
    # ===============================================================================================

    def configure_awareness(
        self,
        autonomous_blinking: bool = None,
        background_movement: bool = None,
        basic_awareness: bool = None,
        listening_movement: bool = None,
        speaking_movement: bool = None,
    ) -> bool:
        """Configure Pepper's autonomous awareness behaviors.

        Each parameter that is not None will be set. Parameters left as
        None are not changed.

        Args:
            autonomous_blinking: Enable/disable autonomous eye blinking.
            background_movement: Enable/disable idle body movements.
            basic_awareness: Enable/disable face tracking/awareness.
            listening_movement: Enable/disable movement while listening.
            speaking_movement: Enable/disable gestures while speaking.

        Returns:
            True if awareness configured successfully.
        """
        self._require_service(self.life, "ALAutonomousLife")
        if autonomous_blinking is not None:
            self.life.setAutonomousAbilityEnabled("AutonomousBlinking", autonomous_blinking)
        if background_movement is not None:
            self.life.setAutonomousAbilityEnabled("BackgroundMovement", background_movement)
        if basic_awareness is not None:
            self.life.setAutonomousAbilityEnabled("BasicAwareness", basic_awareness)
        if listening_movement is not None:
            self.life.setAutonomousAbilityEnabled("ListeningMovement", listening_movement)
        if speaking_movement is not None:
            self.life.setAutonomousAbilityEnabled("SpeakingMovement", speaking_movement)
        return True

    def set_tracking_mode(self, mode: str = "WholeBody") -> bool:
        """Set the basic awareness tracking mode.

        Args:
            mode: One of "Head", "BodyRotation", "WholeBody",
                  "MoveContextually".

        Returns:
            True if tracking mode set successfully.
        """
        self._require_service(self.awareness, "ALBasicAwareness")
        self.awareness.setTrackingMode(mode)
        return True

    # ===============================================================================================
    # Speech Recognition Methods
    # ===============================================================================================

    def wait_for_keyword(
        self,
        keywords: list,
        language: str = "English",
        threshold: float = 0.4,
        timeout: float = None,
    ) -> str:
        """Block until Pepper hears one of the given keywords.

        Args:
            keywords: List of words/phrases to listen for, e.g. ["yes", "no"].
            language: Recognition language ("English", "German", etc.).
            threshold: Confidence threshold (0.0-1.0).
            timeout: Seconds to wait. None = wait forever.

        Returns:
            The recognized keyword string.

        Raises:
            TimeoutError: If timeout expires without recognition.
        """
        self._require_service(self.speech_recognition_service, "ALSpeechRecognition")
        self._setup_speech_recognition(keywords, language)

        def _process_word(data):
            if not data or len(data) < 2:
                return None
            word = data[0]
            confidence = data[1]
            if confidence >= threshold:
                return word
            return None

        try:
            return self._event_manager.wait_for_event(
                "WordRecognized", processor=_process_word, timeout=timeout
            )
        finally:
            self.speech_recognition_service.pause(True)

    def on_keyword_detected(
        self,
        callback: Callable,
        keywords: list,
        language: str = "English",
        threshold: float = 0.4,
    ) -> bool:
        """Register a callback for when Pepper hears a keyword.

        The callback receives the recognized keyword string.

        Args:
            callback: Function(keyword: str) called on recognition.
            keywords: List of words to listen for.
            language: Recognition language.
            threshold: Confidence threshold (0.0-1.0).

        Returns:
            True if callback registered successfully.
        """
        self._require_service(self.speech_recognition_service, "ALSpeechRecognition")
        self._setup_speech_recognition(keywords, language)

        def _on_word(data):
            if not data or len(data) < 2:
                return
            word = data[0]
            confidence = data[1]
            if confidence >= threshold:
                callback(word)

        self._event_manager.subscribe(
            "speech_recognition", "WordRecognized", _on_word
        )
        return True

    def stop_speech_recognition(self) -> bool:
        """Stop listening for keywords.

        Returns:
            True if speech recognition stopped successfully.
        """
        if self.speech_recognition_service:
            self.speech_recognition_service.pause(True)
        self._event_manager.unsubscribe("speech_recognition")
        return True

    def _setup_speech_recognition(self, keywords: list, language: str):
        """Configure speech recognition service for keyword detection."""
        sr = self.speech_recognition_service
        sr.pause(True)
        # Workaround to prevent "modifiable_grammar already exists" error.
        sr.setLanguage("German")
        sr.setLanguage("English")
        sr.setLanguage(language)
        sr.setVocabulary(keywords, False)
        sr.setAudioExpression(True)
        sr.setVisualExpression(True)
        sr.pause(False)

    # ===============================================================================================
    # Face Detection Methods
    # ===============================================================================================

    def wait_for_face(self, timeout: float = None) -> int:
        """Block until Pepper detects a face.

        Args:
            timeout: Seconds to wait. None = wait forever.

        Returns:
            Number of faces detected.

        Raises:
            TimeoutError: If timeout expires without detection.
        """
        self._require_service(self.face_detection_service, "ALFaceDetection")
        if self.awareness:
            self.awareness.pauseAwareness()
        self.face_detection_service.setRecognitionEnabled(False)
        self.face_detection_service.subscribe("pypepper_face", 500, 0)

        def _process_face(data):
            if not data or len(data) == 0:
                return None
            face_count = len(data[1]) - 1
            if face_count > 0:
                return face_count
            return None

        try:
            return self._event_manager.wait_for_event(
                "FaceDetected", processor=_process_face, timeout=timeout
            )
        finally:
            try:
                self.face_detection_service.unsubscribe("pypepper_face")
            except Exception:
                pass
            if self.awareness:
                self.awareness.resumeAwareness()

    def on_face_detected(self, callback: Callable) -> bool:
        """Register a callback for face detection.

        The callback receives the number of faces detected (int).

        Args:
            callback: Function(face_count: int) called on face detection.

        Returns:
            True if callback registered successfully.
        """
        self._require_service(self.face_detection_service, "ALFaceDetection")
        if self.awareness:
            self.awareness.pauseAwareness()
        self.face_detection_service.setRecognitionEnabled(False)
        self.face_detection_service.subscribe("pypepper_face", 500, 0)

        def _on_face(data):
            if not data or len(data) == 0:
                return
            face_count = len(data[1]) - 1
            if face_count > 0:
                callback(face_count)

        self._event_manager.subscribe(
            "face_detection", "FaceDetected", _on_face
        )
        return True

    def stop_face_detection(self) -> bool:
        """Stop face detection and re-enable awareness.

        Returns:
            True if face detection stopped successfully.
        """
        self._event_manager.unsubscribe("face_detection")
        if self.face_detection_service:
            try:
                self.face_detection_service.unsubscribe("pypepper_face")
            except Exception:
                pass
        if self.awareness:
            self.awareness.resumeAwareness()
        return True

    # ===============================================================================================
    # Touch / Button Methods
    # ===============================================================================================

    TOUCH_BUTTONS = [
        "Head",
        "LHand/Touch/Back",
        "RHand/Touch/Back",
        "Bumper/FrontLeft",
        "Bumper/FrontRight",
        "Bumper/Back",
    ]

    def wait_for_touch(
        self,
        buttons: list = None,
        timeout: float = None,
    ) -> str:
        """Block until Pepper is touched on one of the specified buttons.

        Args:
            buttons: List of button/sensor names to listen for.
                     Options: "Head", "LHand/Touch/Back", "RHand/Touch/Back",
                     "Bumper/FrontLeft", "Bumper/FrontRight", "Bumper/Back".
                     Default: all buttons.
            timeout: Seconds to wait. None = wait forever.

        Returns:
            Name of the button/sensor that was touched.

        Raises:
            TimeoutError: If timeout expires without touch.
        """
        if buttons is None:
            buttons = self.TOUCH_BUTTONS

        def _process_touch(data):
            return self._match_touch(data, buttons)

        return self._event_manager.wait_for_event(
            "TouchChanged", processor=_process_touch, timeout=timeout
        )

    def on_touch(self, callback: Callable, buttons: list = None) -> bool:
        """Register a callback for touch events.

        The callback receives the sensor name string of the touched button.

        Args:
            callback: Function(sensor_name: str) called on touch.
            buttons: List of sensor names to listen for. Default: all.

        Returns:
            True if callback registered successfully.
        """
        if buttons is None:
            buttons = self.TOUCH_BUTTONS

        def _on_touch(data):
            result = self._match_touch(data, buttons)
            if result is not None:
                callback(result)

        self._event_manager.subscribe("touch", "TouchChanged", _on_touch)
        return True

    def stop_touch_detection(self) -> bool:
        """Stop listening for touch events.

        Returns:
            True if touch detection stopped successfully.
        """
        self._event_manager.unsubscribe("touch")
        return True

    def _match_touch(self, data, buttons: list) -> Optional[str]:
        """Match touch event data against expected buttons.

        Head sub-sensors (Head/Touch/Front, Head/Touch/Middle, Head/Touch/Rear)
        are consolidated to "Head".  Other sensors are matched exactly.
        """
        for sensor in data:
            if not sensor[1]:  # not pressed
                continue
            sensor_name = sensor[0]
            for button in buttons:
                if button == "Head" and "Head" in sensor_name:
                    return "Head"
                if sensor_name == button:
                    return button
        return None

    # ===============================================================================================
    # QR Code Detection Methods
    # ===============================================================================================

    def wait_for_qr(self, timeout: float = None, allow_all: bool = True) -> str:
        """Block until Pepper scans a QR code.

        Args:
            timeout: Seconds to wait. None = wait forever.
            allow_all: If True, return any QR text. If False, only return
                       QR codes containing a JSON object with an "id" field.

        Returns:
            QR code content string (or the "id" value if JSON format).

        Raises:
            TimeoutError: If timeout expires without detection.
        """
        self._require_service(self.barcode, "ALBarcodeReader")
        self._setup_barcode_reader()

        def _process_qr(data):
            return self._extract_qr_value(data, allow_all)

        try:
            return self._event_manager.wait_for_event(
                "BarcodeReader/BarcodeDetected",
                processor=_process_qr,
                timeout=timeout,
            )
        finally:
            self._teardown_barcode_reader()

    def on_qr_detected(self, callback: Callable, allow_all: bool = True) -> bool:
        """Register a callback for QR code detection.

        The callback receives the QR code content string.

        Args:
            callback: Function(qr_data: str) called on QR detection.
            allow_all: If True, call back on any QR. If False, only JSON "id".

        Returns:
            True if callback registered successfully.
        """
        self._require_service(self.barcode, "ALBarcodeReader")
        self._setup_barcode_reader()

        def _on_qr(data):
            result = self._extract_qr_value(data, allow_all)
            if result is not None:
                callback(result)

        self._event_manager.subscribe(
            "qr_detection", "BarcodeReader/BarcodeDetected", _on_qr
        )
        return True

    def stop_qr_detection(self) -> bool:
        """Stop QR code detection and re-enable awareness.

        Returns:
            True if QR detection stopped successfully.
        """
        self._event_manager.unsubscribe("qr_detection")
        self._teardown_barcode_reader()
        return True

    def _setup_barcode_reader(self):
        """Configure barcode reader for QR detection."""
        if self.awareness:
            self.awareness.pauseAwareness()
        self.barcode.setActiveCamera(0)  # Head camera
        self.barcode.setResolution(2)    # 640x480
        self.barcode.setFrameRate(2)
        self.barcode.subscribe("pypepper_qr", 100, 0)

    def _teardown_barcode_reader(self):
        """Clean up barcode reader subscription."""
        if self.barcode:
            try:
                self.barcode.unsubscribe("pypepper_qr")
            except Exception:
                pass
        if self.awareness:
            self.awareness.resumeAwareness()

    def _extract_qr_value(self, data, allow_all: bool) -> Optional[str]:
        """Extract QR value from BarcodeDetected event data."""
        for qr in data:
            qr_value = qr[0]
            if "id" in str(qr_value):
                try:
                    qr_json = json.loads(qr_value)
                    return qr_json["id"]
                except (json.JSONDecodeError, KeyError):
                    pass
            if allow_all:
                return qr_value
        return None

    # ===============================================================================================
    # Camera Methods
    # ===============================================================================================

    TOP_CAMERA = 0
    BOTTOM_CAMERA = 1
    DEPTH_CAMERA = 2

    def capture_image(self, camera: int = 0, resolution: int = 2) -> "numpy.ndarray":
        """Capture a single frame from one of Pepper's cameras.

        Args:
            camera: Camera index — 0 (top), 1 (bottom), 2 (depth).
                    Use TOP_CAMERA, BOTTOM_CAMERA, DEPTH_CAMERA constants.
            resolution: Resolution code — 0 (160x120), 1 (320x240),
                        2 (640x480), 3 (1280x960).

        Returns:
            numpy.ndarray — BGR image (h, w, 3) uint8 for cameras 0/1,
            or depth map (h, w) uint16 (millimeters) for camera 2.

        Raises:
            RuntimeError: If ALVideoDevice is not available.
            ImportError: If numpy is not installed.
        """
        import numpy as np

        self._require_service(self.video, "ALVideoDevice")

        is_depth = (camera == self.DEPTH_CAMERA)
        colorspace = 17 if is_depth else 13  # kDepthColorSpace or kBGRColorSpace
        subscriber = self.video.subscribeCamera(
            "pypepper_capture", camera, resolution, colorspace, 5
        )
        try:
            raw = self.video.getImageRemote(subscriber)
            w, h = raw[0], raw[1]
            if is_depth:
                return np.frombuffer(raw[6], dtype=np.uint16).reshape(h, w)
            else:
                return np.frombuffer(raw[6], dtype=np.uint8).reshape(h, w, 3)
        finally:
            self.video.unsubscribe(subscriber)

    def save_image(self, path: str, camera: int = 0, resolution: int = 2) -> bool:
        """Capture a single frame and save it to a file.

        For RGB cameras (0, 1), saves a standard color image.
        For the depth camera (2), normalizes the depth map and saves
        a colorized visualization (blue=close, red=far).

        Args:
            path: File path to save the image (e.g. "photo.jpg", "depth.png").
            camera: Camera index — 0 (top), 1 (bottom), 2 (depth).
            resolution: Resolution code — 0 (160x120), 1 (320x240),
                        2 (640x480), 3 (1280x960).

        Returns:
            True if image saved successfully.

        Raises:
            RuntimeError: If ALVideoDevice is not available.
            ImportError: If numpy or opencv-python is not installed.
        """
        import cv2

        image = self.capture_image(camera, resolution)
        if camera == self.DEPTH_CAMERA:
            normalized = cv2.normalize(image, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
            colored = cv2.applyColorMap(normalized, cv2.COLORMAP_JET)
            cv2.imwrite(path, colored)
        else:
            cv2.imwrite(path, image)
        return True

    def show_camera(self, camera: int = 0, resolution: int = 2, fps: int = 15) -> bool:
        """Open a live video stream window from one of Pepper's cameras.

        Displays frames in an OpenCV window. Press 'q' to close the window
        and stop the stream.

        For the depth camera (2), frames are colorized for visibility
        (blue=close, red=far).

        Args:
            camera: Camera index — 0 (top), 1 (bottom), 2 (depth).
            resolution: Resolution code — 0 (160x120), 1 (320x240),
                        2 (640x480), 3 (1280x960).
            fps: Requested frames per second (max 30 for RGB, 20 for depth).

        Returns:
            True when the stream is closed.

        Raises:
            RuntimeError: If ALVideoDevice is not available.
            ImportError: If numpy or opencv-python is not installed.
        """
        import cv2
        import numpy as np

        self._require_service(self.video, "ALVideoDevice")

        is_depth = (camera == self.DEPTH_CAMERA)
        colorspace = 17 if is_depth else 13
        camera_names = {0: "Top", 1: "Bottom", 2: "Depth"}
        window = f"Pepper {camera_names.get(camera, camera)} Camera"
        subscriber = self.video.subscribeCamera(
            "pypepper_stream", camera, resolution, colorspace, fps
        )
        try:
            while True:
                raw = self.video.getImageRemote(subscriber)
                w, h = raw[0], raw[1]
                if is_depth:
                    frame = np.frombuffer(raw[6], dtype=np.uint16).reshape(h, w)
                    frame = cv2.normalize(
                        frame, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U
                    )
                    frame = cv2.applyColorMap(frame, cv2.COLORMAP_JET)
                else:
                    frame = np.frombuffer(raw[6], dtype=np.uint8).reshape(h, w, 3)
                cv2.imshow(window, frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
        finally:
            self.video.unsubscribe(subscriber)
            cv2.destroyWindow(window)
        return True

    # ===============================================================================================
    # Cleanup / Context Manager
    # ===============================================================================================

    def close(self) -> bool:
        """Disconnect from Pepper and clean up resources.

        Unsubscribes all event listeners, stops the tablet server,
        and cleans up the qi session.

        Returns:
            True if cleanup completed successfully.
        """
        if self._event_manager:
            self._event_manager.cleanup()

        if self._tablet_server:
            self._tablet_server.stop()

        self.session = None
        print(f"Disconnected from Pepper at {self.ip}:{self.port}")
        return True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False