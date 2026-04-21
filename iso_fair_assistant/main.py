# main.py — Smart ISO Fair Assistant
#
# Flow:
#   Splash screen ("Tap to Start") → visitor taps → session starts →
#   conversation (touch + voice in parallel) → goodbye → back to splash.
#
# Zero blocking input() calls inside the session loop.

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
from tablet_server import TabletServer

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

# ── Whisper ────────────────────────────────────────────────────────────────────
try:
    import whisper as _whisper
    _whisper_model = _whisper.load_model("base")
    WHISPER_AVAILABLE = True
    log.info("Whisper ready.")
except ImportError:
    WHISPER_AVAILABLE = False
    _whisper_model = None
    log.warning("openai-whisper not installed — touch-only mode.")


def transcribe(audio) -> str | None:
    if _whisper_model is None or audio is None:
        return None
    try:
        r = _whisper_model.transcribe(audio, fp16=False, language="en")
        t = r["text"].strip()
        if t:
            log.info("Whisper: %s", t)
        return t or None
    except Exception as e:
        log.warning("Whisper error: %s", e)
        return None


# ── Parallel voice + touch input ───────────────────────────────────────────────

def get_input(pepper: PepperAgent, tablet: TabletServer,
              duration: float = 7.0) -> str | None:
    """
    Poll tablet touch AND Pepper mic simultaneously.
    Returns whichever arrives first. Never blocks the main thread.
    """
    voice_result = [None]
    voice_done   = threading.Event()

    def _record():
        if WHISPER_AVAILABLE:
            audio = pepper.listen_with_mic(duration=duration)
            voice_result[0] = transcribe(audio)
        voice_done.set()

    threading.Thread(target=_record, daemon=True).start()

    deadline = time.time() + duration + 2
    while not voice_done.is_set() and time.time() < deadline:
        touch = tablet.get_touch_input(timeout=0.2)
        if touch:
            log.info("Touch: %s", touch)
            return touch

    return voice_result[0]


# ── Shutdown ───────────────────────────────────────────────────────────────────

def _shutdown(pepper, temi, tablet):
    log.info("Shutting down ...")
    pepper.disconnect()
    temi.disconnect()
    tablet.stop()
    sys.exit(0)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*55)
    print("  Smart ISO Fair Assistant")
    print("="*55 + "\n")

    from pathlib import Path
    base_dir = Path(__file__).resolve().parent

    # ── Start tablet server ────────────────────────────────────────────────────
    tablet = TabletServer(config.LOCAL_IP, config.TABLET_SERVER_PORT, base_dir)
    if not tablet.start():
        log.critical("Tablet server failed. Exiting.")
        sys.exit(1)

    # ── Connect robots ─────────────────────────────────────────────────────────
    pepper = PepperAgent()
    temi   = TemiAgent()
    pepper.set_tablet_server(tablet)
    temi.set_tablet_server(tablet)

    if not pepper.connect():
        log.critical("Cannot connect to Pepper. Exiting.")
        sys.exit(1)
    if not temi.connect():
        log.critical("Cannot connect to Temi. Exiting.")
        sys.exit(1)

    pepper.print_status()

    kb           = KnowledgeBase(config.KB_INDEX_DIR, config.EMBED_MODEL, config.KB_TOP_K)
    sessions     = SessionManager()
    orchestrator = Orchestrator(pepper, temi, kb, sessions, tablet)

    signal.signal(signal.SIGINT, lambda *_: _shutdown(pepper, temi, tablet))

    pepper.show_tablet_page()

    # ── Outer loop ─────────────────────────────────────────────────────────────
    while True:

        # ── SPLASH: show "Tap to Start", wait for __start__ tap ───────────────
        tablet.set_state("splash")
        tablet.clear_touch_queue()
        pepper.attract_visitors()
        temi.show_welcome()

        log.info("Waiting for visitor to tap 'Start' ...")
        while True:
            touch = tablet.get_touch_input(timeout=0.5)
            if touch == "__start__":
                log.info("Visitor tapped Start.")
                break
            # Also start if visitor speaks (voice detected without needing Start tap)
            if WHISPER_AVAILABLE:
                audio = pepper.listen_with_mic(duration=3.0)
                text  = transcribe(audio)
                if text and len(text.strip()) > 3:
                    log.info("Visitor spoke before tapping Start — auto-starting session.")
                    # Pass text to session below as first input
                    tablet.get_touch_input(timeout=0)   # flush any stale touches
                    first_input = text
                    break
        else:
            first_input = None  # started by __start__ tap

        # ── SESSION: greet and converse ────────────────────────────────────────
        tablet.set_state("idle")
        tablet.clear_touch_queue()

        visitor_id = SessionManager.generate_id()
        log.info("Session: %s", visitor_id)
        orchestrator.start_interaction(visitor_id)

        # If visitor already spoke before tapping Start, handle that first
        if 'first_input' in dir() and first_input and first_input not in ("__start__", "__back__", "__end__"):
            if not orchestrator.handle_input(first_input):
                orchestrator.end_interaction()
                continue
        first_input = None  # reset

        last_input_time = time.time()
        session_active  = True

        while session_active:
            # Idle timeout
            if time.time() - last_input_time > config.SESSION_IDLE_TIMEOUT:
                log.info("Session timed out.")
                session_active = False
                break

            visitor_text = get_input(pepper, tablet, duration=7.0)

            if not visitor_text:
                continue

            last_input_time = time.time()

            if visitor_text == "__back__":
                tablet.set_questions_for_topic("welcome")
                continue

            # Goodbye button or farewell phrase
            if visitor_text == "__end__" or any(
                w in visitor_text.lower()
                for w in ("goodbye", "bye bye", "that's all", "no more questions",
                          "thank you so much", "no thank", "i'm done", "im done")
            ):
                log.info("Visitor ended session.")
                session_active = False
                continue

            if not orchestrator.handle_input(visitor_text):
                session_active = False

        # End session → loop back to splash
        orchestrator.end_interaction()
        log.info("Stats: %s", sessions.stats())
        time.sleep(1)


if __name__ == "__main__":
    main()