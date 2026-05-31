"""
telegram_bot.py
Телеграм-бот — оболочка над существующей логикой ассистента РЖД.

Поддерживает:
  - Текстовые сообщения
  - Голосовые сообщения (ogg → wav → Vosk)
  - Регистрацию пользователя (ФИО, телефон, паспорт, дата рождения)
    с привязкой к telegram_user_id. Повторные /start пропускают анкету.

Зависимости:
  python-telegram-bot>=21.0
  ffmpeg (системный: brew install ffmpeg / apt install ffmpeg)
"""

import json
import logging
import os
import subprocess
import tempfile

import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import MODEL_PATH as VOSK_MODEL_PATH, JAVA_BACKEND_URL, GIGACHAT_CREDENTIALS
from router import AgentRouter
from recognizer import VoskRecognizer

# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("В .env отсутствует TELEGRAM_BOT_TOKEN")

JAVA_REGISTER_URL   = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080").replace("/api/ticket/order", "") + "/api/passenger/register"
JAVA_PASSENGER_URL  = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080").replace("/api/ticket/order", "") + "/api/passenger/by-telegram"

# ---------------------------------------------------------------------------
# Шаги регистрации
# ---------------------------------------------------------------------------

class RegStep:
    FULL_NAME       = "full_name"
    PHONE           = "phone"
    PASSPORT_SERIES = "passport_series"
    PASSPORT_NUMBER = "passport_number"
    BIRTH_DATE      = "birth_date"
    DONE            = "done"

REG_STEPS_ORDER = [
    RegStep.FULL_NAME,
    RegStep.PHONE,
    RegStep.PASSPORT_SERIES,
    RegStep.PASSPORT_NUMBER,
    RegStep.BIRTH_DATE,
]

REG_PROMPTS = {
    RegStep.FULL_NAME:       "👤 Введите ваше полное имя (Фамилия Имя Отчество):",
    RegStep.PHONE:           "📞 Введите номер телефона (например, +79123456789):",
    RegStep.PASSPORT_SERIES: "🪪 Введите серию паспорта (4 цифры, например: 4510):",
    RegStep.PASSPORT_NUMBER: "🪪 Введите номер паспорта (6 цифр, например: 123456):",
    RegStep.BIRTH_DATE:      "🎂 Введите дату рождения (ДД.ММ.ГГГГ, например: 15.03.1990):",
}

# ---------------------------------------------------------------------------
# Состояние сессии
# ---------------------------------------------------------------------------

class SessionState:
    """Изолированное состояние одного пользователя."""

    def __init__(self, gigachat_credentials: str):
        self.router = AgentRouter(gigachat_credentials)

        # Регистрационные данные
        self.reg_step: str | None = None   # None = регистрация не начата / уже пройдена
        self.reg_data: dict = {}

        # Данные зарегистрированного пользователя
        self.phone: str | None = None
        self.full_name: str | None = None
        self.is_registered: bool = False

    def start_registration(self):
        self.reg_step = RegStep.FULL_NAME
        self.reg_data = {}

    def registration_in_progress(self) -> bool:
        return self.reg_step is not None and self.reg_step != RegStep.DONE

    def next_reg_prompt(self) -> str:
        return REG_PROMPTS.get(self.reg_step, "")


# Глобальный словарь сессий и распознаватель речи
_sessions: dict[int, SessionState] = {}
_recognizer: VoskRecognizer | None = None


def get_session(user_id: int) -> SessionState:
    if user_id not in _sessions:
        _sessions[user_id] = SessionState(GIGACHAT_CREDENTIALS)
    return _sessions[user_id]


# ---------------------------------------------------------------------------
# Java: проверка и регистрация пассажира
# ---------------------------------------------------------------------------

def check_registered_in_java(telegram_user_id: int) -> dict | None:
    """
    Запрашивает Java backend: зарегистрирован ли пользователь.
    Возвращает {'registered': True, 'full_name': ..., 'phone': ...} или {'registered': False}.
    При ошибке соединения возвращает None.
    """
    try:
        resp = requests.get(f"{JAVA_PASSENGER_URL}/{telegram_user_id}", timeout=10)
        return resp.json()
    except Exception as e:
        logger.error(f"Ошибка проверки регистрации: {e}")
        return None


