# Copyright (c) 2025 takotime808
"""
Streamlit UI wrapping the photo -> SVG pipeline in this repo.

Upload a photo of a printed card and get back a vectorized SVG, using the
same deskew / ink-mask / potrace pipeline as photo_to_svg.py, extract_border.py
and extract_text.py (all built on card_utils.py).

Run with:
    streamlit run streamlit_app.py

Requires the `potrace` command-line tool on PATH (e.g. `brew install potrace`).
"""

import shutil
from pathlib import Path

import cv2
import numpy as np
import streamlit as st

from card_utils import clean_ink_mask, deskew_card, find_shadow_trim, ink_mask, locate_card
from potrace_utils import run_potrace

st.set_page_config(page_title="Photo to SVG", page_icon="✂️", layout="wide")


def full_card_ink(img, min_area):
    card = deskew_card(img)
    gray = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY)
    ink = ink_mask(gray)

    row_density = ink.mean(axis=1)
    col_density = ink.mean(axis=0)
    h, w = ink.shape
    top = find_shadow_trim(row_density)
    bottom = find_shadow_trim(row_density[::-1])
    left = find_shadow_trim(col_density)
    right = find_shadow_trim(col_density[::-1])

    trimmed = card[top:h - bottom, left:w - right]
    tgray = cv2.cvtColor(trimmed, cv2.COLOR_BGR2GRAY)
    tink = ink_mask(tgray).astype(np.uint8) * 255
    tink = clean_ink_mask(tink, min_area=min_area)
    return trimmed, tink


def border_only_ink(img, min_area, pad, enter_thresh, exit_thresh, exit_run, max_frac):
    trimmed, top, bottom, left, right = locate_card(
        img, pad=pad, enter_thresh=enter_thresh, exit_thresh=exit_thresh,
        exit_run=exit_run, max_frac=max_frac,
    )
    tgray = cv2.cvtColor(trimmed, cv2.COLOR_BGR2GRAY)
    tink = ink_mask(tgray).astype(np.uint8) * 255
    tink = clean_ink_mask(tink, min_area=min_area)

    th, tw = tink.shape
    band = np.zeros((th, tw), dtype=np.uint8)
    band[:top, :] = 255
    band[th - bottom:, :] = 255
    band[:, :left] = 255
    band[:, tw - right:] = 255

    tink = cv2.bitwise_and(tink, band)
    return trimmed, tink


def text_only_ink(img, min_area, pad):
    trimmed, top, bottom, left, right = locate_card(img, pad=pad)
    th, tw = trimmed.shape[:2]
    interior = trimmed[top:th - bottom, left:tw - right]
    igray = cv2.cvtColor(interior, cv2.COLOR_BGR2GRAY)
    iink = ink_mask(igray).astype(np.uint8) * 255
    iink = clean_ink_mask(iink, min_area=min_area)

    tink = np.zeros((th, tw), dtype=np.uint8)
    tink[top:th - bottom, left:tw - right] = iink
    return trimmed, tink


st.title("Photo → SVG")
st.caption(
    "Deskews a photographed card, thresholds it to ink/paper, and traces it "
    "to a vector SVG with potrace — ready to extrude onto a base rectangle."
)

if shutil.which("potrace") is None:
    st.error("`potrace` was not found on PATH. Install it, e.g. `brew install potrace`, then restart this app.")
    st.stop()

uploaded = st.file_uploader("Upload a photo of the card", type=["png", "jpg", "jpeg"])

example_path = Path(__file__).parent / "data" / "wedding_invite.png"
if example_path.exists():
    if st.button(f"Use example image ({example_path.name})"):
        st.session_state["use_example"] = True
if uploaded is not None:
    st.session_state["use_example"] = False

with st.sidebar:
    st.header("Mode")
    mode = st.radio(
        "What to vectorize",
        ["Full card (border + text)", "Border only", "Text only"],
        help="Border/text separation uses the same border-thickness detection as extract_border.py / extract_text.py.",
    )

    st.header("Ink cleanup")
    min_area = st.slider("Min speck area (px)", 0, 50, 2, help="Drop ink specks smaller than this many pixels.")

    if mode != "Full card (border + text)":
        pad = st.slider("Border padding (px)", 0, 30, 4)
    if mode == "Border only":
        enter_thresh = st.slider("Border enter threshold", 0.0, 1.0, 0.15)
        exit_thresh = st.slider("Border exit threshold", 0.0, 1.0, 0.10)
        exit_run = st.slider("Border exit run (px)", 1, 60, 20)
        max_frac = st.slider("Max border search fraction", 0.05, 0.5, 0.3)

    st.header("Potrace curve fitting")
    turdsize = st.slider("Turdsize (speckle suppression)", 0, 20, 2)
    alphamax = st.slider("Alphamax (corner threshold)", 0.0, 1.34, 1.0)
    opttolerance = st.slider("Opttolerance (curve-fit tolerance)", 0.0, 1.0, 0.2)

using_example = uploaded is None and st.session_state.get("use_example", False)

if uploaded is not None or using_example:
    if uploaded is not None:
        file_bytes = np.frombuffer(uploaded.read(), np.uint8)
        name_stem = Path(uploaded.name).stem
    else:
        file_bytes = np.frombuffer(example_path.read_bytes(), np.uint8)
        name_stem = example_path.stem

    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    if img is None:
        st.error("Could not decode that image.")
        st.stop()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Input")
        st.image(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), use_container_width=True)

    if st.button("Generate SVG", type="primary"):
        with st.spinner("Deskewing, thresholding, and tracing..."):
            try:
                if mode == "Full card (border + text)":
                    trimmed, tink = full_card_ink(img, min_area)
                elif mode == "Border only":
                    trimmed, tink = border_only_ink(
                        img, min_area, pad, enter_thresh, exit_thresh, exit_run, max_frac
                    )
                else:
                    trimmed, tink = text_only_ink(img, min_area, pad)

                bitmap = np.where(tink > 0, 0, 255).astype(np.uint8)
                svg_text = run_potrace(bitmap, turdsize, alphamax, opttolerance)
            except RuntimeError as e:
                st.error(str(e))
                st.stop()

        st.session_state["generated_svg"] = svg_text
        st.session_state["generated_svg_name"] = name_stem

        with col2:
            st.subheader("Traced ink mask")
            st.image(tink, use_container_width=True)

        st.subheader("Output SVG")
        st.markdown(
            f'<div style="width:100%">{svg_text}</div>',
            unsafe_allow_html=True,
        )

        st.download_button(
            "Download SVG",
            data=svg_text,
            file_name=name_stem + ".svg",
            mime="image/svg+xml",
        )

        with st.expander("View raw SVG source"):
            st.code(svg_text, language="xml")

        st.info("Ready to extrude this onto a 3D card — open **3D Wedding Invite** in the sidebar.")
else:
    st.info("Upload a photo to get started.")
