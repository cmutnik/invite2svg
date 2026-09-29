# Copyright (c) 2025 takotime808
"""Streamlit page that turns a link/text into a 3D-printable QR code stand:
a flat plate with the QR pattern embossed/engraved on it (reusing the same
SVG -> 3D extrusion pipeline as the 3D Wedding Invite page) plus a separate
slotted base that holds the plate standing up at an angle on a table --
handy for pointing craft-fair visitors at a shop, Instagram, or contact link.

Run with:
    streamlit run streamlit_app.py
(this page is auto-discovered from the sidebar)
"""

import shutil

import streamlit as st

from card3d_utils import mesh_to_3mf_bytes, mesh_to_plotly_figure, mesh_to_stl_bytes
from icons import ICON_PATHS
from qr_stand_utils import (
    build_banner_mesh,
    build_banner_polygons,
    build_qr_plate_mesh,
    build_stand_base_mesh,
    generate_qr_polygons,
    stack_plate_pieces,
)

st.set_page_config(page_title="QR Code Stand", page_icon="🪧", layout="wide")

st.title("QR Code Stand")
st.caption(
    "Turns a link (your shop, Instagram, etc.) into a QR code embossed on a "
    "3D-printable plate, plus a slotted base that holds it standing up on a "
    "table -- ready for a craft fair booth."
)

data = st.text_input("Link or text to encode", placeholder="https://your-shop.example.com")

with st.sidebar:
    st.header("QR code")
    error_correction = st.selectbox(
        "Error correction", ["L", "M", "Q", "H"], index=1,
        help="Higher levels tolerate more damage/dirt but make a denser code. M is a good default.",
    )
    module_size_mm = st.slider(
        "Module size (mm)", 1.0, 4.0, 2.0, step=0.1,
        help="Size of one QR pixel. Bigger is easier to scan from further away, but makes a bigger plate.",
    )
    margin_mm = st.slider(
        "Quiet-zone margin (mm)", 2.0, 20.0, 8.0, step=1.0,
        help="Blank border around the code -- scanners need this. Aim for at least ~4x the module size.",
    )

    st.header("Plate")
    mode_label = st.radio(
        "Artwork direction",
        ["Raised (emboss)", "Indented (engrave)"],
        help="Raised + 2-color printing (3MF) gives the most reliable scans. Engrave relies on shadow contrast alone.",
    )
    mode = "raised" if mode_label.startswith("Raised") else "indented"
    plate_thickness_mm = st.slider("Plate thickness (mm)", 1.5, 5.0, 2.5, step=0.1)
    feature_height_mm = st.slider("Emboss/engrave depth (mm)", 0.2, 2.0, 0.8, step=0.1)

    st.header("Colors")
    st.caption("Used for the preview and the plate's 3MF export (STL has no color).")
    base_color = st.color_picker("Plate color", "#FFFFFF")
    feature_color = st.color_picker("QR color", "#111111")

    st.header("Branding (optional)")
    icon_choice = st.selectbox("Icon", ["None"] + sorted(ICON_PATHS), index=0)
    icon_name = None if icon_choice == "None" else icon_choice
    title_text = st.text_input("Title / company name", "")
    icon_size_mm = title_height_mm = None
    banner_position_label = "Above"
    if icon_name:
        icon_size_mm = st.slider("Icon size (mm)", 5.0, 30.0, 12.0, step=1.0)
    if title_text:
        title_height_mm = st.slider("Title text height (mm)", 3.0, 20.0, 8.0, step=0.5)
        banner_position_label = st.radio(
            "Place above or below the QR code", ["Above", "Below"], horizontal=True,
            help="Icon-only branding (no title) always goes in the upper-right corner instead.",
        )
    banner_position = "above" if banner_position_label == "Above" else "below"

    st.header("Stand base")
    base_depth_mm = st.slider("Base depth (mm)", 20.0, 80.0, 40.0, step=1.0)
    base_height_mm = st.slider("Base height (mm)", 10.0, 40.0, 18.0, step=1.0)
    tilt_deg = st.slider("Lean-back angle (deg)", 0.0, 35.0, 15.0, step=1.0)
    slot_depth_mm = st.slider("Slot depth (mm)", 5.0, 30.0, 12.0, step=1.0)
    slot_clearance_mm = st.slider(
        "Slot clearance (mm)", 0.0, 1.0, 0.3, step=0.05,
        help="Extra slot width so the printed plate slides in. Tune to your printer's tolerance.",
    )

