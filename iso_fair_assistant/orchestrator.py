# orchestrator.py — LLM orchestrator
#
# Takes raw visitor speech → decides what Pepper says + what Temi shows.
# Keeps the last N conversation turns so the LLM has context continuity.

import json
import logging
import os
import threading
import time

from openai import OpenAI

import config
from agents.pepper_agent import PepperAgent
from agents.temi_agent import TemiAgent
from knowledge_base import KnowledgeBase
from session import SessionManager

log = logging.getLogger("orchestrator")

SYSTEM_PROMPT = """
You are Pepper, the friendly AI assistant at the Ostfalia International Student Office (ISO) stand at a university fair.

Your job:
- Answer questions about ISO services using ONLY the provided context.
- Be concise (2-3 sentences max per answer).
- Always be warm, patient, and welcoming.

Scope of the ISO:
- Incoming exchange students and their application process
- Erasmus+ program for outgoing students
- DAAD PROMOS scholarships for non-EU exchange
- Partner universities worldwide
- Language courses at the Sprachenzentrum (DaF, Sprachtandem)
- Housing and address registration basics
- Health insurance for international students
- ISO contact information

OUT OF SCOPE — redirect these to Studierenden-Service:
- General enrollment / first semester admin
- Semester fees, exam registration, library, IT accounts

If asked something out of scope, say:
"That's a great question, but it's handled by the Studierenden-Service office rather than us.
They're the right contact for that. Can I help you with anything about international programs?"

If you don't know the answer from the context, say:
"I'm not 100% sure about that. I recommend contacting our team directly at
incoming-iso@ostfalia.de or visiting Véronique Bizien at Am Exer 2, Raum 008."

Always respond in JSON with this exact schema:
{
  "speech": "<what Pepper says out loud>",
  "topic": "<one of: erasmus | partner_universities | studying_abroad | outgoing_process | europe_partners | non_eu_partners | language_courses | housing | health_insurance | redirect | welcome | farewell | other>",
  "offer_flyer": <true if a physical flyer would help, false otherwise>,
  "flyer_topic": "<topic key for the flyer, or null>",
  "session_end": <true if the visitor is saying goodbye, false otherwise>
}
""".strip()

HISTORY_LIMIT = 6   # number of conversation turns to keep (user + assistant pairs)


