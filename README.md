# VoiceBuyTicket  
Голосовой ассистент для покупки ж/д билетов РЖД

Демонстрационный проект, который позволяет купить билет на поезд, просто разговаривая в микрофон.

## Основная идея

Вы говорите в микрофон →  
система распознаёт речь →  
ИИ ведёт диалог и уточняет детали →  
формирует заказ →  
отправляет на Java-бэкенд →  
проверяет места и оформляет заказ (или предлагает ближайшие альтернативы)

## Технологический стек

### Frontend / Голосовой слой (Python)
- **Vosk** — оффлайн-распознавание русской речи  
- **GigaChat** (Сбер) — языковая модель для естественного диалога  
- sounddevice + queue

### Backend
- **Java 21** + **Spring Boot 3.2**  
- **Spring Data JPA** + Hibernate  
- **PostgreSQL**  
- Lombok, Hibernate Validator

## Как это работает (схема)
Голос → Vosk (оффлайн) → текст
↓
GigaChat → диалог и сбор данных
↓
JSON с заказом
↓
Spring Boot REST API (/api/ticket/order)
↓
Проверка пассажира → поиск рейса → проверка мест
↓
либо успех + списание мест + сохранение заказа
либо ближайшие альтернативные рейсы (±7 дней)
text## Требования для запуска

- Java 21  
- Maven  
- PostgreSQL (можно в docker)  
- Python 3.10+  
- Vosk модель (маленькая русская)  
- Доступ к GigaChat API (токен)

## Быстрый старт

### 1. База данных (PostgreSQL)

```bash
# Пример запуска через docker
docker run -d \
  --name voice-ticket-db \
  -e POSTGRES_PASSWORD=your_password \
  -e POSTGRES_DB=ticket_db \
  -p 5432:5432 \
  postgres:16
Создайте таблицы (можно через schema.sql или flyway/liquibase)
2. Запуск Java-бэкенда
Bash# В папке с проектом
mvn clean package
java -jar target/demo-0.0.1-SNAPSHOT.jar
# или просто через IDE
3. Подготовка Python-части
Bash# Установка зависимостей
pip install -r requirements.txt

# Скачайте модель Vosk (маленькая русская)
# https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
# Распакуйте и укажите путь в .env

# Создайте .env файл
VOSK_MODEL_PATH=/path/to/vosk-model-small-ru-0.22
JAVA_BACKEND_URL=http://localhost:8080/api/ticket/order
GIGACHAT_CREDENTIALS=ваш_токен_гигачата
4. Запуск голосового бота
Bashpython main.py
После запуска введите номер телефона тестового пассажира → говорите в микрофон.
Минимальные тестовые данные в БД
SQL-- Пассажир
INSERT INTO passengers (phone, full_name, passport_series, passport_number)
VALUES ('+79161234567', 'Иванов Иван Иванович', '45 12', '123456');

-- Несколько рейсов (пример)
INSERT INTO trip (departure_station, arrival_station, departure_date, departure_time,
                  train_number, carriage_type, total_seats, available_seats, price)
VALUES 
('Москва', 'Санкт-Петербург', '2026-02-15', '23:45', '029Я', 'Platzkart', 54, 42, 3850),
('Москва', 'Санкт-Петербург', '2026-02-16', '00:35', '059Г', 'Compartment', 36, 18, 6200);
Текущие ограничения

Диалог ИИ ещё не идеален (может зациклиться или неправильно понять)
Нет синтеза речи (пока только текст в консоли)
Нет выбора конкретного места и оплаты
Нет возврата/обмена билетов

Планы на развитие

Добавить голосовой синтез (например, Silero TTS)
Улучшить устойчивость диалога
Добавить выбор конкретного рейса из предложенных альтернатив
Реализовать базовую авторизацию/регистрацию пассажиров
Подключить тестовый платёжный шлюз
