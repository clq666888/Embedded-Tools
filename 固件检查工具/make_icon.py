"""Draw the app icon from geometric shapes; requires Pillow for building only."""

from pathlib import Path
from PIL import Image, ImageDraw


def draw_icon(size: int) -> Image.Image:
    scale = size / 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)

    def box(coords):
        return tuple(round(v * scale) for v in coords)

    d.rounded_rectangle(box((19, 19, 237, 237)), radius=round(48 * scale), fill="#163653")
    for v in (72, 104, 136, 168):
        d.rounded_rectangle(box((v, 42, v + 13, 70)), radius=round(4 * scale), fill="#59D4BE")
        d.rounded_rectangle(box((v, 186, v + 13, 214)), radius=round(4 * scale), fill="#59D4BE")
        d.rounded_rectangle(box((42, v, 70, v + 13)), radius=round(4 * scale), fill="#59D4BE")
        d.rounded_rectangle(box((186, v, 214, v + 13)), radius=round(4 * scale), fill="#59D4BE")
    d.rounded_rectangle(box((63, 63, 193, 193)), radius=round(24 * scale), fill="#E8F6FA")
    d.rounded_rectangle(box((76, 76, 180, 180)), radius=round(16 * scale), fill="#236994")
    width = max(2, round(9 * scale))
    d.line([box((93, 150))[:2], box((112, 150))[:2], box((112, 112))[:2], box((142, 112))[:2]], fill="#E8F6FA", width=width, joint="curve")
    d.ellipse(box((135, 103, 157, 125)), fill="#59D4BE")
    return image


if __name__ == "__main__":
    output = Path(__file__).resolve().parent / "assets" / "firmware.ico"
    output.parent.mkdir(parents=True, exist_ok=True)
    draw_icon(256).save(output, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(output)