class Orchestrator:
    def __init__(self, pepper: PepperAgent, temi: TemiAgent,
                 kb: KnowledgeBase, sessions: SessionManager):
        self._pepper   = pepper
        self._temi     = temi
        self._kb       = kb
        self._sessions = sessions
        self._history: list[dict] = []
        self._current_visitor: str | None = None
        self._listen_fn = None   # injected from main.py after Whisper loads

        api_key = config.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")
        self._llm = OpenAI(api_key=api_key)

    def set_listen_fn(self, fn):
        """
        Inject the Whisper listen function so the orchestrator can use it
        for yes/no detection in _offer_flyer without importing main.py.
        Called from main.py after Whisper initialises:
            orchestrator.set_listen_fn(listen_whisper)
        """
        self._listen_fn = fn

    # ── Public interface ───────────────────────────────────────────────────────

    def start_interaction(self, visitor_id: str):
        """Called when a new visitor is detected."""
        self._current_visitor = visitor_id
        self._history = []
        self._sessions.start_session(visitor_id)
        self._pepper.set_tablet_state("session")
        self._pepper.set_tablet_questions_for_topic("welcome")

        if self._sessions.is_already_helped(visitor_id):
            self._pepper.greet_returning_visitor()
        else:
            self._pepper.greet_new_visitor()

        self._temi.show_welcome()

    def handle_input(self, visitor_text: str) -> bool:
        """
        Process one visitor utterance.
        Returns True to continue the session, False to end it.
        """
        log.info("Visitor said: %s", visitor_text)

        # 1. Retrieve relevant knowledge
        context = self._kb.search(visitor_text)

        # 2. Build messages for LLM
        messages = self._build_messages(visitor_text, context)

        # 3. Show thinking LEDs while waiting for LLM
        self._pepper.set_thinking_leds()
        self._pepper.set_tablet_state("thinking")

        # 4. Call LLM
        decision = self._call_llm(messages)
        if decision is None:
            self._pepper.say("I'm sorry, I had a technical issue. Please ask again.")
            self._pepper.set_tablet_state("listening")
            return True

        # 5. Update conversation history
        self._history.append({"role": "user", "content": visitor_text})
        self._history.append({"role": "assistant", "content": json.dumps(decision)})
        if len(self._history) > HISTORY_LIMIT * 2:
            self._history = self._history[-(HISTORY_LIMIT * 2):]

        # 6. Dispatch
        return self._dispatch(decision)

    def end_interaction(self):
        """Called when session ends (farewell or timeout)."""
        if self._current_visitor:
            self._sessions.close_session(self._current_visitor)
            self._current_visitor = None
        self._history = []
        self._pepper.farewell()
        self._temi.show_farewell()
        self._pepper.clear_tablet()
        self._temi.clear_screen()

    # ── LLM ───────────────────────────────────────────────────────────────────

    def _build_messages(self, visitor_text: str, context: str) -> list[dict]:
        system = SYSTEM_PROMPT + f"\n\nRELEVANT CONTEXT:\n{context}"
        messages = [{"role": "system", "content": system}]
        messages.extend(self._history)
        messages.append({"role": "user", "content": visitor_text})
        return messages

    def _call_llm(self, messages: list[dict]) -> dict | None:
        try:
            response = self._llm.chat.completions.create(
                model=config.LLM_MODEL,
                messages=messages,
                temperature=config.LLM_TEMPERATURE,
                response_format={"type": "json_object"},
            )
            raw      = response.choices[0].message.content
            decision = json.loads(raw)
            log.debug("LLM decision: %s", decision)
            return decision
        except json.JSONDecodeError as e:
            log.error("JSON parse error: %s", e)
        except Exception as e:
            log.error("LLM call failed: %s", e)
        return None

    # ── Dispatch ───────────────────────────────────────────────────────────────

    def _dispatch(self, decision: dict) -> bool:
        """
        Execute the LLM decision.
        Returns True to continue the session, False to end it.
        """
        topic       = decision.get("topic", "other")
        speech      = decision.get("speech", "")
        offer_flyer = decision.get("offer_flyer", False)
        flyer_topic = decision.get("flyer_topic")
        session_end = decision.get("session_end", False)
        flyer_topics = {
            "erasmus",
            "partner_universities",
            "studying_abroad",
            "outgoing_process",
            "europe_partners",
            "non_eu_partners",
            "language_courses",
            "housing",
            "health_insurance",
        }

        if topic:
            self._pepper.set_tablet_questions_for_topic(topic)

        # Track topic in session
        if self._current_visitor and topic not in ("other", "welcome", "farewell"):
            self._sessions.record_topic(self._current_visitor, topic)

        # Update Temi screen to match the topic Pepper is discussing
        self._temi.show_topic_image(topic)

        # Pepper speaks
        self._pepper.set_speaking_leds()
        self._pepper.say(speech, animated=True)
        self._pepper.set_tablet_state("listening")

        # Offer a flyer if the LLM decided one would help
        if (offer_flyer or topic in flyer_topics) and (flyer_topic or topic):
            flyer_topic = flyer_topic or topic
            self._offer_flyer(flyer_topic)

        # Session end?
        if session_end:
            return False

        return True

    def _offer_flyer(self, flyer_topic: str):
        """
        Announce Temi handoff and trigger flyer delivery.

        For yes/no confirmation we use Pepper's own keyword detection
        (wait_for_keyword via pepper.listen_for_speech) which was already
        working for simple words. If nothing is heard within the timeout,
        we auto-send Temi — at a fair, defaulting to yes is better UX
        than blocking forever waiting for an answer.

        The old input() fallback has been removed because it blocked the
        main thread indefinitely when voice detection failed, preventing
        temi.deliver_flyer() from ever being called.
        """
        topic_label = flyer_topic.replace("_", " ")

        if config.AUTO_ACCEPT_FLYER:
            log.info("AUTO_ACCEPT_FLYER — skipping confirmation.")
            self._deliver_and_wait(flyer_topic)
            return

        self._pepper.announce_temi_handoff(topic_label)
        self._pepper.say(
            "Would you like me to ask Temi to bring it now? Please say yes or no.",
            animated=True,
        )

        # Offer the same confirmation directly on the tablet for faster flow.
        self._pepper.set_tablet_questions([
            "Yes, bring the flyer",
            "No, thanks",
        ])

        answer = self._wait_for_flyer_confirmation()

        log.info("Flyer confirmation heard: %s", answer)

        # Restore topic shortcuts after this temporary yes/no prompt.
        self._pepper.set_tablet_questions_for_topic(flyer_topic)

        if answer is None:
            # Nothing heard — auto-send Temi rather than blocking
            log.info("No answer heard — auto-sending Temi.")
            self._pepper.say(
                f"I'll go ahead and ask Temi to bring the {topic_label} flyer.",
                animated=True,
            )
            self._deliver_and_wait(flyer_topic)
        elif answer.lower() in ("yes", "yeah", "yep", "sure", "okay"):
            self._deliver_and_wait(flyer_topic)
        else:
            self._pepper.say(
                f"No problem! The {topic_label} flyers are on the table next to Temi."
            )

    def _deliver_and_wait(self, flyer_topic: str):
        """Start Temi delivery, show waiting state, then continue when Temi is ready or timed out."""
        self._pepper.set_tablet_state("waiting")
        self._temi.deliver_flyer(flyer_topic)

        if self._temi.wait_for_delivery_ready(timeout=config.TEMI_FLYER_PROMPT_TIMEOUT):
            self._pepper.temi_returned()
            self._pepper.set_tablet_state("listening")
            return

        deadline = time.time() + config.TEMI_FLYER_WAIT_TIMEOUT
        while time.time() < deadline:
            if self._temi.wait_for_delivery(timeout=1.0):
                self._pepper.temi_returned()
                self._pepper.set_tablet_state("listening")
                return

        log.info("Temi delivery timed out after %ss; continuing anyway.", config.TEMI_FLYER_WAIT_TIMEOUT)
        self._pepper.say(
            "Temi is taking a little longer, so please feel free to continue looking at the screen.",
            animated=False,
        )
        self._pepper.set_tablet_state("listening")

    def _wait_for_flyer_confirmation(self, timeout: int = 12) -> str | None:
        """Wait for either voice (yes/no) or tablet yes/no button input."""
        answer = [None]
        done = threading.Event()

        def _voice():
            heard = self._pepper.listen_for_speech(
                ["yes", "yeah", "yep", "sure", "okay", "no", "nope"]
            )
            if heard and not done.is_set():
                answer[0] = heard.lower().strip()
                done.set()

        def _tablet():
            choice = self._pepper.get_tablet_input(timeout=timeout)
            if not choice or done.is_set():
                return
            normalized = choice.lower().strip()
            if "yes" in normalized:
                answer[0] = "yes"
                done.set()
            elif "no" in normalized:
                answer[0] = "no"
                done.set()

        threading.Thread(target=_voice, daemon=True).start()
        threading.Thread(target=_tablet, daemon=True).start()

        done.wait(timeout=timeout + 1)
        return answer[0]