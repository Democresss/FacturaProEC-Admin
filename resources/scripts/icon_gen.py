"""icon_gen — Generador del escudo PIL para el icono de la app.

Genera icono PNG/ICO/ICNS con un escudo de dos tonos (azul cuerpo +
borde verde) y "F" blanca, replicable en distintos tamaños.

Uso:
    python icon_gen.py            # genera en resources/icons/
    python icon_gen.py --all      # icon.png + icon.ico + icon.icns
"""
import os
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow no instalado. Ejecuta: pip install Pillow", file=sys.stderr)
    sys.exit(1)

OUT = Path(__file__).resolve().parent.parent / "resources" / "icons"
OUT.mkdir(parents=True, exist_ok=True)

# Paleta
AZUL = (2, 132, 199)        # #0284C7
AZUL_OSC = (3, 105, 161)    # #0369A1
VERDE = (16, 185, 129)      # #10B981
BLANCO = (255, 255, 255, 255)
TRANSP = (0, 0, 0, 0)

def make_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), TRANSP)
    draw = ImageDraw.Draw(img)
    pad = max(2, size // 16)
    # Escudo: poligono tipo armiño
    # Puntos: izq-arriba, der-arriba, der-centro, abajo-centro, izq-centro
    top = pad
    bot = size - pad
    mid = size // 2
    shoulder = int(size * 0.30)
    waist = int(size * 0.62)

    # Borde verde
    def shield_points(inner: int):
        return [
            (pad + inner, top + inner),
            (size - pad - inner, top + inner),
            (size - pad - inner, shoulder + inner),
            (mid, bot - inner),
            (pad + inner, waist + inner),
        ]

    # Dibujar borde exterior verde
    draw.polygon(shield_points(0), fill=VERDE + (255,) if len(VERDE) == 3 else VERDE)
    # Cuerpo azul interior (escudo ligeramente menor)
    border_w = max(2, size // 32)
    draw.polygon(shield_points(border_w), fill=AZUL + (255,) if len(AZUL) == 3 else AZUL)

    # "F" blanca centrada
    try:
        font_size = int(size * 0.55)
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    text = "F"
    tw, th = draw.textbbox((0, 0), text, font=font)[2:]
    tx = (size - tw) // 2
    ty = (size - th) // 2 - int(size * 0.05)
    # Sombra
    draw.text((tx + 2, ty + 2), text, font=font, fill=(0, 0, 0, 80))
    draw.text((tx, ty), text, font=font, fill=BLANCO[:3] + (255,))

    return img


def main():
    sizes = {"icon.png": 512, "icon.ico": 256, "icon@2x.png": 1024}
    args = set(sys.argv[1:])
    do_all = "--all" in args or not args
    if do_all or "png" in args or "--png" in args:
        for name, sz in [("icon.png", 512), ("icon@2x.png", 256)]:
            img = make_icon(sz)
            img.save(OUT / name)
            print(f"Generado {name} ({sz}x{sz})")
    if do_all or "ico" in args or "--ico" in args:
        img = make_icon(256)
        img.save(OUT / "icon.ico")
        print(f"Generado icon.ico")
    if do_all or "icns" in args or "--icns" in args:
        img = make_icon(1024)
        img.save(OUT / "icon.icns")
        print(f"Generado icon.icns")

    # También generar variantes 16,32,64 para Linux tray
    for sz in [16, 24, 32, 48, 64]:
        img = make_icon(sz)
        img.save(OUT / f"icon-{sz}.png")
    print(f"Iconos guardados en {OUT}")


if __name__ == "__main__":
    main()
