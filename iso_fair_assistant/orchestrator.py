# orchestrator.py — LLM orchestrator
#
# Takes raw visitor speech → decides what Pepper says + what Temi shows.
# Keeps the last N conversation turns so the LLM has context continuity.

import json
import logging
import os

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

        api_key = config.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")
        self._llm = OpenAI(api_key=api_key)

    # ── Public interface ───────────────────────────────────────────────────────

    def start_interaction(self, visitor_id: str):
        """Called when a new visitor is detected."""
        self._current_visitor = visitor_id
        self._history = []
        self._sessions.start_session(visitor_id)

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

        # 4. Call LLM
        decision = self._call_llm(messages)
        if decision is None:
            self._pepper.say("I'm sorry, I had a technical issue. Please ask again.")
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

        # Track topic in session
        if self._current_visitor and topic not in ("other", "welcome", "farewell"):
            self._sessions.record_topic(self._current_visitor, topic)

        # Update Temi screen to match the topic Pepper is discussing
        self._temi.show_topic_image(topic)

        # Pepper speaks
        self._pepper.set_speaking_leds()
        self._pepper.say(speech, animated=True)

        # Offer a flyer if the LLM decided one would help
        if offer_flyer and flyer_topic:
            self._offer_flyer(flyer_topic)

        # Session end?
        if session_end:
            return False

        return True

    def _offer_flyer(self, flyer_topic: str):
        """
        Ask visitor's permission, then trigger Temi if they say yes.
        Uses keyword detection on Pepper's microphone.
        """
        topic_label = flyer_topic.replace("_", " ")
        self._pepper.announce_temi_handoff(topic_label)

        answer = self._pepper.listen_for_speech(["yes", "no", "sure", "okay", "nope"])
        if answer and answer.lower() in ("yes", "sure", "okay"):
            self._temi.deliver_flyer(flyer_topic)
            self._pepper.temi_returned()
        else:
            self._pepper.say(
                f"No problem! You can find the {topic_label} flyers on the table next to Temi."
            )
