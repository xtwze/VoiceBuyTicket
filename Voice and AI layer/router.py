"""
router.py
Роутер между двумя агентами:
  - BuyAgent     (assistant_ai.py) - бронирование билетов
  - ConsultAgent (rag_agent.py)    - консультация по правилам РЖД

Логика маршрутизации:
  1. IntentClassifier (ML-модель) определяет намерение
  2. Если уверенность >= CONFIDENCE_THRESHOLD -> к нужному агенту
  3. Если уверенность низкая -> уточняющий вопрос
  4. Если идёт активный диалог бронирования -> всегда к BuyAgent
"""

from intent_classifier import IntentClassifier
from assistant_ai import GigaChatAssistant
from rag_agent import RagConsultAgent

CONFIDENCE_THRESHOLD = 0.65


class AgentRouter:
    """
    Центральный роутер приложения.
    Хранит состояние обоих агентов и переключает между ними.
    """

    def __init__(self, gigachat_credentials: str):
        self.credentials = gigachat_credentials

        self.classifier = IntentClassifier()

        self.consult_agent = RagConsultAgent(gigachat_credentials)

        self.buy_agent = None     # создаётся при первом buy-запросе
        self._active = None       # "buy" | "consult" | None

    # ------------------------------------------------------------------

    def route(self, user_text: str) -> tuple:
        """
        Направить текст пользователя нужному агенту.
        Возвращает (agent_name: str, response: str | None).

        agent_name:
          "buy"     - передать в buy_agent (bot.py вызовет process_user_input)
          "consult" - ответ уже в response
          "clarify" - бот должен вывести response как уточняющий вопрос
        response:
          None для "buy" (bot.py управляет диалогом сам)
          строка для "consult" и "clarify"
        """
        # Если идёт незавершённый диалог бронирования - держим его
        if self._active == "buy" and self.buy_agent and not self.buy_agent.is_done():
            return "buy", None

        # Классифицируем намерение
        intent     = self.classifier.predict(user_text)
        proba      = self.classifier.predict_proba(user_text)
        confidence = proba[intent]

        if confidence < CONFIDENCE_THRESHOLD:
            return "clarify", (
                "Уточните, пожалуйста: вы хотите купить билет "
                "или у вас вопрос по правилам / тарифам РЖД?"
            )

        if intent == "buy":
            self._ensure_buy_agent()
            self._active = "buy"
            return "buy", None

        # consult
        self._active = "consult"
        answer = self.consult_agent.ask(user_text)
        return "consult", answer

    def reset_buy_agent(self):
        """Пересоздать buy_agent для новой сессии бронирования."""
        self.buy_agent = GigaChatAssistant(self.credentials)
        self._active   = "buy"

    def finish_buy_session(self):
        """Завершить сессию бронирования."""
        self._active = None

    def is_buy_active(self) -> bool:
        return (
            self._active == "buy"
            and self.buy_agent is not None
            and not self.buy_agent.is_done()
        )

    def is_buy_done(self) -> bool:
        return (
            self._active == "buy"
            and self.buy_agent is not None
            and self.buy_agent.is_done()
        )

    # ------------------------------------------------------------------

    def _ensure_buy_agent(self):
        if self.buy_agent is None or self.buy_agent.is_done():
            self.buy_agent = GigaChatAssistant(self.credentials)