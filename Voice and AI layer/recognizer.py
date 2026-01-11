import queue
import json
import vosk
import sounddevice as sd


class VoskRecognizer:

    def __init__(self, model_path: str):
        self.model = vosk.Model(model_path)
        self.queue = queue.Queue() #создаем очередь FIFO

    def _callback(self, indata, frames, time, status):
        if status:
            print(status)
        self.queue.put(bytes(indata))

    def listen(self) -> str:
        print("Слушаю Вас...")
        rec = vosk.KaldiRecognizer(self.model, 16000)

        with sd.RawInputStream(
            samplerate=16000,
            blocksize=8000, #разбиваем на чанки
            dtype="int16",
            channels=1,
            callback=self._callback
        ):
            while True:
                data = self.queue.get()
                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    text = result.get("text", "").strip()
                    if text:
                        print(f"[Вы]: {text}" )
                        return text
                    return ""