"""
pytemi - Python Library for Temi Robot Control

Main TemiRobot class providing high-level API for controlling the Temi robot.
"""

import uuid
import requests
from typing import Optional, List

from .exceptions import (
    TemiConnectionError,
    TemiTimeoutError,
    TemiNavigationError,
    TemiSpeechError,
    TemiDisplayError,
)


class TemiRobot:
    """
    High-level Python interface for controlling a Temi robot.
    
    Communicates with the Ktor REST server running on the TemiRest Android app.
    
    Example:
        >>> from pytemi import TemiRobot
        >>> robot = TemiRobot("192.168.1.100")
        >>> robot.say("Hello!", language="english")
        >>> robot.goto("Reception")
    """
    
    def __init__(self, ip: str, port: int = 8080, timeout: int = 300):
        """
        Initialize connection to a Temi robot.
        
        Args:
            ip: Robot's IP address on the network
            port: REST API port (default 8080)
            timeout: Default timeout in seconds for blocking operations
        """
        self.ip = ip
        self.port = port
        self.base_url = f"http://{ip}:{port}"
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
    
    def _generate_id(self) -> str:
        """Generate a unique ID for tracking requests."""
        return str(uuid.uuid4())
    
    def _post(self, endpoint: str, payload: dict, timeout: Optional[int] = None) -> dict:
        """
        Send a POST request to the robot.
        
        Args:
            endpoint: API endpoint (e.g., "/say")
            payload: JSON payload to send
            timeout: Request timeout in seconds
            
        Returns:
            Response data as dict
            
        Raises:
            TemiConnectionError: If unable to connect to robot
            TemiTimeoutError: If request times out
        """
        url = f"{self.base_url}{endpoint}"
        request_timeout = timeout or self.timeout
        
        try:
            response = self._session.post(url, json=payload, timeout=request_timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError as e:
            raise TemiConnectionError(
                f"Failed to connect to robot at {self.base_url}. "
                f"Is the TemiRest app running? Error: {e}"
            ) from e
        except requests.exceptions.Timeout as e:
            raise TemiTimeoutError(
                f"Request to {endpoint} timed out after {request_timeout}s"
            ) from e
        except requests.exceptions.HTTPError as e:
            raise TemiConnectionError(f"HTTP error: {e}") from e
    
    def _get(self, endpoint: str, timeout: Optional[int] = None) -> dict:
        """
        Send a GET request to the robot.
        
        Args:
            endpoint: API endpoint (e.g., "/locations")
            timeout: Request timeout in seconds
            
        Returns:
            Response data
        """
        url = f"{self.base_url}{endpoint}"
        request_timeout = timeout or self.timeout
        
        try:
            response = self._session.get(url, timeout=request_timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError as e:
            raise TemiConnectionError(
                f"Failed to connect to robot at {self.base_url}. "
                f"Is the TemiRest app running? Error: {e}"
            ) from e
        except requests.exceptions.Timeout as e:
            raise TemiTimeoutError(
                f"Request to {endpoint} timed out after {request_timeout}s"
            ) from e
    
    # =========================================================================
    # Speech Methods
    # =========================================================================
    
    def say(
        self,
        text: str,
        language: str = "english",
        animation: bool = False
    ) -> None:
        """
        Speak text using text-to-speech. Blocks until speech completes.
        
        Args:
            text: Text to speak
            language: Language code ("english", "german", "spanish", "french")
            animation: Whether to use facial animations while speaking
            
        Raises:
            TemiSpeechError: If TTS fails
            TemiConnectionError: If unable to connect to robot
        """
        payload = {
            "text": text,
            "language": language.lower(),
            "animation": str(animation).lower(),
            "id": self._generate_id()
        }
        
        try:
            response = self._post("/say", payload)
            if not response.get("success", False):
                raise TemiSpeechError(f"TTS failed: {response.get('message', 'Unknown error')}")
        except (TemiConnectionError, TemiTimeoutError):
            raise
        except Exception as e:
            raise TemiSpeechError(f"TTS error: {e}") from e
    
    def stop_say(self) -> None:
        """
        Interrupt current speech or movement.
        """
        self._post("/stop_say", {}, timeout=5)
    
    # =========================================================================
    # Navigation Methods
    # =========================================================================
    
    def goto(self, location: str, speed: Optional[str] = None) -> None:
        """
        Navigate to a saved location. Blocks until robot arrives.
        
        Args:
            location: Name of the saved location (as shown in Temi app)
            speed: Navigation speed ("slow", "medium", "high") or None for default
            
        Raises:
            TemiNavigationError: If navigation fails
            TemiConnectionError: If unable to connect to robot
        """
        payload = {
            "text": location,
            "id": self._generate_id()
        }
        
        if speed:
            payload["speed"] = speed.upper()
        
        try:
            response = self._post("/goto", payload)
            if not response.get("success", False):
                raise TemiNavigationError(
                    f"Navigation to '{location}' failed: {response.get('message', 'Unknown error')}"
                )
        except (TemiConnectionError, TemiTimeoutError):
            raise
        except Exception as e:
            raise TemiNavigationError(f"Navigation error: {e}") from e
    
    def get_locations(self) -> List[str]:
        """
        Get list of saved navigation locations.
        
        Returns:
            List of location names saved on the robot
        """
        try:
            response = self._get("/locations", timeout=10)
            if isinstance(response, list):
                return response
            return []
        except Exception:
            return []
    
    # =========================================================================
    # Display Methods
    # =========================================================================
    
    def clear_tablet(self) -> None:
        """
        Clear the tablet display, returning it to the default state.
        """
        payload = {
            "clear": True,
            "id": self._generate_id()
        }
        self._post("/clear", payload, timeout=10)
    
    def show_text(self, text: str) -> None:
        """
        Display text on the tablet screen.
        
        Args:
            text: Text to display (supports newlines with \\n)
        """
        payload = {
            "text": text,
            "id": self._generate_id()
        }
        
        try:
            # /txt endpoint expects text body, not JSON
            url = f"{self.base_url}/txt"
            import json
            response = self._session.post(
                url,
                data=json.dumps(payload),
                headers={"Content-Type": "text/plain"},
                timeout=10
            )
            response.raise_for_status()
        except Exception as e:
            raise TemiDisplayError(f"Failed to display text: {e}") from e
    
    def show_image(self, url: str) -> None:
        """
        Display an image on the tablet screen.
        
        Args:
            url: URL of the image to display (must be accessible from robot)
        """
        payload = {
            "image": url,
            "id": self._generate_id()
        }
        
        try:
            # /img endpoint expects text body
            import json
            response = self._session.post(
                f"{self.base_url}/img",
                data=json.dumps(payload),
                headers={"Content-Type": "text/plain"},
                timeout=10
            )
            response.raise_for_status()
        except Exception as e:
            raise TemiDisplayError(f"Failed to display image: {e}") from e
    
    def show_video(self, url: str, timeout: Optional[int] = None) -> None:
        """
        Play a video on the tablet screen. Blocks until video completes.
        
        Args:
            url: URL of the video to play (must be accessible from robot)
            timeout: Maximum wait time in seconds (default: 5 minutes)
            
        Note:
            The robot supports MP4 format. HLS streams are also supported.
        """
        payload = {
            "url": url,
            "id": self._generate_id()
        }
        
        video_timeout = timeout or 300  # 5 minutes default
        
        try:
            response = self._post("/video", payload, timeout=video_timeout)
            if not response.get("success", False):
                raise TemiDisplayError(f"Video playback failed: {response.get('message', 'Unknown error')}")
        except (TemiConnectionError, TemiTimeoutError):
            raise
        except Exception as e:
            raise TemiDisplayError(f"Video error: {e}") from e
    
    # =========================================================================
    # Speech Recognition Methods
    # =========================================================================
    
    def wait_for_keyword(
        self,
        question: str,
        keywords: List[str],
        language: str = "german",
        timeout: int = 0
    ) -> str:
        """
        Ask a question and wait for the user to say one of the keywords.
        
        The robot will speak the question, then listen for speech. If the user's
        response contains one of the keywords, that keyword is returned.
        
        Args:
            question: Question to ask the user (will be spoken)
            keywords: List of keywords to listen for
            language: Language for TTS and ASR ("english", "german", etc.)
            timeout: Maximum wait time in seconds (0 = wait indefinitely)
            
        Returns:
            The matched keyword (lowercase)
            
        Raises:
            TemiSpeechError: If speech recognition fails or no keyword matched
        """
        import json
        
        payload = {
            "question": question,
            "payload": json.dumps(keywords),
            "language": language,
            "id": self._generate_id()
        }
        
        request_timeout = timeout if timeout > 0 else self.timeout
        
        try:
            url = f"{self.base_url}/waitforkeyword"
            response = self._session.post(
                url,
                data=json.dumps(payload),
                headers={"Content-Type": "text/plain"},
                timeout=request_timeout
            )
            response.raise_for_status()
            data = response.json()
            
            # Extract keyword from response
            response_data = data.get("data", data)
            if response_data.get("done") and response_data.get("keyword"):
                return response_data["keyword"].lower()
            else:
                raise TemiSpeechError("No keyword matched in user response")
                
        except requests.exceptions.Timeout:
            raise TemiTimeoutError(f"Keyword detection timed out after {request_timeout}s")
        except TemiSpeechError:
            raise
        except Exception as e:
            raise TemiSpeechError(f"Wait for keyword failed: {e}") from e
    
    def listen(
        self,
        prompt: str = "",
        language: str = "german",
        timeout: int = 0
    ) -> str:
        """
        Listen for speech and return the full transcript.
        
        Unlike wait_for_keyword, this returns the complete user speech
        without keyword matching - useful for AI/LLM processing.
        
        Args:
            prompt: Optional question to ask before listening (will be spoken)
            language: Language for TTS and ASR
            timeout: Maximum wait time in seconds (0 = wait indefinitely)
            
        Returns:
            Full transcript of user's speech
            
        Raises:
            TemiSpeechError: If speech recognition fails
        """
        import json
        
        payload = {
            "prompt": prompt,
            "id": self._generate_id(),
            "language": language
        }
        
        request_timeout = timeout if timeout > 0 else self.timeout
        
        try:
            url = f"{self.base_url}/listen"
            response = self._session.post(
                url,
                data=json.dumps(payload),
                headers={"Content-Type": "text/plain"},
                timeout=request_timeout
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get("success"):
                return data.get("data", {}).get("transcript", "")
            else:
                raise TemiSpeechError(f"Listen failed: {data.get('message', 'Unknown error')}")
                
        except requests.exceptions.Timeout:
            raise TemiTimeoutError(f"Listen timed out after {request_timeout}s")
        except TemiSpeechError:
            raise
        except Exception as e:
            raise TemiSpeechError(f"Listen failed: {e}") from e
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    def wait(self, seconds: float) -> None:
        """
        Wait for a specified duration on the robot side.
        
        This is a blocking wait that happens on the robot, not in Python.
        Useful for timing in sequences.
        
        Args:
            seconds: Duration to wait
        """
        import json
        
        payload = {
            "time": str(int(seconds)),
            "id": self._generate_id()
        }
        
        try:
            url = f"{self.base_url}/wait"
            response = self._session.post(
                url,
                data=json.dumps(payload),
                headers={"Content-Type": "text/plain"},
                timeout=seconds + 10
            )
            response.raise_for_status()
        except Exception:
            pass  # Wait timeout is not critical
    
    def home(self) -> None:
        """
        Trigger the home button action - shows language selection screen,
        broadcasts cancel_flow event, and stops robot speech and actions.
        
        This is typically used to return the robot to its default state
        and allow users to restart their interaction.
        """
        import json
        
        payload = {}
        
        try:
            url = f"{self.base_url}/home"
            response = self._session.post(
                url,
                data=json.dumps(payload),
                headers={"Content-Type": "text/plain"},
                timeout=10
            )
            response.raise_for_status()
        except Exception as e:
            raise TemiConnectionError(f"Home action failed: {e}") from e
    
    def health_check(self) -> bool:
        """
        Check if the robot's REST API is accessible.
        
        Returns:
            True if connected, False otherwise
        """
        try:
            response = self._get("/health", timeout=5)
            return response.get("success", False)
        except Exception:
            return False
    
    def __repr__(self) -> str:
        return f"TemiRobot(ip='{self.ip}', port={self.port})"
