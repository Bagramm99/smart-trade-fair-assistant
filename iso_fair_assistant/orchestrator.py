# orchestrator.py — LLM orchestrator

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

HISTORY_LIMIT = 6


class Orchestrator:
    def __init__(self, pepper: PepperAgent, temi: TemiAgent,
                 kb: KnowledgeBase, sessions: SessionManager,
                 tablet_server=None):
        self._pepper   = pepper
        self._temi     = temi
        self._kb       = kb
        self._sessions = sessions
        self._tablet   = tablet_server
        self._history: list[dict] = []
        self._current_visitor: str | None = None

        api_key = config.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")
        self._llm = OpenAI(api_key=api_key)

    # kept for compatibility but no longer used
    def set_listen_fn(self, fn):
        pass

    # ── Public ────────────────────────────────────────────────────────────────

    def start_interaction(self, visitor_id: str):
        self._current_visitor = visitor_id
        self._history = []
        self._sessions.start_session(visitor_id)

        if self._sessions.is_already_helped(visitor_id):
            self._pepper.greet_returning_visitor()
        else:
            self._pepper.greet_new_visitor()

        self._temi.show_welcome()
        if self._tablet:
            self._tablet.set_questions_for_topic("welcome")

    def handle_input(self, visitor_text: str) -> bool:
        log.info("Visitor said: %s", visitor_text)

        context  = self._kb.search(visitor_text)
        messages = self._build_messages(visitor_text, context)

        self._pepper.set_thinking_leds()

        decision = self._call_llm(messages)
        if decision is None:
            self._pepper.say("I'm sorry, I had a technical issue. Please ask again.")
            return True

        self._history.append({"role": "user",      "content": visitor_text})
        self._history.append({"role": "assistant",  "content": json.dumps(decision)})
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
        if self._tablet:
            self._tablet.reset_to_default()

    # ── LLM ───────────────────────────────────────────────────────────────────

    def _build_messages(self, visitor_text: str, context: str) -> list[dict]:
        system = SYSTEM_PROMPT + f"\n\nRELEVANT CONTEXT:\n{context}"
        return [{"role": "system", "content": system},
                *self._history,
                {"role": "user", "content": visitor_text}]

    def _call_llm(self, messages: list[dict]) -> dict | None:
        try:
            resp  = self._llm.chat.completions.create(
                model=config.LLM_MODEL,
                messages=messages,
                temperature=config.LLM_TEMPERATURE,
                response_format={"type": "json_object"},
            )
            raw      = resp.choices[0].message.content
            decision = json.loads(raw)
            log.debug("LLM: %s", decision)
            return decision
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

        if self._current_visitor and topic not in ("other", "welcome", "farewell"):
            self._sessions.record_topic(self._current_visitor, topic)

        # Update Temi screen + tablet questions
        self._temi.show_topic_image(topic)
        if self._tablet:
            self._tablet.set_questions_for_topic(topic)

        self._pepper.set_speaking_leds()
        self._pepper.say(speech, animated=True)

        # ── Flyer delivery — NO confirmation step ─────────────────────────────
        # Removed the "Would you like Temi to bring it?" step entirely.
        # Reasons:
        #   1. Speed: confirmation added 5+ seconds of blocking wait
        #   2. Reliability: the wait blocked touch input (bug 2 & 3)
        #   3. UX: at a fair nobody refuses a flyer; the delay felt awkward
        # Pepper's speech already introduces Temi, so the handoff is clear.
        if offer_flyer and flyer_topic:
            topic_label = flyer_topic.replace("_", " ")
            self._pepper.say(
                f"My colleague Temi will bring you the {topic_label} flyer now.",
                animated=True,
            )
            self._temi.deliver_flyer(flyer_topic)

        if session_end:
            return False
        return True