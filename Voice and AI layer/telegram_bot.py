"""
telegram_bot.py
Телеграм-бот — оболочка над существующей логикой ассистента РЖД.

Поддерживает:
  - Текстовые сообщения
  - Голосовые сообщения (ogg → wav → Vosk)
  - Регистрацию пользователя (ФИО, телефон, паспорт, дата рождения)
    с привязкой к telegram_user_id. Повторные /start пропускают анкету.
  - Inline-кнопки для ключевых действий

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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    Application,
    CallbackQueryHandler,
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

JAVA_REGISTER_URL  = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080").replace("/api/ticket/order", "") + "/api/passenger/register"
JAVA_PASSENGER_URL = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080").replace("/api/ticket/order", "") + "/api/passenger/by-telegram"
JAVA_TRIPS_URL     = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080").replace("/api/ticket/order", "") + "/api/trips"

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
# Inline-клавиатуры
# ---------------------------------------------------------------------------

def kb_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎫 Купить билет",     callback_data="action:buy"),
            InlineKeyboardButton("❓ Задать вопрос",    callback_data="action:consult"),
        ],
        [
            InlineKeyboardButton("📋 Доступные рейсы", callback_data="action:trips"),
            InlineKeyboardButton("👤 Мой профиль",      callback_data="action:profile"),
        ],
    ])

def kb_reg_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Всё верно",     callback_data="reg:confirm"),
            InlineKeyboardButton("🔄 Ввести заново", callback_data="reg:restart"),
        ]
    ])

def kb_no_seats(alternatives: list) -> InlineKeyboardMarkup:
    buttons = []
    for alt in alternatives[:3]:
        ct = alt.get("carriageType") or alt.get("carriage_type", "")
        label = f"📅 {alt.get('date')} {str(alt.get('time',''))[:5]} · {ct} · {int(alt.get('price', 0))} ₽"
        buttons.append([InlineKeyboardButton(label, callback_data=f"alt_date:{alt.get('date')}")])
    buttons.append([InlineKeyboardButton("❌ Отменить заказ", callback_data="action:cancel")])
    return InlineKeyboardMarkup(buttons)

def kb_order_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Подтвердить",   callback_data="buy:yes"),
            InlineKeyboardButton("❌ Начать заново", callback_data="buy:no"),
        ]
    ])

def kb_cancel_buy() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отменить заказ", callback_data="action:cancel")]
    ])

# ---------------------------------------------------------------------------
# Состояние сессии
# ---------------------------------------------------------------------------

class SessionState:
    def __init__(self, gigachat_credentials: str):
        self.router = AgentRouter(gigachat_credentials)
        self.reg_step: str | None = None
        self.reg_data: dict = {}
        self.phone: str | None = None
        self.full_name: str | None = None
        self.is_registered: bool = False
        self.last_alternatives: list = []
        # Флаг: ожидаем текстового «да/нет» для подтверждения заказа
        self.awaiting_order_confirm: bool = False

    def start_registration(self):
        self.reg_step = RegStep.FULL_NAME
        self.reg_data = {}

    def registration_in_progress(self) -> bool:
        return self.reg_step is not None and self.reg_step != RegStep.DONE

    def next_reg_prompt(self) -> str:
        return REG_PROMPTS.get(self.reg_step, "")


_sessions: dict[int, SessionState] = {}
_recognizer: VoskRecognizer | None = None


def get_session(user_id: int) -> SessionState:
    if user_id not in _sessions:
        _sessions[user_id] = SessionState(GIGACHAT_CREDENTIALS)
    return _sessions[user_id]


# ---------------------------------------------------------------------------
# Java helpers
# ---------------------------------------------------------------------------

def check_registered_in_java(telegram_user_id: int) -> dict | None:
    try:
        resp = requests.get(f"{JAVA_PASSENGER_URL}/{telegram_user_id}", timeout=10)
        return resp.json()
    except Exception as e:
        logger.error(f"Ошибка проверки регистрации: {e}")
        return None


def register_in_java(telegram_user_id: int, reg_data: dict) -> bool:
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
# send_to_java — принимает telegram.Message напрямую, не Update
# Это ключевое исправление: callback_query не имеет update.message
# ---------------------------------------------------------------------------

async def send_to_java(message: Message, order_json: dict, phone: str, session: SessionState) -> tuple[bool, list]:
    """
    Отправляет заказ в Java backend.
    Принимает объект Message (не Update), чтобы работать и из handle_callback,
    и из process_text — в обоих случаях мы всегда можем получить Message.
    """
    order_json["contact_phone"] = phone
    try:
        response = requests.post(JAVA_BACKEND_URL, json=order_json, timeout=15)
        data = response.json()
        status = data.get("status")

        if status == "success":
            await message.reply_text(
                f"✅ {data.get('message')}\n\n"
                f"🚂 Поезд: {data.get('trainNumber')}\n"
                f"🕐 Время: {data.get('departureTime')}\n"
                f"💰 Цена: {data.get('priceTotal')} руб.\n\n"
                "Приятной поездки!",
                reply_markup=kb_main_menu(),
            )
            return True, []

        elif status in ("no_seats_on_date", "no_trips"):
            alternatives = data.get("alternatives", [])
            session.last_alternatives = alternatives

            await message.reply_text(f"😔 {data.get('message', 'Мест нет.')}")
            if alternatives:
                lines = ["📋 Ближайшие доступные варианты:\n"]
                for alt in alternatives[:3]:
                    lines.append(
                        f"📅 {alt['date']} в {alt['time']} — "
                        f"поезд {alt.get('trainNumber', alt.get('train_number', ''))}, "
                        f"{alt.get('carriageType', alt.get('carriage_type', ''))}, "
                        f"мест: {alt.get('availableSeats', alt.get('available_seats', ''))}, "
                        f"цена {alt['price']} руб."
                    )
                await message.reply_text("\n".join(lines), reply_markup=kb_no_seats(alternatives))
            else:
                await message.reply_text(
                    "Рейсов на ближайшие даты нет. Попробуйте другой маршрут.",
                    reply_markup=kb_main_menu(),
                )
            return False, alternatives

        else:
            await message.reply_text(
                f"❌ Ошибка: {data.get('message', 'Неизвестная ошибка')}",
                reply_markup=kb_main_menu(),
            )
            return False, []

    except Exception as e:
        logger.error(f"Java backend error: {e}")
        await message.reply_text(
            f"⚠️ Ошибка связи с сервером: {e}",
            reply_markup=kb_main_menu(),
        )
        return False, []


async def show_available_trips(message: Message):
    try:
        resp = requests.get(JAVA_TRIPS_URL, timeout=10)
        trips = resp.json()
        # resp.json() может вернуть список словарей или строку при ошибке
        if not isinstance(trips, list):
            await message.reply_text("⚠️ Не удалось получить список рейсов (неожиданный ответ сервера).")
            return
        if not trips:
            await message.reply_text("📭 Доступных рейсов пока нет.")
            return

        lines = ["🚂 *Доступные рейсы для тестирования:*\n"]
        for t in trips:
            if not isinstance(t, dict):
                continue
            lines.append(
                f"• *{t.get('departureStation')} → {t.get('arrivalStation')}*\n"
                f"  📅 {t.get('departureDate')}  🕐 {t.get('departureTime')}\n"
                f"  🚃 {t.get('carriageType')}  |  🪑 мест: {t.get('availableSeats')}  |  💰 {t.get('price')} ₽\n"
                f"  🔢 Поезд: {t.get('trainNumber')}\n"
            )
        await message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка получения рейсов: {e}")
        await message.reply_text("⚠️ Не удалось получить список рейсов. Проверьте, что Java-сервер запущен.")


# ---------------------------------------------------------------------------
# Валидация полей регистрации
# ---------------------------------------------------------------------------

import re

def validate_reg_field(step: str, value: str) -> str | None:
    value = value.strip()
    if step == RegStep.FULL_NAME:
        if len(value.split()) < 2:
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


async def process_registration(update: Update, text: str, session: SessionState):
    step  = session.reg_step
    value = text.strip()
    error = validate_reg_field(step, value)
    if error:
        await update.message.reply_text(error)
        await update.message.reply_text(session.next_reg_prompt())
        return

    session.reg_data[step] = value
    idx = REG_STEPS_ORDER.index(step)
    if idx + 1 < len(REG_STEPS_ORDER):
        session.reg_step = REG_STEPS_ORDER[idx + 1]
        await update.message.reply_text(session.next_reg_prompt())
    else:
        d = session.reg_data
        summary = (
            "📋 Проверьте введённые данные:\n\n"
            f"👤 Имя: {d[RegStep.FULL_NAME]}\n"
            f"📞 Телефон: {d[RegStep.PHONE]}\n"
            f"🪪 Паспорт: {d[RegStep.PASSPORT_SERIES]} {d[RegStep.PASSPORT_NUMBER]}\n"
            f"🎂 Дата рождения: {d[RegStep.BIRTH_DATE]}\n\n"
            "Всё верно?"
        )
        session.reg_step = "confirm"
        await update.message.reply_text(summary, reply_markup=kb_reg_confirm())


async def process_reg_confirm(update: Update, text: str, session: SessionState, user_id: int):
    answer = text.strip().lower()
    if any(w in answer for w in ["да", "yes", "верно", "ок", "окей", "давай"]):
        await _finalize_registration(update.message, session, user_id)
    elif any(w in answer for w in ["нет", "no", "неверно", "заново", "исправить"]):
        session.start_registration()
        await update.message.reply_text("🔄 Начинаем заново.\n\n" + session.next_reg_prompt())
    else:
        await update.message.reply_text(
            "Пожалуйста, используйте кнопки или ответьте «да» / «нет».",
            reply_markup=kb_reg_confirm(),
        )


async def _finalize_registration(message: Message, session: SessionState, user_id: int):
    ok = register_in_java(user_id, session.reg_data)
    if ok:
        session.phone      = session.reg_data[RegStep.PHONE]
        session.full_name  = session.reg_data[RegStep.FULL_NAME]
        session.is_registered = True
        session.reg_step   = RegStep.DONE
        await message.reply_text(
            f"✅ Регистрация прошла успешно! Добро пожаловать, {session.full_name}!\n\n"
            "Выберите действие или просто напишите / скажите, что вас интересует. 🚂",
            reply_markup=kb_main_menu(),
        )
    else:
        await message.reply_text(
            "⚠️ Не удалось сохранить данные. Проверьте, что сервер доступен, и попробуйте /start снова."
        )
        session.reg_step = None


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
        rec = vosk.KaldiRecognizer(_recognizer.model, 16000)
        with open(wav_path, "rb") as wav_file:
            wav_file.read(44)
            while True:
                data = wav_file.read(8000)
                if not data:
                    break
                rec.AcceptWaveform(data)
        return json.loads(rec.FinalResult()).get("text", "").strip()


# ---------------------------------------------------------------------------
# Вспомогательный метод: отправить следующий вопрос бота покупки билета
# ---------------------------------------------------------------------------

async def _send_buy_question(message: Message, buy):
    """Отправляет следующий вопрос диалога покупки с нужной клавиатурой."""
    next_q = buy.get_next_question()
    if "Проверьте заказ" in next_q or "Всё верно?" in next_q:
        await message.reply_text(next_q, reply_markup=kb_order_confirm())
    else:
        await message.reply_text(next_q, reply_markup=kb_cancel_buy())


# ---------------------------------------------------------------------------
# Основная логика обработки текстового сообщения
# ---------------------------------------------------------------------------

async def process_text(update: Update, text: str, session: SessionState, user_id: int):
    msg = update.message

    # ── Регистрация: подтверждение анкеты ──────────────────────────────────
    if session.reg_step == "confirm":
        await process_reg_confirm(update, text, session, user_id)
        return

    # ── Регистрация: сбор данных ────────────────────────────────────────────
    if session.registration_in_progress():
        await process_registration(update, text, session)
        return

    if not session.is_registered:
        await msg.reply_text("Пожалуйста, начните с команды /start для регистрации.")
        return

    router = session.router

    # ── Ожидаем текстовое подтверждение заказа (fallback для buy:yes/no) ───
    # Это нужно, если пользователь написал "да"/"нет" вместо нажатия кнопки
    if session.awaiting_order_confirm:
        answer = text.lower().strip()
        if any(w in answer for w in ["да", "yes", "верно", "ок", "окей", "давай", "подтверждаю"]):
            session.awaiting_order_confirm = False
            buy = router.buy_agent
            # Сбрасываем состояние агента чтобы is_done() не мешал
            buy.state = buy.state.__class__.DONE  # уже DONE — идём в отправку
            order_json = buy.get_order_json()
            success, alternatives = await send_to_java(msg, order_json, session.phone, session)
            if success:
                router.finish_buy_session()
                await msg.reply_text("Чем ещё могу помочь? 😊", reply_markup=kb_main_menu())
            else:
                buy.handle_no_seats(alternatives)
                if not alternatives:
                    await msg.reply_text("Попробуем другую дату.", reply_markup=kb_cancel_buy())
        elif any(w in answer for w in ["нет", "no", "неверно", "исправь", "сначала", "заново"]):
            session.awaiting_order_confirm = False
            router.finish_buy_session()
            await msg.reply_text("🔄 Заказ отменён. Начнём заново?", reply_markup=kb_main_menu())
        else:
            await msg.reply_text(
                "Пожалуйста, нажмите кнопку или ответьте «да» / «нет».",
                reply_markup=kb_order_confirm(),
            )
        return

    # ── Активный диалог бронирования ────────────────────────────────────────
    if router.is_buy_active():
        buy = router.buy_agent
        error = buy.process_user_input(text)
        if error:
            await msg.reply_text(f"⚠️ {error}", reply_markup=kb_cancel_buy())
            return

        if buy.is_done():
            # Агент перешёл в DONE — это значит пользователь подтвердил "да"
            order_json = buy.get_order_json()
            success, alternatives = await send_to_java(msg, order_json, session.phone, session)
            if success:
                router.finish_buy_session()
                await msg.reply_text("Чем ещё могу помочь? 😊", reply_markup=kb_main_menu())
            else:
                buy.handle_no_seats(alternatives)
                if not alternatives:
                    await msg.reply_text("Попробуем другую дату.", reply_markup=kb_cancel_buy())
        else:
            next_q = buy.get_next_question()
            # Показываем шаг подтверждения — кнопки да/нет
            if "Проверьте заказ" in next_q or "Всё верно?" in next_q:
                session.awaiting_order_confirm = True
                await msg.reply_text(next_q, reply_markup=kb_order_confirm())
            else:
                await msg.reply_text(next_q, reply_markup=kb_cancel_buy())
        return

    # ── Маршрутизация нового намерения ───────────────────────────────────────
    agent_name, response = router.route(text)

    if agent_name == "clarify":
        await msg.reply_text(
            f"🤔 {response}",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎫 Купить билет",  callback_data="action:buy"),
                    InlineKeyboardButton("❓ Задать вопрос", callback_data="action:consult"),
                ]
            ]),
        )

    elif agent_name == "consult":
        await msg.reply_text(response)
        await msg.reply_text("Могу ещё чем-то помочь? 😊", reply_markup=kb_main_menu())

    elif agent_name == "buy":
        buy = router.buy_agent
        buy.process_user_input(text)
        await _send_buy_question(msg, buy)


# ---------------------------------------------------------------------------
# Хэндлер inline-кнопок (CallbackQuery)
# ---------------------------------------------------------------------------

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    session = get_session(user_id)
    data    = query.data

    # Все ответы через query.message — это единственный способ ответить
    # из callback, у него всегда есть reply_text
    msg: Message = query.message

    # ── Подтверждение / перезапуск регистрации ──────────────────────────────
    if data == "reg:confirm":
        await _finalize_registration(msg, session, user_id)
        return

    if data == "reg:restart":
        session.start_registration()
        await msg.reply_text("🔄 Начинаем заново.\n\n" + session.next_reg_prompt())
        return

    # ── Подтверждение финального заказа кнопкой ─────────────────────────────
    if data == "buy:yes":
        session.awaiting_order_confirm = False
        if session.router.buy_agent is not None:
            buy = session.router.buy_agent
            # Принудительно переводим агента в DONE
            from assistant_ai import DialogState
            buy.state = DialogState.DONE
            order_json = buy.get_order_json()
            success, alternatives = await send_to_java(msg, order_json, session.phone, session)
            if success:
                session.router.finish_buy_session()
                await msg.reply_text("Чем ещё могу помочь? 😊", reply_markup=kb_main_menu())
            else:
                buy.handle_no_seats(alternatives)
                if not alternatives:
                    await msg.reply_text("Попробуем другую дату.", reply_markup=kb_cancel_buy())
        return

    if data == "buy:no":
        session.awaiting_order_confirm = False
        session.router.finish_buy_session()
        await msg.reply_text("🔄 Заказ отменён. Начнём заново?", reply_markup=kb_main_menu())
        return

    # ── Выбор альтернативной даты ───────────────────────────────────────────
    if data.startswith("alt_date:"):
        chosen_date = data.split(":", 1)[1]
        if session.router.buy_agent is not None:
            buy   = session.router.buy_agent
            error = buy.process_user_input(chosen_date)
            if error:
                await msg.reply_text(f"⚠️ {error}")
            else:
                await _send_buy_question(msg, buy)
        return

    # ── Главное меню — Купить билет ──────────────────────────────────────────
    if data == "action:buy":
        session.awaiting_order_confirm = False
        session.router.finish_buy_session()
        session.router._ensure_buy_agent()
        session.router._active = "buy"
        buy = session.router.buy_agent
        await msg.reply_text(
            "🎫 Оформляем билет!\n\n" + buy.get_next_question(),
            reply_markup=kb_cancel_buy(),
        )
        return

    if data == "action:consult":
        await msg.reply_text("❓ Задайте ваш вопрос о правилах, тарифах или возврате билетов:")
        return

    if data == "action:trips":
        await show_available_trips(msg)
        return

    if data == "action:profile":
        info = check_registered_in_java(user_id)
        if info and info.get("registered"):
            await msg.reply_text(
                f"👤 *Ваш профиль:*\n\n"
                f"Имя: {info['full_name']}\n"
                f"Телефон: {info['phone']}\n\n",
                parse_mode="Markdown",
                reply_markup=kb_main_menu(),
            )
        else:
            await msg.reply_text("Не удалось получить данные. Попробуйте позже.", reply_markup=kb_main_menu())
        return

    if data == "action:cancel":
        session.awaiting_order_confirm = False
        session.router.finish_buy_session()
        await msg.reply_text("❌ Заказ отменён.", reply_markup=kb_main_menu())
        return


# ---------------------------------------------------------------------------
# Хэндлеры команд
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name    = update.effective_user.first_name or "Пассажир"
    _sessions.pop(user_id, None)
    session = get_session(user_id)
    info    = check_registered_in_java(user_id)

    if info is None:
        await update.message.reply_text(
            f"👋 Здравствуйте, {name}!\n\n⚠️ Не удалось связаться с сервером. Попробуйте позже.\n"
        )
        session.start_registration()
        await update.message.reply_text(
            "📝 Для начала работы нужно пройти быструю регистрацию.\n\n" + session.next_reg_prompt()
        )
        return

    if info.get("registered"):
        session.phone         = info["phone"]
        session.full_name     = info["full_name"]
        session.is_registered = True
        await update.message.reply_text(
            f"👋 С возвращением, {info['full_name']}! 🚂\n\n"
            "Выберите действие или просто напишите / скажите, что вас интересует.",
            reply_markup=kb_main_menu(),
        )
    else:
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
        "🎫 Купить билет — напишите «хочу билет» или нажмите кнопку\n"
        "📋 Консультация — задайте вопрос о правилах, тарифах, возврате\n"
        "🎤 Голосовые сообщения — говорите, я пойму\n"
        "📋 /trips — список доступных рейсов\n\n"
        "Команды:\n"
        "/start — начать заново\n"
        "/cancel — отменить текущий заказ\n"
        "/profile — ваши данные\n"
        "/trips — доступные рейсы\n"
        "/help — эта справка",
        reply_markup=kb_main_menu(),
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)
    session.awaiting_order_confirm = False
    session.router.finish_buy_session()
    await update.message.reply_text("❌ Заказ отменён. Чем ещё могу помочь?", reply_markup=kb_main_menu())


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)
    if not session.is_registered:
        await update.message.reply_text("Вы ещё не зарегистрированы. Используйте /start.")
        return
    info = check_registered_in_java(user_id)
    if info and info.get("registered"):
        await update.message.reply_text(
            f"👤 Ваш профиль:\n\nИмя: {info['full_name']}\nТелефон: {info['phone']}\n\n"
            "Для обновления данных используйте /start.",
            reply_markup=kb_main_menu(),
        )
    else:
        await update.message.reply_text("Не удалось получить данные. Попробуйте позже.")


async def cmd_trips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_available_trips(update.message)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)
    text    = update.message.text.strip()
    logger.info(f"[user={user_id}] Текст: {text}")
    await process_text(update, text, session, user_id)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)

    if session.registration_in_progress() or session.reg_step == "confirm":
        await update.message.reply_text("📝 Во время регистрации вводите данные текстом.")
        return

    await update.message.reply_text("🎤 Распознаю голосовое сообщение...")
    voice_file = await update.message.voice.get_file()
    ogg_bytes  = await voice_file.download_as_bytearray()
    text       = voice_to_text(bytes(ogg_bytes))

    if not text:
        await update.message.reply_text("😕 Не удалось распознать речь. Попробуйте ещё раз или напишите текстом.")
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
    app.add_handler(CommandHandler("trips",   cmd_trips))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    logger.info("Бот запущен. Ожидаем сообщения...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()