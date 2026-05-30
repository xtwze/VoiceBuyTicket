import queue
import json
import vosk
import sounddevice as sd


class VoskRecognizer:
    def __init__(self, model_path: str):
        self.model = vosk.Model(model_path)
        self.queue: queue.Queue = queue.Queue()

    def _callback(self, indata, frames, time, status):
        """Callback для sounddevice"""
        if status:
            print(f"[Vosk] Status: {status}")  # логируем ошибки

        # Преобразуем в bytes и кладём в очередь
        self.queue.put(bytes(indata))

    def listen(self, timeout: float | None = None) -> str:
        """
        Слушает микрофон до конца фразы и возвращает распознанный текст.
        """
        rec = vosk.KaldiRecognizer(self.model, 16000)

        with sd.RawInputStream(
                samplerate=16000,
                blocksize=8000,
                dtype="int16",
                channels=1,
                callback=self._callback
        ):
            print("🎤 Слушаю...")

            while True:
                try:
                    data = self.queue.get(timeout=timeout)
                except queue.Empty:
                    return ""  # таймаут

                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    text = result.get("text", "").strip()
                    if text:
                        return text
                    # Если AcceptWaveform сработал, но текста нет — продолжаем
                    continue

                # Опционально: можно смотреть промежуточные результаты
                # partial = json.loads(rec.PartialResult())
                # print("Partial:", partial.get("partial", ""))