# assistant_ai.py
import json
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_gigachat.chat_models import GigaChat


class GigaChatAssistant:

    SYSTEM_PROMPT = """
    Ты — вежливый голосовой ассистент для покупки железнодорожных билетов РЖД.
    Сначала спроси откуда, куда и на какую дату пользователь хочет отправиться.
    Собирай данные постепенно, задавая по одному вопросу за раз.
    Если нет мест — предложи ближайшие даты с доступными рейсами.

    Когда все данные собраны и места проверены — ответь ТОЛЬКО валидным JSON без лишнего текста.
    JSON формат:
    {
      "departure_station": "string",
      "arrival_station": "string",
      "departure_date": "YYYY-MM-DD",
      "departure_time": "HH:MM" (опционально),
      "train_number": "string" (опционально),
      "carriage_type": "Platzkart|Compartment|Luxe|SV",
      "number_of_passengers": integer (1-4),
      "passengers": [{"ticket_type": "Adult|Child|Senior|Student"}]
    }

    Будь естественным, не повторяйся.
    """

    def __init__(self, credentials: str):
        self.client = GigaChat(credentials=credentials, temperature=0.7, verify_ssl_certs=False)
        self.history = []  # Пустая история для сообщений пользователя

    def add_user_message(self, text: str):
        self.history.append(HumanMessage(content=text))

    def get_response(self) -> str:
        messages = [SystemMessage(content=self.SYSTEM_PROMPT)] + self.history
        response = self.client.invoke(messages)
        return response.content.strip()

    def is_complete_json(self, text: str) -> bool:
        try:
            data = json.loads(text)
            required = ["departure_station", "arrival_station", "departure_date", "carriage_type",
                        "number_of_passengers"]
            return all(key in data for key in required)
        except json.JSONDecodeError:
            return False

    def parse_json(self, text: str):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None