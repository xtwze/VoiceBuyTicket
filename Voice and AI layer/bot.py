"""
bot.py
Главный управляющий класс бота.
Интегрирует:
  - AgentRouter (маршрутизация между агентами)
  - VoskRecognizer (распознавание речи)
  - Java backend (оформление заказа)
"""

import json
import requests

from router import AgentRouter
from recognizer import VoskRecognizer


class VoiceTicketBot:

    def __init__(self, model_path: str, java_url: str, gigachat_credentials: str):
        self.recognizer = VoskRecognizer(model_path)
        self.router     = AgentRouter(gigachat_credentials)
        self.java_url   = java_url
        self.credentials = gigachat_credentials

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def bot_say(self, text: str):
        print(f"\n[Бот]: {text}\n")

    def listen(self) -> str:
        text = self.recognizer.listen()
        if not text:
            self.bot_say("Не расслышал. Повторите, пожалуйста.")
        return text

    # ------------------------------------------------------------------
    # Java backend
    # ------------------------------------------------------------------

    def send_to_java(self, order_json: dict, phone: str) -> tuple:
        """
        Отправить заказ в Java backend.
        Возвращает (success: bool, alternatives: list).
        """
        order_json["contact_phone"] = phone
        try:
            print("\n[Отправляем заказ в Java backend...]")
            print(json.dumps(order_json, indent=2, ensure_ascii=False))

            response = requests.post(self.java_url, json=order_json, timeout=15)
            print(f"[HTTP {response.status_code}]: {response.text}")
            data = response.json()

            status = data.get("status")

            if status == "success":
                self.bot_say(
                    f"{data.get('message')}\n"
                    f"Поезд: {data.get('trainNumber')}\n"
                    f"Время: {data.get('departureTime')}\n"
                    f"Цена:  {data.get('priceTotal')} руб.\n"
                    f"Приятной поездки!"
                )
                return True, []

            elif status in ("no_seats_on_date", "no_trips"):
                self.bot_say(data.get("message", "Мест нет."))
                alternatives = data.get("alternatives", [])
                if alternatives:
                    self.bot_say("Ближайшие доступные варианты:")
                    for alt in alternatives[:3]:
                        self.bot_say(
                            f"  {alt['date']} в {alt['time']} — "
                            f"поезд {alt['train_number']}, "
                            f"{alt['carriage_type']}, "
                            f"мест: {alt['available_seats']}, "
                            f"цена {alt['price']} руб."
                        )
                else:
                    self.bot_say("Рейсов на ближайшие даты нет. Попробуйте другой маршрут.")
                return False, alternatives

            else:
                self.bot_say(f"Ошибка: {data.get('message', 'Неизвестная ошибка')}")
                return False, []

        except Exception as e:
            self.bot_say(f"Ошибка связи с сервером: {e}")
            return False, []

    # ------------------------------------------------------------------
    # Главный цикл
    # ------------------------------------------------------------------

    def run(self):
        self.bot_say(
            "Здравствуйте! Это голосовой ассистент РЖД.\n"
            "Я могу помочь купить билет или ответить на вопросы\n"
            "о правилах перевозок, тарифах и возврате."
        )

        phone = self._ask_phone()
        self.bot_say("Отлично! Говорите — я слушаю.")

        while True:
            # ---- Если идёт активный диалог бронирования ----
            if self.router.is_buy_active():
                buy = self.router.buy_agent
                question = buy.get_next_question()
                self.bot_say(question)

                user_text = self.listen()
                if not user_text:
                    continue

                error = buy.process_user_input(user_text)
                if error:
                    self.bot_say(error)
                    continue

                # Подтверждение получено — отправляем
                if buy.is_done():
                    order_json = buy.get_order_json()
                    success, alternatives = self.send_to_java(order_json, phone)

                    if success:
                        self.router.finish_buy_session()
                        self.bot_say("Чем ещё могу помочь?")
                    else:
                        # Нет мест — сбрасываем только дату, продолжаем
                        buy.handle_no_seats(alternatives)
                        if alternatives:
                            self.bot_say("Выберите одну из предложенных дат или назовите другую.")
                        else:
                            self.bot_say("Попробуем другую дату.")
                continue

            # ---- Ожидаем новое намерение от пользователя ----
            user_text = self.listen()
            if not user_text:
                continue

            agent_name, response = self.router.route(user_text)

            if agent_name == "clarify":
                self.bot_say(response)

            elif agent_name == "consult":
                self.bot_say(response)
                self.bot_say("Могу ещё чем-то помочь?")

            elif agent_name == "buy":
                # Роутер создал buy_agent — начинаем диалог бронирования
                # Передаём первое сообщение пользователя в агент
                buy = self.router.buy_agent
                error = buy.process_user_input(user_text)
                if error:
                    # Если первая фраза не содержит нужных данных — просто начинаем диалог
                    pass
                # Следующая итерация цикла подхватит is_buy_active() == True

    # ------------------------------------------------------------------

    def _ask_phone(self) -> str:
        while True:
            phone = input("Введите номер телефона (например, +79123456789): ").strip()
            if 10 <= len(phone) <= 15 and (phone.startswith("+") or phone.isdigit()):
                return phone
            print("Некорректный номер. Попробуйте снова.")
