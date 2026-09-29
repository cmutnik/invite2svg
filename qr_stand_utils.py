# Copyright (c) 2025 takotime808
"""QR code -> 3D model pipeline shared by the QR Code Stand and QR Code
Keychain pages.

Core piece, used by both:

- A flat plate with the QR code embossed/engraved on it -- built the same
  "background top cap + base + raised/engraved pegs" way
  `card3d_utils.build_invite_mesh` extrudes SVG artwork for the 3D Wedding
  Invite page, but via a QR-specific builder (see `build_qr_plate_mesh`)
  that decomposes the plate into simple, hole-free rectangles instead of
  merging touching modules -- a QR code's dense data area can otherwise
  produce a polygon that crashes the underlying `triangle` C library.
- An optional banner strip (icon and/or title text, see `build_banner_mesh`)
  fused onto the plate above or below the QR code via `stack_plate_pieces`.

Page-specific pieces, each fused onto (or, for the stand, paired
alongside) that same plate:

- QR Code Stand: a base block with a slot cut into its top at an angle,
  sized to grip the plate's edge so it stands up leaning back on a table,
  printed as a *separate* part and assembled by hand (see
  `build_stand_base_mesh`). The slot is cut in 2D (shapely boolean) before
  extruding, the same "cut in 2D, then extrude" approach `card3d_utils`
  uses to avoid a 3D CSG library.
- QR Code Keychain: a loop with a through-hole for a split ring, fused
  directly onto the plate as *one* printable piece (see
  `build_keychain_loop_mesh`).
"""

import itertools
from pathlib import Path

import numpy as np
import qrcode
import trimesh
from shapely.affinity import rotate, scale, translate
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from card3d_utils import _as_polygons, _combined_bounds, _drop_cap, _TRIANGLE_ARGS, _triangulate_capped, parse_svg_polygons
from icons import ICON_PATHS, ICON_VIEWBOX_SIZE
from potrace_utils import run_potrace

_FONT_PATH = Path(__file__).parent / "data" / "fonts" / "DejaVuSans-Bold.ttf"
_TEXT_RENDER_PX = 200  # rasterization height for title text before potrace traces it

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


def icon_polygons(name, size_mm):
    """Return brand icon `name` (a key of `icons.ICON_PATHS`) as shapely
    Polygons scaled to `size_mm` x `size_mm`, in local coordinates with
    (0, 0) at the icon's own bottom-left corner and y increasing upward.
    """
    if name not in ICON_PATHS:
        raise ValueError(f"Unknown icon: {name!r}")

    svg_text = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {ICON_VIEWBOX_SIZE} {ICON_VIEWBOX_SIZE}">'
        f'<path d="{ICON_PATHS[name]}"/></svg>'
    )
    polygons = parse_svg_polygons(svg_text)
    if not polygons:
        raise ValueError(f"Icon {name!r} produced no fillable shape.")

    scale_factor = size_mm / ICON_VIEWBOX_SIZE
    # scale first (also flips SVG's y-down to mesh's y-up), then shift the
    # result to sit flush against (0, 0) -- Simple Icons' glyphs don't
    # start exactly at their viewBox origin.
    flipped = [scale(p, xfact=scale_factor, yfact=-scale_factor, origin=(0, 0)) for p in polygons]
    minx, miny, _, _ = _combined_bounds(flipped)
    return [translate(p, xoff=-minx, yoff=-miny) for p in flipped]


def text_to_polygons(text, cap_height_mm, turdsize=2, alphamax=1.0, opttolerance=0.2):
    """Render `text` with the bundled DejaVu Sans Bold font and trace it
    with potrace -- the same raster-then-trace approach streamlit_app.py
    uses for photographed cards -- into shapely Polygons scaled so the
    traced artwork is `cap_height_mm` tall. Returns (polygons, width_mm,
    height_mm); polygons are in local coordinates with (0, 0) at the
    text's own bottom-left corner and y increasing upward.

    Requires the `potrace` command-line tool on PATH, same as the rest of
    this app.
    """
    from PIL import Image, ImageDraw, ImageFont

    if not text or not text.strip():
        raise ValueError("Enter a title/company name.")

    font = ImageFont.truetype(str(_FONT_PATH), _TEXT_RENDER_PX)
    probe_bbox = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=font)
    pad = 8
    width_px = int(probe_bbox[2] - probe_bbox[0]) + 2 * pad
    height_px = int(probe_bbox[3] - probe_bbox[1]) + 2 * pad

    img = Image.new("L", (width_px, height_px), color=255)
    ImageDraw.Draw(img).text((pad - probe_bbox[0], pad - probe_bbox[1]), text, font=font, fill=0)
    bitmap = np.array(img, dtype=np.uint8)

    svg_text = run_potrace(bitmap, turdsize=turdsize, alphamax=alphamax, opttolerance=opttolerance)
    polygons = parse_svg_polygons(svg_text)
    if not polygons:
        raise ValueError("Could not trace any text -- try a different title.")

    minx, miny, maxx, maxy = _combined_bounds(polygons)
    traced_height = maxy - miny
    if traced_height <= 0:
        raise ValueError("Traced text has zero height.")
    scale_factor = cap_height_mm / traced_height

    flipped = [scale(p, xfact=scale_factor, yfact=-scale_factor, origin=(0, 0)) for p in polygons]
    fminx, fminy, fmaxx, fmaxy = _combined_bounds(flipped)
    placed = [translate(p, xoff=-fminx, yoff=-fminy) for p in flipped]
    return placed, fmaxx - fminx, fmaxy - fminy


