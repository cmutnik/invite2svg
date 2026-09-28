# Copyright (c) 2025 takotime808
"""QR code -> 3D stand pipeline for the QR Code Stand page.

Two parts, printed separately and assembled by hand:

- A flat plate with the QR code embossed/engraved on it -- built the same
  "background top cap + base + raised/engraved pegs" way
  `card3d_utils.build_invite_mesh` extrudes SVG artwork for the 3D Wedding
  Invite page, but via a QR-specific builder (see `build_qr_plate_mesh`)
  that decomposes the plate into simple, hole-free rectangles instead of
  merging touching modules -- a QR code's dense data area can otherwise
  produce a polygon that crashes the underlying `triangle` C library.
- A base block with a slot cut into its top at an angle, sized to grip the
  plate's edge so it stands up leaning back on a table. The slot is cut in
  2D (shapely boolean) before extruding, the same "cut in 2D, then extrude"
  approach `card3d_utils` uses to avoid a 3D CSG library.
"""

import itertools

import numpy as np
import qrcode
import trimesh
from shapely.affinity import rotate
from shapely.geometry import MultiPolygon, Polygon, box

from card3d_utils import _drop_cap, _triangulate_capped

_ERROR_LEVELS = {
    "L": qrcode.constants.ERROR_CORRECT_L,
    "M": qrcode.constants.ERROR_CORRECT_M,
    "Q": qrcode.constants.ERROR_CORRECT_Q,
    "H": qrcode.constants.ERROR_CORRECT_H,
}

# boundary-only triangulation (no Steiner points): fine for flat structural
# faces like these, and keeps the STL small -- same args card3d_utils uses
# for its own plain base plate. QR pegs stick to this too, never the
# quality-constrained "pq30a2Y" args card3d_utils uses for curved artwork --
# see `generate_qr_polygons` for why.
_BOUNDARY_ONLY_ARGS = "pY"


def generate_qr_polygons(data, error_correction="M", module_size_mm=2.0):
    """Encode `data` as a QR code and return (polygons, active_size_mm):
    one filled rectangle Polygon per horizontal run of dark modules (row by
    row), in mm, and the code's side length in mm (module count x
    module_size_mm, with no quiet zone -- that's left to the caller, e.g.
    via `build_qr_plate_mesh`'s margin_mm).

    Deliberately *not* one polygon per dark module unioned into whatever
    shape touching modules happen to form: the Shewchuk `triangle` C
    library `card3d_utils` relies on for triangulation can segfault on a
    large, rectilinear, many-vertex polygon -- exactly what a QR code's
    connected regions look like once merged, unlike the curved letterform
    artwork that pipeline was built for. Keeping each polygon a simple
    axis-aligned rectangle (merged only along one row, so it never
    self-touches at a corner) sidesteps that entirely.
    """
    if not data:
        raise ValueError("Enter some text or a URL to encode.")

    qr = qrcode.QRCode(error_correction=_ERROR_LEVELS[error_correction], box_size=1, border=0)
    qr.add_data(data)
    qr.make(fit=True)
    matrix = qr.get_matrix()

    polygons = []
    for row, line in enumerate(matrix):
        col = 0
        for dark, run in itertools.groupby(line):
            run_len = sum(1 for _ in run)
            if dark:
                polygons.append(
                    box(
                        col * module_size_mm,
                        row * module_size_mm,
                        (col + run_len) * module_size_mm,
                        (row + 1) * module_size_mm,
                    )
                )
            col += run_len

    if not polygons:
        raise ValueError("Generated QR code has no dark modules.")

    return polygons, len(matrix) * module_size_mm


