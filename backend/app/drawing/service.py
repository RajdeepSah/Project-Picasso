"""Immutable drawing revisions with optional durable storage and a bounded cache."""

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import math
import threading
import uuid

from ..models import Dimensions, DrawingDraft, DrawingSpec, DrawingTransform, GenerateRequest, ImportRequest, RevisionRequest
from .commands import resolve_command
from .errors import DrawingError
from .gcode import encode, parse, verify_roundtrip
from .geometry import Budget, TOLERANCE, generate_geometry
from .importer import import_source as normalize_import

WARNINGS = [
    "Simulation only. No physical machine profile or workspace is verified.",
    "Initial travel assumes a starting position of (0, 0) mm; this is not a hardware position reading.",
    "Draft downloads are unverified, not prepared jobs. Do not execute them until calibration and pen settling are verified.",
    "Draft revisions live in memory and are lost on restart. Download JSON to retain a copy; durable history arrives in Phase 4.",
]
IMAGE_SIZE_MM = 180  # default fit box for a traced image when the caller gives none
IMAGE_DETAIL = {"low": "sparse", "medium": "standard", "high": "dense"}


@dataclass(frozen=True)
class StoredDraft:
    json_bytes: bytes
    gcode_bytes: bytes
    svg_bytes: bytes
    filename: str

    @property
    def size(self):
        return len(self.json_bytes) + len(self.gcode_bytes) + len(self.svg_bytes)


def svg_bytes(draft: DrawingDraft) -> bytes:
    box = draft.preview.bounds
    margin = 5
    width, height = box.width_mm + margin * 2, box.height_mm + margin * 2
    # Values come only from finite validated points. No untrusted SVG/XML input.
    path = " ".join(f"M{s.start[0]:.3f},{-s.start[1]:.3f} L{s.end[0]:.3f},{-s.end[1]:.3f}"
                    for s in draft.preview.segments if s.pen_down)
    metadata = json.dumps({"execution_ready": False, "simulation_start_mm": [0, 0], "gcode_sha256": draft.gcode_sha256})
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.3f}mm" height="{height:.3f}mm" '
            f'viewBox="{box.min_x_mm - margin:.3f} {-box.max_y_mm - margin:.3f} {width:.3f} {height:.3f}">'
            f'<title>Unverified Picasso drawing draft</title><metadata>{metadata}</metadata>'
            f'<path d="{path}" fill="none" stroke="black" stroke-width="0.3" stroke-linecap="round" stroke-linejoin="round"/></svg>').encode()


