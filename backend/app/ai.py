"""Optional AI line art for requests the offline grammar cannot draw (OpenAI Image API).

The provider returns only a raster image. It is traced on this computer by the same OpenCV
path as an imported picture, so every line still passes the drawing engine's validation and
no provider output is ever executed. The API key stays in the backend environment: it is
never returned by the API, written to history or sent anywhere except the provider.
"""

import base64
import binascii
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import threading
import time

import httpx

from .drawing.errors import DrawingError
from .models import AiProvenance, Capability

ROOT = Path(__file__).resolve().parents[2]
ENDPOINT = "https://api.openai.com/v1/images/generations"
DEFAULT_MODEL = "gpt-image-2.5-flare"  # OpenAI's fast everyday image model
SIZE = "1024x1024"
# Detail chooses the provider's rendering quality (cost and time) and how much line work is asked for;
# the tracer then applies the matching Low/Medium/High level.
TIMEOUT_S = {"low": 60, "medium": 120, "high": 180}
DETAIL_STYLE = {
    "low": "Very simple and iconic: a few bold, continuous outlines, minimal interior detail.",
    "medium": "Clear outlines with moderate interior detail.",
    "high": "Detailed, precise contour lines with fine features, still drawn only as lines.",
}
STYLE = ("A single-colour black line drawing for a pen plotter on plain white paper. "
         "Uniform thin black strokes only: no shading, no hatching, no filled areas, no gradients, no colour, "
         "no text or lettering, no border and no background scenery. Centre the subject with a white margin. ")
MAX_SUBJECT = 1000


