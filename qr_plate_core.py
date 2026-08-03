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
    return any(entity.attributes.itemByName(group, "marker") for group in _attr_groups())


def delete_previous(design):
    root = design.rootComponent
    for occ in [occ for occ in root.occurrences if _is_ours(occ.component)]:
        occ.deleteMe()
    # Part Design documents hold the plate as loose bodies in the root
    # component. Deleting one body also removes the feature that created it,
    # which can take sibling bodies with it, so re-scan after every delete
    # rather than iterating over a list that goes stale.
    while True:
        doomed = next((body for body in root.bRepBodies if _is_ours(body)), None)
        if doomed is None:
            return
        remaining = root.bRepBodies.count
        doomed.deleteMe()
        if root.bRepBodies.count >= remaining:
            return  # nothing was removed; stop rather than spin


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


def _apply_appearance(design, bodies, library_name):
    """Best-effort: color the given bodies from the Fusion library."""
    try:
        app = adsk.core.Application.get()
        fusion_lib = app.materialLibraries.itemByName("Fusion Appearance Library")
        source = fusion_lib.appearances.itemByName(library_name)
        local = design.appearances.itemByName(library_name)
        if not local:
            local = design.appearances.addByOriginal(source, library_name)
        for body in bodies:
            if body.isSolid:
                body.appearance = local
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

    root = design.rootComponent
    identity = adsk.core.Matrix3D.create()

    # Child components per material: the QR's dark modules are naturally
    # disjoint islands, which Fusion splits into many bodies. Grouping each
    # material in its own component keeps the browser tidy and lets the user
    # export "Base" and "Code" as one aligned mesh each.
    #
    # Part Design documents allow only one component, so there everything is
    # built directly in the root component and the two materials are told
    # apart by body name instead.
    try:
        plate_comp = root.occurrences.addNewComponent(identity).component
        plate_comp.name = "QR Plate"
        plate_comp.attributes.add(ATTR_GROUP, "marker", "1")
        base_comp = plate_comp.occurrences.addNewComponent(identity).component
        base_comp.name = "Base"
        code_comp = plate_comp.occurrences.addNewComponent(identity).component
        code_comp.name = "Code"
    except RuntimeError:
        base_comp = code_comp = root
    # Bodies already in the target component belong to the user, not to us.
    pre_existing = {body.entityToken for body in base_comp.bRepBodies}

    # --- Base plate: rounded-rectangle extrude + top rim chamfer ---
    sketch = base_comp.sketches.add(base_comp.xYConstructionPlane)
    sketch.isComputeDeferred = True
    _rounded_rect_profile(sketch, -half, y_bottom, half, half, corner_r)
    sketch.isComputeDeferred = False
    sketch.name = "Base outline"

    base_ext = base_comp.features.extrudeFeatures.addSimple(
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
            chamfers = base_comp.features.chamferFeatures
            chamfer_input = chamfers.createInput2()
            chamfer_input.chamferEdgeSets.addEqualDistanceChamferEdgeSet(
                edges, adsk.core.ValueInput.createByReal(chamfer), True
            )
            chamfers.add(chamfer_input)
        except Exception:
            pass  # cosmetic only; never fail the build over the rim chamfer

    # --- QR layer: one temporary-BRep body from merged module runs ---
    temp_mgr = adsk.fusion.TemporaryBRepManager.get()
    x_dir = adsk.core.Vector3D.create(1, 0, 0)
    y_dir = adsk.core.Vector3D.create(0, 1, 0)
    eps = 0.0004  # fuse boxes that only share an edge
    z_center = base_h + code_h / 2
    boxes = []
    for row, c0, c1 in _module_runs(matrix):
        x_center = -half + (quiet + (c0 + c1 + 1) / 2) * pitch
        y_center = half - (quiet + row + 0.5) * pitch
        length = (c1 - c0 + 1) * pitch + eps
        obb = adsk.core.OrientedBoundingBox3D.create(
            adsk.core.Point3D.create(x_center, y_center, z_center),
            x_dir,
            y_dir,
            length,
            pitch + eps,
            code_h,
        )
        boxes.append(temp_mgr.createBox(obb))
    qr_temp = _union_tree(temp_mgr, boxes)

    parametric = design.designType == adsk.fusion.DesignTypes.ParametricDesignType
    if parametric:
        base_feature = code_comp.features.baseFeatures.add()
        base_feature.startEdit()
        code_comp.bRepBodies.add(qr_temp, base_feature)
        base_feature.finishEdit()
    else:
        code_comp.bRepBodies.add(qr_temp)

    # --- Optional title text, also in the Code component ---
    # Fusion's SketchText API produces empty glyph geometry in some builds,
    # so the text is constructed directly from font outlines instead.
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

        def wire(polygon):
            points = [
                adsk.core.Point3D.create(x * em + dx, y * em + dy, base_h)
                for x, y in polygon
            ]
            lines = [
                adsk.core.Line3D.create(points[i], points[(i + 1) % len(points)])
                for i in range(len(points))
            ]
            body, _ = temp_mgr.createWireFromCurves(lines)
            return body

        face_bodies = [
            temp_mgr.createFaceFromPlanarWires([wire(outer)] + [wire(h) for h in holes])
            for outer, holes in groups
        ]

        if parametric:
            text_base_feature = code_comp.features.baseFeatures.add()
            text_base_feature.startEdit()
            for face_body in face_bodies:
                code_comp.bRepBodies.add(face_body, text_base_feature)
            text_base_feature.finishEdit()
        else:
            for face_body in face_bodies:
                code_comp.bRepBodies.add(face_body)

        surface_bodies = [b for b in code_comp.bRepBodies if not b.isSolid]
        faces = adsk.core.ObjectCollection.create()
        for body in surface_bodies:
            for face in body.faces:
                faces.add(face)

        def thicken(amount):
            thicken_input = code_comp.features.thickenFeatures.createInput(
                faces,
                adsk.core.ValueInput.createByReal(amount),
                False,
                adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
                False,
            )
            return code_comp.features.thickenFeatures.add(thicken_input)

        text_feature = thicken(code_h)
        top_z = max(b.boundingBox.maxPoint.z for b in text_feature.bodies)
        if top_z <= base_h + 1e-6:
            text_feature.deleteMe()
            text_feature = thicken(-code_h)

        for body in surface_bodies:
            body.isLightBulbOn = False

    # Tag what we made so a rerun can delete exactly it, and colour the two
    # materials differently. In a Part Design document these bodies sit in the
    # root component alongside the user's own, hence the token comparison.
    components = [base_comp] if code_comp is base_comp else [base_comp, code_comp]
    ours = [
        body
        for component in components
        for body in component.bRepBodies
        if body.entityToken not in pre_existing
    ]
    base_token = base_body.entityToken
    for body in ours:
        body.attributes.add(ATTR_GROUP, "marker", "1")
        if code_comp is root and body.entityToken != base_token:
            body.name = "Code"  # Fusion appends a suffix for duplicates
    _apply_appearance(design, [base_body], "Plastic - Matte (White)")
    _apply_appearance(
        design,
        [body for body in ours if body.entityToken != base_token],
        "Plastic - Matte (Black)",
    )

    save_params(design, params)

    return {
        "modules": n,
        "pitch_mm": round(pitch * 10, 4),
        "plate_mm": [round(plate_w * 10, 2), round((plate_w + band) * 10, 2)],
        "dark_modules": sum(map(sum, matrix)),
        "code_bodies": sum(1 for b in ours if b.isSolid) - 1,  # minus the base
        "layout": "root" if code_comp is root else "components",
        "payload_len": len(payload),
        "mode": params.get("mode", payloads.MODE_WIFI),
    }
