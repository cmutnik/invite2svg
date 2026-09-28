# Copyright (c) 2025 takotime808
"""Shared wrapper around the `potrace` command-line tool, used by the
Photo -> SVG pipeline (streamlit_app.py) and by anything else in this repo
that needs to trace a bitmap into an SVG (e.g. QR Code Stand's title-text
rendering, via qr_stand_utils.text_to_polygons).

Requires the `potrace` command-line tool on PATH (e.g. `brew install potrace`).
"""

import subprocess
import tempfile
from pathlib import Path

import cv2


def run_potrace(bitmap, turdsize=2, alphamax=1.0, opttolerance=0.2):
    """bitmap: uint8 array, 0=ink (black), 255=paper (white). Returns SVG text."""
    with tempfile.TemporaryDirectory() as tmp:
        bmp_path = Path(tmp) / "ink.bmp"
        svg_path = Path(tmp) / "out.svg"
        cv2.imwrite(str(bmp_path), bitmap)

        cmd = [
            "potrace", str(bmp_path),
            "--svg",
            "--group",
            "--turdsize", str(turdsize),
            "--alphamax", str(alphamax),
            "--opttolerance", str(opttolerance),
            "-o", str(svg_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"potrace failed:\n{result.stderr}")
        return svg_path.read_text()
