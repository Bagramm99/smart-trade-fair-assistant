"""
explore_temi.py  —  Understanding the Temi Middleware (pytemi) library.

pytemi is not available on PyPI — it lives in your class's GitLab repo
(visible in the screenshot as "Temi Middleware").
This file shows what the Temi SDK typically looks like and how to
connect it to the same pypepper Event/FSM pattern used in explore_pepper.py.

Until you have access to the real library, the TemiStub class below
lets you run and test the full logic on your laptop.

Run:
    python explore_temi.py
"""

from enum import Enum
from pypepper.event.event import Event
from pypepper.fsm.fsm import FSM, Options, Transition, State


# ──────────────────────────────────────────────────────────────────────────────
# PART 1 — TEMI SDK STUB
# Replace this class with the real pytemi import once you have access.
#
# Typical Temi SDK structure (based on the official Temi developer docs):
#   temi.tts.speak(text)             — text to speech
#   temi.navigation.go_to(location)  — move to a saved map location
#   temi.media.show_image(path)      — display image on the screen
#   temi.follow_me()                 — follow the nearest person
#   temi.stop()                      — stop current action
# ──────────────────────────────────────────────────────────────────────────────

try:
    from pytemi import TemiRobot                            # type: ignore
    print("[Temi] Real pytemi library found.")
except ImportError:
    print("[Temi] pytemi not installed — using stub (no hardware needed).")

    class _TTS:
        def speak(self, text: str):
            print(f"  [Temi TTS] {text}")

    class _Navigation:
        def go_to(self, location: str):
            print(f"  [Temi NAV] Moving to '{location}'")

    class _Media:
        def show_image(self, path: str):
            print(f"  [Temi SCREEN] Displaying: {path}")

    class TemiRobot:
        """Stub that mirrors the expected pytemi interface."""
        def __init__(self, ip: str = "192.168.1.x", port: int = 7070):
            self.ip = ip
            self.tts = _TTS()
            self.navigation = _Navigation()
            self.media = _Media()
            print(f"  [Temi] Connected to {ip}:{port} (stub)")

        def follow_me(self):
            print("  [Temi] Following visitor")

        def stop(self):
            print("  [Temi] Stopped")


# ──────────────────────────────────────────────────────────────────────────────
# PART 2 — CONNECT TO TEMI
# ──────────────────────────────────────────────────────────────────────────────

temi = TemiRobot(ip="192.168.1.102", port=7070)


# ──────────────────────────────────────────────────────────────────────────────
# PART 3 — FSM FOR TEMI
# Same pypepper FSM pattern as Pepper, but for Temi's tour guide role.
# ──────────────────────────────────────────────────────────────────────────────

def make_event(flow: str, name: str) -> Event:
    e = Event()
    e.set_flow(flow)
    e.set_name(name)
    return e

EVT_START_TOUR   = make_event("temi", "start_tour")
EVT_NEXT_SECTION = make_event("temi", "next_section")
EVT_ANSWER_Q     = make_event("temi", "answer_question")
EVT_END_TOUR     = make_event("temi", "end_tour")


class TemiState(str, Enum):
    IDLE      = "idle"
    TOURING   = "touring"
    EXPLAINING = "explaining"
    DONE      = "done"

IDLE_STATE       = State(TemiState.IDLE)
TOURING_STATE    = State(TemiState.TOURING)
EXPLAINING_STATE = State(TemiState.EXPLAINING)
DONE_STATE       = State(TemiState.DONE)

# Handlers call the actual Temi SDK methods
def on_start_tour():
    temi.tts.speak("Welcome! I will guide you through our stand. Follow me!")
    temi.navigation.go_to("Section A")
    temi.media.show_image("section_a_overview.jpg")

def on_next_section():
    temi.tts.speak("Let me show you our next product.")
    temi.navigation.go_to("Section B")

def on_answer():
    temi.tts.speak("Great question! Let me explain in more detail...")

def on_end_tour():
    temi.tts.speak("That concludes our tour. Heading back to the entrance.")
    temi.navigation.go_to("entrance")

temi_fsm = FSM(
    Options(
        fsm_id="temi",
        initial=IDLE_STATE,
        transitions=[
            Transition(
                event=EVT_START_TOUR,
                from_state=[IDLE_STATE],
                to_state=TOURING_STATE,
                handler=on_start_tour,
            ),
            Transition(
                event=EVT_NEXT_SECTION,
                from_state=[TOURING_STATE, EXPLAINING_STATE],
                to_state=TOURING_STATE,
                handler=on_next_section,
            ),
            Transition(
                event=EVT_ANSWER_Q,
                from_state=[TOURING_STATE],
                to_state=EXPLAINING_STATE,
                handler=on_answer,
            ),
            Transition(
                event=EVT_END_TOUR,
                from_state=[TOURING_STATE, EXPLAINING_STATE],
                to_state=DONE_STATE,
                handler=on_end_tour,
            ),
        ],
    )
)


# ──────────────────────────────────────────────────────────────────────────────
# DEMO
# ──────────────────────────────────────────────────────────────────────────────

def fire(label: str, event: Event):
    print(f"\n-> Event: '{label}'")
    resp = temi_fsm.on(event)
    print(f"   State: {temi_fsm.current().value}", end="")
    if resp.error:
        print(f"  WARNING: {resp.error}", end="")
    print()


if __name__ == "__main__":
    print("=" * 50)
    print("  Temi Middleware -- FSM demo")
    print("=" * 50)
    print(f"Initial state: {temi_fsm.current().value}\n")

    fire("visitor hands off from Pepper", EVT_START_TOUR)
    fire("visitor asks a question",       EVT_ANSWER_Q)
    fire("moving to next section",        EVT_NEXT_SECTION)
    fire("visitor says goodbye",          EVT_END_TOUR)

    print(f"\nFinal state: {temi_fsm.current().value}")
