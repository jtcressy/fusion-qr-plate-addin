"""Geometry core for the QR Plate add-in.

Dialog-independent so it can be driven by the add-in UI or tested headlessly.
All lengths are Fusion internal units (cm) unless a name says otherwise.
"""

import json
import os
import sys

import adsk.core
import adsk.fusion

_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

import segno  # vendored in ./lib

import payloads
from payloads import MODES, SECURITY_MAP, build_payload

PARAMETRIC = adsk.fusion.DesignTypes.ParametricDesignType

ATTR_GROUP = "QRPlate"
# Documents created by the pre-rename add-in stored their parameters and the
# component marker under this group; still read (and clean up) both.
LEGACY_ATTR_GROUPS = ("WiFiQRPlate",)


def _attr_groups():
    return (ATTR_GROUP,) + LEGACY_ATTR_GROUPS

DEFAULTS = dict(payloads.FIELD_DEFAULTS)
DEFAULTS.update({
    "title": "",
    "title_h": 0.5,   # cm
    "plate_w": 4.0,   # cm
    "base_h": 0.42,   # cm
    "code_h": 0.08,   # cm
    "corner_r": 0.3,  # cm
    "chamfer": 0.06,  # cm
    "quiet": 4,       # modules
    "error": "M",
})


def qr_matrix(payload, error):
    qr = segno.make_qr(payload, error=error.lower())
    return [list(row) for row in qr.matrix]


def load_params(design):
    params = dict(DEFAULTS)
    for group in _attr_groups():
        attr = design.attributes.itemByName(group, "params")
        if not attr:
            continue
        try:
            params.update(json.loads(attr.value))
        except ValueError:
            continue
        break
    return params


def save_params(design, params):
    design.attributes.add(ATTR_GROUP, "params", json.dumps(params))


def _is_ours(entity):
    try:
        return any(
            entity.attributes.itemByName(group, "marker") for group in _attr_groups()
        )
    except (AttributeError, RuntimeError):
        return False  # not every timeline entity supports attributes


def mark(entity):
    try:
        entity.attributes.add(ATTR_GROUP, "marker", "1")
    except (AttributeError, RuntimeError):
        pass


def delete_previous(design):
    root = design.rootComponent
    for occ in [occ for occ in root.occurrences if _is_ours(occ.component)]:
        occ.deleteMe()

    # In a parametric design bodies are feature output: BRepBody.deleteMe()
    # silently does nothing, so the previous plate has to be removed by
    # deleting the timeline features that built it (newest first).
    timeline = design.timeline if design.designType == PARAMETRIC else None
    if timeline:
        for index in range(timeline.count - 1, -1, -1):
            entity = timeline.item(index).entity
            if _is_ours(entity):
                entity.deleteMe()  # the feature, not the timeline wrapper

    for body in [body for body in root.bRepBodies if _is_ours(body)]:
        body.deleteMe()


def _rounded_rect_profile(sketch, x0, y0, x1, y1, r):
    import math

    lines = sketch.sketchCurves.sketchLines
    arcs = sketch.sketchCurves.sketchArcs
    p = adsk.core.Point3D.create
    quarter = math.pi / 2

    lines.addByTwoPoints(p(x0 + r, y0, 0), p(x1 - r, y0, 0))
    lines.addByTwoPoints(p(x1, y0 + r, 0), p(x1, y1 - r, 0))
    lines.addByTwoPoints(p(x1 - r, y1, 0), p(x0 + r, y1, 0))
    lines.addByTwoPoints(p(x0, y1 - r, 0), p(x0, y0 + r, 0))
    arcs.addByCenterStartSweep(p(x1 - r, y0 + r, 0), p(x1 - r, y0, 0), quarter)
    arcs.addByCenterStartSweep(p(x1 - r, y1 - r, 0), p(x1, y1 - r, 0), quarter)
    arcs.addByCenterStartSweep(p(x0 + r, y1 - r, 0), p(x0 + r, y1, 0), quarter)
    arcs.addByCenterStartSweep(p(x0 + r, y0 + r, 0), p(x0, y0 + r, 0), quarter)


def _module_runs(matrix):
    """Merge horizontal runs of dark modules into (row, col_start, col_end)."""
    runs = []
    for row_index, row in enumerate(matrix):
        col = 0
        n = len(row)
        while col < n:
            if row[col]:
                start = col
                while col < n and row[col]:
                    col += 1
                runs.append((row_index, start, col - 1))
            else:
                col += 1
    return runs


