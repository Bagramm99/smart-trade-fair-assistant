# main.py — Smart ISO Fair Assistant
#
# Run with:   python3.11 main.py
# Stop with:  Ctrl+C  (clean shutdown)
#
# Flow:
#   1. Attract loop: Pepper waves + pitch, shows splash, waits for touch OR Enter
#   2. Visitor arrives: Pepper switches to WholeBody tracking, greets
#   3. Conversation loop:
#        - Temi listens (Android ASR, /listen endpoint) in a thread
#        - Terminal input runs in parallel as fallback
#        - First input wins
#        - If nothing heard: Pepper apologises and asks to type or tap
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


# ── Parallel input helpers ─────────────────────────────────────────────────────

def _wait_for_start(pepper: PepperAgent) -> None:
    """
    Block until a visitor starts the session via either:
      - Touching Pepper's tablet or any sensor  (pepper.wait_for_any_touch)
      - Pressing Enter on the terminal           (input())

    Both run in parallel threads — whichever fires first wins.
    """
    done = threading.Event()

    def _touch():
        try:
            pepper.wait_for_any_touch()   # blocks until touched
        except Exception as e:
            log.debug("Touch wait error: %s", e)
        done.set()

    def _terminal():
        try:
            input("  [Press Enter when visitor is ready, or visitor taps the screen]: ")
        except (EOFError, KeyboardInterrupt):
            pass
        done.set()

    threading.Thread(target=_touch,    daemon=True).start()
    threading.Thread(target=_terminal, daemon=True).start()
    done.wait()   # wait forever until one of them fires


def get_input(temi: TemiAgent, timeout: int = 15) -> str | None:
    """
    Get free-form visitor input from two parallel sources:
      A) Temi's microphone via temi.listen()  — Android ASR, full transcript
      B) Terminal keyboard input              — always available as fallback

    Returns the first non-empty result, or None if both time out.

    Why Temi's mic instead of Pepper's:
      - Temi is positioned on the table closer to the visitor
      - Android ASR returns a full free-form transcript (no vocabulary limit)
      - Pepper's NAOqi ASR only supports fixed keyword lists
    """
    result = [None]
    done   = threading.Event()

    def _temi_listen():
        try:
            text = temi.listen(timeout=timeout)
            if text and not done.is_set():
                result[0] = text
                done.set()
        except Exception as e:
            log.warning("Temi listen thread error: %s", e)
        finally:
            # Always signal done so the terminal thread doesn't wait forever
            done.set()

    def _terminal_listen():
        try:
            if config.ENABLE_TYPED_FALLBACK:
                text = input("  [TYPE your question, or speak to Temi]: ").strip()
                if text and not done.is_set():
                    result[0] = text
                    done.set()
        except (EOFError, KeyboardInterrupt):
            pass
        done.set()

    threading.Thread(target=_temi_listen,    daemon=True).start()
    threading.Thread(target=_terminal_listen, daemon=True).start()

    done.wait(timeout=timeout + 5)   # +5s buffer past Temi's timeout
    return result[0]


# ── Shutdown ───────────────────────────────────────────────────────────────────

def _shutdown(pepper: PepperAgent, temi: TemiAgent):
    log.info("Shutting down ...")
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
        pepper.attract_visitors()    # wave + welcome pitch (existing method)
        pepper.show_splash()         # show "tap to start" on tablet
        temi.show_welcome()          # ISO contact card on Temi screen

        log.info("Waiting for visitor (touch Pepper's screen or press Enter) ...")
        _wait_for_start(pepper)      # blocks until touch OR Enter

        # ── Visitor detected ───────────────────────────────────────────────────
        log.info("Visitor started session.")
        pepper.set_body_tracking()   # Pepper turns whole body toward the person

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

            # Get input: Temi mic OR terminal (parallel threads, first wins)
            visitor_text = get_input(temi, timeout=15)

            if not visitor_text:
                # Nothing heard from Temi, nothing typed
                pepper.say(
                    "Sorry, I couldn't catch that. "
                    "Please type your question in the terminal, "
                    "or speak clearly toward Temi.",
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
        # Loop back to attract phase


if __name__ == "__main__":
    main()