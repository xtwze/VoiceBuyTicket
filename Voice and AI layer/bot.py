# bot.py
import json
import requests

from assistant_ai import GigaChatAssistant
from recognizer import VoskRecognizer

class VoiceTicketBot:
    def __init__(self, model_path: str, java_url: str, gigachat_credentials: str):
        self.recognizer = VoskRecognizer(model_path)
        self.assistant_ai = GigaChatAssistant(gigachat_credentials)
        self.java_url = java_url

    def bot_say(self, text: str):
        print(f"\n[Бот]: {text}\n")

    def send_to_java(self, order_json: dict, phone: str):
        order_json["contact_phone"] = phone
        try:
            print("\n[Отправляем заказ в Java backend...]")
            print(json.dumps(order_json, indent=2, ensure_ascii=False))

            response = requests.post(self.java_url, json=order_json, timeout=15)
            data = response.json()

            if response.status_code != 200:
                self.bot_say(f"Ошибка сервера: {data.get('message', 'Неизвестная ошибка')}")
                return False  # Не оформлено

            status = data.get("status")
            msg = data.get("message", "")

            if status == "success":
                self.bot_say(
                    f"{msg}\n"
                    f"Поезд: {data.get('train_number')}\n"
                    f"Время: {data.get('departure_time')}\n"
                    f"Цена: {data.get('price_total')} руб.\n"
                    f"Приятной поездки!"
                )
                return True  # Оформлено

            elif status in ["no_seats_on_date", "no_trips"]:
                self.bot_say(msg)
                alternatives = data.get("alternatives", [])
                if alternatives:
                    self.bot_say("Ближайшие доступные варианты:")
                    for alt in alternatives[:3]:  # Ограничим 3
                        self.bot_say(
                            f"{alt['date']} в {alt['time']}, "
                            f"поезд {alt['train_number']}, "
                            f"{alt['carriage_type']}, мест: {alt['available_seats']}, цена {alt['price']} руб."
                        )
                    self.bot_say("Какой вариант выбираете, или уточните дату?")
                else:
                    self.bot_say("Попробуйте другие даты.")
                return False  # Продолжаем диалог

            else:
                self.bot_say(f"Неизвестный ответ: {msg}")
                return False

        except Exception as e:
            self.bot_say(f"Ошибка связи: {e}")
            return False

    def run(self):
        self.bot_say("Здравствуйте! Это голосовой сервис покупки билетов РЖД.")

        is_avaible_phone = False
        while is_avaible_phone == False:
            phone = input("Введите номер телефона пользователя (например, +79123456789): ").strip()
            if len(phone) >= 15:
                phone = input("Номер телефона некоректен. Введите ещё раз (например, +79123456789): ").strip()
                is_avaible_phone = False
            else:
                is_avaible_phone = True


        self.assistant_ai.add_user_message(
            f"Начни диалог с вопроса: откуда, куда и на какую дату хочет отправиться пользователь."
        )

        self.bot_say("Диалог начат. Говорите в микрофон.")

        while True:
            ai_response = self.assistant_ai.get_response()
            self.bot_say(ai_response)

            if self.assistant_ai.is_complete_json(ai_response):
                order_json = self.assistant_ai.parse_json(ai_response)
                if order_json:
                    if self.send_to_java(order_json, phone):
                        break  # Заказ оформлен — конец
                    # Если мест нет — продолжаем диалог
            else:
                user_text = self.recognizer.listen()
                if not user_text:
                    self.bot_say("Не расслышал. Повторите.")
                    continue
                self.assistant_ai.add_user_message(user_text)