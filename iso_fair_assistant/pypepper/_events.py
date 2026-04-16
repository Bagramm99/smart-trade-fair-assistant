"""Internal event subscription manager for NAOqi ALMemory events.

Uses the legacy memory.subscribeToEvent() API with a qi-registered service
object, which is compatible with NAOqi 2.5.x.
"""

import threading
import logging
from typing import Callable, Any

logger = logging.getLogger("pypepper.events")


class _EventDispatcher:
    """Python object registered as a qi service.

    NAOqi calls on_event(event_name, data) on this object when a subscribed
    ALMemory event fires.  The dispatcher then routes the data to all
    registered Python callbacks for that event.
    """

    def __init__(self):
        self._callbacks = {}
        self._lock = threading.Lock()

    # -- public: called by NAOqi via the registered service -----------------

    def on_event(self, event_name, data):
        """Called by NAOqi when a subscribed ALMemory event fires.

        Args:
            event_name: The ALMemory event name string.
            data: The event payload (type varies per event).
        """
        with self._lock:
            callbacks = list(self._callbacks.get(event_name, []))

        for cb in callbacks:
            try:
                cb(data)
            except Exception as e:
                logger.error(f"Error in callback for '{event_name}': {e}")

    # -- internal: called by EventManager -----------------------------------

    def _add(self, event_name, callback):
        """Add a callback for an event.

        Returns True if this is the FIRST callback registered for this event
        (meaning the caller needs to call memory.subscribeToEvent).
        """
        with self._lock:
            if event_name not in self._callbacks:
                self._callbacks[event_name] = []
                self._callbacks[event_name].append(callback)
                return True
            self._callbacks[event_name].append(callback)
            return False

    def _remove(self, event_name, callback):
        """Remove a callback for an event.

        Returns True if there are NO callbacks left for this event
        (meaning the caller needs to call memory.unsubscribeToEvent).
        """
        with self._lock:
            if event_name in self._callbacks:
                try:
                    self._callbacks[event_name].remove(callback)
                except ValueError:
                    pass
                if not self._callbacks[event_name]:
                    del self._callbacks[event_name]
                    return True
            return False

    def _clear(self):
        """Remove all callbacks. Returns list of event names that were active."""
        with self._lock:
            events = list(self._callbacks.keys())
            self._callbacks.clear()
            return events


class EventManager:
    """Manages NAOqi ALMemory event subscriptions.

    Registers an ``_EventDispatcher`` as a qi service so NAOqi can call back
    into it.  Then uses ``memory.subscribeToEvent(event, service, method)``
    to subscribe to ALMemory events — the same API the pepper-middleware uses.

    Provides two patterns:
    1. Blocking: wait_for_event() blocks until the event fires or timeout.
    2. Callback: subscribe() registers a persistent callback.
    """

    SERVICE_NAME = "PyPepperEvents"

    def __init__(self, memory_service, session):
        self._memory = memory_service
        self._dispatcher = _EventDispatcher()
        self._subscriptions = {}   # key -> (event_name, callback)
        self._lock = threading.Lock()

        # Register the dispatcher so NAOqi can invoke on_event() on it.
        session.registerService(self.SERVICE_NAME, self._dispatcher)

    # -- blocking wait ------------------------------------------------------

    def wait_for_event(
        self,
        event_name: str,
        processor: Callable = None,
        timeout: float = None,
    ) -> Any:
        """Subscribe to an ALMemory event and block until it fires.

        Args:
            event_name: NAOqi event name (e.g. "FaceDetected").
            processor: Optional callable(data) -> result.  If it returns None
                       the event is ignored and waiting continues.  A non-None
                       return becomes the result.
            timeout: Seconds to wait.  None = wait indefinitely.

        Returns:
            The event data (or processed result).

        Raises:
            TimeoutError: If timeout is specified and expires.
        """
        result_holder = [None]
        got_event = threading.Event()

        def _on_value(data):
            if processor:
                processed = processor(data)
                if processed is None:
                    return
                result_holder[0] = processed
            else:
                result_holder[0] = data
            got_event.set()

        is_first = self._dispatcher._add(event_name, _on_value)
        if is_first:
            self._memory.subscribeToEvent(
                event_name, self.SERVICE_NAME, "on_event"
            )

        try:
            triggered = got_event.wait(timeout=timeout)
            if not triggered:
                raise TimeoutError(
                    f"Timed out waiting for event '{event_name}' after {timeout}s"
                )
            return result_holder[0]
        finally:
            is_last = self._dispatcher._remove(event_name, _on_value)
            if is_last:
                try:
                    self._memory.unsubscribeToEvent(
                        event_name, self.SERVICE_NAME
                    )
                except Exception:
                    pass

    # -- persistent callback subscription -----------------------------------

    def subscribe(
        self,
        key: str,
        event_name: str,
        callback: Callable,
    ) -> None:
        """Register a persistent callback for an ALMemory event.

        Args:
            key: Unique key for this subscription (for later unsubscribe).
            event_name: NAOqi event name.
            callback: Called with (data) each time the event fires.
        """
        with self._lock:
            if key in self._subscriptions:
                self._unsubscribe_internal(key)

            is_first = self._dispatcher._add(event_name, callback)
            if is_first:
                self._memory.subscribeToEvent(
                    event_name, self.SERVICE_NAME, "on_event"
                )

            self._subscriptions[key] = (event_name, callback)

    def unsubscribe(self, key: str) -> None:
        """Remove a persistent callback subscription."""
        with self._lock:
            if key in self._subscriptions:
                self._unsubscribe_internal(key)

    def _unsubscribe_internal(self, key: str) -> None:
        event_name, callback = self._subscriptions.pop(key)
        is_last = self._dispatcher._remove(event_name, callback)
        if is_last:
            try:
                self._memory.unsubscribeToEvent(
                    event_name, self.SERVICE_NAME
                )
            except Exception:
                logger.debug(f"Failed to unsubscribe from event '{event_name}'")

    def cleanup(self) -> None:
        """Remove all active subscriptions. Called on PepperRobot.close()."""
        with self._lock:
            for key in list(self._subscriptions.keys()):
                self._unsubscribe_internal(key)

            # Clean up any remaining dispatcher callbacks
            remaining_events = self._dispatcher._clear()
            for event_name in remaining_events:
                try:
                    self._memory.unsubscribeToEvent(
                        event_name, self.SERVICE_NAME
                    )
                except Exception:
                    pass
