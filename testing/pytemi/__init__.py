"""
pytemi - Python Library for Temi Robot Control

A simple Python interface for controlling Temi robots via their REST API.

Example:
    >>> from pytemi import TemiRobot
    >>> 
    >>> robot = TemiRobot("192.168.1.100")
    >>> robot.say("Hello!", language="english")
    >>> robot.goto("Reception")
"""

from .robot import TemiRobot
from .events import TemiEventListener
from .exceptions import (
    TemiError,
    TemiConnectionError,
    TemiTimeoutError,
    TemiNavigationError,
    TemiSpeechError,
    TemiDisplayError,
)

__version__ = "1.0.0"
__author__ = "Temi HAUM"

__all__ = [
    "TemiRobot",
    "TemiEventListener",
    "TemiError",
    "TemiConnectionError",
    "TemiTimeoutError",
    "TemiNavigationError",
    "TemiSpeechError",
    "TemiDisplayError",
]
