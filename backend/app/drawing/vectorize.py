"""Raster image to pen strokes: OpenCV edge tracing with bounded, travel-ordered output."""

from dataclasses import dataclass
import os
import threading

import numpy as np

# Refuse decompression bombs before OpenCV allocates them (50 MP is far above any useful trace).
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(50_000_000))
import cv2  # noqa: E402

from .errors import DrawingError

MAX_IMAGE_BYTES = 8_000_000


@dataclass(frozen=True)
class Level:
    side: int          # longest traced side in pixels
    blur: int          # edge-preserving smoothing diameter
    contrast: int      # drawings: how much darker than its surroundings ink must be (0-255)
    edges: float       # photographs: Canny threshold as a multiple of the Otsu level
    epsilon: float     # Douglas-Peucker tolerance in pixels
    min_length: float  # shortest stroke kept, in pixels
    points: int        # vertex budget (the drawing engine allows 20,000)
    strokes: int       # stroke budget (the drawing engine allows 1,000)


LEVELS = {
    "low": Level(side=480, blur=9, contrast=24, edges=1.4, epsilon=1.5, min_length=30, points=3500, strokes=200),
    "medium": Level(side=640, blur=7, contrast=14, edges=1.0, epsilon=1.0, min_length=16, points=9000, strokes=550),
    "high": Level(side=900, blur=5, contrast=8, edges=0.7, epsilon=0.6, min_length=12, points=19000, strokes=1000),
}
JOIN_PX = 2.0  # consecutive strokes closer than this are drawn without lifting the pen


def _check(cancel: threading.Event):
    if cancel.is_set():
        raise DrawingError("GENERATION_CANCELLED", "Image import was cancelled.", 499)


