"""Font glyph outlines as flat polygons, for building text geometry directly.

Fusion's SketchText API can fail to generate glyph curves (it produces empty
geometry in current builds), so the add-in builds title text itself: glyph
contours are read straight from a system TrueType font by `truetype.py`,
flattened to polygons here, and turned into BRep faces by `qr_plate_core`.

Output coordinate space: font units scaled so the em size equals 1.0, y up,
baseline at y=0, pen advancing +x. Callers scale by the desired text height.
"""

import os
import struct

import truetype

# Preferred faces, first existing + parsable one wins. Bold faces print far
# better at small sizes than regular weights.
FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Verdana Bold.ttf",
    "/System/Library/Fonts/Supplemental/Tahoma Bold.ttf",
    "/System/Library/Fonts/Geneva.ttf",
    # Windows
    "C:/Windows/Fonts/ariblk.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/verdanab.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/tahomabd.ttf",
]

_BEZIER_STEPS = 10

_font_cache = {}


def available_fonts():
    """Candidate font paths that exist on this machine."""
    return [path for path in FONT_CANDIDATES if os.path.exists(path)]


def _load(path=None):
    if path:
        candidates = [path]
    else:
        candidates = available_fonts()
    if not candidates:
        raise RuntimeError("No usable title font found on this system")

    errors = []
    for candidate in candidates:
        if candidate in _font_cache:
            return _font_cache[candidate]
        try:
            font = truetype.TrueTypeFont(candidate)
        except (ValueError, OSError, struct.error) as err:
            errors.append("{}: {}".format(os.path.basename(candidate), err))
            continue
        _font_cache[candidate] = font
        return font
    raise RuntimeError("No readable title font found (" + "; ".join(errors) + ")")


def _flatten_quadratic(p0, control, p1, out):
    for i in range(1, _BEZIER_STEPS + 1):
        t = i / _BEZIER_STEPS
        mt = 1 - t
        out.append(
            (
                mt * mt * p0[0] + 2 * mt * t * control[0] + t * t * p1[0],
                mt * mt * p0[1] + 2 * mt * t * control[1] + t * t * p1[1],
            )
        )


def _contour_to_polygon(points):
    """Flatten one TrueType contour of (x, y, on_curve) into a polygon.

    Consecutive off-curve points imply an on-curve midpoint between them.
    """
    if not points:
        return []

    # Rotate so the contour starts on an on-curve point; if the contour is all
    # off-curve, start at the implied midpoint of the last and first points.
    start_index = next((i for i, p in enumerate(points) if p[2]), None)
    if start_index is None:
        first, last = points[0], points[-1]
        start = ((first[0] + last[0]) / 2.0, (first[1] + last[1]) / 2.0)
        ordered = points[:]
    else:
        ordered = points[start_index:] + points[:start_index]
        start = (ordered[0][0], ordered[0][1])
        ordered = ordered[1:]

    polygon = [start]
    current = start
    pending_control = None
    for x, y, on_curve in ordered:
        if on_curve:
            if pending_control is None:
                polygon.append((x, y))
            else:
                _flatten_quadratic(current, pending_control, (x, y), polygon)
                pending_control = None
            current = (x, y)
        else:
            if pending_control is not None:
                midpoint = (
                    (pending_control[0] + x) / 2.0,
                    (pending_control[1] + y) / 2.0,
                )
                _flatten_quadratic(current, pending_control, midpoint, polygon)
                current = midpoint
            pending_control = (x, y)

    # Close the contour back to its start
    if pending_control is not None:
        _flatten_quadratic(current, pending_control, start, polygon)
    if len(polygon) > 2 and _dist2(polygon[0], polygon[-1]) < 1e-12:
        polygon.pop()
    return polygon if len(polygon) >= 3 else []


def _dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _point_in_polygon(point, polygon):
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _interior_point(polygon):
    """A point that is inside the polygon, for nesting tests."""
    for i in range(len(polygon)):
        a, b, c = polygon[i], polygon[(i + 1) % len(polygon)], polygon[(i + 2) % len(polygon)]
        candidate = ((a[0] + c[0]) / 2.0, (a[1] + c[1]) / 2.0)
        if _point_in_polygon(candidate, polygon):
            return candidate
        candidate = ((a[0] + b[0] + c[0]) / 3.0, (a[1] + b[1] + c[1]) / 3.0)
        if _point_in_polygon(candidate, polygon):
            return candidate
    return polygon[0]


def _group_contours(contours):
    """Group contours into (outer, [holes]) by even-odd nesting depth."""
    probes = [_interior_point(contour) for contour in contours]
    depths = []
    for i, _ in enumerate(contours):
        depth = sum(
            1
            for j, other in enumerate(contours)
            if j != i and _point_in_polygon(probes[i], other)
        )
        depths.append(depth)

    groups = []
    for i, contour in enumerate(contours):
        if depths[i] % 2:
            continue
        holes = [
            other
            for j, other in enumerate(contours)
            if depths[j] == depths[i] + 1 and _point_in_polygon(probes[j], contour)
        ]
        groups.append((contour, holes))
    return groups


def text_polygons(text, font_path=None):
    """Lay out `text` and return (groups, width) in em units.

    groups: list of (outer_polygon, [hole_polygons]) per filled region.
    width: total advance width of the string in em units.
    Polygons are lists of (x, y) with baseline y=0 and em size 1.0.
    """
    font = _load(font_path)
    scale = 1.0 / font.units_per_em

    contours = []
    pen_x = 0.0
    for char in text:
        glyph_id = font.glyph_id(char)
        if glyph_id is None:
            pen_x += 0.5  # unmapped character: leave a half-em gap
            continue
        for contour in font.glyph_contours(glyph_id):
            polygon = _contour_to_polygon(contour)
            if polygon:
                contours.append([(x * scale + pen_x, y * scale) for x, y in polygon])
        pen_x += font.advance(glyph_id) * scale
    return _group_contours(contours), pen_x
