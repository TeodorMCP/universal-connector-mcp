"""Generate assets/demo.gif: a typed 'terminal' animation of a real MCP session.

The numbers are not faked - the script drives the actual connector against
Open-Meteo to fetch the live temperature, then renders the transcript as an
animated GIF with Pillow. Re-run to refresh.

Usage: python scripts/make_demo_gif.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

from universal_connector.config import Config
from universal_connector.tools import ConnectorService

ROOT = Path(__file__).resolve().parent.parent
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\CascadiaCode.ttf",
    r"C:\Windows\Fonts\consola.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]

# Palette (GitHub dark).
BG = (13, 17, 23)
BAR = (22, 27, 34)
TEXT = (230, 237, 243)
BLUE = (88, 166, 255)
CYAN = (57, 197, 207)
GREEN = (63, 185, 80)
YELLOW = (227, 179, 65)
PURPLE = (188, 140, 255)
DIM = (139, 148, 158)

W, H = 900, 470
PAD_X, TOP = 28, 58
LINE_H = 28
FONT_SIZE = 18


async def fetch_temperature() -> float:
    service = ConnectorService(Config(allow_all_hosts=True))
    results = await service.search_catalog("weather forecast", include_directory=False)
    entry = next(r for r in results if r["name"] == "open_meteo")
    await service.load_api(spec=entry["spec"], name="open_meteo", base_url=entry.get("base_url"))
    out = await service.execute(
        "open_meteo.get_v1_forecast",
        {"latitude": 52.52, "longitude": 13.41, "current": "temperature_2m"},
        extract=["current.temperature_2m"],
    )
    return float(out["data"]["current.temperature_2m"])


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def build_lines(temp: float) -> list[tuple[int, str, tuple[int, int, int]]]:
    """(indent_chars, text, color) per logical line; '' lines are spacers."""
    return [
        (0, 'you >  what is the temperature in Berlin right now?', BLUE),
        (0, "", TEXT),
        (0, "the agent picks its own tools:", DIM),
        (2, 'search_catalog("weather forecast")', CYAN),
        (5, "-> open_meteo   (no API key needed)", GREEN),
        (2, 'load_api("open_meteo")', CYAN),
        (5, "-> 1 operation ready", GREEN),
        (2, 'execute("open_meteo.get_v1_forecast",', CYAN),
        (10, 'extract=["current.temperature_2m"])', CYAN),
        (5, '-> { "current.temperature_2m": %.1f }' % temp, YELLOW),
        (0, "", TEXT),
        (0, "agent >  It is %.1f\u00b0C in Berlin right now." % temp, TEXT),
        (0, "", TEXT),
        (0, "one connector  |  any API  |  fewer tokens", PURPLE),
    ]


def render_frame(
    lines: list[tuple[int, str, tuple[int, int, int]]],
    upto_line: int,
    upto_char: int,
    font: ImageFont.FreeTypeFont,
    bar_font: ImageFont.FreeTypeFont,
    cursor: bool,
) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Title bar with traffic-light dots.
    d.rectangle([0, 0, W, 38], fill=BAR)
    for i, color in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([20 + i * 22, 14, 32 + i * 22, 26], fill=color)
    d.text((100, 11), "universal-connector-mcp", font=bar_font, fill=DIM)

    char_w = font.getlength("m")
    y = TOP
    for idx in range(min(upto_line + 1, len(lines))):
        indent, text, color = lines[idx]
        shown = text if idx < upto_line else text[:upto_char]
        x = PAD_X + int(indent * char_w)
        d.text((x, y), shown, font=font, fill=color)
        if idx == upto_line and cursor:
            cx = x + int(font.getlength(shown))
            d.rectangle([cx + 1, y + 3, cx + int(char_w) - 1, y + FONT_SIZE + 4], fill=TEXT)
        y += LINE_H
    return img


def main() -> None:
    temp = asyncio.run(fetch_temperature())
    print("live Berlin temperature:", temp)

    font = _font(FONT_SIZE)
    bar_font = _font(15)
    lines = build_lines(temp)

    frames: list[Image.Image] = []
    durations: list[int] = []
    step = 3

    for i, (_, text, _) in enumerate(lines):
        if not text:
            frames.append(render_frame(lines, i, 0, font, bar_font, False))
            durations.append(120)
            continue
        for c in range(step, len(text) + 1, step):
            frames.append(render_frame(lines, i, c, font, bar_font, True))
            durations.append(28)
        # Small hold with cursor at end of the completed line.
        frames.append(render_frame(lines, i, len(text), font, bar_font, True))
        durations.append(260)

    # Final: whole transcript, blinking cursor, long hold.
    last = len(lines) - 1
    for _ in range(3):
        frames.append(render_frame(lines, last, len(lines[last][1]), font, bar_font, True))
        durations.append(500)
        frames.append(render_frame(lines, last, len(lines[last][1]), font, bar_font, False))
        durations.append(500)

    out = ROOT / "assets" / "demo.gif"
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    size_kb = out.stat().st_size / 1024
    print(f"wrote {out} ({len(frames)} frames, {size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