def build_banner_polygons(
    plate_width_mm,
    icon_name=None,
    icon_size_mm=12.0,
    title_text=None,
    title_height_mm=8.0,
    gap_mm=4.0,
    side_pad_mm=4.0,
    vertical_pad_mm=3.0,
):
    """Lay out the optional icon + title row for the plate's banner strip.
    Returns (polygons, banner_height_mm) in banner-local coordinates
    ((0, 0) at the banner's own bottom-left corner, spanning the full
    `plate_width_mm`, y increasing upward) -- empty/0 if neither is given.

    - both given: icon then title, left to right, centered as one group.
    - title only: title centered.
    - icon only: right-aligned -- this is what ends up "in the upper right
      corner" the caller promises, true whenever (as intended) an
      icon-only banner is placed at the top of the plate.

    A long title is shrunk (icon included, to keep it proportional) just
    enough to fit within `plate_width_mm` minus side padding -- otherwise
    its raised/engraved artwork would extend past the plate's own edge,
    printing as geometry disconnected from the base.
    """
    icon_polys, icon_size = [], 0.0
    if icon_name:
        icon_polys = icon_polygons(icon_name, icon_size_mm)
        icon_size = icon_size_mm

    title_polys, title_w, title_h = [], 0.0, 0.0
    if title_text:
        title_polys, title_w, title_h = text_to_polygons(title_text, title_height_mm)

    if not icon_polys and not title_polys:
        return [], 0.0

    content_w = icon_size + (gap_mm if icon_polys and title_polys else 0.0) + title_w
    available_w = max(plate_width_mm - 2 * side_pad_mm, 1e-6)
    fit_scale = min(1.0, available_w / content_w) if content_w > 0 else 1.0
    if fit_scale < 1.0:
        icon_polys = [scale(p, xfact=fit_scale, yfact=fit_scale, origin=(0, 0)) for p in icon_polys]
        title_polys = [scale(p, xfact=fit_scale, yfact=fit_scale, origin=(0, 0)) for p in title_polys]
        icon_size *= fit_scale
        title_w *= fit_scale
        title_h *= fit_scale
        gap_mm *= fit_scale

    banner_height_mm = max(icon_size, title_h) + 2 * vertical_pad_mm
    placed = []

    if icon_polys and title_polys:
        content_w = icon_size + gap_mm + title_w
        start_x = max((plate_width_mm - content_w) / 2, side_pad_mm)
        placed += [translate(p, xoff=start_x, yoff=(banner_height_mm - icon_size) / 2) for p in icon_polys]
        placed += [
            translate(p, xoff=start_x + icon_size + gap_mm, yoff=(banner_height_mm - title_h) / 2)
            for p in title_polys
        ]
    elif title_polys:
        start_x = max((plate_width_mm - title_w) / 2, side_pad_mm)
        placed += [translate(p, xoff=start_x, yoff=(banner_height_mm - title_h) / 2) for p in title_polys]
    else:
        start_x = plate_width_mm - icon_size - side_pad_mm
        placed += [translate(p, xoff=start_x, yoff=(banner_height_mm - icon_size) / 2) for p in icon_polys]

    return placed, banner_height_mm


