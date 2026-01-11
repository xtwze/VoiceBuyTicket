from config import MODEL_PATH, JAVA_BACKEND_URL, GIGACHAT_CREDENTIALS
from bot import VoiceTicketBot

if __name__ == "__main__":
    bot = VoiceTicketBot(
        model_path=MODEL_PATH,
        java_url=JAVA_BACKEND_URL,
        gigachat_credentials=GIGACHAT_CREDENTIALS
    )
    try:
        bot.run()
    except KeyboardInterrupt:
        print("\n[Бот остановлен пользователем]")