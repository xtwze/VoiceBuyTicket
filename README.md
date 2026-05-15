# 🎤 VoiceBuyTicket

**Голосовой ассистент для покупки железнодорожных билетов РЖД**

*Демонстрационный проект, где вы просто говорите в микрофон — и билет куплен.*

![Java](https://img.shields.io/badge/Java-21-ED8B00?logo=openjdk&logoColor=white)
![Spring Boot](https://img.shields.io/badge/Spring_Boot-6DB33F?logo=springboot&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)
![Vosk](https://img.shields.io/badge/Vosk-Offline%20ASR-00B4D8)
![GigaChat](https://img.shields.io/badge/GigaChat-Sber-4CAF50)

---

## ✨ О проекте

**VoiceBuyTicket** — это инновационный голосовой интерфейс для покупки билетов на поезд.  
Проект демонстрирует интеграцию **оффлайн распознавания речи**, **генеративного ИИ** и **enterprise Java backend**.

Вы говорите в микрофон → ИИ понимает запрос → проверяет места → оформляет заказ.

### Ключевые возможности

- 🎙️ Полностью голосовое управление (оффлайн)
- 🧠 Интеллектуальный диалог с GigaChat
- 🛤️ Поиск и бронирование билетов
- 🔄 Предложение альтернативных рейсов
- 🗄️ Надёжный Java Backend с PostgreSQL

---

## 🖼️ Как это работает

```mermaid
graph LR
    A[🎤 Голос] --> B[Vosk ASR]
    B --> C[GigaChat]
    C --> D[JSON Заказ]
    D --> E[Spring Boot API]
    E --> F[PostgreSQL]
    F --> G[✅ Билет оформлен]

🚀 Быстрый старт
1. Клонируйте репозиторий
Bashgit clone https://github.com/xtwze/VoiceBuyTicket.git
cd VoiceBuyTicket
2. Запуск Backend (Java)
Bashcd JavaLayer
mvn clean package
java -jar target/*.jar
3. Запуск Голосового Ассистента (Python)
Bashcd "Voice and AI layer"
pip install -r requirements.txt
python main.py
Подробная инструкция с настройкой БД, Vosk-модели и GigaChat токена — ниже.

🛠️ Технологический стек
Голосовой + AI слой (Python)

Vosk — оффлайн распознавание русской речи
GigaChat (Sber) — мощная языковая модель для диалога
sounddevice, queue, requests

Backend (Java)

Java 21 + Spring Boot 3.2
Spring Data JPA + Hibernate
PostgreSQL
REST API, валидация, Lombok


📁 Структура проекта
textVoiceBuyTicket/
├── JavaLayer/                  # Spring Boot backend
│   ├── src/main/java/...
│   └── pom.xml
├── Voice and AI layer/         # Голосовой ассистент
│   ├── main.py
│   ├── requirements.txt
│   └── .env.example
├── README.md
└── .gitignore

🎯 Основной сценарий

Запуск приложения
Ввод номера телефона пассажира
Разговор с ассистентом:
«Хочу в Санкт-Петербург на 15 февраля»
«На вечерний поезд»
«В плацкарте»

Система находит места → оформляет заказ


📈 Планы развития

🔊 Синтез речи (Silero TTS / Yandex SpeechKit)
🎟️ Выбор конкретного места в вагоне
💳 Интеграция тестового платежного шлюза
👤 Полноценная авторизация пассажиров
📱 Telegram-бот версия
🌐 Веб-интерфейс для демонстрации


📝 Текущие ограничения

Диалог иногда требует уточнений
Нет синтеза речи (только текст + голосовой ввод)
Упрощённая модель бронирования