def _grayscale(data: bytes) -> np.ndarray:
    buffer = np.frombuffer(data, np.uint8)
    # Formats that carry transparency are composited onto white paper; everything
    # else decodes straight to luma, which also honours JPEG EXIF orientation.
    alpha_capable = data[:8] == b"\x89PNG\r\n\x1a\n" or (data[:4] == b"RIFF" and data[8:12] == b"WEBP") or data[:4] == b"GIF8"
    try:
        image = cv2.imdecode(buffer, cv2.IMREAD_UNCHANGED if alpha_capable else cv2.IMREAD_GRAYSCALE)
    except cv2.error:
        image = None
    if image is None or image.size == 0:
        raise DrawingError("INVALID_IMPORT", "This image could not be read. Use a PNG, JPG, WEBP, BMP or TIFF file.")
    if image.dtype != np.uint8:
        image = cv2.normalize(image, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
    if image.ndim == 2:
        return image
    if image.shape[2] == 4:
        alpha = image[:, :, 3:4].astype(np.float32) / 255
        image = (image[:, :, :3] * alpha + 255 * (1 - alpha)).astype(np.uint8)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _centrelines(gray: np.ndarray, level: Level) -> np.ndarray:
    """A one-pixel skeleton of the image's ink: pixels clearly darker than their
    neighbourhood. Thinning turns each inked line into a single centreline."""
    height, width = gray.shape
    scale = level.side / max(height, width)
    if scale != 1:
        size = (max(1, round(width * min(scale, 4))), max(1, round(height * min(scale, 4))))
        gray = cv2.resize(gray, size, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    smooth = cv2.bilateralFilter(gray, level.blur, 50, level.blur)
    if np.count_nonzero(smooth >= 200) >= smooth.size * .5:
        # Mostly light paper: a drawing, logo or diagram. Trace the ink itself.
        block = max(level.side // 24, 5) | 1
        lines = cv2.adaptiveThreshold(smooth, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block, level.contrast)
    else:
        # A photograph: subjects may be lighter or darker than their surroundings,
        # so trace region boundaries instead.
        otsu, _ = cv2.threshold(smooth, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        high = float(np.clip(otsu * level.edges, 30, 250))
        lines = cv2.Canny(smooth, high * .4, high, L2gradient=True)
    return cv2.ximgproc.thinning(lines)


def _smooth(points: np.ndarray, closed: bool, window=5) -> np.ndarray:
    """Moving average along the path, removing the skeleton's pixel staircase."""
    if len(points) <= window:
        return points
    pad = window // 2
    padded = np.pad(points, ((pad, pad), (0, 0)), mode="wrap" if closed else "edge")
    kernel = np.full(window, 1 / window, np.float32)
    result = np.column_stack([np.convolve(padded[:, axis], kernel, "valid") for axis in (0, 1)])
    if not closed:
        result[0], result[-1] = points[0], points[-1]  # junctions stay exactly shared
    return result.astype(np.float32)


def _trace(edges: np.ndarray, level: Level) -> list[np.ndarray]:
    """Skeleton pixels to simplified polylines. Border following walks a thin line out
    and back, so each pixel is kept only the first time any contour reaches it."""
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    seen = np.zeros(edges.shape, bool)
    paths = []
    for contour in contours:
        points = contour[:, 0, :]
        if len(points) < 2:
            continue
        ids = points[:, 1] * edges.shape[1] + points[:, 0]
        fresh = np.zeros(len(points), bool)
        fresh[np.unique(ids, return_index=True)[1]] = True
        fresh &= ~seen[points[:, 1], points[:, 0]]
        seen[points[:, 1], points[:, 0]] = True
        if fresh.all():
            paths.append((points, True))
            continue
        # Rotate so the cyclic contour starts on a revisited pixel, then split into fresh runs.
        shift = int(np.argmin(fresh))
        points, fresh = np.roll(points, -shift, axis=0), np.roll(fresh, -shift)
        change = np.flatnonzero(np.diff(fresh.astype(np.int8)))
        for start, stop in zip(change[::2] + 1, change[1::2] + 1):
            # Keep the revisited neighbour on each side so strokes meet at junctions.
            paths.append((points[start - 1:stop + 1], False))
        if fresh[-1] and len(change) % 2:
            paths.append((np.vstack([points[change[-1]:], points[:1]]), False))
    strokes = []
    for points, closed in paths:
        if cv2.arcLength(points.reshape(-1, 1, 2), closed) < level.min_length:
            continue
        curve = _smooth(points.astype(np.float32), closed).reshape(-1, 1, 2)
        simple = cv2.approxPolyDP(curve, level.epsilon, closed)[:, 0, :].astype(np.float64)
        if closed:
            simple = np.vstack([simple, simple[:1]])
        if len(simple) >= 2:
            strokes.append(simple)
    return strokes


def _budget(strokes: list[np.ndarray], level: Level) -> list[np.ndarray]:
    """Keep the longest strokes that fit the vertex and stroke budgets."""
    lengths = [float(np.linalg.norm(np.diff(stroke, axis=0), axis=1).sum()) for stroke in strokes]
    kept, points = [], 0
    for index in np.argsort(lengths)[::-1]:
        if len(kept) >= level.strokes:
            break
        if points + len(strokes[index]) <= level.points:
            kept.append(strokes[index]); points += len(strokes[index])
    return kept


def _order(strokes: list[np.ndarray], start: np.ndarray, cancel: threading.Event) -> list[np.ndarray]:
    """Greedy nearest-neighbour ordering. Open strokes may be reversed; closed loops
    may start at any vertex. Strokes that begin where the last ended are joined."""
    entries, owner, offset, spans = [], [], [], []
    for index, stroke in enumerate(strokes):
        closed = len(stroke) > 3 and np.array_equal(stroke[0], stroke[-1])
        candidates = stroke[:-1] if closed else stroke[[0, -1]]
        spans.append((len(owner), len(owner) + len(candidates), closed))
        entries.append(candidates); owner.extend([index] * len(candidates))
        offset.extend(range(len(candidates)) if closed else (0, -1))
    coords, owner, offset = np.vstack(entries), np.array(owner), np.array(offset)
    alive = np.ones(len(coords), bool)
    cursor, ordered = start, []
    for step in range(len(strokes)):
        if step % 64 == 0:
            _check(cancel)
        distance = np.einsum("ij,ij->i", coords - cursor, coords - cursor)
        distance[~alive] = np.inf
        pick = int(np.argmin(distance))
        index, (low, high, closed) = owner[pick], spans[owner[pick]]
        alive[low:high] = False
        stroke = strokes[index]
        if closed:
            path = np.vstack([stroke[offset[pick]:-1], stroke[:offset[pick] + 1]])
        else:
            path = stroke if offset[pick] == 0 else stroke[::-1]
        if ordered and distance[pick] <= JOIN_PX ** 2:
            ordered[-1] = np.vstack([ordered[-1], path[1:] if np.array_equal(path[0], cursor) else path])
        else:
            ordered.append(path)
        cursor = path[-1]
    return ordered


def image_strokes(data: bytes, detail: str, cancel: threading.Event) -> list[list[tuple[float, float]]]:
    """Trace an encoded image into ordered polylines in pixel units, with Y pointing up."""
    if len(data) > MAX_IMAGE_BYTES:
        raise DrawingError("IMPORT_TOO_LARGE", "Images must be 8 MB or smaller.")
    level = LEVELS[detail]
    gray = _grayscale(data)
    _check(cancel)
    edges = _centrelines(gray, level)
    _check(cancel)
    strokes = _budget(_trace(edges, level), level)
    if not strokes:
        raise DrawingError("DEGENERATE_PATH", "No outlines were found in this image. Try a higher detail level or an image with clearer contrast.")
    _check(cancel)
    height, width = edges.shape
    ordered = _order(strokes, np.array([width / 2, height / 2]), cancel)
    return [[(float(x), float(-y)) for x, y in stroke] for stroke in ordered]
