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
import select
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

# Short keywords that Pepper can reliably detect with ALSpeechRecognition.
SPEECH_SHORTCUTS = {
    "erasmus": "Tell me about Erasmus.",
    "housing": "How do I find housing?",
    "insurance": "What health insurance do I need?",
    "language": "What language courses are available?",
    "abroad": "How can I study abroad?",
    "partners": "Which partner universities do you have?",
}


# ── Whisper STT (optional — runs in parallel with tablet + keyword detection) ───

try:
    import whisper as _whisper
    import sounddevice as _sd

    _whisper_model = _whisper.load_model("base")

    def listen_whisper(duration: float = 6.0, sample_rate: int = 16_000) -> str | None:
        """Record from laptop mic and transcribe. Runs as a background thread
        inside get_input() in parallel with tablet and keyword detection.
        The 0.5s gap before recording prevents Pepper's last word bleeding in."""
        try:
            import numpy as _np
            audio = _sd.rec(int(duration * sample_rate), samplerate=sample_rate,
                            channels=1, dtype="float32")
            _sd.wait()
            result = _whisper_model.transcribe(audio.flatten(), fp16=False, language="en")
            text = result["text"].strip()
            if text:
                log.info("Whisper heard: %s", text)
            return text if text else None
        except Exception as e:
            log.debug("Whisper error: %s", e)
            return None

    log.info("Whisper STT ready.")

except ImportError:
    log.warning("whisper/sounddevice not installed — Whisper unavailable.")

    def listen_whisper(duration: float = 6.0, sample_rate: int = 16_000) -> str | None:
        return None  # tablet + keywords still work without Whisper


def _wait_for_start(pepper: PepperAgent, timeout: int = 8) -> str | None:
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
            input("  [Press Enter to start, tap Pepper\'s button, or let Pepper detect your face]: ")
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
    result = [None]
    done = threading.Event()
    started = time.time()

    def _tablet_listen():
        try:
            text = pepper.get_tablet_input(timeout=timeout)
            if text and not done.is_set():
                result[0] = text
                done.set()
        except Exception as e:
            log.debug("Pepper tablet input error: %s", e)

    def _speech_listen():
        if not config.ENABLE_SPEECH_FALLBACK:
            return
        try:
            heard = pepper.listen_for_speech(
                list(SPEECH_SHORTCUTS.keys()),
                timeout=min(timeout, config.SPEECH_KEYWORD_TIMEOUT),
                threshold=config.SPEECH_KEYWORD_THRESHOLD,
            )
            if heard and not done.is_set():
                normalized = heard.lower().strip()
                result[0] = SPEECH_SHORTCUTS.get(normalized, heard)
                done.set()
        except Exception as e:
            log.debug("Pepper speech input error: %s", e)

    def _whisper_listen():
        time.sleep(0.5)  # gap: clears Pepper's last word from mic before recording
        text = listen_whisper(duration=6.0)
        if text and not done.is_set():
            result[0] = text
            done.set()

    threading.Thread(target=_tablet_listen,  daemon=True).start()
    threading.Thread(target=_speech_listen,  daemon=True).start()
    threading.Thread(target=_whisper_listen, daemon=True).start()

    if config.ENABLE_TYPED_FALLBACK:
        print("  [Speak a keyword, tap Pepper, or type in terminal and press Enter]", flush=True)
    deadline = started + timeout
    while not done.is_set() and time.time() < deadline:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        done.wait(timeout=0.2)
        if not done.is_set() and config.ENABLE_TYPED_FALLBACK:
            try:
                readable, _, _ = select.select([sys.stdin], [], [], 0.01)
                if readable:
                    line = sys.stdin.readline()
                    if line:
                        text = line.strip()
                        if text and not done.is_set():
                            result[0] = text
                            done.set()
                            break
            except (OSError, ValueError):
                pass

    if not done.is_set():
        elapsed = time.time() - started
        remaining = max(0.0, timeout - elapsed)
        done.wait(timeout=remaining + 0.2)

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

    while True:

        pepper.set_head_tracking()
        temi.show_welcome()

        log.info("Waiting for visitor start signal on Pepper ...")
        while True:
            pepper.show_splash(wait_for_tap=False)
            pepper.attract_visitors()
            start_reason = _wait_for_start(pepper, timeout=8)
            if start_reason:
                log.info("Visitor started session via %s.", start_reason)
                break
            log.info("No start signal yet. Repeating attract cycle ...")

        log.info("Visitor started session.")
        pepper.set_body_tracking()
        pepper.set_tablet_state("session")

        visitor_id = SessionManager.generate_id()
        log.info("Session ID: %s", visitor_id)

        orchestrator.start_interaction(visitor_id)

        last_input_time = time.time()
        session_active  = True

        while session_active:

            if time.time() - last_input_time > config.SESSION_IDLE_TIMEOUT:
                log.info("Session timed out — no input for %ds.", config.SESSION_IDLE_TIMEOUT)
                session_active = False
                break

            visitor_text = get_input(pepper, timeout=15)

            if not visitor_text:
                pepper.say(
                    "Sorry, I couldn\'t catch that. "
                    "Please speak a short keyword like Erasmus or housing, "
                    "tap a button on Pepper, or type your question in the terminal.",
                    animated=False,
                )
                continue

            last_input_time = time.time()

            continue_session = orchestrator.handle_input(visitor_text)

            if not continue_session:
                session_active = False

        orchestrator.end_interaction()

        stats = sessions.stats()
        log.info("Session stats: %s", stats)

        time.sleep(2)
        temi.clear_screen()


if __name__ == "__main__":
    main()