import os

from dotenv import load_dotenv


load_dotenv()

MODEL_PATH = os.getenv("VOSK_MODEL_PATH", "vosk-model-small-ru-0.22")
JAVA_BACKEND_URL = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080/api/ticket/order")
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")

if not GIGACHAT_CREDENTIALS:
    raise ValueError("В .env отсутствует GIGACHAT_CREDENTIALS")