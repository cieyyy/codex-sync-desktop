from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SCALE = 4
SIZE = 256


def point(value: int) -> int:
    return value * SCALE


def generate() -> None:
    canvas = Image.new("RGBA", (point(SIZE), point(SIZE)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    draw.rounded_rectangle(
        (point(8), point(8), point(248), point(248)),
        radius=point(56),
        fill="#080E24",
        outline="#1D2B53",
        width=point(8),
    )
    line_width = point(18)
    draw.arc(
        (point(54), point(45), point(207), point(154)),
        start=202,
        end=338,
        fill="#38BDF8",
        width=line_width,
    )
    draw.polygon(
        ((point(188), point(59)), (point(212), point(99)), (point(166), point(103))),
        fill="#38BDF8",
    )
    draw.arc(
        (point(49), point(102), point(202), point(211)),
        start=22,
        end=158,
        fill="#67E8F9",
        width=line_width,
    )
    draw.polygon(
        ((point(68), point(197)), (point(44), point(157)), (point(90), point(153))),
        fill="#67E8F9",
    )
    draw.rounded_rectangle(
        (point(46), point(98), point(104), point(144)),
        radius=point(12),
        fill="#38BDF8",
    )
    draw.rounded_rectangle(
        (point(152), point(112), point(210), point(158)),
        radius=point(12),
        fill="#67E8F9",
    )
    draw.ellipse((point(67), point(113), point(83), point(129)), fill="#050816")
    draw.ellipse((point(173), point(127), point(189), point(143)), fill="#050816")

    icon = canvas.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    ASSETS.mkdir(parents=True, exist_ok=True)
    icon.save(ASSETS / "icon.png", optimize=True)
    icon.save(
        ASSETS / "icon.ico",
        format="ICO",
        sizes=((16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)),
    )
    icon.save(ASSETS / "icon.icns", format="ICNS")


if __name__ == "__main__":
    generate()
