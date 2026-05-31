**Вот обновлённая версия `README.md` без каких-либо упоминаний отчёта:**

```markdown
# 🎤 VoiceBuyTicket

**Голосовой AI-чат-бот для покупки железнодорожных билетов РЖД и консультаций**

*Интеллектуальный ассистент с многошаговым диалогом, RAG-консультациями и enterprise-бэкендом.*

![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)
![Java](https://img.shields.io/badge/Java-21-ED8B00?logo=openjdk&logoColor=white)
![Spring Boot](https://img.shields.io/badge/Spring_Boot-6DB33F?logo=springboot&logoColor=white)
![GigaChat](https://img.shields.io/badge/GigaChat-Sber-4CAF50)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-2CA5E0?logo=telegram&logoColor=white)

---

## ✨ О проекте

**VoiceBuyTicket** — это полноценная система AI-чат-бота для покупки железнодорожных билетов и консультаций пользователей.

Проект реализует:
- **Многошаговый диалог** для бронирования билетов через естественный язык
- **Классификацию намерений** (покупка / консультация)
- **RAG-агента** для точных ответов по правилам РЖД
- **Голосовое распознавание** (Vosk)
- **Двухуровневую архитектуру** (Python + Spring Boot)

Система способна вести осмысленный диалог, извлекать сущности из свободного текста, обрабатывать ошибки и предлагать альтернативы при отсутствии мест.

---

## 🚀 Ключевые возможности

### Подсистема бронирования
- Распознавание намерения купить билет с помощью ML-классификатора (TF-IDF + Logistic Regression)
- Пошаговый сбор данных: станция отправления, прибытия, дата, тип вагона, количество и категории пассажиров
- Извлечение сущностей из произвольного текста через **GigaChat**
- Нормализация ввода (числительные прописью, синонимы типов вагонов)
- Подтверждение заказа и обработка ответа от бэкенда
- Автоматическое предложение альтернативных рейсов при отсутствии мест

### Подсистема консультаций (RAG)
- Ответы на вопросы по правилам перевозок, тарифам, возврату билетов, правам пассажиров и др.
- **Retrieval-Augmented Generation** на базе **ChromaDB** + GigaChat
- Семантический поиск по документам базы знаний
- Поддержка контекстной памяти диалога

### Дополнительно
- Голосовой ввод (Vosk — полностью оффлайн)
- Регистрация и привязка пассажиров к Telegram-аккаунту
- Полноценное Docker-развёртывание

---

## 🛠️ Технологический стек

**Python (Voice + AI слой)**
- `python-telegram-bot`
- `LangChain`
- `GigaChat API` (Sber)
- `ChromaDB` + `sentence-transformers`
- `scikit-learn` (Intent Classification)
- `Vosk` (Offline Speech Recognition)

**Java (Backend)**
- Spring Boot 3.2 + Java 21
- Spring Data JPA + Hibernate
- PostgreSQL
- REST API

**Инфраструктура**
- Docker + Docker Compose

---

## 📁 Структура проекта

```bash
VoiceBuyTicket/
├── JavaLayer/                          # Spring Boot бэкенд
├── Voice and AI layer/                 # AI-чатбот
│   ├── main.py
│   ├── telegram_bot.py
│   ├── router.py
│   ├── intent_classifier.py
│   ├── assistant_ai.py
│   ├── rag_agent.py
│   ├── requirements.txt
│   └── .env.example
├── knowledge_base/                     # Документы для RAG
├── chroma_db/                          # Векторная база
├── docker-compose.yml
└── README.md
```

---

## 🚀 Быстрый старт

1. **Клонируйте репозиторий**
   ```bash
   git clone https://github.com/xtwze/VoiceBuyTicket.git
   cd VoiceBuyTicket
   ```

2. **Запустите через Docker Compose** (рекомендуется)
   ```bash
   docker-compose up --build
   ```

3. **Или вручную:**
   - Запустите PostgreSQL и Java-бэкенд
   - Настройте `.env` в папке `Voice and AI layer`
   - `cd "Voice and AI layer"`
   - `pip install -r requirements.txt`
   - `python main.py`

---

## 📸 Демонстрация

Скриншоты и примеры работы бота находятся в папке `demo/` (при наличии).

---

## 🔧 Архитектура

- `AgentRouter` — центральный маршрутизатор между агентами
- `IntentClassifier` — ML-классификатор намерений
- `GigaChatAssistant` — конечный автомат бронирования (8 состояний)
- `RagConsultAgent` — RAG-консультант
- Java REST API (`TicketController`, `PassengerController`, `TripController`)

---

## 🔮 Планы развития

- Синтез речи (TTS)
- История заказов пользователя
- Выбор конкретного места в вагоне
- Интеграция с реальным API РЖД
- Платёжный модуль

---

**Автор**: Константинов Михаил Алексеевич, группа УИТ-311  
**Год**: 2026

⭐ Если проект вам понравился — поставьте звезду!
```
