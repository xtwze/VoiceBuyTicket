import json
import re
from enum import Enum, auto
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_gigachat.chat_models import GigaChat


class DialogState(Enum):
    ASK_DEPARTURE    = auto()
    ASK_ARRIVAL      = auto()
    ASK_DATE         = auto()
    ASK_CARRIAGE     = auto()
    ASK_PASSENGERS   = auto()
    ASK_TICKET_TYPES = auto()
    CONFIRM          = auto()
    DONE             = auto()


CARRIAGE_ALIASES = {
    "плацкарт": "Platzkart",
    "platzkart": "Platzkart",
    "купе": "Compartment",
    "compartment": "Compartment",
    "люкс": "Luxe",
    "luxe": "Luxe",
    "lux": "Luxe",
    "св": "SV",
    "sv": "SV",
    "спальный": "SV",
}

TICKET_ALIASES = {
    "взрослый": "Adult",
    "взрослых": "Adult",
    "adult": "Adult",
    "детский": "Child",
    "ребёнок": "Child",
    "ребенок": "Child",
    "дети": "Child",
    "child": "Child",
    "пенсионер": "Senior",
    "пенсионный": "Senior",
    "senior": "Senior",
    "студент": "Student",
    "студенческий": "Student",
    "student": "Student",
}

# Вопросы для каждого шага — задаёт бот напрямую, без LLM
STATE_QUESTIONS = {
    DialogState.ASK_DEPARTURE:    "Откуда вы хотите отправиться?",
    DialogState.ASK_ARRIVAL:      "Куда едете?",
    DialogState.ASK_DATE:         "На какую дату? (например, 1 июня или 2026-06-01)",
    DialogState.ASK_CARRIAGE:     "Какой тип вагона? (Плацкарт, Купе, Люкс, СВ)",
    DialogState.ASK_PASSENGERS:   "Сколько пассажиров? (от 1 до 4)",
}


