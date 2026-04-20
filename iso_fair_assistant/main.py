# main.py — Smart ISO Fair Assistant
#
# Run:   python3.11 main.py
# Stop:  Ctrl+C
#
# Input sources (checked every loop — whichever arrives first wins):
#   1. Tablet touch button  ← always checked first, non-blocking
#   2. Pepper mic + Whisper ← runs in background thread
# No blocking input() calls in the conversation loop.

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

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


# ── Whisper ────────────────────────────────────────────────────────────────────

try:
    import whisper as _whisper
    import numpy as _np
    _whisper_model = _whisper.load_model("base")
    WHISPER_AVAILABLE = True
    log.info("Whisper STT ready.")
except ImportError:
    WHISPER_AVAILABLE = False
    _whisper_model = None
    log.warning("openai-whisper not installed — voice input unavailable.")


def transcribe(audio_array) -> str | None:
    if _whisper_model is None or audio_array is None:
        return None
    try:
        result = _whisper_model.transcribe(audio_array, fp16=False, language="en")
        text = result["text"].strip()
        if text:
            log.info("Whisper: %s", text)
        return text or None
    except Exception as e:
        log.warning("Whisper error: %s", e)
        return None


# ── Non-blocking input: touch + voice in parallel ─────────────────────────────

def get_visitor_input(
    pepper: PepperAgent,
    tablet: TabletServer,
    listen_duration: float = 7.0,
) -> str | None:
    """
    Listen for input from two sources simultaneously:
      A) Tablet touch buttons  — polled every 0.2s (non-blocking)
      B) Pepper mic + Whisper  — runs in a background thread

    Returns the FIRST input that arrives.
    NEVER calls input() — no terminal blocking.
    """
    voice_result = [None]
    voice_done   = threading.Event()

    def _record():
        if WHISPER_AVAILABLE:
            audio = pepper.listen_with_mic(duration=listen_duration)
            voice_result[0] = transcribe(audio)
        voice_done.set()

    t = threading.Thread(target=_record, daemon=True)
    t.start()

    # Poll tablet while voice records
    deadline = time.time() + listen_duration + 2
    while not voice_done.is_set() and time.time() < deadline:
        touch = tablet.get_touch_input(timeout=0.2)
        if touch:
            log.info("Touch input: %s", touch)
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
    print("  Smart ISO Fair Assistant — Starting up")
    print("="*55 + "\n")

    from pathlib import Path
    base_dir = Path(__file__).resolve().parent

    # ── Tablet server ──────────────────────────────────────────────────────────
    tablet = TabletServer(config.LOCAL_IP, config.TABLET_SERVER_PORT, base_dir)
    if not tablet.start():
        log.critical("Tablet server failed to start. Exiting.")
        sys.exit(1)

    # ── Robots ─────────────────────────────────────────────────────────────────
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

    # ── Orchestrator ───────────────────────────────────────────────────────────
    kb       = KnowledgeBase(config.KB_INDEX_DIR, config.EMBED_MODEL, config.KB_TOP_K)
    sessions = SessionManager()
    orchestrator = Orchestrator(pepper, temi, kb, sessions, tablet)

    signal.signal(signal.SIGINT, lambda *_: _shutdown(pepper, temi, tablet))

    pepper.show_tablet_page()

    print("\nSystem ready. Waiting for visitors ...\n")
    pepper.attract_visitors()
    temi.show_welcome()

    # ── Event loop ─────────────────────────────────────────────────────────────
    while True:

        # Wait for visitor — face detection, fallback to Enter
        log.debug("Scanning for visitors ...")
        visitor_detected = False
        for _ in range(3):
            if pepper.detect_face():
                visitor_detected = True
                break

        if not visitor_detected:
            # Only block here (before session starts) — this is fine
            try:
                input("  [No face detected. Press Enter when visitor is ready]: ")
            except (EOFError, KeyboardInterrupt):
                continue

        log.info("Visitor detected — starting interaction.")
        tablet.clear_touch_queue()

        visitor_id = SessionManager.generate_id()
        log.info("Session ID: %s", visitor_id)

        orchestrator.start_interaction(visitor_id)

        last_input_time = time.time()
        session_active  = True

        while session_active:

            # Idle timeout
            if time.time() - last_input_time > config.SESSION_IDLE_TIMEOUT:
                log.info("Session timed out.")
                session_active = False
                break

            # Get input — NON-BLOCKING touch poll + background voice
            # No input() calls here.
            visitor_text = get_visitor_input(pepper, tablet, listen_duration=7.0)

            if not visitor_text:
                continue

            last_input_time = time.time()

            # Back button — reset questions, don't call LLM
            if visitor_text == "__back__":
                tablet.set_questions_for_topic("welcome")
                continue

            # Goodbye button or farewell phrase — end session immediately
            if visitor_text == "__end__" or any(
                w in visitor_text.lower()
                for w in ("goodbye", "that's all", "no more questions",
                          "thank you so much", "no thank", "bye bye")
            ):
                log.info("Visitor ended session (%s).", visitor_text)
                session_active = False
                continue

            continue_session = orchestrator.handle_input(visitor_text)
            if not continue_session:
                session_active = False

        # End session and reset
        orchestrator.end_interaction()
        log.info("Session stats: %s", sessions.stats())

        time.sleep(2)
        tablet.reset_to_default()
        pepper.attract_visitors()


if __name__ == "__main__":
    main()