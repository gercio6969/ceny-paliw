"""Generuje ikony aplikacji (uruchamiane ręcznie: python scripts/make_icons.py)."""

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "web" / "icons"
BG = (17, 18, 20)
YELLOW = (255, 210, 63)


def draw(size: int, *, maskable: bool, rounded: bool) -> Image.Image:
    scale = 4  # supersampling dla gładkich krawędzi
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if rounded:
        d.rounded_rectangle((0, 0, s, s), radius=int(s * 0.22), fill=BG)
    else:
        d.rectangle((0, 0, s, s), fill=BG)

    # kropla paliwa: koło + trójkąt styczny do koła (bez wcięć na łączeniu);
    # dla maskable mniejsza, żeby zmieściła się w strefie bezpiecznej
    k = 0.62 if maskable else 0.8
    r = s * 0.24 * k
    cx, cy = s / 2, s / 2 + r * 0.5  # środek koła
    apex_y = cy - r * 2.4
    dist = cy - apex_y
    # punkt styczności: odległość od środka wzdłuż osi i połowa szerokości cięciwy
    ty = cy - r * r / dist
    tx = r * math.sqrt(1 - (r / dist) ** 2)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=YELLOW)
    d.polygon([(cx, apex_y), (cx - tx, ty), (cx + tx, ty)], fill=YELLOW)
    hl = r * 0.28  # odblask
    d.ellipse(
        (cx - r * 0.45 - hl, cy - r * 0.05 - hl, cx - r * 0.45 + hl, cy - r * 0.05 + hl),
        fill=(255, 236, 160),
    )
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw(192, maskable=False, rounded=True).save(OUT / "icon-192.png")
    draw(512, maskable=False, rounded=True).save(OUT / "icon-512.png")
    draw(512, maskable=True, rounded=False).save(OUT / "icon-maskable-512.png")
    # iOS sam zaokrągla rogi i nie obsługuje przezroczystości
    draw(180, maskable=False, rounded=False).convert("RGB").save(OUT / "apple-touch-icon.png")


if __name__ == "__main__":
    main()