def register_in_java(telegram_user_id: int, reg_data: dict) -> bool:
    """Отправляет данные регистрации в Java backend. Возвращает True при успехе."""
    payload = {
        "telegram_user_id": telegram_user_id,
        "full_name":        reg_data[RegStep.FULL_NAME],
        "phone":            reg_data[RegStep.PHONE],
        "passport_series":  reg_data[RegStep.PASSPORT_SERIES],
        "passport_number":  reg_data[RegStep.PASSPORT_NUMBER],
        "birth_date":       reg_data[RegStep.BIRTH_DATE],
    }
    try:
        resp = requests.post(JAVA_REGISTER_URL, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Ошибка регистрации в Java: {e}")
        return False


# ---------------------------------------------------------------------------
# Валидация полей регистрации
# ---------------------------------------------------------------------------

import re

def validate_reg_field(step: str, value: str) -> str | None:
    """Возвращает сообщение об ошибке или None если всё ок."""
    value = value.strip()
    if step == RegStep.FULL_NAME:
        parts = value.split()
        if len(parts) < 2:
            return "❌ Введите минимум фамилию и имя."
    elif step == RegStep.PHONE:
        if not (10 <= len(value) <= 15 and (value.startswith("+") or value.isdigit())):
            return "❌ Некорректный номер. Пример: +79123456789"
    elif step == RegStep.PASSPORT_SERIES:
        if not re.fullmatch(r"\d{4}", value):
            return "❌ Серия паспорта — 4 цифры. Пример: 4510"
    elif step == RegStep.PASSPORT_NUMBER:
        if not re.fullmatch(r"\d{6}", value):
            return "❌ Номер паспорта — 6 цифр. Пример: 123456"
    elif step == RegStep.BIRTH_DATE:
        if not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", value):
            return "❌ Формат даты: ДД.ММ.ГГГГ. Пример: 15.03.1990"
    return None


# ---------------------------------------------------------------------------
# Обработка шагов регистрации
# ---------------------------------------------------------------------------

async def process_registration(update: Update, text: str, session: SessionState):
    """Ведёт пользователя по анкете регистрации."""
    step = session.reg_step
    value = text.strip()

    error = validate_reg_field(step, value)
    if error:
        await update.message.reply_text(error)
        await update.message.reply_text(session.next_reg_prompt())
        return

    session.reg_data[step] = value

    # Переходим к следующему шагу
    idx = REG_STEPS_ORDER.index(step)
    if idx + 1 < len(REG_STEPS_ORDER):
        session.reg_step = REG_STEPS_ORDER[idx + 1]
        await update.message.reply_text(session.next_reg_prompt())
    else:
        # Все поля собраны — показываем подтверждение
        d = session.reg_data
        summary = (
            "📋 Проверьте введённые данные:\n\n"
            f"👤 Имя: {d[RegStep.FULL_NAME]}\n"
            f"📞 Телефон: {d[RegStep.PHONE]}\n"
            f"🪪 Паспорт: {d[RegStep.PASSPORT_SERIES]} {d[RegStep.PASSPORT_NUMBER]}\n"
            f"🎂 Дата рождения: {d[RegStep.BIRTH_DATE]}\n\n"
            "Всё верно? Ответьте *да* для сохранения или *нет* для ввода заново."
        )
        session.reg_step = "confirm"
        await update.message.reply_text(summary, parse_mode="Markdown")


async def process_reg_confirm(update: Update, text: str, session: SessionState, user_id: int):
    """Обрабатывает подтверждение или отмену регистрации."""
    answer = text.strip().lower()

    if any(w in answer for w in ["да", "yes", "верно", "ок", "окей", "давай"]):
        ok = register_in_java(user_id, session.reg_data)
        if ok:
            session.phone = session.reg_data[RegStep.PHONE]
            session.full_name = session.reg_data[RegStep.FULL_NAME]
            session.is_registered = True
            session.reg_step = RegStep.DONE
            await update.message.reply_text(
                f"✅ Регистрация прошла успешно! Добро пожаловать, {session.full_name}!\n\n"
                "Теперь я могу помочь вам купить билет или ответить на вопросы о РЖД.\n"
                "Просто напишите или скажите, что вас интересует. 🚂"
            )
        else:
            await update.message.reply_text(
                "⚠️ Не удалось сохранить данные. Проверьте, что сервер доступен, и попробуйте /start снова."
            )
            session.reg_step = None

    elif any(w in answer for w in ["нет", "no", "неверно", "заново", "исправить"]):
        session.start_registration()
        await update.message.reply_text("🔄 Начинаем заново.\n\n" + session.next_reg_prompt())
    else:
        await update.message.reply_text("Пожалуйста, ответьте «да» или «нет».")


# ---------------------------------------------------------------------------
# Распознавание голоса
# ---------------------------------------------------------------------------

def voice_to_text(ogg_bytes: bytes) -> str:
    global _recognizer
    if _recognizer is None:
        _recognizer = VoskRecognizer(VOSK_MODEL_PATH)

    with tempfile.TemporaryDirectory() as tmpdir:
        ogg_path = os.path.join(tmpdir, "voice.ogg")
        wav_path = os.path.join(tmpdir, "voice.wav")

        with open(ogg_path, "wb") as f:
            f.write(ogg_bytes)

        result = subprocess.run(
            ["ffmpeg", "-y", "-i", ogg_path, "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
            capture_output=True,
        )
        if result.returncode != 0:
            logger.error(f"ffmpeg error: {result.stderr.decode()}")
            return ""

        import vosk
        model = _recognizer.model
        rec = vosk.KaldiRecognizer(model, 16000)

        with open(wav_path, "rb") as wav_file:
            wav_file.read(44)
            while True:
                data = wav_file.read(8000)
                if not data:
                    break
                rec.AcceptWaveform(data)

        final = json.loads(rec.FinalResult())
        return final.get("text", "").strip()


# ---------------------------------------------------------------------------
# Отправка заказа в Java backend
# ---------------------------------------------------------------------------

async def send_to_java(update: Update, order_json: dict, phone: str) -> tuple[bool, list]:
    order_json["contact_phone"] = phone
    try:
        response = requests.post(JAVA_BACKEND_URL, json=order_json, timeout=15)
        data = response.json()
        status = data.get("status")

        if status == "success":
            await update.message.reply_text(
                f"✅ {data.get('message')}\n\n"
                f"🚂 Поезд: {data.get('trainNumber')}\n"
                f"🕐 Время: {data.get('departureTime')}\n"
                f"💰 Цена: {data.get('priceTotal')} руб.\n\n"
                f"Приятной поездки!"
            )
            return True, []

        elif status in ("no_seats_on_date", "no_trips"):
            await update.message.reply_text(f"😔 {data.get('message', 'Мест нет.')}")
            alternatives = data.get("alternatives", [])
            if alternatives:
                lines = ["📋 Ближайшие доступные варианты:\n"]
                for alt in alternatives[:3]:
                    lines.append(
                        f"📅 {alt['date']} в {alt['time']} — "
                        f"поезд {alt['train_number']}, "
                        f"{alt['carriage_type']}, "
                        f"мест: {alt['available_seats']}, "
                        f"цена {alt['price']} руб."
                    )
                await update.message.reply_text("\n".join(lines))
            else:
                await update.message.reply_text("Рейсов на ближайшие даты нет. Попробуйте другой маршрут.")
            return False, alternatives

        else:
            await update.message.reply_text(f"❌ Ошибка: {data.get('message', 'Неизвестная ошибка')}")
            return False, []

    except Exception as e:
        logger.error(f"Java backend error: {e}")
        await update.message.reply_text(f"⚠️ Ошибка связи с сервером: {e}")
        return False, []


# ---------------------------------------------------------------------------
# Основная логика обработки сообщения
# ---------------------------------------------------------------------------

async def process_text(update: Update, text: str, session: SessionState, user_id: int):

    # ── Регистрация: подтверждение анкеты ──────────────────────────────────
    if session.reg_step == "confirm":
        await process_reg_confirm(update, text, session, user_id)
        return

    # ── Регистрация: сбор данных ────────────────────────────────────────────
    if session.registration_in_progress():
        await process_registration(update, text, session)
        return

    # ── Пользователь не зарегистрирован (сюда попасть не должны, но на всякий случай) ──
    if not session.is_registered:
        await update.message.reply_text("Пожалуйста, начните с команды /start для регистрации.")
        return

    router = session.router

    # ── Активный диалог бронирования ────────────────────────────────────────
    if router.is_buy_active():
        buy = router.buy_agent
        error = buy.process_user_input(text)
        if error:
            await update.message.reply_text(f"⚠️ {error}")
            return

        if buy.is_done():
            order_json = buy.get_order_json()
            success, alternatives = await send_to_java(update, order_json, session.phone)
            if success:
                router.finish_buy_session()
                await update.message.reply_text("Чем ещё могу помочь? 😊")
            else:
                buy.handle_no_seats(alternatives)
                if alternatives:
                    await update.message.reply_text("Выберите одну из предложенных дат или назовите другую.")
                else:
                    await update.message.reply_text("Попробуем другую дату.")
        else:
            await update.message.reply_text(buy.get_next_question())
        return

    # ── Маршрутизация нового намерения ───────────────────────────────────────
    agent_name, response = router.route(text)

    if agent_name == "clarify":
        await update.message.reply_text(f"🤔 {response}")

    elif agent_name == "consult":
        await update.message.reply_text(response)
        await update.message.reply_text("Могу ещё чем-то помочь? 😊")

    elif agent_name == "buy":
        buy = router.buy_agent
        buy.process_user_input(text)
        await update.message.reply_text(f"🎫 Оформляем билет!\n\n{buy.get_next_question()}")


# ---------------------------------------------------------------------------
# Хэндлеры Telegram
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name = update.effective_user.first_name or "Пассажир"

    # Сбрасываем in-memory сессию
    _sessions.pop(user_id, None)
    session = get_session(user_id)

    # Проверяем, зарегистрирован ли пользователь в Java
    info = check_registered_in_java(user_id)

    if info is None:
        # Сервер недоступен — сообщаем и всё равно запускаем регистрацию
        await update.message.reply_text(
            f"👋 Здравствуйте, {name}!\n\n"
            "⚠️ Не удалось связаться с сервером. Попробуйте позже или зарегистрируйтесь сейчас.\n\n"
        )
        session.start_registration()
        await update.message.reply_text(
            "📝 Для начала работы нужно пройти быструю регистрацию.\n\n"
            + session.next_reg_prompt()
        )
        return

    if info.get("registered"):
        # Пользователь уже есть в базе — пропускаем анкету
        session.phone = info["phone"]
        session.full_name = info["full_name"]
        session.is_registered = True
        await update.message.reply_text(
            f"👋 С возвращением, {info['full_name']}! 🚂\n\n"
            "Я готов помочь. Напишите или скажите, что вас интересует.\n"
            "Например: «хочу билет» или «как вернуть билет»."
        )
    else:
        # Новый пользователь — начинаем регистрацию
        await update.message.reply_text(
            f"👋 Здравствуйте, {name}!\n\n"
            "Я — виртуальный ассистент РЖД 🚂\n\n"
            "🎫 Помогу купить билет на поезд\n"
            "📋 Отвечу на вопросы о правилах, тарифах и возврате\n"
            "🎤 Принимаю голосовые сообщения\n\n"
            "Для начала нужно пройти быструю регистрацию."
        )
        session.start_registration()
        await update.message.reply_text(session.next_reg_prompt())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Что я умею:\n\n"
        "🎫 Купить билет — напишите «хочу билет» или «еду из Москвы в Питер»\n"
        "📋 Консультация — задайте вопрос о правилах, тарифах, возврате\n"
        "🎤 Голосовые сообщения — говорите, я пойму\n\n"
        "Команды:\n"
        "/start — начать заново\n"
        "/cancel — отменить текущий заказ\n"
        "/profile — ваши данные\n"
        "/help — эта справка"
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)
    session.router.finish_buy_session()
    await update.message.reply_text("❌ Заказ отменён. Чем ещё могу помочь?")


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает данные текущего пользователя."""
    user_id = update.effective_user.id
    session = get_session(user_id)

    if not session.is_registered:
        await update.message.reply_text("Вы ещё не зарегистрированы. Используйте /start.")
        return

    info = check_registered_in_java(user_id)
    if info and info.get("registered"):
        await update.message.reply_text(
            f"👤 Ваш профиль:\n\n"
            f"Имя: {info['full_name']}\n"
            f"Телефон: {info['phone']}\n\n"
            "Для обновления данных используйте /start."
        )
    else:
        await update.message.reply_text("Не удалось получить данные. Попробуйте позже.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)
    text = update.message.text.strip()
    logger.info(f"[user={user_id}] Текст: {text}")
    await process_text(update, text, session, user_id)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)

    # Голос во время регистрации — просим писать текстом
    if session.registration_in_progress() or session.reg_step == "confirm":
        await update.message.reply_text(
            "📝 Во время регистрации, пожалуйста, вводите данные текстом."
        )
        return

    await update.message.reply_text("🎤 Распознаю голосовое сообщение...")

    voice_file = await update.message.voice.get_file()
    ogg_bytes = await voice_file.download_as_bytearray()
    text = voice_to_text(bytes(ogg_bytes))

    if not text:
        await update.message.reply_text(
            "😕 Не удалось распознать речь. Попробуйте ещё раз или напишите текстом."
        )
        return

    logger.info(f"[user={user_id}] Голос → текст: {text}")
    await update.message.reply_text(f"🗣 Вы сказали: «{text}»")
    await process_text(update, text, session, user_id)


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

def main():
    logger.info("Запуск Telegram-бота РЖД...")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("cancel",  cmd_cancel))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    logger.info("Бот запущен. Ожидаем сообщения...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()