class GigaChatAssistant:

    # LLM используется только для двух задач:
    # 1. Извлечь сущность из произвольного ответа пользователя
    # 2. Сформировать подтверждение перед финальной отправкой
    EXTRACT_PROMPT = """Ты — парсер данных. Извлеки из фразы пользователя нужное значение.
Отвечай ТОЛЬКО запрошенным значением без пояснений.
Если не можешь извлечь — ответь словом: НЕТ"""

    def __init__(self, credentials: str):
        self.client = GigaChat(credentials=credentials, temperature=0.2, verify_ssl_certs=False)
        self.state   = DialogState.ASK_DEPARTURE
        self.data    = {}   # собранные поля
        self._ticket_index = 0  # счётчик при сборе типов билетов

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def get_next_question(self) -> str:
        """Возвращает следующий вопрос боту (детерминировано, без LLM)."""
        if self.state == DialogState.ASK_TICKET_TYPES:
            idx = self._ticket_index
            total = self.data.get("number_of_passengers", 1)
            return f"Пассажир {idx + 1} из {total} — тип билета? (Взрослый, Детский, Пенсионер, Студент)"
        if self.state == DialogState.CONFIRM:
            return self._build_confirmation()
        return STATE_QUESTIONS.get(self.state, "")

    def process_user_input(self, text: str) -> str | None:
        """
        Обрабатывает ответ пользователя для текущего шага.
        Возвращает сообщение об ошибке (если ввод невалиден) или None (если всё ок).
        """
        text = text.strip()

        if self.state == DialogState.ASK_DEPARTURE:
            station = self._extract(text, "название города/станции отправления")
            if not station or station == "НЕТ":
                return "Не распознал город. Повторите, пожалуйста."
            self.data["departure_station"] = station
            self.state = DialogState.ASK_ARRIVAL

        elif self.state == DialogState.ASK_ARRIVAL:
            station = self._extract(text, "название города/станции назначения")
            if not station or station == "НЕТ":
                return "Не распознал город назначения. Повторите."
            if station.lower() == self.data.get("departure_station", "").lower():
                return "Станция назначения совпадает с отправлением. Укажите другую."
            self.data["arrival_station"] = station
            self.state = DialogState.ASK_DATE

        elif self.state == DialogState.ASK_DATE:
            date = self._extract(text, "дата в формате YYYY-MM-DD. Текущий год 2026.")
            if not date or date == "НЕТ" or not re.match(r"\d{4}-\d{2}-\d{2}", date):
                return "Не распознал дату. Скажите, например: первое июня или 2026-06-01."
            self.data["departure_date"] = date
            self.state = DialogState.ASK_CARRIAGE

        elif self.state == DialogState.ASK_CARRIAGE:
            carriage = self._normalize_carriage(text)
            if not carriage:
                return "Не распознал тип вагона. Доступны: Плацкарт, Купе, Люкс, СВ."
            self.data["carriage_type"] = carriage
            self.state = DialogState.ASK_PASSENGERS

        elif self.state == DialogState.ASK_PASSENGERS:
            count = self._extract_number(text)
            if count is None or not (1 <= count <= 4):
                return "Укажите число пассажиров от 1 до 4."
            self.data["number_of_passengers"] = count
            self.data["passengers"] = []
            self._ticket_index = 0
            self.state = DialogState.ASK_TICKET_TYPES

        elif self.state == DialogState.ASK_TICKET_TYPES:
            ticket = self._normalize_ticket_type(text)
            if not ticket:
                return "Не распознал тип. Доступны: Взрослый, Детский, Пенсионер, Студент."
            self.data["passengers"].append({"ticket_type": ticket})
            self._ticket_index += 1
            if self._ticket_index >= self.data["number_of_passengers"]:
                self.state = DialogState.CONFIRM

        elif self.state == DialogState.CONFIRM:
            answer = text.lower()
            if any(w in answer for w in ["да", "верно", "подтверждаю", "yes", "ок", "окей", "давай"]):
                self.state = DialogState.DONE
            elif any(w in answer for w in ["нет", "неверно", "исправь", "сначала", "заново", "no"]):
                self._reset()
                return "Хорошо, начнём заново."
            else:
                return "Пожалуйста, ответьте «да» для подтверждения или «нет» для исправления."

        return None  # всё прошло успешно

    def is_done(self) -> bool:
        return self.state == DialogState.DONE

    def get_order_json(self) -> dict:
        """Возвращает готовый словарь для отправки в Java backend."""
        return {
            "departure_station":    self.data["departure_station"],
            "arrival_station":      self.data["arrival_station"],
            "departure_date":       self.data["departure_date"],
            "carriage_type":        self.data["carriage_type"],
            "number_of_passengers": self.data["number_of_passengers"],
            "passengers":           self.data["passengers"],
        }

    def handle_no_seats(self, alternatives: list):
        """
        Вызывается из бота когда сервер вернул no_seats.
        Сбрасываем только дату — остальные данные сохраняем.
        """
        self.data.pop("departure_date", None)
        self.state = DialogState.ASK_DATE

    # ------------------------------------------------------------------
    # Приватные вспомогательные методы
    # ------------------------------------------------------------------

    def _extract(self, user_text: str, what_to_extract: str) -> str:
        """Просит LLM извлечь конкретную сущность из свободного текста."""
        messages = [
            SystemMessage(content=self.EXTRACT_PROMPT),
            HumanMessage(content=f"Извлеки: {what_to_extract}\nФраза пользователя: «{user_text}»"),
        ]
        response = self.client.invoke(messages)
        return response.content.strip()

    def _extract_number(self, text: str) -> int | None:
        """Достаёт первое число из строки (включая слова: один, два, ...)."""
        words = {
            "один": 1, "одного": 1, "одну": 1,
            "два": 2, "двух": 2, "двое": 2,
            "три": 3, "трёх": 3, "троих": 3,
            "четыре": 4, "четырёх": 4, "четверо": 4,
        }
        lower = text.lower()
        for word, num in words.items():
            if word in lower:
                return num
        match = re.search(r"\d+", text)
        return int(match.group()) if match else None

    def _normalize_carriage(self, text: str) -> str | None:
        lower = text.lower()
        for alias, canonical in CARRIAGE_ALIASES.items():
            if alias in lower:
                return canonical
        return None

    def _normalize_ticket_type(self, text: str) -> str | None:
        lower = text.lower()
        for alias, canonical in TICKET_ALIASES.items():
            if alias in lower:
                return canonical
        return None

    def _build_confirmation(self) -> str:
        d = self.data
        passengers_str = ", ".join(
            TICKET_ALIASES.get(p["ticket_type"].lower(), p["ticket_type"])
            for p in d.get("passengers", [])
        )
        return (
            f"Проверьте заказ:\n"
            f"  Откуда: {d.get('departure_station')}\n"
            f"  Куда:   {d.get('arrival_station')}\n"
            f"  Дата:   {d.get('departure_date')}\n"
            f"  Вагон:  {d.get('carriage_type')}\n"
            f"  Пассажиров: {d.get('number_of_passengers')} ({passengers_str})\n"
            f"Всё верно? (да / нет)"
        )

    def _reset(self):
        self.state = DialogState.ASK_DEPARTURE
        self.data  = {}
        self._ticket_index = 0