"""
pytemi - Python Library for Temi Robot Control

Custom exceptions for error handling.
"""


class TemiError(Exception):
    """Base exception for all Temi errors."""
    pass


class TemiConnectionError(TemiError):
    """Failed to connect to the Temi robot REST API."""
    pass


class TemiTimeoutError(TemiError):
    """Operation timed out waiting for robot response."""
    pass


class TemiNavigationError(TemiError):
    """Navigation to location failed."""
    pass


class TemiSpeechError(TemiError):
    """Text-to-speech or speech recognition failed."""
    pass


class TemiDisplayError(TemiError):
    """Display operation (image/video/text) failed."""
    pass
