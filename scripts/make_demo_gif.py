"""Generate assets/demo.gif: a typed 'terminal' animation of a real MCP session.

Nothing is faked: the script drives the actual connector, running one
execute_graph call that fetches the weather for three cities in parallel,
then renders the transcript as an animated GIF. Re-run to refresh the data.

Usage: python scripts/make_demo_gif.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time
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
BAR_BG = (22, 27, 34)
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

CITIES = {
    "berlin": (52.52, 13.41),
    "tokyo": (35.68, 139.69),
    "nyc": (40.71, -74.01),
}

Line = tuple[int, str, tuple[int, int, int]]


async def fetch_data() -> tuple[dict[str, float], float, int, int]:
    """Load Open-Meteo and run the real parallel graph; return live numbers."""
    service = ConnectorService(Config(allow_all_hosts=True))
    results = await service.search_catalog("weather forecast", include_directory=False)
    entry = next(r for r in results if r["name"] == "open_meteo")
    await service.load_api(spec=entry["spec"], name="open_meteo", base_url=entry.get("base_url"))

    nodes = [
        {
            "id": city,
            "operation_id": "open_meteo.get_v1_forecast",
            "params": {"latitude": lat, "longitude": lon, "current": "temperature_2m"},
            "extract": ["current.temperature_2m"],
        }
        for city, (lat, lon) in CITIES.items()
    ]
    start = time.perf_counter()
    graph = await service.execute_graph(nodes)
    elapsed = time.perf_counter() - start
    temps = {c: float(graph[c]["data"]["current.temperature_2m"]) for c in CITIES}

    # Same call without extract, to report the honest size difference.
    full = await service.execute(
        "open_meteo.get_v1_forecast",
        {"latitude": 52.52, "longitude": 13.41, "current": "temperature_2m"},
        fresh=True,
    )
    full_bytes = len(json.dumps(full.get("data", {})))
    slim_bytes = len(json.dumps(graph["berlin"]["data"]))
    return temps, elapsed, full_bytes, slim_bytes


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


class Renderer:
    def __init__(self) -> None:
        self.font = _font(FONT_SIZE)
        self.bar_font = _font(15)
        self.char_w = self.font.getlength("m")

    def frame(self, lines: list[Line], cursor_at: tuple[int, int] | None = None) -> Image.Image:
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, W, 38], fill=BAR_BG)
        for i, color in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse([20 + i * 22, 14, 32 + i * 22, 26], fill=color)
        d.text((100, 11), "universal-connector-mcp", font=self.bar_font, fill=DIM)

        y = TOP
        for idx, (indent, text, color) in enumerate(lines):
            x = PAD_X + int(indent * self.char_w)
            d.text((x, y), text, font=self.font, fill=color)
            if cursor_at is not None and cursor_at[0] == idx:
                cx = x + int(self.font.getlength(text[: cursor_at[1]]))
                d.rectangle(
                    [cx + 1, y + 3, cx + int(self.char_w) - 1, y + FONT_SIZE + 4], fill=TEXT
                )
            y += LINE_H
        return img


class Movie:
    def __init__(self, renderer: Renderer) -> None:
        self.r = renderer
        self.frames: list[Image.Image] = []
        self.durations: list[int] = []

    def add(self, lines: list[Line], duration: int, cursor: tuple[int, int] | None = None) -> None:
        self.frames.append(self.r.frame(lines, cursor))
        self.durations.append(duration)

    def type_scene(self, lines: list[Line], step: int = 3, hold_end: int = 1400) -> None:
        """Type *lines* one by one on a fresh screen, then hold."""
        shown: list[Line] = []
        for indent, text, color in lines:
            if not text:
                shown.append((indent, "", color))
                self.add(shown, 110)
                continue
            for c in range(step, len(text) + 1, step):
                partial = shown + [(indent, text[:c], color)]
                self.add(partial, 26, cursor=(len(shown), c))
            shown.append((indent, text, color))
            self.add(shown, 240, cursor=(len(shown) - 1, len(text)))
        self.add(shown, hold_end)


def scene_question(mv: Movie) -> None:
    mv.type_scene(
        [
            (0, "you >  compare the weather in Berlin, Tokyo and New York", BLUE),
            (0, "", TEXT),
            (0, "three cities. one API to load - not three MCP servers:", DIM),
            (0, "", TEXT),
            (2, 'search_catalog("weather")  ->  open_meteo (no key needed)', CYAN),
            (2, 'load_api("open_meteo")     ->  ready', CYAN),
        ],
        hold_end=1100,
    )


def scene_graph(mv: Movie, temps: dict[str, float], elapsed: float) -> None:
    intro: list[Line] = [
        (0, "one tool call runs the whole graph - nodes fire in parallel:", DIM),
        (0, "", TEXT),
        (2, "execute_graph(nodes=[", CYAN),
        (4, '{id:"berlin", op:"get_v1_forecast", extract:["current.temperature_2m"]},', CYAN),
        (4, '{id:"tokyo",  op:"get_v1_forecast", extract:["current.temperature_2m"]},', CYAN),
        (4, '{id:"nyc",    op:"get_v1_forecast", extract:["current.temperature_2m"]},', CYAN),
        (2, "])", CYAN),
        (0, "", TEXT),
    ]
    # Type the intro (reuse the typing helper, then continue on the same screen).
    shown: list[Line] = []
    for indent, text, color in intro:
        if not text:
            shown.append((indent, "", color))
            mv.add(shown, 100)
            continue
        for c in range(3, len(text) + 1, 3):
            mv.add(shown + [(indent, text[:c], color)], 24, cursor=(len(shown), c))
        shown.append((indent, text, color))
        mv.add(shown, 180)

    # All three progress bars grow simultaneously - that's the point.
    width = 14
    for t in range(1, width + 1):
        bar = "#" * t + "-" * (width - t)
        rows = [(2, f"{city:<8}[{bar}]", GREEN) for city in CITIES]
        note = [(2, "", TEXT)] if t < width else []
        mv.add(shown + rows + note, 55)

    done_rows: list[Line] = [
        (2, f"{city:<8}[{'#' * width}]  {temps[city]:.1f}\u00b0C", GREEN) for city in CITIES
    ]
    final = shown + done_rows
    final += [
        (0, "", TEXT),
        (0, f"3 live HTTP calls, 1 tool call, {elapsed:.2f}s total.", YELLOW),
    ]
    mv.add(final, 2400)


def scene_score(mv: Movie, full_bytes: int, slim_bytes: int) -> None:
    mv.type_scene(
        [
            (0, "the score:", DIM),
            (0, "", TEXT),
            (2, "3+ tool calls      ->  1   (execute_graph, auto-parallel)", TEXT),
            (2, f"{full_bytes} B response  ->  {slim_bytes} B  (extract: only fields you ask)", TEXT),
            (2, "3  MCP servers     ->  0 extra installed", TEXT),
            (0, "", TEXT),
            (2, "2500+ public APIs in the built-in catalog", GREEN),
            (2, "OpenAPI | GraphQL | gRPC | SOAP", GREEN),
            (0, "", TEXT),
            (2, "$ uvx universal-connector-mcp", PURPLE),
        ],
        hold_end=3200,
    )


def main() -> None:
    temps, elapsed, full_bytes, slim_bytes = asyncio.run(fetch_data())
    print(f"live temps: {temps}  graph took {elapsed:.2f}s  {full_bytes}B -> {slim_bytes}B")

    mv = Movie(Renderer())
    scene_question(mv)
    scene_graph(mv, temps, elapsed)
    scene_score(mv, full_bytes, slim_bytes)

    out = ROOT / "assets" / "demo.gif"
    mv.frames[0].save(
        out,
        save_all=True,
        append_images=mv.frames[1:],
        duration=mv.durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(f"wrote {out} ({len(mv.frames)} frames, {out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