def _env_file_value(name: str, path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""
    for line in lines:
        key, separator, value = line.strip().removeprefix("export ").partition("=")
        if separator and key.strip() == name:
            return value.split(" #")[0].strip().strip("\"'")
    return ""


def plotter_prompt(subject: str, detail: str) -> str:
    return f"{STYLE}{DETAIL_STYLE[detail]} Subject: {subject.strip()[:MAX_SUBJECT]}"


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    provenance: AiProvenance


class ImageService:
    def __init__(self, key: str = "", model: str = DEFAULT_MODEL, *, enabled=True, transport: httpx.BaseTransport | None = None):
        self._key = key.strip()
        self.model = model.strip() or DEFAULT_MODEL
        self.enabled = enabled
        self._transport = transport  # tests inject httpx.MockTransport; nothing else is contacted
        self._busy = threading.Lock()

    @classmethod
    def from_environment(cls, transport=None):
        """OPENAI_API_KEY from the environment, else from the project's git-ignored .env file."""
        env_file = Path(os.environ.get("PICASSO_ENV_FILE", ROOT / ".env"))
        def setting(name):
            return os.environ.get(name) or _env_file_value(name, env_file)
        return cls(setting("OPENAI_API_KEY"), setting("PICASSO_OPENAI_IMAGE_MODEL") or DEFAULT_MODEL,
                   enabled=setting("PICASSO_AI").lower() not in ("off", "0", "false"), transport=transport)

    def __repr__(self):  # never reveal the key in logs or tracebacks
        return f"ImageService(model={self.model!r}, configured={bool(self._key)}, enabled={self.enabled})"

    def available(self) -> bool:
        return self.enabled and bool(self._key)

    def capability(self) -> Capability:
        if not self.enabled:
            return Capability(available=False, phase=7, reason="AI drawing is turned off (PICASSO_AI=off). Offline shapes work without a network.")
        if not self._key:
            return Capability(available=False, phase=7, reason="Add OPENAI_API_KEY to .env (see .env.example) and restart to draw requests beyond the offline shapes. Offline shapes need no key.")
        return Capability(available=True, phase=7, reason=f"OpenAI {self.model} draws requests the offline shapes cannot. Each one is sent to OpenAI and billed to your API key; the image is traced into lines on this computer. Offline shapes never use the network.")

    def generate(self, subject: str, detail: str, cancel: threading.Event) -> GeneratedImage:
        if not self.available():
            raise DrawingError("AI_UNAVAILABLE", self.capability().reason, 503)
        if not self._busy.acquire(blocking=False):
            raise DrawingError("AI_BUSY", "An AI drawing is already being generated. Wait for it to finish.", 429)
        try:
            prompt = plotter_prompt(subject, detail)
            body = {"model": self.model, "prompt": prompt, "n": 1, "size": SIZE, "quality": detail,
                    "background": "opaque", "output_format": "jpeg", "output_compression": 92}
            started = time.monotonic()
            response = self._post(body, TIMEOUT_S[detail], cancel)
            data = self._image(response)
            return GeneratedImage(data, AiProvenance(model=self.model, quality=detail, size=SIZE, prompt=prompt,
                                                     image_sha256=hashlib.sha256(data).hexdigest(),
                                                     elapsed_s=round(time.monotonic() - started, 2)))
        finally:
            self._busy.release()

    def _post(self, body: dict, timeout: float, cancel: threading.Event) -> httpx.Response:
        """The blocking request runs on a helper thread so an abandoned request returns at once.
        The provider may still finish (and bill) a request it has already received."""
        result: dict = {}
        def call():
            try:
                with httpx.Client(transport=self._transport, timeout=httpx.Timeout(timeout, connect=10)) as client:
                    result["response"] = client.post(ENDPOINT, json=body, headers={"Authorization": f"Bearer {self._key}"})
            except Exception as exc:
                result["error"] = exc
        worker = threading.Thread(target=call, name="ai-image", daemon=True)
        worker.start()
        while worker.is_alive():
            if cancel.wait(0.1):
                raise DrawingError("GENERATION_CANCELLED", "The AI drawing was cancelled.", 499)
        error = result.get("error")
        if isinstance(error, httpx.TimeoutException):
            raise DrawingError("AI_TIMEOUT", "OpenAI did not answer in time. Try Low detail, or try again shortly.", 504)
        if isinstance(error, httpx.TransportError):
            raise DrawingError("AI_OFFLINE", "OpenAI could not be reached. Check the internet connection; offline shapes such as circles, spirals and mandalas still work.", 503)
        if error is not None:
            raise DrawingError("AI_PROVIDER_ERROR", "The AI request failed unexpectedly. Try again.", 502)
        return result["response"]

    def _image(self, response: httpx.Response) -> bytes:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code != 200:
            error = payload.get("error") if isinstance(payload, dict) else None
            error = error if isinstance(error, dict) else {}
            code = str(error.get("code") or error.get("type") or "")
            detail = " ".join(str(error.get("message") or "").split())[:200].replace(self._key, "…") if self._key else ""
            if response.status_code == 401:
                raise DrawingError("AI_KEY_INVALID", "OpenAI rejected the API key. Check OPENAI_API_KEY in .env, then restart Picasso.", 502)
            if response.status_code == 429 and code == "insufficient_quota":
                raise DrawingError("AI_QUOTA", "The OpenAI account has no remaining quota. Check its billing; offline shapes still work.", 429)
            if response.status_code == 429:
                raise DrawingError("AI_RATE_LIMITED", "OpenAI is rate-limiting requests. Wait a moment and try again.", 429)
            if code in ("moderation_blocked", "content_policy_violation"):
                raise DrawingError("AI_REJECTED", "OpenAI declined this request under its content policy. Describe the drawing differently.", 422)
            if 400 <= response.status_code < 500:
                raise DrawingError("AI_REQUEST_FAILED", f"OpenAI refused the request{': ' + detail if detail else '.'}", 502)
            raise DrawingError("AI_PROVIDER_ERROR", "OpenAI had a temporary problem. Try again shortly.", 502)
        try:
            encoded = payload["data"][0]["b64_json"]
            data = base64.b64decode(encoded, validate=True)
        except (KeyError, IndexError, TypeError, binascii.Error, ValueError) as exc:
            raise DrawingError("AI_RESPONSE_INVALID", "OpenAI returned no usable image. Try again.", 502) from exc
        from .drawing.vectorize import MAX_IMAGE_BYTES  # OpenCV loads with the first trace, not at startup
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise DrawingError("AI_RESPONSE_INVALID", "OpenAI returned an image that cannot be traced. Try again.", 502)
        return data
