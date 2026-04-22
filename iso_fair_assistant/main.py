# main.py — Smart ISO Fair Assistant
#
# Run with:   python3.11 main.py
# Stop with:  Ctrl+C  (clean shutdown)
#
# Flow:
#   1. Attract loop: Pepper waves + pitch, shows splash, repeats until touch
#   2. Visitor arrives: Pepper switches to WholeBody tracking, greets
#   3. Conversation loop:
#        - Pepper tablet buttons run in parallel with terminal input
#        - First input wins
#        - If nothing is entered: Pepper apologises and asks to tap or type
#   4. Session ends → back to step 1

import logging
import signal
import sys
import time
import threading

import config
from agents.pepper_agent import PepperAgent
from agents.temi_agent import TemiAgent
from knowledge_base import KnowledgeBase
from orchestrator import Orchestrator
from session import SessionManager

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


def _wait_for_start(pepper: PepperAgent, timeout: int = 8) -> str | None:
    """
    Wait for a start signal from any of these sources:
      - Pepper tablet start button / body touch
      - Face detection (useful when the tap is unreliable)
      - Enter in the terminal

    Returns a short reason string, or None on timeout.
    """
    result = [None]
    done = threading.Event()

    def _tablet_or_touch():
        try:
            if pepper.wait_for_start_touch(timeout=timeout):
                result[0] = "tablet_or_touch"
                done.set()
        except Exception as e:
            log.debug("Start touch wait error: %s", e)

    def _face():
        try:
            if pepper.detect_face():
                result[0] = "face_detected"
                done.set()
        except Exception as e:
            log.debug("Face wait error: %s", e)

    def _terminal():
        try:
            input("  [Press Enter to start, tap Pepper's button, or let Pepper detect your face]: ")
            if not done.is_set():
                result[0] = "terminal"
                done.set()
        except (EOFError, KeyboardInterrupt):
            pass

    threading.Thread(target=_tablet_or_touch, daemon=True).start()
    threading.Thread(target=_face, daemon=True).start()
    threading.Thread(target=_terminal, daemon=True).start()

    done.wait(timeout=timeout + 5)
    return result[0]


def get_input(pepper: PepperAgent, timeout: int = 15) -> str | None:
    """
    Get visitor input from Pepper's tablet buttons and terminal keyboard.

    Returns the first non-empty result, or None if both time out.
    """
    result = [None]
    done   = threading.Event()

    def _tablet_listen():
        try:
            text = pepper.get_tablet_input(timeout=timeout)
            if text and not done.is_set():
                result[0] = text
                done.set()
        except Exception as e:
            log.debug("Pepper tablet input error: %s", e)

    def _terminal_listen():
        try:
            if config.ENABLE_TYPED_FALLBACK:
                text = input("  [TYPE your question, or tap a Pepper button]: ").strip()
                if text and not done.is_set():
                    result[0] = text
                    done.set()
        except (EOFError, KeyboardInterrupt):
            pass
        done.set()

    threading.Thread(target=_tablet_listen,   daemon=True).start()
    threading.Thread(target=_terminal_listen, daemon=True).start()

    done.wait(timeout=timeout + 5)   # +5s buffer past Temi's timeout
    return result[0]


# ── Shutdown ───────────────────────────────────────────────────────────────────

def _shutdown(pepper: PepperAgent, temi: TemiAgent):
    log.info("Shutting down ...")
    pepper.clear_tablet()
    temi.clear_screen()
    pepper.disconnect()
    temi.disconnect()
    sys.exit(0)


# ── Main loop ──────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*55)
    print("  Smart ISO Fair Assistant — Starting up")
    print("="*55 + "\n")

    # 1. Connect
    pepper   = PepperAgent()
    temi     = TemiAgent()
    kb       = KnowledgeBase(config.KB_INDEX_DIR, config.EMBED_MODEL, config.KB_TOP_K)
    sessions = SessionManager()

    if not pepper.connect():
        log.critical("Cannot connect to Pepper. Exiting.")
        sys.exit(1)

    if not temi.connect():
        log.critical("Cannot connect to Temi. Exiting.")
        sys.exit(1)

    pepper.print_status()

    orchestrator = Orchestrator(pepper, temi, kb, sessions)

    signal.signal(signal.SIGINT, lambda *_: _shutdown(pepper, temi))

    print("\nSystem ready.\n")

    # 2. Outer attract loop — repeats between sessions
    while True:

        # ── Attract phase ──────────────────────────────────────────────────────
        pepper.set_head_tracking()   # head follows people, body stays still
        temi.show_welcome()          # ISO contact card on Temi screen

        log.info("Waiting for visitor start signal on Pepper ...")
        while True:
            pepper.show_splash(wait_for_tap=False)
            pepper.attract_visitors()
            start_reason = _wait_for_start(pepper, timeout=8)
            if start_reason:
                log.info("Visitor started session via %s.", start_reason)
                break
            log.info("No start signal yet. Repeating attract cycle ...")

        # ── Visitor detected ───────────────────────────────────────────────────
        log.info("Visitor started session.")
        pepper.set_body_tracking()   # Pepper turns whole body toward the person
        pepper.set_tablet_state("session")

        # Assign anonymous session ID (QR code scan removed — caused 20s delay)
        visitor_id = SessionManager.generate_id()
        log.info("Session ID: %s", visitor_id)

        orchestrator.start_interaction(visitor_id)

        # ── Conversation loop ──────────────────────────────────────────────────
        last_input_time = time.time()
        session_active  = True

        while session_active:

            # Idle timeout
            if time.time() - last_input_time > config.SESSION_IDLE_TIMEOUT:
                log.info("Session timed out — no input for %ds.", config.SESSION_IDLE_TIMEOUT)
                session_active = False
                break

            # Get input: Pepper tablet OR terminal (parallel threads, first wins)
            visitor_text = get_input(pepper, timeout=15)

            if not visitor_text:
                # Nothing pressed on Pepper, nothing typed
                pepper.say(
                    "Sorry, I couldn't catch that. "
                    "Please tap a button on Pepper or type your question in the terminal.",
                    animated=False,
                )
                continue

            last_input_time = time.time()

            # Hand off to orchestrator (LLM → Pepper speaks → Temi shows/delivers)
            continue_session = orchestrator.handle_input(visitor_text)

            if not continue_session:
                session_active = False

        # ── End of session ─────────────────────────────────────────────────────
        orchestrator.end_interaction()

        stats = sessions.stats()
        log.info("Session stats: %s", stats)

        time.sleep(2)
        temi.clear_screen()
        # Loop back to attract phase


if __name__ == "__main__":
    main()