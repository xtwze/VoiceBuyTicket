"""
telegram_bot.py
Телеграм-бот — оболочка над существующей логикой ассистента РЖД.

Поддерживает:
  - Текстовые сообщения
  - Голосовые сообщения (ogg → wav → Vosk)

Каждый пользователь имеет свою изолированную сессию (router + состояние диалога).

Зависимости (добавить в requirements.txt):
  python-telegram-bot>=21.0
  pydub>=0.25.1
  ffmpeg  (системный, установить отдельно: brew install ffmpeg / apt install ffmpeg)
"""

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from config import MODEL_PATH as VOSK_MODEL_PATH, JAVA_BACKEND_URL, GIGACHAT_CREDENTIALS

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from router import AgentRouter
from recognizer import VoskRecognizer

import requests

# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("В .env отсутствует TELEGRAM_BOT_TOKEN")

# ---------------------------------------------------------------------------
# Хранилище сессий: user_id -> SessionState
# ---------------------------------------------------------------------------

class SessionState:
    """Состояние одного пользователя."""

    def __init__(self, gigachat_credentials: str):
        self.router = AgentRouter(gigachat_credentials)
        self.phone: str | None = None
        self.waiting_for_phone: bool = True   # первый шаг — запросить телефон

    def is_phone_set(self) -> bool:
        return self.phone is not None


# Глобальный словарь сессий и распознаватель речи (один на всех)
_sessions: dict[int, SessionState] = {}
_recognizer: VoskRecognizer | None = None


def get_session(user_id: int) -> SessionState:
    if user_id not in _sessions:
        logger.info(f"Создаём новую сессию для user_id={user_id}")
        _sessions[user_id] = SessionState(GIGACHAT_CREDENTIALS)
    return _sessions[user_id]


# ---------------------------------------------------------------------------
# Распознавание голоса
# ---------------------------------------------------------------------------

def voice_to_text(ogg_bytes: bytes) -> str:
    """
    Конвертирует ogg-файл (от Telegram) в wav и распознаёт через Vosk.
    Возвращает распознанный текст или пустую строку.
    """
    global _recognizer
    if _recognizer is None:
        _recognizer = VoskRecognizer(VOSK_MODEL_PATH)

    with tempfile.TemporaryDirectory() as tmpdir:
        ogg_path = os.path.join(tmpdir, "voice.ogg")
        wav_path = os.path.join(tmpdir, "voice.wav")

        with open(ogg_path, "wb") as f:
            f.write(ogg_bytes)

        # ffmpeg: ogg → wav 16kHz mono
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", ogg_path,
             "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
            capture_output=True,
        )
        if result.returncode != 0:
            logger.error(f"ffmpeg error: {result.stderr.decode()}")
            return ""

        # Читаем wav и распознаём
        import vosk
        model = _recognizer.model
        rec = vosk.KaldiRecognizer(model, 16000)

        with open(wav_path, "rb") as wav_file:
            wav_file.read(44)  # пропускаем WAV-заголовок
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

async def send_to_java(
    update: Update,
    order_json: dict,
    phone: str,
) -> tuple[bool, list]:
    """Отправляет заказ в Java backend, возвращает (success, alternatives)."""
    order_json["contact_phone"] = phone

    try:
        response = requests.post(JAVA_BACKEND_URL, json=order_json, timeout=15)
        data = response.json()
        status = data.get("status")

        if status == "success":
            text = (
                f"✅ {data.get('message')}\n\n"
                f"🚂 Поезд: {data.get('trainNumber')}\n"
                f"🕐 Время: {data.get('departureTime')}\n"
                f"💰 Цена: {data.get('priceTotal')} руб.\n\n"
                f"Приятной поездки!"
            )
            await update.message.reply_text(text)
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
                await update.message.reply_text(
                    "Рейсов на ближайшие даты нет. Попробуйте другой маршрут."
                )
            return False, alternatives

        else:
            await update.message.reply_text(
                f"❌ Ошибка: {data.get('message', 'Неизвестная ошибка')}"
            )
            return False, []

    except Exception as e:
        logger.error(f"Java backend error: {e}")
        await update.message.reply_text(f"⚠️ Ошибка связи с сервером: {e}")
        return False, []


# ---------------------------------------------------------------------------
# Основная логика обработки сообщения
# ---------------------------------------------------------------------------

