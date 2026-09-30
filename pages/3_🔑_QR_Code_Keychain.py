# Copyright (c) 2025 takotime808
"""Streamlit page that turns a link/text into a 3D-printable QR code
keychain: a small flat plate with the QR pattern embossed/engraved on it,
fused directly into a loop with a through-hole for a split ring -- one
single FDM-ready part, unlike the QR Code Stand page's two separate
pieces.

Run with:
    streamlit run streamlit_app.py
(this page is auto-discovered from the sidebar)
"""

import streamlit as st

from card3d_utils import mesh_to_3mf_bytes, mesh_to_plotly_figure, mesh_to_stl_bytes
from qr_stand_utils import build_keychain_loop_mesh, build_qr_plate_mesh, generate_qr_polygons, stack_plate_pieces

st.set_page_config(page_title="QR Code Keychain", page_icon="🔑", layout="wide")

st.title("QR Code Keychain")
st.caption(
    "Turns a link (your shop, Wi-Fi password, contact card, etc.) into a QR code "
    "embossed on a small plate with a keyring loop built right in -- one part, ready "
    "to print on an FDM printer."
)

data = st.text_input("Link or text to encode", placeholder="https://your-shop.example.com")

with st.sidebar:
    st.header("QR code")
    error_correction = st.selectbox(
        "Error correction", ["L", "M", "Q", "H"], index=1,
        help="Higher levels tolerate more damage/dirt but make a denser code. M is a good default.",
    )
    module_size_mm = st.slider(
        "Module size (mm)", 0.6, 2.5, 1.2, step=0.1,
        help="Size of one QR pixel. Keychains stay pocket-sized, so this defaults smaller than the stand page's.",
    )
    margin_mm = st.slider(
        "Quiet-zone margin (mm)", 1.5, 10.0, 4.0, step=0.5,
        help="Blank border around the code -- scanners need this. Aim for at least ~4x the module size.",
    )

    st.header("Plate")
    mode_label = st.radio(
        "Artwork direction",
        ["Raised (emboss)", "Indented (engrave)"],
        help="Raised + 2-color printing (3MF) gives the most reliable scans. Engrave holds up well to handling too.",
    )
    mode = "raised" if mode_label.startswith("Raised") else "indented"
    plate_thickness_mm = st.slider(
        "Plate thickness (mm)", 2.0, 6.0, 3.0, step=0.5,
        help="Thicker than the stand page's default -- a keychain takes more handling.",
    )
    feature_height_mm = st.slider("Emboss/engrave depth (mm)", 0.2, 1.5, 0.6, step=0.1)

    st.header("Colors")
    st.caption("Used for the preview and the 3MF export (STL has no color).")
    base_color = st.color_picker("Plate color", "#FFFFFF")
    feature_color = st.color_picker("QR color", "#111111")

    st.header("Keyring loop")
    loop_position_label = st.radio("Loop position", ["Above", "Below"], horizontal=True, index=0)
    loop_position = "above" if loop_position_label == "Above" else "below"
    loop_diameter_mm = st.slider("Loop outer diameter (mm)", 10.0, 25.0, 16.0, step=0.5)
    hole_diameter_mm = st.slider(
        "Split-ring hole diameter (mm)", 3.0, 12.0, 5.5, step=0.5,
        help="A standard keyring split ring needs ~5-6mm to thread through comfortably.",
    )
    neck_width_mm = st.slider("Neck width (mm)", 4.0, 20.0, 10.0, step=1.0)
    neck_height_mm = st.slider(
        "Neck height (mm)", 0.0, 8.0, 2.0, step=0.5,
        help="Extra straight material between the plate and the loop, before the loop curves away.",
    )

if data:
    if st.button("Generate keychain", type="primary"):
        with st.spinner("Encoding the QR code and building the 3D model..."):
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

                loop_mesh, loop_feature_mask = build_keychain_loop_mesh(
                    plate_size_mm,
                    plate_thickness_mm,
                    loop_diameter_mm=loop_diameter_mm,
                    hole_diameter_mm=hole_diameter_mm,
                    neck_width_mm=neck_width_mm,
                    neck_height_mm=neck_height_mm,
                )

                keychain_mesh, keychain_feature_mask = stack_plate_pieces(
                    plate_mesh, feature_mask, loop_mesh, loop_feature_mask, position=loop_position,
                )
            except ValueError as e:
                st.error(str(e))
                st.stop()

        # download_button clicks rerun the script with st.button() back to
        # False, so results live in session_state -- see the 3D Wedding
        # Invite page for the same pattern.
        st.session_state["qr_keychain"] = {
            "mesh": keychain_mesh,
            "feature_mask": keychain_feature_mask,
        }

    if "qr_keychain" in st.session_state:
        result = st.session_state["qr_keychain"]
        width_mm, height_mm = result["mesh"].bounds[1][:2]
        st.success(f"Built a {width_mm:.0f}x{height_mm:.0f}mm QR code keychain.")

        st.plotly_chart(
            mesh_to_plotly_figure(result["mesh"], result["feature_mask"], base_color, feature_color),
            use_container_width=True,
        )

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "Download STL",
                data=mesh_to_stl_bytes(result["mesh"]),
                file_name="qr_keychain.stl",
                mime="model/stl",
            )
        with col2:
            st.download_button(
                "Download 3MF (colored)",
                data=mesh_to_3mf_bytes(result["mesh"], result["feature_mask"], base_color, feature_color),
                file_name="qr_keychain.3mf",
                mime="model/3mf",
                help="Two-color printing gives the most reliable scans -- geometry/shadow alone can be unreliable.",
            )

        st.info(
            "Print flat on the bed (loop side up or down, either works) -- no supports needed "
            "for the hole since it's a small, mostly-vertical span."
        )
else:
    st.info("Enter a link or some text above to get started.")
