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
from typing import List

try:
    from pypepper.event.event import Event
    from pypepper.fsm.fsm import FSM, Options, Transition, State
except ImportError:
    print("[Temi] pypepper not available — using local Event/FSM fallback.")

    class Event:
        def __init__(self):
            self.flow = ""
            self.name = ""

        def set_flow(self, flow: str):
            self.flow = flow

        def set_name(self, name: str):
            self.name = name

    class State:
        def __init__(self, value):
            self.value = value

        def __eq__(self, other):
            return isinstance(other, State) and self.value == other.value

        def __hash__(self):
            return hash(self.value)

    class Transition:
        def __init__(self, event: Event, from_state: List[State], to_state: State, handler=None):
            self.event = event
            self.from_state = from_state
            self.to_state = to_state
            self.handler = handler

    class Options:
        def __init__(self, fsm_id: str, initial: State, transitions: List[Transition]):
            self.fsm_id = fsm_id
            self.initial = initial
            self.transitions = transitions

    class _Response:
        def __init__(self, error=None):
            self.error = error

    class FSM:
        def __init__(self, options: Options):
            self._current = options.initial
            self._transitions = options.transitions

        def current(self) -> State:
            return self._current

        def on(self, event: Event) -> _Response:
            for transition in self._transitions:
                same_event = (
                    transition.event.flow == event.flow
                    and transition.event.name == event.name
                )
                if same_event and self._current in transition.from_state:
                    if transition.handler:
                        transition.handler()
                    self._current = transition.to_state
                    return _Response()

            return _Response(
                f"No transition for event '{event.name}' from state '{self._current.value}'"
            )


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

        def get_locations(self) -> List[str]:
            # Fake saved map points so location listing works without hardware.
            return ["entrance", "Section A", "Section B", "info_desk"]

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


def get_saved_locations(robot: TemiRobot) -> List[str]:
    """Read predefined map locations, supporting multiple Temi SDK styles."""
    if hasattr(robot, "get_locations") and callable(getattr(robot, "get_locations")):
        locations = robot.get_locations()
        if isinstance(locations, list):
            return [str(item) for item in locations]

    nav = getattr(robot, "navigation", None)
    if nav and hasattr(nav, "get_locations") and callable(getattr(nav, "get_locations")):
        locations = nav.get_locations()
        if isinstance(locations, list):
            return [str(item) for item in locations]

    return []


def show_saved_locations(robot: TemiRobot):
    print("\nSaved locations on Temi:")
    locations = get_saved_locations(robot)
    if not locations:
        print("  (none found or robot not reachable)")
        return

    for idx, location in enumerate(locations, start=1):
        print(f"  {idx}. {location}")


def temi_speak(robot: TemiRobot, text: str):
    """Speak text via whichever Temi API style is available."""
    if hasattr(robot, "tts") and hasattr(robot.tts, "speak"):
        robot.tts.speak(text)
        return
    if hasattr(robot, "say"):
        robot.say(text)


def temi_go_to(robot: TemiRobot, location: str):
    """Navigate using either navigation.go_to() or goto()."""
    if hasattr(robot, "navigation") and hasattr(robot.navigation, "go_to"):
        robot.navigation.go_to(location)
        return
    if hasattr(robot, "goto"):
        robot.goto(location)


def temi_show_image(robot: TemiRobot, path: str):
    """Display an image for SDKs that expose a screen/image API."""
    if hasattr(robot, "media") and hasattr(robot.media, "show_image"):
        robot.media.show_image(path)
        return
    if hasattr(robot, "show_image"):
        robot.show_image(path)


# ──────────────────────────────────────────────────────────────────────────────
# PART 2 — CONNECT TO TEMI
# ──────────────────────────────────────────────────────────────────────────────

temi = TemiRobot(ip="172.30.36.32", port=8080)

# Print available predefined locations before running the tour FSM.
show_saved_locations(temi)


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
    temi_speak(temi, "Welcome! I will guide you through our stand. Follow me!")
    temi_go_to(temi, "Section A")
    temi_show_image(temi, "section_a_overview.jpg")

def on_next_section():
    temi_speak(temi, "Let me show you our next product.")
    temi_go_to(temi, "Section B")

def on_answer():
    temi_speak(temi, "Great question! Let me explain in more detail...")

def on_end_tour():
    temi_speak(temi, "That concludes our tour. Heading back to the entrance.")
    temi_go_to(temi, "entrance")

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