def _union_tree(temp_mgr, bodies):
    union = adsk.fusion.BooleanTypes.UnionBooleanType
    while len(bodies) > 1:
        merged = []
        for i in range(0, len(bodies) - 1, 2):
            temp_mgr.booleanOperation(bodies[i], bodies[i + 1], union)
            merged.append(bodies[i])
        if len(bodies) % 2:
            merged.append(bodies[-1])
        bodies = merged
    return bodies[0]


def _paint(design, body, top_z):
    """White body, black raised top faces, so the viewport preview scans."""
    try:
        app = adsk.core.Application.get()
        library = app.materialLibraries.itemByName("Fusion Appearance Library")

        def appearance(name):
            # Assigning a library appearance copies it into the design.
            return design.appearances.itemByName(name) or library.appearances.itemByName(name)

        body.appearance = appearance("Plastic - Matte (White)")
        dark = appearance("Plastic - Matte (Black)")
        for face in body.faces:
            try:
                if abs(face.centroid.z - top_z) < 1e-5:
                    face.appearance = dark
            except RuntimeError:
                continue  # non-planar faces without a simple centroid
    except Exception:
        pass  # cosmetic only


def generate(design, params):
    """(Re)build the plate. Returns a summary dict."""
    payload = build_payload(params)
    matrix = qr_matrix(payload, params["error"])
    n = len(matrix)

    plate_w = params["plate_w"]
    base_h = params["base_h"]
    code_h = params["code_h"]
    corner_r = params["corner_r"]
    chamfer = params["chamfer"]
    quiet = int(params["quiet"])
    title = params["title"].strip()
    title_h = params["title_h"]

    pitch = plate_w / (n + 2 * quiet)
    quiet_w = quiet * pitch
    if corner_r >= quiet_w:
        corner_r = max(quiet_w - 0.02, 0.0)

    band = title_h * 1.9 if title else 0.0
    half = plate_w / 2
    y_bottom = -half - band

    delete_previous(design)
    timeline = design.timeline if design.designType == PARAMETRIC else None
    timeline_start = timeline.count if timeline else 0

    # Built in the root component as one solid body: no components, no
    # assembly, prints in place. The raised code sits in its own Z band, so
    # colour is a filament change at the base thickness in the slicer.
    comp = design.rootComponent
    # Bodies already here belong to the user, not to us.
    pre_existing = {body.entityToken for body in comp.bRepBodies}

    # --- Base plate: rounded-rectangle extrude + top rim chamfer ---
    sketch = comp.sketches.add(comp.xYConstructionPlane)
    sketch.isComputeDeferred = True
    _rounded_rect_profile(sketch, -half, y_bottom, half, half, corner_r)
    sketch.isComputeDeferred = False
    sketch.name = "Base outline"

    base_ext = comp.features.extrudeFeatures.addSimple(
        sketch.profiles.item(0),
        adsk.core.ValueInput.createByReal(base_h),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
    )
    base_body = base_ext.bodies.item(0)
    base_body.name = "Base"

    if chamfer > 0:
        try:
            top_face = next(
                f
                for f in base_body.faces
                if abs(f.centroid.z - base_h) < 1e-6
            )
            edges = adsk.core.ObjectCollection.create()
            for loop in top_face.loops:
                if loop.isOuter:
                    for edge in loop.edges:
                        edges.add(edge)
            chamfers = comp.features.chamferFeatures
            chamfer_input = chamfers.createInput2()
            chamfer_input.chamferEdgeSets.addEqualDistanceChamferEdgeSet(
                edges, adsk.core.ValueInput.createByReal(chamfer), True
            )
            chamfers.add(chamfer_input)
        except Exception:
            pass  # cosmetic only; never fail the build over the rim chamfer

    # --- Raised layer: one temporary-BRep body for QR modules AND title ---
    temp_mgr = adsk.fusion.TemporaryBRepManager.get()
    x_dir = adsk.core.Vector3D.create(1, 0, 0)
    y_dir = adsk.core.Vector3D.create(0, 1, 0)
    eps = 0.0004  # fuse boxes that only share an edge

    def raised_box(x_center, y_center, length, width):
        obb = adsk.core.OrientedBoundingBox3D.create(
            adsk.core.Point3D.create(x_center, y_center, base_h + code_h / 2),
            x_dir,
            y_dir,
            length + eps,
            width + eps,
            code_h,
        )
        return temp_mgr.createBox(obb)

    boxes = []
    for row, c0, c1 in _module_runs(matrix):
        x_center = -half + (quiet + (c0 + c1 + 1) / 2) * pitch
        y_center = half - (quiet + row + 0.5) * pitch
        boxes.append(raised_box(x_center, y_center, (c1 - c0 + 1) * pitch, pitch))

    # Title text: glyph outlines rasterised into scanline run-boxes, same as
    # the QR modules. (Fusion's SketchText API emits empty geometry in current
    # builds, and face+thicken features took ~2 s of UI-blocking recompute;
    # 0.15 mm scanlines are far below what a nozzle can reproduce anyway.)
    if title:
        import text_outline

        groups, width_em = text_outline.text_polygons(title)
        if not groups:
            raise ValueError("Title produced no printable glyphs")

        em = title_h
        max_width = plate_w - 2 * (corner_r + chamfer) - 0.2
        if width_em * em > max_width:
            em = max_width / width_em

        xs = [x for outer, _ in groups for x, _ in outer]
        ys = [y for outer, _ in groups for _, y in outer]
        ink_cx = (min(xs) + max(xs)) / 2 * em
        ink_cy = (min(ys) + max(ys)) / 2 * em
        band_cy = (y_bottom + -half) / 2
        dx, dy = -ink_cx, band_cy - ink_cy

        polygons = [
            [(x * em + dx, y * em + dy) for x, y in poly]
            for outer, holes in groups
            for poly in [outer] + list(holes)
        ]
        step = 0.015  # cm; scanline height for the letter outlines
        y_min = min(y for poly in polygons for _, y in poly)
        y_max = max(y for poly in polygons for _, y in poly)
        row_count = max(1, int((y_max - y_min) / step) + 1)
        for row in range(row_count):
            yc = y_min + (row + 0.5) * step
            hits = []
            for poly in polygons:
                m = len(poly)
                for i in range(m):
                    xa, ya = poly[i]
                    xb, yb = poly[(i + 1) % m]
                    if (ya > yc) != (yb > yc):
                        hits.append(xa + (yc - ya) * (xb - xa) / (yb - ya))
            hits.sort()
            for i in range(0, len(hits) - 1, 2):
                width = hits[i + 1] - hits[i]
                if width > 0.004:  # skip sub-hairline slivers
                    boxes.append(
                        raised_box((hits[i] + hits[i + 1]) / 2, yc, width, step)
                    )

    raised_temp = _union_tree(temp_mgr, boxes)

    parametric = design.designType == PARAMETRIC
    if parametric:
        base_feature = comp.features.baseFeatures.add()
        base_feature.startEdit()
        comp.bRepBodies.add(raised_temp, base_feature)
        base_feature.finishEdit()
    else:
        comp.bRepBodies.add(raised_temp)

    # Fuse everything into a single solid. The raised code occupies its own Z
    # band above the base, so one body still prints in two colours: add a
    # filament change at the base thickness in the slicer.
    tools = adsk.core.ObjectCollection.create()
    for body in comp.bRepBodies:
        if body.isSolid and body.entityToken not in pre_existing:
            if body.entityToken != base_body.entityToken:
                tools.add(body)
    if tools.count:
        combine_input = comp.features.combineFeatures.createInput(base_body, tools)
        combine_input.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
        comp.features.combineFeatures.add(combine_input)
    base_body.name = "QR Plate"
    _paint(design, base_body, base_h + code_h)

    # Tag what we made so a rerun deletes exactly it and nothing of the user's:
    # the bodies, and the timeline features that produced them.
    ours = [b for b in comp.bRepBodies if b.entityToken not in pre_existing]
    for body in ours:
        mark(body)
    if timeline:
        for index in range(timeline_start, timeline.count):
            mark(timeline.item(index).entity)

    save_params(design, params)

    return {
        "modules": n,
        "pitch_mm": round(pitch * 10, 4),
        "plate_mm": [round(plate_w * 10, 2), round((plate_w + band) * 10, 2)],
        "dark_modules": sum(map(sum, matrix)),
        "code_bodies": sum(1 for b in ours if b.isSolid) - 1,  # minus the base
        "layout": "root" if True else "components",
        "payload_len": len(payload),
        "mode": params.get("mode", payloads.MODE_WIFI),
    }
