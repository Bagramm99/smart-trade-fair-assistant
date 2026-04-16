# main.py — Smart ISO Fair Assistant
#
# Run with:   python main.py
# Stop with:  Ctrl+C  (clean shutdown)
#
# The loop:
#   1. Pepper scans for a face
#   2. New face → try to read QR code for visitor ID
#   3. Greet visitor (returning vs new)
#   4. Conversation loop using Whisper STT + LLM + Temi display
#   5. Session ends on farewell or timeout → back to step 1

import logging
import signal
import sys
import time

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


# ── Speech-to-text (Whisper) ───────────────────────────────────────────────────
# Whisper runs on your laptop microphone, not Pepper's mic.
# Pepper's mic is used only for keyword detection (yes/no confirmations).
# For full free-form conversation, plug a USB microphone into the laptop
# and run Whisper to transcribe each visitor utterance.

try:
    import whisper as _whisper
    import sounddevice as _sd
    import numpy as _np

    _whisper_model = _whisper.load_model("base")

    def listen_whisper(duration: float = 7.0, sample_rate: int = 16_000) -> str | None:
        """
        Record from the laptop mic and transcribe with Whisper.

        Timing fixes:
          - 0.5s delay after Pepper finishes speaking so the visitor has
            a moment to start talking (Pepper's say() is blocking, so this
            runs right after speech ends)
          - Print a clear signal so the operator/visitor knows to speak now
          - 7 seconds (was 6) gives a bit more room
        """
        import time as _time
        _time.sleep(0.5)   # brief gap after Pepper stops talking
        print("\n  🎤  Listening ... (speak now)", flush=True)

        audio = _sd.rec(
            int(duration * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
        )
        _sd.wait()
        print("  ⏹  Done listening.", flush=True)

        flat = audio.flatten()
        result = _whisper_model.transcribe(flat, fp16=False, language="en")
        text = result["text"].strip()
        if text:
            log.info("Whisper heard: %s", text)
        else:
            log.debug("Whisper heard nothing.")
        return text if text else None

    log.info("Whisper STT ready.")

except ImportError:
    log.warning("whisper/sounddevice not installed — using keyboard input fallback.")

    def listen_whisper(duration: float = 6.0, sample_rate: int = 16_000) -> str | None:
        """Keyboard fallback for development without a microphone."""
        try:
            text = input("  [TYPE visitor input]: ").strip()
            return text if text else None
        except (EOFError, KeyboardInterrupt):
            return None


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
    orchestrator.set_listen_fn(listen_whisper)   # use Whisper for yes/no too

    signal.signal(signal.SIGINT, lambda *_: _shutdown(pepper, temi))

    print("\nSystem ready. Waiting for visitors ...\n")
    pepper.attract_visitors()
    temi.show_welcome()

    # 2. Main event loop
    while True:

        
        # ── Wait for a face ────────────────────────────────────────────────────
               # log.debug("Scanning for visitors ...")
                # if not pepper.detect_face():
                  #  time.sleep(1)
                   # continue

               # log.info("Visitor detected!")
        input("  [Press Enter when visitor is ready]: ")
        
        # ── Get visitor ID via QR code (optional) ──────────────────────────────
        visitor_id = pepper.scan_qr_code()
        if visitor_id is None:
            # No QR scan → assign a temporary anonymous ID for this session
            visitor_id = SessionManager.generate_id()
            log.info("No QR code — assigned anonymous ID: %s", visitor_id)

        # ── Start the interaction ──────────────────────────────────────────────
        orchestrator.start_interaction(visitor_id)

        # ── Conversation loop ──────────────────────────────────────────────────
        last_input_time = time.time()
        session_active  = True

        while session_active:
            # Check idle timeout
            if time.time() - last_input_time > config.SESSION_IDLE_TIMEOUT:
                log.info("Session timed out — no input for %ds.", config.SESSION_IDLE_TIMEOUT)
                session_active = False
                break

            # Listen for visitor speech (Whisper if available, keyboard fallback otherwise)
            visitor_text = listen_whisper(duration=6.0)

            if not visitor_text and config.ENABLE_TYPED_FALLBACK:
                try:
                    typed = input("  [No speech detected. TYPE visitor input or press Enter to skip]: ").strip()
                    visitor_text = typed if typed else None
                except (EOFError, KeyboardInterrupt):
                    visitor_text = None

            if not visitor_text:
                continue

            last_input_time = time.time()

            # Hand off to orchestrator
            continue_session = orchestrator.handle_input(visitor_text)

            if not continue_session:
                session_active = False

        # ── End of session ─────────────────────────────────────────────────────
        orchestrator.end_interaction()

        stats = sessions.stats()
        log.info("Session stats: %s", stats)

        # Brief pause before scanning for the next visitor
        time.sleep(2)
        pepper.attract_visitors()


if __name__ == "__main__":
    main()