if title_text and shutil.which("potrace") is None:
    st.error("`potrace` was not found on PATH. Install it, e.g. `brew install potrace`, to render title text.")

if data:
    if st.button("Generate stand", type="primary"):
        with st.spinner("Encoding the QR code and building the 3D parts..."):
            try:
                polygons, active_size_mm = generate_qr_polygons(
                    data, error_correction=error_correction, module_size_mm=module_size_mm,
                )
                plate_size_mm = active_size_mm + 2 * margin_mm

                plate_mesh, feature_mask = build_qr_plate_mesh(
                    polygons,
                    active_size_mm=active_size_mm,
                    module_size_mm=module_size_mm,
                    plate_size_mm=plate_size_mm,
                    base_thickness_mm=plate_thickness_mm,
                    feature_height_mm=feature_height_mm,
                    mode=mode,
                )

                if icon_name or title_text:
                    banner_polygons, banner_height_mm = build_banner_polygons(
                        plate_size_mm,
                        icon_name=icon_name,
                        icon_size_mm=icon_size_mm or 12.0,
                        title_text=title_text or None,
                        title_height_mm=title_height_mm or 8.0,
                    )
                    banner_mesh, banner_feature_mask = build_banner_mesh(
                        banner_polygons, plate_size_mm, banner_height_mm, plate_thickness_mm, feature_height_mm,
                        mode=mode,
                    )
                    plate_mesh, feature_mask = stack_plate_pieces(
                        plate_mesh, feature_mask, banner_mesh, banner_feature_mask, position=banner_position,
                    )

                base_mesh = build_stand_base_mesh(
                    width_mm=plate_size_mm,
                    base_depth_mm=base_depth_mm,
                    base_height_mm=base_height_mm,
                    plate_thickness_mm=plate_thickness_mm,
                    tilt_deg=tilt_deg,
                    slot_clearance_mm=slot_clearance_mm,
                    slot_depth_mm=slot_depth_mm,
                )
            except ValueError as e:
                st.error(str(e))
                st.stop()

        # download_button clicks rerun the script with st.button() back to
        # False, so results live in session_state -- see the 3D Wedding
        # Invite page for the same pattern.
        st.session_state["qr_stand"] = {
            "plate_mesh": plate_mesh,
            "feature_mask": feature_mask,
            "base_mesh": base_mesh,
            "plate_size_mm": plate_size_mm,
        }

    if "qr_stand" in st.session_state:
        result = st.session_state["qr_stand"]
        plate_w, plate_h = result["plate_mesh"].bounds[1][:2]
        st.success(f"Built a {plate_w:.0f}x{plate_h:.0f}mm QR plate and matching stand base.")

        tab_plate, tab_base = st.tabs(["QR plate", "Stand base"])
        with tab_plate:
            st.plotly_chart(
                mesh_to_plotly_figure(result["plate_mesh"], result["feature_mask"], base_color, feature_color),
                use_container_width=True,
            )
            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    "Download plate STL",
                    data=mesh_to_stl_bytes(result["plate_mesh"]),
                    file_name="qr_plate.stl",
                    mime="model/stl",
                )
            with col2:
                st.download_button(
                    "Download plate 3MF (colored)",
                    data=mesh_to_3mf_bytes(result["plate_mesh"], result["feature_mask"], base_color, feature_color),
                    file_name="qr_plate.3mf",
                    mime="model/3mf",
                    help="Two-color printing gives the most reliable scans -- geometry/shadow alone can be unreliable.",
                )

        with tab_base:
            st.plotly_chart(
                mesh_to_plotly_figure(result["base_mesh"], base_color=base_color),
                use_container_width=True,
            )
            st.download_button(
                "Download base STL",
                data=mesh_to_stl_bytes(result["base_mesh"]),
                file_name="qr_stand_base.stl",
                mime="model/stl",
            )

        st.info(
            "Print both parts flat on the bed, then slide the plate into the base's slot -- "
            "no glue needed if the clearance is tuned right."
        )
else:
    st.info("Enter a link or some text above to get started.")
