# Copyright (c) 2025 takotime808
"""Flat QR code image export (SVG / PNG) for the QR Code Image page."""

import io

import qrcode
from PIL import Image

_ERROR_LEVELS = {
    "L": qrcode.constants.ERROR_CORRECT_L,
    "M": qrcode.constants.ERROR_CORRECT_M,
    "Q": qrcode.constants.ERROR_CORRECT_Q,
    "H": qrcode.constants.ERROR_CORRECT_H,
}


def _matrix(data, error_correction):
    if not data:
        raise ValueError("Enter some text or a URL to encode.")
    qr = qrcode.QRCode(error_correction=_ERROR_LEVELS[error_correction], box_size=1, border=0)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.get_matrix()


def qr_to_svg_bytes(data, error_correction="M", border_modules=4, fg="#000000", bg="#ffffff"):
    """Vector QR code as UTF-8 SVG bytes: one rect per horizontal run of
    dark modules, in module units (scales losslessly)."""
    matrix = _matrix(data, error_correction)
    n = len(matrix)
    total = n + 2 * border_modules
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" '
        f'shape-rendering="crispEdges">',
        f'<rect width="{total}" height="{total}" fill="{bg}"/>',
        f'<path fill="{fg}" d="',
    ]
    d = []
    for r, row in enumerate(matrix):
        c = 0
        while c < n:
            if row[c]:
                start = c
                while c < n and row[c]:
                    c += 1
                d.append(f"M{start + border_modules} {r + border_modules}h{c - start}v1h-{c - start}z")
            else:
                c += 1
    parts.append("".join(d))
    parts.append('"/></svg>')
    return "".join(parts).encode("utf-8")


def qr_to_png_bytes(data, error_correction="M", border_modules=4, module_px=10, fg="#000000", bg="#ffffff"):
    """Raster QR code as PNG bytes, `module_px` pixels per module."""
    matrix = _matrix(data, error_correction)
    n = len(matrix)
    img = Image.new("1", (n, n), 1)
    px = img.load()
    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            if dark:
                px[c, r] = 0
    img = img.resize((n * module_px, n * module_px), Image.NEAREST).convert("L")
    mask = img.point(lambda v: 255 if v == 0 else 0)  # 255 where dark
    canvas_px = (n + 2 * border_modules) * module_px
    out = Image.new("RGB", (canvas_px, canvas_px), bg)
    out.paste(Image.new("RGB", img.size, fg), (border_modules * module_px,) * 2, mask)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()
