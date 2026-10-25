"""Pure geometry: analytic circles, cubic curves and bounded flattening in mm."""

from dataclasses import dataclass
import math
import random
import threading
import time

from ..models import DrawingSpec, DrawingTransform, PolylineDrawing, Stroke
from .errors import DrawingError

Point = tuple[float, float]
MAX_POINTS = 20000
MAX_STROKES = 1000
MAX_COORDINATE = 5000  # Computational preview limit, NOT a physical machine envelope.
MAX_PATH_MM = 250000
TOLERANCE = {"sparse": 0.2, "standard": 0.08, "dense": 0.025}


class Budget:
    def __init__(self, cancel: threading.Event | None = None, seconds: float = 3):
        self.deadline = time.monotonic() + seconds
        self.cancel = cancel or threading.Event()
        self.points = 0

    def check(self):
        if self.cancel.is_set():
            raise DrawingError("GENERATION_CANCELLED", "Drawing generation was cancelled.", 499)
        if time.monotonic() > self.deadline:
            raise DrawingError("GENERATION_TIMEOUT", "Generation took too long. Reduce dimensions or detail.", 422)

    def point(self):
        self.check()
        self.points += 1
        if self.points > MAX_POINTS:
            raise DrawingError("DRAWING_TOO_COMPLEX", "This drawing exceeds 20,000 points. Reduce size, detail, petals or turns.")


@dataclass(frozen=True)
class Curve:
    start: Point
    end: Point
    controls: tuple[Point, Point] | None = None


@dataclass(frozen=True)
class Circle:
    center: Point = (0, 0)
    radius: float = 1
    multiple: int = 4


Contour = list[Curve] | Circle


def rotate(point: Point, angle: float) -> Point:
    c, s = math.cos(angle), math.sin(angle)
    return point[0] * c - point[1] * s, point[0] * s + point[1] * c


def mapped(curves: list[Curve], fn) -> list[Curve]:
    return [Curve(fn(curve.start), fn(curve.end), tuple(fn(p) for p in curve.controls) if curve.controls else None) for curve in curves]


def polygon(points: list[Point], closed: bool = True) -> list[Curve]:
    vertices = points + [points[0]] if closed else points
    return [Curve(a, b) for a, b in zip(vertices, vertices[1:])]