def build_qr_plate_mesh(
    polygons, active_size_mm, module_size_mm, plate_size_mm, base_thickness_mm, feature_height_mm, mode="raised",
):
    """QR-specific counterpart to `card3d_utils.build_invite_mesh`: same
    watertight "background top cap + base + raised/engraved pegs"
    assembly, but built entirely from simple, hole-free rectangles instead
    of merging touching modules and carving them out of the plate as one
    (possibly multiply-holed) polygon.

    That distinction matters here in a way it doesn't for
    `build_invite_mesh`'s curved letterform artwork: a QR code's dense,
    rectilinear data area routinely produces a merged polygon with several
    of its own interior holes (an isolated light module fully boxed in by
    dark ones), and the Shewchuk `triangle` C library that pipeline relies
    on for triangulation has been observed to segfault on exactly that
    shape. Decomposing the whole plate row by row (matching the QR grid)
    instead -- each row split into a strictly alternating sequence of dark
    and light *intervals*, never a hole -- sidesteps that entirely while
    still producing the same finished geometry.
    """
    if not polygons:
        raise ValueError("No QR modules to extrude.")
    if mode not in ("raised", "indented"):
        raise ValueError(f"Unknown mode: {mode!r}")

    offset = (plate_size_mm - active_size_mm) / 2
    if offset < 0:
        raise ValueError("Plate is smaller than the QR code; increase the plate size or margin.")

    grid_size = round(active_size_mm / module_size_mm)

    # dark run-rectangles, grouped by their QR row, in local (unshifted,
    # unflipped) mm space -- exactly what `generate_qr_polygons` emitted.
    rows = {}
    for poly in polygons:
        x0, y0, x1, y1 = poly.bounds
        row = round(y0 / module_size_mm)
        rows.setdefault(row, []).append((x0, x1))

    def to_mesh_rect(x0, x1, row):
        # mirrors `fit_polygons_to_plate`'s y-down -> y-up flip (scale=1
        # here, since the caller sizes the plate to exactly fit the code),
        # so the code isn't mirrored on the finished plate.
        mesh_y0 = plate_size_mm - offset - (row + 1) * module_size_mm
        mesh_y1 = plate_size_mm - offset - row * module_size_mm
        return box(x0 + offset, mesh_y0, x1 + offset, mesh_y1)

    top_z = base_thickness_mm
    plate_rect = [(0, 0), (plate_size_mm, 0), (plate_size_mm, plate_size_mm), (0, plate_size_mm)]

    background_rects = []
    if offset > 1e-9:
        background_rects.extend([
            box(0, 0, plate_size_mm, offset),
            box(0, plate_size_mm - offset, plate_size_mm, plate_size_mm),
            box(0, offset, offset, plate_size_mm - offset),
            box(plate_size_mm - offset, offset, plate_size_mm, plate_size_mm - offset),
        ])

    feature_rects = []
    for row in range(grid_size):
        dark_intervals = sorted(rows.get(row, []))
        cursor = 0.0
        for x0, x1 in dark_intervals:
            if x0 > cursor + 1e-9:
                background_rects.append(to_mesh_rect(cursor, x0, row))
            feature_rects.append(to_mesh_rect(x0, x1, row))
            cursor = x1
        if cursor < active_size_mm - 1e-9:
            background_rects.append(to_mesh_rect(cursor, active_size_mm, row))

    parts = []
    for piece in background_rects:
        if piece.is_empty or piece.area < 1e-9:
            continue
        cap = _triangulate_capped(piece, top_z, upward=True)
        if cap is not None:
            parts.append(cap)

    base_solid = trimesh.creation.extrude_polygon(
        Polygon(plate_rect), height=base_thickness_mm, engine="triangle", triangle_args=_BOUNDARY_ONLY_ARGS,
    )
    parts.append(_drop_cap(base_solid, top_z, flip=False))
    n_background_faces = sum(len(p.faces) for p in parts)

    for module in feature_rects:
        peg = trimesh.creation.extrude_polygon(
            module, height=feature_height_mm, engine="triangle", triangle_args=_BOUNDARY_ONLY_ARGS,
        )
        if mode == "raised":
            peg.apply_translation([0, 0, top_z])
            parts.append(_drop_cap(peg, top_z, flip=False))
        else:
            peg.apply_translation([0, 0, top_z - feature_height_mm])
            parts.append(_drop_cap(peg, top_z, flip=True))

    result = trimesh.util.concatenate(parts)
    result.merge_vertices(digits_vertex=8)
    result.remove_unreferenced_vertices()

    feature_mask = np.zeros(len(result.faces), dtype=bool)
    feature_mask[n_background_faces:] = True
    return result, feature_mask


def build_stand_base_mesh(
    width_mm,
    base_depth_mm,
    base_height_mm,
    plate_thickness_mm,
    tilt_deg=15.0,
    slot_clearance_mm=0.3,
    slot_depth_mm=12.0,
    entry_depth_frac=0.35,
):
    """Build a self-standing base block with a slot cut into its top,
    tilted `tilt_deg` back from vertical, sized to grip a flat
    `plate_thickness_mm`-thick plate (see `card3d_utils.build_invite_mesh`)
    so it stands leaning back at that angle once inserted.

    The cross-section (depth = front-to-back on the table, height =
    vertical) is built as a single 2D boolean difference, then extruded
    along `width_mm`. `entry_depth_frac` places the slot's mouth toward the
    front of the base (default 35% back from the front edge), leaving more
    material behind it as a back support for the plate to lean over.
    """
    if slot_depth_mm >= base_height_mm:
        raise ValueError("Slot depth must be less than the base height.")

    block = box(0, 0, base_depth_mm, base_height_mm)
    entry_depth = base_depth_mm * entry_depth_frac
    slot_width = plate_thickness_mm + 2 * slot_clearance_mm
    overshoot = 2.0  # cut past the top face so the slot opens cleanly

    slot = box(
        entry_depth - slot_width / 2,
        base_height_mm - slot_depth_mm,
        entry_depth + slot_width / 2,
        base_height_mm + overshoot,
    )
    # Negative angle here (shapely's rotate is CCW-positive, y-up) swings
    # the buried half of the slot toward the front; by rigid continuation
    # through the pivot on the top face, that's what leans the plate's
    # exposed top backward once it's inserted.
    slot = rotate(slot, -tilt_deg, origin=(entry_depth, base_height_mm))

    footprint = block.difference(slot)
    if isinstance(footprint, MultiPolygon):
        footprint = max(footprint.geoms, key=lambda p: p.area)
    if footprint.is_empty or footprint.area < 1e-6:
        raise ValueError("Slot parameters leave no material in the stand base.")

    mesh = trimesh.creation.extrude_polygon(
        footprint, height=width_mm, engine="triangle", triangle_args=_BOUNDARY_ONLY_ARGS,
    )

    # extrude_polygon lays the 2D (depth, height) cross-section in XY and
    # extrudes along Z by width_mm. Cycle the axes -- a 3-cycle, so winding
    # is preserved -- so the mesh instead sits with x=width, y=depth,
    # z=height: flat on the print bed, matching the QR plate's own axes.
    v = mesh.vertices
    vertices = np.column_stack([v[:, 2], v[:, 0], v[:, 1]])
    return trimesh.Trimesh(vertices=vertices, faces=mesh.faces, process=False)
