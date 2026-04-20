# main.py — Smart ISO Fair Assistant
#
# Run:   python3.11 main.py
# Stop:  Ctrl+C
#
# Input priority each turn (whichever arrives first wins):
#   1. Visitor taps a question on Pepper's tablet touch screen
#   2. Visitor speaks → captured via Pepper's mic → Whisper transcribes
#   3. Keyboard fallback (if Whisper unavailable)

import logging
import signal
import sys
import time
from pathlib import Path

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


# ── Whisper (runs locally, transcribes audio from Pepper's mic) ───────────────

try:
    import whisper as _whisper
    import numpy as _np

    _whisper_model = _whisper.load_model("base")
    log.info("Whisper STT ready (model: base).")
    WHISPER_AVAILABLE = True

except ImportError:
    log.warning("openai-whisper not installed — voice input unavailable.")
    WHISPER_AVAILABLE = False
    _whisper_model = None


def transcribe(audio_array) -> str | None:
    """Run Whisper on a float32 numpy array. Returns text or None."""
    if _whisper_model is None or audio_array is None:
        return None
    try:
        result = _whisper_model.transcribe(audio_array, fp16=False, language="en")
        text = result["text"].strip()
        if text:
            log.info("Whisper: %s", text)
        return text or None
    except Exception as e:
        log.warning("Whisper transcription failed: %s", e)
        return None


# ── Input: touch OR voice (whichever comes first) ─────────────────────────────

def get_visitor_input(
    pepper: PepperAgent,
    tablet: TabletServer,
    listen_duration: float = 7.0,
) -> str | None:
    """
    Try to get input from two sources in parallel:
      A) Pepper's mic → Whisper (runs in background thread)
      B) Tablet touch queue (checked every 0.2s during recording)

    Returns the first input received, or None.
    If voice capture is unavailable, falls back to the tablet and then keyboard.
    """
    import threading

    voice_result = [None]
    voice_done   = threading.Event()

    def _record_and_transcribe():
        audio = pepper.listen_with_mic(duration=listen_duration)
        voice_result[0] = transcribe(audio)
        voice_done.set()

    if WHISPER_AVAILABLE:
        t = threading.Thread(target=_record_and_transcribe, daemon=True)
        t.start()

        # Poll tablet while voice is recording
        start = time.time()
        while not voice_done.is_set():
            touch = tablet.get_touch_input(timeout=0.2)
            if touch:
                log.info("Touch input received: %s", touch)
                return touch
            if time.time() - start > listen_duration + 2:
                break

        return voice_result[0]

    else:
        # No Whisper — just check tablet, then keyboard
        touch = tablet.get_touch_input(timeout=0)
        if touch:
            return touch

        if config.ENABLE_TYPED_FALLBACK:
            try:
                typed = input("  [TYPE visitor input]: ").strip()
                return typed or None
            except (EOFError, KeyboardInterrupt):
                return None
        return None


# ── Whisper-based yes/no for flyer confirmation ────────────────────────────────

def listen_for_confirmation(pepper: PepperAgent, tablet: TabletServer) -> str | None:
    """
    Record 5 seconds and check if the transcript contains yes or no.
    Also checks the tablet touch queue (visitor may tap a question = implicit yes).
    """
    import threading

    voice_result = [None]
    voice_done   = threading.Event()

    def _record():
        audio = pepper.listen_with_mic(duration=5.0)
        raw = transcribe(audio)
        if raw:
            t = raw.lower()
            if any(w in t for w in ("yes", "yeah", "yep", "sure", "okay", "please")):
                voice_result[0] = "yes"
            elif any(w in t for w in ("no", "nope", "don't", "not", "skip")):
                voice_result[0] = "no"
        voice_done.set()

    if WHISPER_AVAILABLE:
        t = threading.Thread(target=_record, daemon=True)
        t.start()

        while not voice_done.is_set():
            touch = tablet.get_touch_input(timeout=0.2)
            if touch and touch != "__back__":
                return "yes"   # any touch = wanting more info = yes

        return voice_result[0]
    else:
        touch = tablet.get_touch_input(timeout=0)
        if touch and touch != "__back__":
            return "yes"
        if config.ENABLE_TYPED_FALLBACK:
            try:
                typed = input("  [yes/no]: ").strip().lower()
                if typed in ("y", "yes", "yeah", "sure"):
                    return "yes"
                if typed in ("n", "no", "nope"):
                    return "no"
            except (EOFError, KeyboardInterrupt):
                pass
        return None


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

    base_dir = Path(__file__).resolve().parent

    # ── Start tablet server ────────────────────────────────────────────────────
    tablet = TabletServer(config.LOCAL_IP, config.TABLET_SERVER_PORT, base_dir)
    if not tablet.start():
        log.critical("Tablet server failed to start. Exiting.")
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

    # ── Knowledge base ─────────────────────────────────────────────────────────
    kb       = KnowledgeBase(config.KB_INDEX_DIR, config.EMBED_MODEL, config.KB_TOP_K)
    sessions = SessionManager()
    orchestrator = Orchestrator(pepper, temi, kb, sessions, tablet)
    orchestrator.set_listen_fn(listen_for_confirmation)

    signal.signal(signal.SIGINT, lambda *_: _shutdown(pepper, temi, tablet))

    # ── Load tablet page on Pepper's screen ────────────────────────────────────
    pepper.show_tablet_page()

    print("\nSystem ready. Waiting for visitors ...\n")
    pepper.attract_visitors()
    temi.show_welcome()

    # ── Main event loop ────────────────────────────────────────────────────────
    while True:

        # Step 1: Wait for a visitor
        # Using face detection — no QR scan, no delay.
        # Face detection runs in a short loop; if it fails, falls back to Enter.
        log.debug("Scanning for visitors ...")
        visitor_detected = False
        for _ in range(3):   # try 3 times before prompting manually
            if pepper.detect_face():
                visitor_detected = True
                break

        if not visitor_detected:
            try:
                input("  [No face detected. Press Enter when visitor is ready]: ")
            except (EOFError, KeyboardInterrupt):
                continue

        log.info("Visitor detected — starting interaction.")
        tablet.clear_touch_queue()   # discard any stale touches

        # Step 2: Assign anonymous session ID (no QR wait)
        visitor_id = SessionManager.generate_id()
        log.info("Session ID: %s", visitor_id)

        # Step 3: Greet
        orchestrator.start_interaction(visitor_id)

        # Step 4: Conversation loop
        last_input_time = time.time()
        session_active  = True

        while session_active:
            if time.time() - last_input_time > config.SESSION_IDLE_TIMEOUT:
                log.info("Session timed out.")
                session_active = False
                break

            visitor_text = get_visitor_input(pepper, tablet, listen_duration=7.0)

            if visitor_text == "__back__":
                # Visitor tapped "← Back" — reset questions, no LLM call
                tablet.set_questions_for_topic("welcome")
                continue

            # Goodbye button or explicit farewell phrasing → end session directly
            if visitor_text == "__end__" or any(
                w in visitor_text.lower()
                for w in ("goodbye", "bye", "that's all", "that is all",
                          "no more", "thank you so much", "no thanks", "no thank")
            ):
                log.info("Session ended by visitor (%s).", visitor_text)
                session_active = False
                continue

            if not visitor_text:
                continue

            last_input_time = time.time()
            continue_session = orchestrator.handle_input(visitor_text)

            if not continue_session:
                session_active = False

        # Step 5: End session
        orchestrator.end_interaction()
        log.info("Session stats: %s", sessions.stats())

        time.sleep(2)
        tablet.reset_to_default()
        pepper.attract_visitors()


if __name__ == "__main__":
    main()
