"""Small documented English grammar, deliberately not an AI/chat parser."""

import re

from pydantic import ValidationError

from ..models import Dimensions, DrawingSpec, GeneratorParameters
from .errors import DrawingError

NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
SUBJECTS = {"circle": "circle", "ellipse": "circle", "oval": "circle", "rectangle": "rectangle",
            "square": "rectangle", "spiral": "spiral", "butterfly": "butterfly", "mandala": "mandala",
            "geometric pattern": "pattern", "pattern": "pattern"}
FILLER = {"draw", "create", "make", "a", "an", "the", "beautiful", "lovely", "please", "me", "with",
          "and", "of", "at", "by", "size", "wide", "width", "high", "height", "tall", "diameter",
          "radius", "mm", "millimeters", "millimetres", "petals", "turns", "symmetry", "seed",
          "simple", "sparse", "standard", "intricate", "complex", "dense"}


def resolve_command(prompt: str, default_detail: str = "standard") -> DrawingSpec:
    text = prompt.lower().replace("×", "x")
    # Prefer the longest match so "geometric pattern" is one subject.
    matches = list(re.finditer(r"\b(?:geometric pattern|circle|ellipse|oval|rectangle|square|spiral|butterfly|mandala|pattern)\b", text))
    if len(matches) != 1:
        raise DrawingError("UNSUPPORTED_COMMAND", "Choose one drawing: circle, ellipse, rectangle, spiral, butterfly, mandala or geometric pattern. Example: Draw a mandala with 12 petals, 120 mm wide.")
    subject = matches[0].group()
    rest = text[:matches[0].start()] + " " + text[matches[0].end():]
    # Reject unrecognized words rather than silently discarding requested meaning.
    words = re.findall(r"[a-z]+", re.sub(NUMBER, " ", rest))
    unknown = set(words) - FILLER - {"x"}
    if unknown:
        raise DrawingError("UNSUPPORTED_COMMAND", "That modifier is not supported offline. Use millimetres, width/height, petals, turns, symmetry, seed, or simple/standard/intricate. Rotation and placement are available in the inspector.")
    sizes = list(re.finditer(rf"({NUMBER})\s*x\s*({NUMBER})(?:\s*(?:mm|millimeters|millimetres))?\b", rest))
    if len(sizes) > 1:
        raise DrawingError("AMBIGUOUS_COMMAND", "Specify the drawing dimensions only once.")
    width, height = (120.0, 90.0) if subject == "butterfly" else (120.0, 80.0) if subject in ("rectangle", "ellipse", "oval") else (120.0, 120.0)
    consumed = [(match.start(), match.end()) for match in sizes]
    if sizes:
        width, height = map(float, sizes[0].groups())
    parameters = {}
    seen = set()
    # Named attributes accept either "120 mm wide" or "width 120 mm".
    attribute = re.compile(rf"(?:(?P<value>{NUMBER})\s*(?:mm\s*)?(?P<name>wide|width|high|height|tall|diameter|radius|petals|turns|symmetry|seed)\b|\b(?P<name2>width|height|diameter|radius|petals|turns|symmetry|seed)\s+(?P<value2>{NUMBER})\s*(?:mm\b)?)")
    for match in attribute.finditer(rest):
        name = match.group("name") or match.group("name2")
        name = {"wide": "width", "high": "height", "tall": "height"}.get(name, name)
        if name in seen:
            raise DrawingError("AMBIGUOUS_COMMAND", f"Specify {name} only once.")
        seen.add(name)
        value = float(match.group("value") or match.group("value2"))
        consumed.append((match.start(), match.end()))
        if name == "width":
            width = value
        elif name == "height":
            height = value
        elif name in ("radius", "diameter"):
            if subject not in ("circle", "ellipse", "oval"):
                raise DrawingError("UNSUPPORTED_PARAMETER", "Radius and diameter are supported for circles/ellipses only.")
            width = height = value * (2 if name == "radius" else 1)
        elif name in ("seed", "petals", "symmetry"):
            if not value.is_integer():
                raise DrawingError("INVALID_PARAMETER", f"{name.title()} must be a whole number.")
            parameters[name] = int(value)
        else:
            parameters[name] = value
    dimension_names = seen & {"width", "height", "radius", "diameter"}
    if (sizes and dimension_names) or (seen & {"radius", "diameter"} and len(dimension_names) > 1):
        raise DrawingError("AMBIGUOUS_COMMAND", "Use one dimension format: width/height, W x H, radius, or diameter.")
    if "width" in seen and "height" not in seen and not sizes:
        height = width if subject not in ("rectangle", "ellipse", "oval", "butterfly") else width * (0.75 if subject == "butterfly" else 2 / 3)
    if "height" in seen and "width" not in seen and not sizes:
        width = height if subject not in ("rectangle", "ellipse", "oval", "butterfly") else height / (0.75 if subject == "butterfly" else 2 / 3)
    remaining = list(rest)
    for start, end in consumed:
        remaining[start:end] = " " * (end - start)
    if re.search(r"\b(?:width|wide|height|high|tall|radius|diameter|petals|turns|symmetry|seed)\b", "".join(remaining)):
        raise DrawingError("AMBIGUOUS_COMMAND", "Give each named parameter a value, such as width 120 mm or seed 7.")
    if re.search(r"\d", "".join(remaining)):
        raise DrawingError("AMBIGUOUS_COMMAND", "Give each number a meaning, such as 120 mm wide, 12 petals, or seed 7.")
    detail_sets = [{"simple", "sparse"}, {"standard"}, {"intricate", "complex", "dense"}]
    detail_matches = [i for i, group in enumerate(detail_sets) if group & set(words)]
    if len(detail_matches) > 1:
        raise DrawingError("AMBIGUOUS_COMMAND", "Choose one detail level: simple, standard or intricate.")
    detail = ("sparse", "standard", "dense")[detail_matches[0]] if detail_matches else default_detail
    seed = parameters.pop("seed", 0)
    try:
        return DrawingSpec(generator=SUBJECTS[subject], dimensions=Dimensions(width_mm=width, height_mm=height),
                           parameters=GeneratorParameters(**parameters), seed=seed, detail=detail)
    except ValidationError as exc:
        raise DrawingError("INVALID_PARAMETER", "Use positive dimensions up to 2000 mm, 3–64 petals, 2–64 symmetry, up to 100 turns, and a seed from 0 to 4294967295. Parameters must apply to the chosen drawing.") from exc
