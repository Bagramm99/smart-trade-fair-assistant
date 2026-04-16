"""
pytemi - Python Library for Temi Robot Control

Event handling and polling for robot events (language selection, etc.)
"""

import time
import threading
from typing import Optional, Callable, List, Dict, Any

from .exceptions import TemiConnectionError, TemiTimeoutError


class TemiEventListener:
    """
    Event listener for Temi robot events.
    
    Polls the robot's event queue for specific events like language selection.
    Can be used for one-time waits or continuous background polling.
    
    Example:
        >>> from pytemi import TemiRobot
        >>> from pytemi.events import TemiEventListener
        >>> 
        >>> robot = TemiRobot("192.168.1.100")
        >>> listener = TemiEventListener(robot)
        >>> 
        >>> # Wait for language selection
        >>> language = listener.wait_for_language(timeout=30)
        >>> print(f"User selected: {language}")
    """
    
    def __init__(self, robot: "TemiRobot", poll_interval: float = 1.0):
        """
        Create an event listener for the robot.
        
        Args:
            robot: TemiRobot instance to listen to
            poll_interval: How often to poll for events (seconds)
        """
        self.robot = robot
        self.poll_interval = poll_interval
        self._last_timestamp = int(time.time() * 1000)  # Start from now
        self._polling = False
        self._poll_thread: Optional[threading.Thread] = None
        self._callbacks: List[Callable[[Dict[str, Any]], None]] = []
    
    def get_events(self, topic: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get events from the robot's event queue.
        
        Args:
            topic: Optional topic to filter events (e.g., "user_language")
            
        Returns:
            List of event dictionaries with keys: topic, message, timestamp
        """
        try:
            endpoint = f"/events/{topic}" if topic else "/events"
            response = self.robot._get(endpoint, timeout=5)
            
            if isinstance(response, dict) and "events" in response:
                return response["events"]
            return []
        except Exception:
            return []
    
    def get_new_events(self, topic: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get only new events since the last check.
        
        Args:
            topic: Optional topic to filter events
            
        Returns:
            List of new event dictionaries
        """
        events = self.get_events(topic)
        new_events = [e for e in events if e.get("timestamp", 0) > self._last_timestamp]
        
        if new_events:
            self._last_timestamp = max(e.get("timestamp", 0) for e in new_events)
        
        return new_events
    
    def wait_for_language(self, timeout: Optional[float] = None) -> str:
        """
        Wait for user to select a language on the tablet.
        
        This blocks until a language selection event is received or timeout.
        
        Args:
            timeout: Maximum wait time in seconds (None = wait indefinitely)
            
        Returns:
            Language code: "english" or "german"
            
        Raises:
            TemiTimeoutError: If timeout is reached without language selection
        """
        start_time = time.time()
        
        while True:
            # Check for timeout
            if timeout and (time.time() - start_time) > timeout:
                raise TemiTimeoutError(f"Language selection timed out after {timeout}s")
            
            # Poll for new language events
            new_events = self.get_new_events("user_language")
            
            for event in new_events:
                if "user_language" in event.get("topic", ""):
                    language = event.get("message", "").lower()
                    if language in ["english", "german"]:
                        return language
            
            # Sleep before next poll
            time.sleep(self.poll_interval)
    
    def wait_for_event(
        self,
        topic: str,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Wait for a specific event topic.
        
        Args:
            topic: Event topic to wait for (e.g., "reset_flow", "cancel_flow")
            timeout: Maximum wait time in seconds
            
        Returns:
            The event dictionary
            
        Raises:
            TemiTimeoutError: If timeout is reached
        """
        start_time = time.time()
        
        while True:
            if timeout and (time.time() - start_time) > timeout:
                raise TemiTimeoutError(f"Wait for event '{topic}' timed out")
            
            new_events = self.get_new_events(topic)
            
            for event in new_events:
                if topic in event.get("topic", ""):
                    return event
            
            time.sleep(self.poll_interval)
    
    def start_polling(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """
        Start polling for events in a background thread.
        
        Each new event will trigger the callback function.
        
        Args:
            callback: Function to call with each new event
            
        Example:
            >>> def on_event(event):
            ...     print(f"Event: {event['topic']} = {event['message']}")
            >>> 
            >>> listener.start_polling(on_event)
        """
        if self._polling:
            return
        
        self._callbacks.append(callback)
        self._polling = True
        
        def poll_loop():
            while self._polling:
                try:
                    new_events = self.get_new_events()
                    for event in new_events:
                        for cb in self._callbacks:
                            try:
                                cb(event)
                            except Exception:
                                pass
                except Exception:
                    pass
                time.sleep(self.poll_interval)
        
        self._poll_thread = threading.Thread(target=poll_loop, daemon=True)
        self._poll_thread.start()
    
    def stop_polling(self) -> None:
        """
        Stop the background polling thread.
        """
        self._polling = False
        if self._poll_thread:
            self._poll_thread.join(timeout=2.0)
            self._poll_thread = None
        self._callbacks.clear()
    
    def reset_timestamp(self) -> None:
        """
        Reset the event timestamp to now.
        
        This causes get_new_events() to ignore all past events
        and only return events that occur after this call.
        """
        self._last_timestamp = int(time.time() * 1000)
