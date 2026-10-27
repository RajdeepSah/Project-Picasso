"""Offline speech-to-text for the command composer (Faster-Whisper small, CPU int8).

A transcript is only text for the operator to review; it never generates, prepares or starts anything.
The model loads from a local directory, so recognition needs no network after setup.
"""

import argparse
import importlib.util
import io
import itertools
import os
from pathlib import Path
import re
import threading
import time

from .drawing.errors import DrawingError
from .models import Capability, VoiceTranscript

ROOT = Path(__file__).resolve().parents[2]
MODEL_SIZE = "small"
DEFAULT_MODEL_DIR = ROOT / "models" / "faster-whisper-small"
MAX_AUDIO_BYTES = 4_000_000
MAX_SECONDS = 30
SAMPLE_RATE = 16000
# Biases recognition toward the offline command vocabulary ("mandala", "mm", digits).
COMMAND_PROMPT = ("Draw a butterfly. Create a mandala with 12 petals, 120 mm wide. Draw a circle diameter 100. "
                  "Draw a spiral with 5 turns. Draw a geometric pattern with symmetry 8, seed 7.")


def normalize(text: str) -> str:
    """Spoken forms the command grammar does not accept become their written forms."""
    text = " ".join(text.split()).strip(" \"'“”")
    text = re.sub(r"\b(?:millimet(?:er|re)s?)\b", "mm", text, flags=re.IGNORECASE)
    text = re.sub(r"(\d)\s*mm\s+by\s+(\d)", r"\1 x \2", text, flags=re.IGNORECASE)
    text = re.sub(r"(\d)\s+by\s+(\d)", r"\1 x \2", text, flags=re.IGNORECASE)
    text = re.sub(r"(\d),(\d{3})\b", r"\1\2", text)
    return text.rstrip(".!?…").strip()[:2000]


def decode(audio: bytes):
    """Browser recording (WebM/Ogg Opus, MP4/AAC, WAV) → 16 kHz mono float32, bounded by MAX_SECONDS."""
    import av
    import numpy as np
    limit = (MAX_SECONDS + 1) * SAMPLE_RATE
    chunks, total = [], 0
    try:
        with av.open(io.BytesIO(audio), mode="r") as container:
            if not container.streams.audio:
                raise ValueError("no audio stream")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for frame in itertools.chain(container.decode(audio=0), [None]):  # None flushes the resampler
                for out in resampler.resample(frame):
                    chunk = out.to_ndarray().reshape(-1)
                    chunks.append(chunk); total += len(chunk)
                if total > limit:
                    raise DrawingError("VOICE_TOO_LONG", f"Recordings are limited to {MAX_SECONDS} seconds.", 413)
    except DrawingError:
        raise
    except Exception as exc:  # malformed or unsupported container
        raise DrawingError("VOICE_AUDIO_INVALID", "The recording could not be decoded. Try again, or type the command.") from exc
    if not total:
        raise DrawingError("VOICE_NO_SPEECH", "The recording was empty. Try again, or type the command.")
    return np.concatenate(chunks).astype(np.float32) / 32768.0


