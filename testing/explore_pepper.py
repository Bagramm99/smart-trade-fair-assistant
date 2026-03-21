"""
explore_pepper.py  —  Understanding the pypepper middleware library.

pypepper is NOT a direct robot-control SDK.
It is a middleware framework with three main building blocks:

  1. Event    — a message/command you send between parts of the system
  2. FSM      — a state machine that reacts to events (the core of robot logic)
  3. Workflow — an ordered list of Tasks that execute in sequence

Run:
    python explore_pepper.py
"""

from enum import Enum
from pypepper.event.event import Event
from pypepper.fsm.fsm import FSM, Options, Transition, State
from pypepper.scheduler.task import Task
from pypepper.scheduler.workflow import Workflow
from pypepper.scheduler.executor import Executor
from pypepper.scheduler.tag import Tag


# ──────────────────────────────────────────────────────────────────────────────
# PART 1 — EVENTS
# An Event has two fields that matter: flow (topic) and name (message type).
# You create them once and reuse them as triggers for the FSM.
# ──────────────────────────────────────────────────────────────────────────────

def make_event(flow: str, name: str) -> Event:
    e = Event()
    e.set_flow(flow)
    e.set_name(name)
    return e

EVT_VISITOR_DETECTED   = make_event("pepper", "visitor_detected")
EVT_VISITOR_INTERESTED = make_event("pepper", "visitor_interested")
EVT_VISITOR_LEFT       = make_event("pepper", "visitor_left")
EVT_RESET              = make_event("pepper", "reset")


# ──────────────────────────────────────────────────────────────────────────────
# PART 2 — STATE MACHINE
# States represent what Pepper is currently doing.
# Transitions wire (event + current_state) -> next_state + optional handler.
# ──────────────────────────────────────────────────────────────────────────────

class PepperState(str, Enum):
    IDLE       = "idle"
    GREETING   = "greeting"
    PRESENTING = "presenting"
    FAREWELL   = "farewell"

IDLE_STATE       = State(PepperState.IDLE)
GREETING_STATE   = State(PepperState.GREETING)
PRESENTING_STATE = State(PepperState.PRESENTING)
FAREWELL_STATE   = State(PepperState.FAREWELL)

# Handlers — in a real system these call the robot's actual API
def on_greet():
    print("  [Pepper] Playing greeting animation + TTS: 'Welcome!'")

def on_present():
    print("  [Pepper] Starting product intro speech")

def on_farewell():
    print("  [Pepper] Waving goodbye + TTS: 'Thank you for visiting!'")

pepper_fsm = FSM(
    Options(
        fsm_id="pepper",
        initial=IDLE_STATE,
        transitions=[
            Transition(
                event=EVT_VISITOR_DETECTED,
                from_state=[IDLE_STATE],
                to_state=GREETING_STATE,
                handler=on_greet,
            ),
            Transition(
                event=EVT_VISITOR_INTERESTED,
                from_state=[GREETING_STATE],
                to_state=PRESENTING_STATE,
                handler=on_present,
            ),
            Transition(
                event=EVT_VISITOR_LEFT,
                from_state=[GREETING_STATE, PRESENTING_STATE],
                to_state=FAREWELL_STATE,
                handler=on_farewell,
            ),
            Transition(
                event=EVT_RESET,
                from_state=[FAREWELL_STATE],
                to_state=IDLE_STATE,
            ),
        ],
    )
)


# ──────────────────────────────────────────────────────────────────────────────
# PART 3 — WORKFLOW (sequence of Tasks)
# Workflow lets you chain Tasks. Each Task wraps an Executor.
# Note: Executor and Tag are stub base classes in pypepper —
#       subclass them and add your own logic.
# ──────────────────────────────────────────────────────────────────────────────

class WaveExecutor(Executor):
    def run(self):
        print("  [Task] Pepper: wave arm at visitor")

class SpeakExecutor(Executor):
    def run(self):
        print("  [Task] Pepper: TTS 'Welcome to our stand!'")

def build_greeting_workflow() -> Workflow:
    wave_task = Task(
        channel_id="ch-pepper",
        dag_id="greeting_wf",
        fingerprint="wave",
        name="wave",
        category="motion",
        description="Wave arm at visitor",
        tags=[Tag()],
        executor=WaveExecutor(),
    )
    speak_task = Task(
        channel_id="ch-pepper",
        dag_id="greeting_wf",
        fingerprint="speak",
        name="say_welcome",
        category="tts",
        description="Play welcome TTS message",
        tags=[Tag()],
        executor=SpeakExecutor(),
    )
    wf = Workflow()
    wf.add_tasks([wave_task, speak_task])
    return wf


# ──────────────────────────────────────────────────────────────────────────────
# DEMO
# ──────────────────────────────────────────────────────────────────────────────

def fire(label: str, event: Event):
    print(f"\n-> Event: '{label}'")
    resp = pepper_fsm.on(event)
    print(f"   State: {pepper_fsm.current().value}", end="")
    if resp.error:
        print(f"  WARNING: {resp.error}", end="")
    print()


if __name__ == "__main__":
    print("=" * 50)
    print("  pypepper -- FSM demo")
    print("=" * 50)
    print(f"Initial state: {pepper_fsm.current().value}")

    fire("visitor walks up to stand", EVT_VISITOR_DETECTED)
    fire("visitor says 'yes, show me more'", EVT_VISITOR_INTERESTED)
    fire("visitor walks away", EVT_VISITOR_LEFT)
    fire("system resets", EVT_RESET)

    print(f"\nBack to: {pepper_fsm.current().value}")

    print("\n" + "=" * 50)
    print("  pypepper -- Workflow demo")
    print("=" * 50)
    wf = build_greeting_workflow()
    print(f"Workflow '{wf.tasks[0].dag_id}' has {len(wf.get_tasks())} tasks:")
    for task in wf.get_tasks():
        print(f"  [{task.category}] {task.name}: {task.description}")
        task.executor.run()
