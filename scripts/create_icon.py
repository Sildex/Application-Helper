#!/usr/bin/env python3
"""Generate autoapply.ico for PyInstaller. Run once before building."""
import io, struct, sys, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPainter, QPixmap, QFont, QPen, QBrush, QColor, QLinearGradient
from PyQt6.QtCore import Qt, QRectF, QRect, QBuffer, QIODevice

app = QApplication(sys.argv)


def render_png(size: int) -> bytes:
    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    # Background rounded square
    r = size * 0.18
    grad = QLinearGradient(0, 0, 0, size)
    grad.setColorAt(0, QColor("#1e1e50"))
    grad.setColorAt(1, QColor("#08081a"))
    p.setBrush(QBrush(grad))
    border_w = max(1.5, size * 0.035)
    pen = QPen(QColor("#6d6df5"), border_w)
    p.setPen(pen)
    margin = border_w / 2 + 1
    p.drawRoundedRect(QRectF(margin, margin, size - margin * 2, size - margin * 2), r, r)

    # "A" glyph
    p.setPen(QColor("#eeeef8"))
    fsz = max(6, int(size * 0.50))
    f = QFont("Segoe UI Variable", fsz, QFont.Weight.Bold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -size * 0.02)
    p.setFont(f)
    p.drawText(QRect(0, -int(size * 0.04), size, size), Qt.AlignmentFlag.AlignCenter, "A")

    # Arrow underline
    if size >= 24:
        aw = max(1.5, size * 0.06)
        pen2 = QPen(QColor("#6d6df5"), aw)
        pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen2)
        y  = int(size * 0.77)
        x1 = int(size * 0.20)
        x2 = int(size * 0.80)
        p.drawLine(x1, y, x2, y)
        tip = int(size * 0.10)
        p.drawLine(x2 - tip, y - tip // 2, x2, y)
        p.drawLine(x2 - tip, y + tip // 2, x2, y)

    p.end()

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    px.save(buf, "PNG")
    return bytes(buf.data())


def build_ico(images: dict) -> bytes:
    """Pack multiple PNG blobs into a .ico file."""
    keys = sorted(images.keys())
    count = len(keys)
    header = struct.pack("<HHH", 0, 1, count)
    data_offset = 6 + count * 16
    dirs = b""
    blobs = b""
    for sz in keys:
        png = images[sz]
        w = h = sz if sz < 256 else 0
        dirs += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(png), data_offset + len(blobs))
        blobs += png
    return header + dirs + blobs


sizes = [16, 24, 32, 48, 64, 128, 256]
pngs = {s: render_png(s) for s in sizes}
ico = build_ico(pngs)
out = os.path.join(os.path.dirname(__file__), "autoapply.ico")
with open(out, "wb") as f:
    f.write(ico)
print(f"Created {out} ({len(ico):,} bytes)")