class VoiceService:
    def __init__(self, model_dir: Path, loader=None):
        self.model_dir = model_dir
        self._whisper = loader is None  # tests inject a fake loader
        self._loader = loader or self._load_whisper
        self._model = None
        self._warming = False
        self._error = ""
        self._load_lock = threading.Lock()
        self._run_lock = threading.Lock()

    def installed(self) -> bool:
        return not self._whisper or (self.model_dir / "model.bin").is_file() and importlib.util.find_spec("faster_whisper") is not None

    def capability(self) -> Capability:
        if not self.installed():
            return Capability(available=False, phase=8, reason="Voice input needs the offline speech model. Run python3 scripts/setup.py once with internet access.")
        if self._error:
            return Capability(available=False, phase=8, reason=f"The offline speech model could not be loaded: {self._error}")
        return Capability(available=True, phase=8, reason="Offline Faster-Whisper (small) speech recognition. Recognized words go into the command box for review; nothing is drawn automatically.")

    def _load_whisper(self):
        from faster_whisper import WhisperModel
        # A directory path is read from disk only; no model hub is contacted.
        return WhisperModel(str(self.model_dir), device="cpu", compute_type="int8", cpu_threads=min(8, os.cpu_count() or 4))

    def model(self):
        with self._load_lock:
            if self._model is None:
                if not self.installed():
                    raise DrawingError("VOICE_UNAVAILABLE", self.capability().reason, 503)
                try:
                    self._model = self._loader()
                    self._error = ""
                except Exception as exc:  # corrupt or incompatible model files
                    self._error = str(exc)[:200] or type(exc).__name__
                    raise DrawingError("VOICE_UNAVAILABLE", self.capability().reason, 503) from exc
            return self._model

    def warm(self) -> Capability:
        """Start loading the model in the background so it is ready when the operator stops speaking."""
        with self._load_lock:
            start = self.installed() and self._model is None and not self._error and not self._warming
            self._warming = self._warming or start
        if start:
            threading.Thread(target=self._warm, name="voice-warm", daemon=True).start()
        return self.capability()

    def _warm(self):
        try:
            model = self.model()
        except DrawingError:
            return  # reported through capability()
        finally:
            self._warming = False
        if self._whisper:
            import numpy as np
            with self._run_lock:  # one throwaway decode primes the runtime, so the first real command is fast
                segments, _ = model.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), language="en", beam_size=1, vad_filter=False)
                list(segments)

    def transcribe(self, audio: bytes, cancel: threading.Event) -> VoiceTranscript:
        if not audio:
            raise DrawingError("VOICE_AUDIO_INVALID", "No audio was received. Record again, or type the command.")
        if len(audio) > MAX_AUDIO_BYTES:
            raise DrawingError("VOICE_TOO_LONG", f"Recordings are limited to {MAX_SECONDS} seconds.", 413)
        model = self.model()
        started = time.monotonic()
        samples = decode(audio)
        duration = len(samples) / SAMPLE_RATE
        with self._run_lock:
            segments, _ = model.transcribe(samples, language="en", beam_size=5, vad_filter=True,
                                           condition_on_previous_text=False, initial_prompt=COMMAND_PROMPT)
            parts = []
            for segment in segments:  # decoding is lazy; stop between segments if the request is abandoned
                if cancel.is_set():
                    raise DrawingError("VOICE_CANCELLED", "Transcription was cancelled.", 499)
                parts.append(segment.text)
        text = normalize(" ".join(parts))
        if not text:
            raise DrawingError("VOICE_NO_SPEECH", "No speech was recognized. Speak a little closer to the microphone, or type the command.")
        return VoiceTranscript(text=text, duration_s=round(duration, 2), processing_s=round(time.monotonic() - started, 2))


def download(model_dir: Path = DEFAULT_MODEL_DIR):
    """Fetch the model once into the project; Hugging Face caches stay under .cache/."""
    os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "huggingface"))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from faster_whisper import download_model
    download_model(MODEL_SIZE, output_dir=str(model_dir))
    if not (model_dir / "model.bin").is_file():
        raise SystemExit(f"Speech model download incomplete: {model_dir}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["download", "check"])
    args = parser.parse_args()
    model_dir = Path(os.environ.get("PICASSO_VOICE_MODEL_DIR", DEFAULT_MODEL_DIR))
    if args.command == "download":
        if (model_dir / "model.bin").is_file():
            print(f"Offline speech model already installed: {model_dir}")
        else:
            print(f"Downloading the Faster-Whisper {MODEL_SIZE} speech model (about 480 MB) to {model_dir}…", flush=True)
            download(model_dir)
            print("Speech model installed. Voice input now works offline.")
    else:
        service = VoiceService(model_dir)
        service.model()
        print(service.capability().reason)


if __name__ == "__main__":
    main()