def primitives(spec: DrawingSpec) -> list[Contour]:
    rng = random.Random(spec.seed)
    level = ("sparse", "standard", "dense").index(spec.detail)
    name = spec.generator
    if name == "circle":
        return [Circle()]
    if name == "rectangle":
        return [polygon([(-1, -1), (1, -1), (1, 1), (-1, 1)])]
    if name == "spiral":
        turns = spec.parameters.turns if spec.parameters.turns is not None else 4 + level
        total = math.tau * turns
        count = max(8, math.ceil(turns * 16))
        phase = rng.random() * math.tau
        def value(t):
            return t / total * math.cos(t + phase), t / total * math.sin(t + phase)
        def derivative(t):
            return ((math.cos(t + phase) - t * math.sin(t + phase)) / total,
                    (math.sin(t + phase) + t * math.cos(t + phase)) / total)
        curves = []
        # Hermite cubics define the generated spiral; flattening is bounded
        # relative to these curves, not to an unstored ideal analytic spiral.
        for index in range(count):
            t0, t1 = index * total / count, (index + 1) * total / count
            a, b = value(t0), value(t1)
            da, db = derivative(t0), derivative(t1)
            step = (t1 - t0) / 3
            curves.append(Curve(a, b, ((a[0] + da[0] * step, a[1] + da[1] * step),
                                        (b[0] - db[0] * step, b[1] - db[1] * step))))
        return [curves]
    if name == "butterfly":
        fullness = 0.88 + rng.random() * .24
        wing = [Curve((0, .12), (.87, .02), ((.7 * fullness, 1.45), (1.5, 1.05))),
                Curve((.87, .02), (.18, -.28), ((1.05, -.35), (.76 * fullness, -1.1))),
                Curve((.18, -.28), (0, .12), ((.08, -.18), (0, -.2)))]
        contours: list[Contour] = [wing, mapped(wing, lambda p: (-p[0], p[1]))]
        contours += [mapped([Curve((-.055, 0), (.055, 0), ((-.055, .5), (.055, .5))),
                             Curve((.055, 0), (-.055, 0), ((.055, -.5), (-.055, -.5)))], lambda p: p)]
        for side in (-1, 1):
            contours.append([Curve((side * .03, .2), (side * .27, .55), ((side * .08, .55), (side * .3, .7)))])
            for index in range(2 + level):
                t = (index + 1) / (3 + level)
                vein = Curve((.08, .07), (.3 + .48 * t, .1 + .52 * (1 - t)), ((.3, .25), (.4 + .2 * t, .7)))
                contours.append(mapped([vein], lambda p, side=side: (p[0] * side, p[1])))
        return contours
    symmetry = spec.parameters.symmetry or spec.parameters.petals or (12 if name == "mandala" else 8)
    if name == "mandala":
        contours = [Circle(radius=radius, multiple=math.lcm(4, symmetry)) for radius in (.13, .27, .98, 1)]
        for layer in range(2 + level):
            inner = .18 + layer * .12
            outer = .96 - layer * .14
            width = (.7 + rng.random() * .35) * outer * math.sin(math.pi / symmetry)
            petal = [Curve((0, inner), (0, outer), ((-width, inner + .12), (-width, outer - .08))),
                     Curve((0, outer), (0, inner), ((width, outer - .08), (width, inner + .12)))]
            for index in range(symmetry):
                angle = math.tau * (index + (.5 if layer % 2 else 0)) / symmetry
                contours.append(mapped(petal, lambda p, angle=angle: rotate(p, angle)))
        return contours
    # Interlocking, nested polygon/star paths; seed controls the whole motif.
    phase = rng.random() * math.pi / symmetry
    contours = [Circle(multiple=math.lcm(4, symmetry))]
    for layer in range(3 + level * 2):
        radius = .95 - layer * .1
        points = [rotate((radius, 0), phase + math.tau * i / symmetry + layer * math.pi / symmetry)
                  for i in range(symmetry)]
        contours.append(polygon(points))
        if layer % 2 == 0:
            star = [rotate((radius * (1 if i % 2 == 0 else .45), 0), phase + math.pi * i / symmetry)
                    for i in range(symmetry * 2)]
            contours.append(polygon(star))
    return contours


def cubic_value(p0, p1, p2, p3, t):
    u = 1 - t
    return u**3 * p0 + 3 * u**2 * t * p1 + 3 * u * t**2 * p2 + t**3 * p3


def curve_bounds(contours: list[Contour]) -> tuple[float, float, float, float]:
    xs, ys = [], []
    for contour in contours:
        if isinstance(contour, Circle):
            xs.extend([contour.center[0] - contour.radius, contour.center[0] + contour.radius])
            ys.extend([contour.center[1] - contour.radius, contour.center[1] + contour.radius])
            continue
        for curve in contour:
            for axis, values in ((0, xs), (1, ys)):
                p0, p3 = curve.start[axis], curve.end[axis]
                values.extend([p0, p3])
                if curve.controls:
                    p1, p2 = curve.controls[0][axis], curve.controls[1][axis]
                    a, b, c = -p0 + 3 * p1 - 3 * p2 + p3, 2 * (p0 - 2 * p1 + p2), p1 - p0
                    roots = []
                    if abs(a) < 1e-12:
                        if abs(b) > 1e-12:
                            roots = [-c / b]
                    elif b * b - 4 * a * c >= 0:
                        d = math.sqrt(max(0, b * b - 4 * a * c))
                        roots = [(-b - d) / (2 * a), (-b + d) / (2 * a)]
                    values.extend(cubic_value(p0, p1, p2, p3, t) for t in roots if 0 < t < 1)
    return min(xs), min(ys), max(xs), max(ys)