class DraftService:
    def __init__(self, *, max_drafts=16, max_bytes=32_000_000, repository=None):
        self._items: OrderedDict[str, StoredDraft] = OrderedDict()
        self._lock = threading.Lock()
        self._workers = threading.BoundedSemaphore(2)
        self.max_drafts = max_drafts
        self.max_bytes = max_bytes
        self.repository = repository

    def get(self, revision_id: str) -> DrawingDraft:
        return DrawingDraft.model_validate_json(self.export(revision_id).json_bytes)

    def export(self, revision_id: str) -> StoredDraft:
        with self._lock:
            if self.repository is not None:
                files = self.repository.load(revision_id, "revision")
                draft = DrawingDraft.model_validate_json(files["draft.json"])
                return StoredDraft(files["draft.json"], files["drawing.nc"], files["preview.svg"], f"picasso-{draft.spec.generator}-{draft.revision_id[:8]}-UNVERIFIED")
            if revision_id not in self._items:
                raise DrawingError("DRAFT_NOT_FOUND", "Draft not found. It may have expired or the service restarted. Generate a new drawing.", 404)
            self._items.move_to_end(revision_id)
            return self._items[revision_id]

    def generate(self, request: GenerateRequest, cancel: threading.Event) -> DrawingDraft:
        spec = resolve_command(request.prompt)
        return self._build(spec, DrawingTransform(), request.prompt, cancel)

    def revise(self, revision_id: str, request: RevisionRequest, cancel: threading.Event) -> DrawingDraft:
        parent = self.get(revision_id)
        if parent.spec.generator == 'imported' and request.regenerate:
            raise DrawingError("UNSUPPORTED_REGENERATION", "Imported paths can be resized or transformed; regeneration applies to generated drawings only.")
        spec = (request.spec or parent.spec).model_copy(deep=True)
        if request.regenerate and not request.seed_locked:
            spec.seed = (spec.seed + 1) % 4294967296
        if spec.generator != parent.spec.generator:
            raise DrawingError("INVALID_REVISION", "Use a new command to change drawing generators.")
        return self._build(spec, request.transform or parent.transform, parent.prompt, cancel, parent, parent.import_source)

    def import_drawing(self, request: ImportRequest, cancel: threading.Event) -> DrawingDraft:
        source = normalize_import(request, cancel)
        image = source.dialect == "image"
        box = source.original_bounds
        width, height = max(box.width_mm, .001), max(box.height_mm, .001)
        fit_width, fit_height = request.fit_width_mm, request.fit_height_mm
        if image and fit_width is None and fit_height is None:
            fit_width = fit_height = IMAGE_SIZE_MM  # traced pixels have no physical size
        # Scale uniformly so the drawing fits inside every requested dimension.
        scale = min(fit_width / width if fit_width else math.inf, fit_height / height if fit_height else math.inf)
        if math.isfinite(scale):
            width, height = max(round(width * scale, 3), .001), max(round(height * scale, 3), .001)
        if max(width, height) > 2000:
            raise DrawingError("IMPORT_TOO_LARGE", "Fit the imported drawing to dimensions no larger than 2000 mm.")
        spec = DrawingSpec(generator="imported", dimensions=Dimensions(width_mm=width, height_mm=height),
                           detail=IMAGE_DETAIL[request.detail] if image else "standard")
        centered = request.center_on_origin or image
        transform = DrawingTransform(offset_x_mm=0 if centered else (box.min_x_mm+box.max_x_mm)/2,
                                     offset_y_mm=0 if centered else (box.min_y_mm+box.max_y_mm)/2)
        return self._build(spec, transform, f"Imported {source.filename}", cancel, import_source=source)

    def _build(self, spec, transform, prompt, cancel, parent=None, import_source=None) -> DrawingDraft:
        if not self._workers.acquire(blocking=False):
            raise DrawingError("GENERATION_BUSY", "Two drawings are already being generated. Try again shortly.", 429)
        try:
            budget = Budget(cancel)
            geometry = generate_geometry(spec, transform, budget, import_source.input_strokes if import_source else None)
            code = encode(geometry)
            preview = parse(code, budget=budget)
            verify_roundtrip(geometry, preview)
            title = spec.generator.title()
            if spec.generator == "circle" and spec.dimensions.width_mm != spec.dimensions.height_mm:
                title = "Ellipse"
            draft = DrawingDraft(
                drawing_id=parent.drawing_id if parent else uuid.uuid4().hex,
                revision_id=uuid.uuid4().hex, parent_revision_id=parent.revision_id if parent else None,
                revision=parent.revision + 1 if parent else 1, title=title, prompt=prompt,
                spec=spec, transform=transform, geometry=geometry, preview=preview,
                gcode=code, gcode_sha256=hashlib.sha256(code.encode("ascii")).hexdigest(),
                chord_tolerance_mm=TOLERANCE[spec.detail], warnings=([*WARNINGS[:3], "Saved automatically in local history."] if self.repository else WARNINGS),
                import_source=import_source,
            )
            item = StoredDraft(draft.model_dump_json().encode(), code.encode("ascii"), svg_bytes(draft),
                               f"picasso-{spec.generator}-{draft.revision_id[:8]}-UNVERIFIED")
            if item.size > self.max_bytes:
                raise DrawingError("DRAWING_TOO_COMPLEX", "Draft exceeds the session memory limit. Reduce detail.")
            budget.check()
            if self.repository is not None:
                self.repository.save(draft.revision_id, "revision", {"draft.json": item.json_bytes, "drawing.nc": item.gcode_bytes, "preview.svg": item.svg_bytes},
                                     {"drawing_id": draft.drawing_id, "parent_id": draft.parent_revision_id, "ordinal": draft.revision,
                                      "title": draft.title, "prompt": draft.prompt, "generator": draft.spec.generator})
            with self._lock:
                self._items[draft.revision_id] = item
                while len(self._items) > self.max_drafts or sum(value.size for value in self._items.values()) > self.max_bytes:
                    self._items.popitem(last=False)
            return draft
        finally:
            self._workers.release()
