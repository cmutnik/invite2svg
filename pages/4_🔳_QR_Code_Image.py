# Copyright (c) 2025 takotime808
"""Streamlit page that turns a link/text into a flat QR code image you can
download as an SVG (vector) or PNG.

Run with:
    streamlit run streamlit_app.py
(this page is auto-discovered from the sidebar)
"""

import streamlit as st

from qr_image_utils import qr_to_png_bytes, qr_to_svg_bytes

st.set_page_config(page_title="QR Code Image", page_icon="🔳", layout="wide")

st.title("QR Code Image")
st.caption("Turns a link or text into a QR code you can download as an SVG or PNG.")

data = st.text_input("Link or text to encode", placeholder="https://your-shop.example.com")

with st.sidebar:
    st.header("QR code")
    error_correction = st.selectbox(
        "Error correction", ["L", "M", "Q", "H"], index=1,
        help="Higher levels tolerate more damage/dirt but make a denser code. M is a good default.",
    )
    border_modules = st.slider(
        "Quiet-zone border (modules)", 0, 10, 4,
        help="Blank border around the code -- scanners need this. The QR spec asks for at least 4.",
    )
    module_px = st.slider("PNG module size (px)", 2, 40, 10, help="Pixels per QR square in the PNG.")
    fg = st.color_picker("Code color", "#000000")
    bg = st.color_picker("Background color", "#ffffff")

if data:
    try:
        svg_bytes = qr_to_svg_bytes(data, error_correction, border_modules, fg, bg)
        png_bytes = qr_to_png_bytes(data, error_correction, border_modules, module_px, fg, bg)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    st.image(png_bytes, width=320)
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("Download SVG", data=svg_bytes, file_name="qr_code.svg", mime="image/svg+xml")
    with col2:
        st.download_button("Download PNG", data=png_bytes, file_name="qr_code.png", mime="image/png")
