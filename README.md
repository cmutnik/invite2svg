<!-- # Copyright (c) 2025 takotime808 -->
# Invite to SVG


[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://invite2svg.streamlit.app/)

### Wedding invite layer extraction

Turns a photographed wedding invitation into assets for a 3D model —
either as separate transparent PNG layers (border, text) or as a single
vector SVG capturing both — corrected for the camera's skew/rotation.

All three scripts share `card_utils.py`, which deskews the card, trims
the photographic drop-shadow, and profiles ink density near each edge to
find the border band thickness.


## Usage (python)

```sh
python extract_border.py wedding_invite.png -o wedding_invite_border.png
python extract_text.py   wedding_invite.png -o wedding_invite_text.png
python photo_to_svg.py   wedding_invite.png -o wedding_invite.svg
```

- **`extract_border.py`** keeps only the printed border band (transparent elsewhere).
- **`extract_text.py`** keeps only the ink inside the border, rendered as solid black on transparent (use `--keep-color` to keep the original ink color instead). Its output lines up with `extract_border.py`'s — same canvas size, since both measure the same border thickness.
- **`photo_to_svg.py`** vectorizes the whole deskewed card (border + text combined) into one SVG via [potrace](http://potrace.sourceforge.net/) (`brew install potrace`), ready to extrude onto a base rectangle.

Common options:
- `--top / --bottom / --left / --right` — override a side's border thickness (px) if auto-detection misjudges it (`extract_border.py`, `extract_text.py`)
- `--pad` — extra px kept past the detected border band
- `--min-area` — drop ink specks smaller than this many px; edge-touching photographic shadow residue is always dropped regardless of size
- `--debug` (`extract_border.py`) — also save the deskewed card and a boundary-overlay image for verification
- `--turdsize` / `--alphamax` / `--opttolerance` (`photo_to_svg.py`) — passed through to potrace to tune curve smoothing

## UI

`streamlit_app.py` wraps the same pipeline in a browser UI: upload a photo,
pick full-card / border-only / text-only, tune the same options via sliders,
and download the resulting SVG.

```sh
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Requires `potrace` on PATH, same as `photo_to_svg.py`. Deploying to Streamlit
Community Cloud picks up `packages.txt` to install it automatically.

### 3D Wedding Invite page

The **3D Wedding Invite** page (`pages/1_🧊_3D_Wedding_Invite.py`) extrudes a
3"x5" base plate and the invite's SVG artwork into a single watertight solid,
via `card3d_utils.py`:

1. Parses the SVG (any producer, including potrace's group-transform output)
   into filled polygons, resolving letterform holes (e.g. the counter of an
   "o") by containment nesting rather than trusting winding direction.
2. Scales/centers the artwork onto the plate, preserving aspect ratio.
3. Assembles the final solid face-by-face (background top surface, base
   sides/bottom, per-feature walls/caps) using a quality-constrained
   Delaunay triangulation ([triangle](https://rufat.be/triangle/)),
   giving a single watertight solid without needing a 3D boolean.
4. Renders it interactively (Plotly) and offers an STL download for 3D printing.

It picks up the SVG generated on the Photo → SVG page automatically (via
`st.session_state`), or you can upload any other `.svg` file directly.

### QR Code Stand page

The **QR Code Stand** page (`pages/2_🪧_QR_Code_Stand.py`) turns a link (a
shop, Instagram, etc.) into two 3D-printable parts, via `qr_stand_utils.py`:

1. A flat plate with the QR code embossed (or engraved) on it, built the
   same "background + raised/engraved artwork" way as the 3D Wedding
   Invite page, but from its own QR-specific mesh builder rather than
   `card3d_utils.build_invite_mesh`: a QR code's dense, rectilinear data
   area can produce a merged polygon with its own interior holes that
   crashes the `triangle` triangulation library underneath that pipeline
   (fine for curved letterform artwork, not for a QR grid), so the plate
   is decomposed row by row into simple, hole-free rectangles instead.
2. A base block with a slot cut into its top at an angle (cut in 2D with
   shapely, then extruded, same as the plate/invite geometry), sized to
   grip the plate's edge so it stands up leaning back on a table.

Print both parts flat on the bed and slide the plate into the base's slot
to assemble -- handy for pointing craft-fair visitors at a link.