async def process_text(update: Update, text: str, session: SessionState):
    """Обрабатывает распознанный/введённый текст и отвечает пользователю."""

    # Шаг 0: запрашиваем телефон
    if not session.is_phone_set():
        phone = text.strip()
        if 10 <= len(phone) <= 15 and (phone.startswith("+") or phone.isdigit()):
            session.phone = phone
            await update.message.reply_text(
                f"✅ Телефон сохранён: {phone}\n\nОтлично! Теперь говорите или пишите.\n"
                "Я могу помочь купить билет или ответить на вопросы о РЖД."
            )
        else:
            await update.message.reply_text(
                "❌ Некорректный номер. Введите номер телефона, например: +79123456789"
            )
        return

    router = session.router

    # Шаг 1: активный диалог бронирования
    if router.is_buy_active():
        buy = router.buy_agent
        error = buy.process_user_input(text)

        if error:
            await update.message.reply_text(f"⚠️ {error}")
            return

        if buy.is_done():
            # Заказ собран — отправляем в Java
            order_json = buy.get_order_json()
            success, alternatives = await send_to_java(update, order_json, session.phone)

            if success:
                router.finish_buy_session()
                await update.message.reply_text("Чем ещё могу помочь? 😊")
            else:
                buy.handle_no_seats(alternatives)
                if alternatives:
                    await update.message.reply_text(
                        "Выберите одну из предложенных дат или назовите другую."
                    )
                else:
                    await update.message.reply_text("Попробуем другую дату.")
        else:
            # Следующий вопрос диалога бронирования
            next_q = buy.get_next_question()
            await update.message.reply_text(next_q)
        return

    # Шаг 2: маршрутизация нового намерения
    agent_name, response = router.route(text)

    if agent_name == "clarify":
        await update.message.reply_text(f"🤔 {response}")

    elif agent_name == "consult":
        await update.message.reply_text(response)
        await update.message.reply_text("Могу ещё чем-то помочь? 😊")

    elif agent_name == "buy":
        buy = router.buy_agent
        error = buy.process_user_input(text)
        # Задаём первый вопрос диалога бронирования
        next_q = buy.get_next_question()
        await update.message.reply_text(f"🎫 Оформляем билет!\n\n{next_q}")


# ---------------------------------------------------------------------------
# Хэндлеры Telegram
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start — приветствие и запрос телефона."""
    user_id = update.effective_user.id

    # Сбрасываем сессию при /start
    _sessions.pop(user_id, None)
    session = get_session(user_id)

    name = update.effective_user.first_name or "Пассажир"

    await update.message.reply_text(
        f"👋 Здравствуйте, {name}!\n\n"
        "Я — виртуальный ассистент РЖД 🚂\n\n"
        "Я умею:\n"
        "🎫 Помочь купить билет на поезд\n"
        "📋 Ответить на вопросы о правилах, тарифах и возврате\n"
        "🎤 Принимать голосовые сообщения\n\n"
        "Для начала введите ваш номер телефона (например, +79123456789):"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Что я умею:\n\n"
        "🎫 Купить билет — просто напишите «хочу билет» или «еду из Москвы в Питер»\n"
        "📋 Консультация — задайте вопрос о правилах, тарифах, возврате\n"
        "🎤 Голосовые сообщения — говорите, я пойму\n\n"
        "Команды:\n"
        "/start — начать заново\n"
        "/cancel — отменить текущий заказ\n"
        "/help — эта справка"
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_session(user_id)
    session.router.finish_buy_session()
    await update.message.reply_text(
        "❌ Заказ отменён. Чем ещё могу помочь?"
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений."""
    user_id = update.effective_user.id
    session = get_session(user_id)
    text = update.message.text.strip()

    logger.info(f"[user={user_id}] Текст: {text}")
    await process_text(update, text, session)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик голосовых сообщений."""
    user_id = update.effective_user.id
    session = get_session(user_id)

    await update.message.reply_text("🎤 Распознаю голосовое сообщение...")

    # Скачиваем ogg-файл от Telegram
    voice_file = await update.message.voice.get_file()
    ogg_bytes = await voice_file.download_as_bytearray()

    # Распознаём через Vosk
    text = voice_to_text(bytes(ogg_bytes))

    if not text:
        await update.message.reply_text(
            "😕 Не удалось распознать речь. Попробуйте ещё раз или напишите текстом."
        )
        return

    logger.info(f"[user={user_id}] Голос → текст: {text}")
    await update.message.reply_text(f"🗣 Вы сказали: «{text}»")

    await process_text(update, text, session)


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

def main():
    logger.info("Запуск Telegram-бота РЖД...")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    logger.info("Бот запущен. Ожидаем сообщения...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()