def build_banner_mesh(polygons, width_mm, height_mm, base_thickness_mm, feature_height_mm, mode="raised"):
    """Build the banner strip's own flat plate (base + optional icon/text
    pegs) -- the same watertight "background + base + pegs" assembly as
    `build_qr_plate_mesh`, but for arbitrary curved artwork (icon/text
    outlines) instead of a QR grid.

    Deliberately does *not* reuse `card3d_utils.build_invite_mesh`'s way
    of merging touching features into one hole-carrying polygon per
    connected component: some brand icons (e.g. Instagram, whose
    camera-ring counter itself contains a separate, disjoint dot shape)
    nest two holes deep, which that merge step turns into an invalid
    polygon for. Each polygon `parse_svg_polygons` returns is already a
    fully valid, correctly-holed shape on its own, so features are
    triangulated independently instead of being re-merged -- and for
    `indented`, a single `unary_union` + `difference` is a well-defined
    boolean regardless of nesting depth, so the background doesn't need
    that reconstruction either (verified against all 6 bundled icons).
    """
    if mode not in ("raised", "indented"):
        raise ValueError(f"Unknown mode: {mode!r}")

    top_z = base_thickness_mm
    plate_rect = [(0, 0), (width_mm, 0), (width_mm, height_mm), (0, height_mm)]

    if polygons and mode == "indented":
        top_cap_main = Polygon(plate_rect).difference(unary_union(polygons))
        pieces = _as_polygons(top_cap_main)
    else:
        pieces = [Polygon(plate_rect)]

    parts = []
    for piece in pieces:
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

    for feature in polygons:
        peg = trimesh.creation.extrude_polygon(
            feature, height=feature_height_mm, engine="triangle", triangle_args=_TRIANGLE_ARGS,
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


def stack_plate_pieces(qr_mesh, qr_feature_mask, extra_mesh, extra_feature_mask, position="above"):
    """Stack the QR plate and another plate-shaped piece -- a banner strip
    (see `build_banner_mesh`) or a keychain loop (see
    `build_keychain_loop_mesh`) -- into one printable piece: same width and
    thickness, placed edge to edge along y. `position` is "above" or
    "below" the QR code, matching the plate's own y-up = physically-up
    convention once it's standing in the base (see `build_stand_base_mesh`)
    or hanging from the loop.
    """
    if position not in ("above", "below"):
        raise ValueError(f"Unknown position: {position!r}")

    qr_height = qr_mesh.bounds[1][1]
    extra_height = extra_mesh.bounds[1][1]
    qr_mesh = qr_mesh.copy()
    extra_mesh = extra_mesh.copy()

    if position == "above":
        extra_mesh.apply_translation([0, qr_height, 0])
    else:
        qr_mesh.apply_translation([0, extra_height, 0])

    result = trimesh.util.concatenate([qr_mesh, extra_mesh])
    result.merge_vertices(digits_vertex=8)
    result.remove_unreferenced_vertices()

    feature_mask = np.concatenate([qr_feature_mask, extra_feature_mask])
    return result, feature_mask


def build_keychain_loop_mesh(
    plate_width_mm,
    base_thickness_mm,
    loop_diameter_mm=16.0,
    hole_diameter_mm=5.5,
    neck_width_mm=10.0,
    neck_height_mm=2.0,
):
    """Build a keychain's loop tab: a neck rising from y=0 (fused, via
    `stack_plate_pieces`, to the top of the QR plate) into a circular loop
    with a through-hole for a split ring, centered horizontally within
    `plate_width_mm`. Returns (mesh, feature_mask) -- `feature_mask` is all
    False, since the loop is plain structural material, not part of the QR
    artwork (matches `base_color`, not `feature_color`, in a 3MF export).

    A single uniform-thickness solid with one hole is simple enough to
    extrude directly -- unlike the QR plate/banner, it doesn't need the
    "background + separately-extruded pegs" split those use to put two
    different heights on one shared base.
    """
    wall = (loop_diameter_mm - hole_diameter_mm) / 2
    if wall < 2.5:
        raise ValueError("Loop diameter must leave at least ~2.5mm of wall around the hole to stay sturdy.")

    loop_radius = loop_diameter_mm / 2
    hole_radius = hole_diameter_mm / 2
    cx = plate_width_mm / 2
    cy = neck_height_mm + loop_radius

    # the neck reaches all the way to the loop's own center, guaranteeing a
    # clean union with the circle regardless of neck_width vs loop size.
    neck = box(cx - neck_width_mm / 2, 0, cx + neck_width_mm / 2, cy)
    loop = Point(cx, cy).buffer(loop_radius, resolution=64)
    outline = unary_union([neck, loop])
    hole = Point(cx, cy).buffer(hole_radius, resolution=64)
    footprint = outline.difference(hole)
    if isinstance(footprint, MultiPolygon):
        footprint = max(footprint.geoms, key=lambda p: p.area)

    mesh = trimesh.creation.extrude_polygon(
        footprint, height=base_thickness_mm, engine="triangle", triangle_args=_TRIANGLE_ARGS,
    )
    feature_mask = np.zeros(len(mesh.faces), dtype=bool)
    return mesh, feature_mask


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
