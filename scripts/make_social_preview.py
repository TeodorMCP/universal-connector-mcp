"""Compose assets/social-preview.png (1280x640) for the GitHub social preview.

Upload it manually: repo Settings -> General -> Social preview -> Edit.

Usage: python scripts/make_social_preview.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent

BG = (13, 17, 23)
TEXT = (230, 237, 243)
DIM = (139, 148, 158)
GREEN = (63, 185, 80)
PURPLE = (188, 140, 255)

W, H = 1280, 640

FONT_BOLD = r"C:\Windows\Fonts\segoeuib.ttf"
FONT_REG = r"C:\Windows\Fonts\segoeui.ttf"
FONT_MONO = r"C:\Windows\Fonts\CascadiaCode.ttf"


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Subtle top accent strip.
    d.rectangle([0, 0, W, 6], fill=PURPLE)

    logo = Image.open(ROOT / "assets" / "logo.png").convert("RGBA").resize((340, 340))
    img.paste(logo, (80, (H - 340) // 2), logo)

    x = 470
    title_font = ImageFont.truetype(FONT_BOLD, 64)
    d.text((x, 150), "Universal API", font=title_font, fill=TEXT)
    d.text((x, 225), "Connector MCP", font=title_font, fill=TEXT)

    tag_font = ImageFont.truetype(FONT_REG, 34)
    d.text((x, 330), "Any API. One MCP server.", font=tag_font, fill=DIM)

    chip_font = ImageFont.truetype(FONT_MONO, 26)
    d.text((x, 405), "OpenAPI | GraphQL | gRPC | SOAP", font=chip_font, fill=GREEN)

    foot_font = ImageFont.truetype(FONT_MONO, 22)
    d.text((x, 470), "2500+ public APIs - security-first - local", font=foot_font, fill=DIM)
    d.text((x, 510), "$ uvx universal-connector-mcp", font=foot_font, fill=PURPLE)

    out = ROOT / "assets" / "social-preview.png"
    img.save(out, optimize=True)
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