def segment_distance(point: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == dy == 0:
        return math.dist(point, a)
    t = max(0, min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.dist(point, (a[0] + t * dx, a[1] + t * dy))


def flatten_cubic(a: Point, b: Point, c: Point, d: Point, tolerance: float, points: list[Point], budget: Budget, depth=0):
    budget.check()
    if max(segment_distance(b, a, d), segment_distance(c, a, d)) <= tolerance:
        budget.point()
        points.append(d)
        return
    if depth >= 18:
        raise DrawingError("DRAWING_TOO_COMPLEX", "Curve detail exceeds the subdivision limit. Reduce size or detail.")
    def mid(p, q):
        return (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
    ab, bc, cd = mid(a, b), mid(b, c), mid(c, d)
    abc, bcd = mid(ab, bc), mid(bc, cd)
    center = mid(abc, bcd)
    flatten_cubic(a, ab, abc, center, tolerance, points, budget, depth + 1)
    flatten_cubic(center, bcd, cd, d, tolerance, points, budget, depth + 1)


def validate_strokes(strokes: list[list[Point]]):
    if not strokes or len(strokes) > MAX_STROKES or sum(map(len, strokes)) > MAX_POINTS:
        raise DrawingError("DRAWING_TOO_COMPLEX", "Drawing exceeds the path budget.")
    distance = 0.0
    for stroke in strokes:
        if len(stroke) < 2:
            raise DrawingError("DEGENERATE_PATH", "Drawing is too small after rounding. Increase its dimensions.")
        for x, y in stroke:
            if not math.isfinite(x) or not math.isfinite(y) or max(abs(x), abs(y)) > MAX_COORDINATE:
                raise DrawingError("PREVIEW_LIMIT_EXCEEDED", "Coordinates exceed the computational preview limit of ±5000 mm. This is not a verified machine envelope.")
        length = sum(math.dist(a, b) for a, b in zip(stroke, stroke[1:]))
        if length <= 0:
            raise DrawingError("DEGENERATE_PATH", "Each stroke needs a nonzero drawing segment.")
        distance += length
    if distance <= 0 or distance > MAX_PATH_MM:
        raise DrawingError("DRAWING_TOO_COMPLEX", "Drawing length must be greater than zero and at most 250 metres.")


def generate_geometry(spec: DrawingSpec, transform: DrawingTransform, budget: Budget) -> PolylineDrawing:
    budget.check()
    contours = primitives(spec)
    if len(contours) > MAX_STROKES:
        raise DrawingError("DRAWING_TOO_COMPLEX", "Too many strokes.")
    left, bottom, right, top = curve_bounds(contours)
    if right - left <= 1e-9 or top - bottom <= 1e-9:
        raise DrawingError("DEGENERATE_PATH", "The requested drawing has no two-dimensional extent.")
    sx, sy = spec.dimensions.width_mm / (right - left), spec.dimensions.height_mm / (top - bottom)
    if transform.preserve_aspect:
        sx = sy = min(sx, sy)
    center = ((left + right) / 2, (top + bottom) / 2)
    def world(point: Point) -> Point:
        x, y = rotate(((point[0] - center[0]) * sx, (point[1] - center[1]) * sy), math.radians(transform.rotation_degrees))
        return x + transform.offset_x_mm, y + transform.offset_y_mm
    tolerance = TOLERANCE[spec.detail]
    strokes = []
    for contour in contours:
        budget.check()
        points: list[Point] = []
        if isinstance(contour, Circle):
            radius_bound = contour.radius * max(sx, sy)
            step = 2 * math.acos(max(-1, 1 - min(tolerance / radius_bound, 1)))
            count = max(contour.multiple, math.ceil(math.tau / step / contour.multiple) * contour.multiple)
            for index in range(count):
                budget.point()
                t = math.tau * index / count
                points.append(world((contour.center[0] + contour.radius * math.cos(t), contour.center[1] + contour.radius * math.sin(t))))
            budget.point()
            points.append(points[0])
        else:
            budget.point()
            points.append(world(contour[0].start))
            for curve in contour:
                if curve.controls:
                    flatten_cubic(world(curve.start), world(curve.controls[0]), world(curve.controls[1]), world(curve.end), tolerance, points, budget)
                else:
                    budget.point()
                    points.append(world(curve.end))
        rounded = []
        for x, y in points:
            point = (round(x, 3) or 0.0, round(y, 3) or 0.0)
            if not rounded or point != rounded[-1]:
                rounded.append(point)
        strokes.append(rounded)
    # Validate rounded geometry too: sub-micron strokes can disappear entirely.
    validate_strokes(strokes)
    budget.check()
    return PolylineDrawing(source=spec, strokes=[Stroke(points=points, closed=points[0] == points[-1]) for points in strokes])
