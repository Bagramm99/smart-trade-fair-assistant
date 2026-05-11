# orchestrator.py — LLM orchestrator

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

HISTORY_LIMIT = 6

# PILOT FIX: removed "no", "thanks", "thank you", "no thanks", "no thank you",
# "all good" — these caused accidental session shutdowns (pilot P2):
#   "no"    → fired when visitor said no to flyer, or naturally in speech
#   "thanks"/"thank you" → fired after every answer when visitor said thanks
# Only keep phrases that unambiguously mean "I am leaving this conversation."
SESSION_END_PHRASES = {
    "goodbye",
    "bye",
    "see you",
    "see you later",
    "that's all",
    "thats all",
    "all done",
    "i'm done",
    "im done",
}


class Orchestrator:
    def __init__(self, pepper: PepperAgent, temi: TemiAgent,
                 kb: KnowledgeBase, sessions: SessionManager):
        self._pepper   = pepper
        self._temi     = temi
        self._kb       = kb
        self._sessions = sessions
        self._history: list[dict] = []
        self._current_visitor: str | None = None
        self._listen_fn = None

        api_key = config.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")
        self._llm = OpenAI(api_key=api_key)

    def set_listen_fn(self, fn):
        self._listen_fn = fn

    # ── Public interface ───────────────────────────────────────────────────────

    def start_interaction(self, visitor_id: str):
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
        normalized = visitor_text.strip().lower()
        if normalized in SESSION_END_PHRASES:
            log.info("Visitor ended session with explicit farewell: %s", visitor_text)
            return False

        log.info("Visitor said: %s", visitor_text)

        context  = self._kb.search(visitor_text)
        messages = self._build_messages(visitor_text, context)

        # Show thinking state + brief verbal cue.
        # PILOT FIX: pilot P1 reported silence during LLM processing confused them.
        # "Let me check" confirms Pepper heard them and is working on it.
        self._pepper.set_thinking_leds()
        self._pepper.set_tablet_state("thinking")
        self._pepper.say("Let me check that for you.", animated=False)

        decision = self._call_llm(messages)
        if decision is None:
            self._pepper.say("I'm sorry, I had a technical issue. Please ask again.")
            self._pepper.set_tablet_state("listening")
            return True

        self._history.append({"role": "user",     "content": visitor_text})
        self._history.append({"role": "assistant", "content": json.dumps(decision)})
        if len(self._history) > HISTORY_LIMIT * 2:
            self._history = self._history[-(HISTORY_LIMIT * 2):]

        return self._dispatch(decision)

    def end_interaction(self):
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
        topic       = decision.get("topic", "other")
        speech      = decision.get("speech", "")
        offer_flyer = decision.get("offer_flyer", False)
        flyer_topic = decision.get("flyer_topic")
        session_end = decision.get("session_end", False)
        flyer_topics = {
            "erasmus", "partner_universities", "studying_abroad",
            "outgoing_process", "europe_partners", "non_eu_partners",
            "language_courses", "housing", "health_insurance",
        }

        if topic:
            self._pepper.set_tablet_questions_for_topic(topic)

        if self._current_visitor and topic not in ("other", "welcome", "farewell"):
            self._sessions.record_topic(self._current_visitor, topic)

        self._temi.show_topic_image(topic)

        self._pepper.set_speaking_leds()
        self._pepper.say(speech, animated=True)
        self._pepper.set_tablet_state("listening")

        if (offer_flyer or topic in flyer_topics) and (flyer_topic or topic):
            flyer_topic = flyer_topic or topic
            self._offer_flyer(flyer_topic)

        if session_end:
            return False

        return True

    def _offer_flyer(self, flyer_topic: str):
        topic_label = flyer_topic.replace("_", " ")

        if config.AUTO_ACCEPT_FLYER:
            log.info("AUTO_ACCEPT_FLYER — skipping confirmation.")
            self._deliver_and_wait(flyer_topic)
            return

        self._pepper.announce_temi_handoff(topic_label)
        self._pepper.say(
            "Would you like me to ask Temi to bring it now? "
            "Tap Yes on my screen, or say no to decline.",
            animated=True,
        )

        self._pepper.set_tablet_questions(["Yes, bring the flyer", "No, thanks"])

        answer = self._wait_for_flyer_confirmation()

        log.info("Flyer confirmation: %s", answer)

        self._pepper.set_tablet_questions_for_topic(flyer_topic)

        if answer is None:
            log.info("No answer — auto-sending Temi.")
            self._pepper.say(
                f"I'll go ahead and ask Temi to bring the {topic_label} flyer.",
                animated=True,
            )
            self._deliver_and_wait(flyer_topic)
        elif answer == "no":
            self._pepper.say(
                f"No problem! The {topic_label} flyers are on the table next to Temi."
            )
        else:
            self._deliver_and_wait(flyer_topic)

    def _deliver_and_wait(self, flyer_topic: str):
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

        log.info("Temi delivery timed out; continuing.")
        self._pepper.say(
            "Temi is on its way — feel free to continue browsing.",
            animated=False,
        )
        self._pepper.set_tablet_state("listening")

    def _wait_for_flyer_confirmation(self, timeout: int = 12) -> str | None:
        """
        Wait for yes/no from tablet buttons OR Pepper voice — tablet has priority.

        PILOT FIX: voice thread now only listens for "no" (explicit decline).
        Previously listening for both "yes" AND "no" caused P2's issue where
        "yes" was misheard as "no", blocking Temi delivery.
        Any tap on the tablet = yes. Silence = auto-send (default yes at a fair).
        Tablet thread starts 1.5s before voice so visitor can see and tap buttons.
        """
        answer = [None]
        done   = threading.Event()

        def _tablet():
            choice = self._pepper.get_tablet_input(timeout=timeout)
            if not choice or done.is_set():
                return
            normalized = choice.lower().strip()
            if "yes" in normalized or "bring" in normalized:
                answer[0] = "yes"
                done.set()
            elif "no" in normalized:
                answer[0] = "no"
                done.set()

        def _voice_no():
            # Only listen for explicit "no" — avoids "yes" being misheard as "no"
            heard = self._pepper.listen_for_speech(
                ["no", "nope", "not now"],
                timeout=timeout - 2,
            )
            if heard and not done.is_set():
                answer[0] = "no"
                done.set()

        # Tablet first — give visitor 1.5s to see the Yes/No buttons
        threading.Thread(target=_tablet, daemon=True).start()
        time.sleep(1.5)
        threading.Thread(target=_voice_no, daemon=True).start()

        done.wait(timeout=timeout + 1)
        return answer[0]