"""
intent_classifier.py
Классификатор намерений пользователя.
Определяет к какому агенту направить запрос:
  - "buy"     -> агент бронирования билетов
  - "consult" -> RAG-агент консультации (правила, возврат, тарифы, FAQ)

Модель: TF-IDF + LogisticRegression (sklearn)
"""

import pickle
import os
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

# ---------------------------------------------------------------------------
# Обучающие данные
# ---------------------------------------------------------------------------

TRAIN_DATA = [
    # --- buy ---
    ("хочу купить билет", "buy"),
    ("купи мне билет", "buy"),
    ("хочу поехать из москвы в питер", "buy"),
    ("закажи билет на поезд", "buy"),
    ("нужен билет до сочи", "buy"),
    ("отправиться из казани в екатеринбург", "buy"),
    ("хочу отправиться", "buy"),
    ("поехать первого июня", "buy"),
    ("забронируй место в купе", "buy"),
    ("нужно доехать до новосибирска", "buy"),
    ("билет на плацкарт", "buy"),
    ("два билета до краснодара", "buy"),
    ("едем в москву", "buy"),
    ("поездка на следующей неделе", "buy"),
    ("можешь оформить заказ", "buy"),
    ("хочу место в св", "buy"),
    ("один взрослый билет", "buy"),
    ("студенческий билет до питера", "buy"),
    ("три билета в люкс вагоне", "buy"),
    ("оформить поездку", "buy"),
    ("когда ближайший поезд до сочи", "buy"),
    ("есть ли места на пятое июня", "buy"),
    ("поехали", "buy"),
    ("билет туда", "buy"),
    ("хочу в санкт-петербург", "buy"),
    # --- consult ---
    ("можно ли вернуть билет", "consult"),
    ("как вернуть деньги за билет", "consult"),
    ("правила возврата", "consult"),
    ("сколько стоит плацкарт", "consult"),
    ("чем отличается купе от люкса", "consult"),
    ("какой багаж можно взять", "consult"),
    ("можно ли с животным", "consult"),
    ("скидка для пенсионеров", "consult"),
    ("детский билет со скидкой", "consult"),
    ("что входит в стоимость билета", "consult"),
    ("есть ли вай-фай в поезде", "consult"),
    ("можно ли курить", "consult"),
    ("опоздал на поезд что делать", "consult"),
    ("забыл вещи в поезде", "consult"),
    ("как обменять билет", "consult"),
    ("нужен ли распечатанный билет", "consult"),
    ("как ехать без бумажного билета", "consult"),
    ("правила посадки", "consult"),
    ("когда лучше покупать чтобы дешевле", "consult"),
    ("акции и скидки ржд", "consult"),
    ("студенческая скидка когда действует", "consult"),
    ("как перевезти велосипед", "consult"),
    ("ребёнок без билета", "consult"),
    ("постельное бельё включено", "consult"),
    ("что такое св вагон", "consult"),
    ("расскажи про плацкарт", "consult"),
    ("сколько мест в купе", "consult"),
    ("динамические цены", "consult"),
    ("невозвратный тариф", "consult"),
    ("задержка поезда", "consult"),
]

MODEL_PATH = os.path.join(os.path.dirname(__file__), "intent_model.pkl")


class IntentClassifier:
    """
    Обёртка над sklearn Pipeline (TfidfVectorizer + LogisticRegression).
    При первом запуске обучает и сохраняет модель в intent_model.pkl.
    При последующих запусках загружает готовую модель.
    """

    def __init__(self, model_path: str = MODEL_PATH):
        self.model_path = model_path
        self.pipeline = self._load_or_train()

    def predict(self, text: str) -> str:
        """Возвращает 'buy' или 'consult'."""
        return self.pipeline.predict([text.lower()])[0]

    def predict_proba(self, text: str) -> dict:
        """Возвращает вероятности классов: {'buy': 0.85, 'consult': 0.15}"""
        classes = self.pipeline.classes_
        probs   = self.pipeline.predict_proba([text.lower()])[0]
        return dict(zip(classes, probs))

    def _load_or_train(self):
        if os.path.exists(self.model_path):
            with open(self.model_path, "rb") as f:
                pipeline = pickle.load(f)
            return pipeline
        return self._train_and_save()

    def _train_and_save(self):
        texts  = [t for t, _ in TRAIN_DATA]
        labels = [l for _, l in TRAIN_DATA]

        pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(
                analyzer="char_wb",
                ngram_range=(2, 4),
                max_features=5000,
                sublinear_tf=True,
            )),
            ("clf", LogisticRegression(
                C=5.0,
                max_iter=1000,
                solver="lbfgs",
            )),
        ])

        pipeline.fit(texts, labels)

        with open(self.model_path, "wb") as f:
            pickle.dump(pipeline, f)

        return pipeline

    def retrain(self):
        """Принудительно переобучить и перезаписать модель."""
        if os.path.exists(self.model_path):
            os.remove(self.model_path)
        self.pipeline = self._train_and_save()