#!/usr/bin/env python3
"""Render LocalAgent website demo MP4s + posters from scenes.json."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
SCENES_PATH = ROOT / "scenes.json"
OUT_DIR = ROOT.parent / "assets" / "demos"

COLORS = {
    "bg": (14, 14, 18),
    "elevated": (20, 20, 26),
    "bar": (10, 10, 14),
    "line": (48, 48, 56),
    "text": (232, 228, 220),
    "muted": (155, 150, 140),
    "gold": (201, 166, 107),
    "gold_soft": (214, 188, 140),
    "cyan": (110, 196, 232),
    "out": (200, 196, 186),
    "traffic_r": (201, 166, 107),
    "traffic_y": (110, 196, 232),
    "traffic_g": (120, 120, 128),
}

KIND_COLOR = {
    "prompt": COLORS["gold_soft"],
    "you": COLORS["cyan"],
    "assistant": COLORS["text"],
    "out": COLORS["out"],
    "meta": COLORS["muted"],
    "dim": COLORS["muted"],
    "accent": COLORS["gold"],
    "label": COLORS["gold_soft"],
}


def _load_font(size: int, *, prefer_cjk: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if prefer_cjk:
        candidates.extend(
            [
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/Hiragino Sans GB.ttc",
                "/System/Library/Fonts/STHeiti Light.ttc",
                "/Library/Fonts/Arial Unicode.ttf",
            ]
        )
    candidates.extend(
        [
            "/System/Library/Fonts/Menlo.ttc",
            "/System/Library/Fonts/SFNSMono.ttf",
            "/System/Library/Fonts/Supplemental/Courier New.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size, index=0)
        except OSError:
            continue
    return ImageFont.load_default()


def _needs_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    if not text:
        return [""]
    words: list[str] = []
    # Prefer character wrapping for CJK / long unbroken tokens.
    if _needs_cjk(text) or " " not in text.strip():
        buf = ""
        for ch in text:
            trial = buf + ch
            if draw.textlength(trial, font=font) <= max_width:
                buf = trial
            else:
                if buf:
                    words.append(buf)
                buf = ch
        if buf:
            words.append(buf)
        return words or [""]

    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        trial = word if not current else f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _draw_chrome(draw: ImageDraw.ImageDraw, width: int, title_font: ImageFont.ImageFont) -> int:
    bar_h = 42
    draw.rectangle((0, 0, width, bar_h), fill=COLORS["bar"])
    draw.line((0, bar_h, width, bar_h), fill=COLORS["line"], width=1)
    for i, color in enumerate(
        (COLORS["traffic_r"], COLORS["traffic_y"], COLORS["traffic_g"])
    ):
        x = 18 + i * 18
        draw.ellipse((x, 15, x + 11, 26), fill=color)
    label = "LOCALAGENT"
    draw.text((78, 12), label, fill=COLORS["muted"], font=title_font)
    return bar_h


def _layout_lines(
    events: list[dict],
    *,
    width: int,
    body_top: int,
    font: ImageFont.ImageFont,
    label_font: ImageFont.ImageFont,
    draw: ImageDraw.ImageDraw,
) -> list[tuple[str, str, int]]:
    """Return visible rows as (kind, text, y)."""
    pad_x = 28
    max_w = width - pad_x * 2
    y = body_top + 22
    rows: list[tuple[str, str, int]] = []
    line_gap = 6

    for event in events:
        kind = event["kind"]
        if kind == "gap":
            y += 14
            continue
        text = event.get("text", "")
        use_font = label_font if kind == "label" else font
        wrapped = _wrap_text(text, use_font, max_w, draw)
        for part in wrapped:
            rows.append((kind, part, y))
            bbox = use_font.getbbox(part or " ")
            h = max(18, bbox[3] - bbox[1])
            y += h + line_gap
        if kind == "label":
            y += 4
    return rows


def render_frame(
    rows: list[tuple[str, str, int]],
    *,
    width: int,
    height: int,
    fonts: dict[str, ImageFont.ImageFont],
    cursor: tuple[str, int, int] | None = None,
) -> Image.Image:
    img = Image.new("RGB", (width, height), COLORS["elevated"])
    draw = ImageDraw.Draw(img)
    bar_h = _draw_chrome(draw, width, fonts["title"])
    draw.rectangle((0, bar_h, width, height), fill=COLORS["bg"])

    for kind, text, y in rows:
        color = KIND_COLOR.get(kind, COLORS["text"])
        font = fonts["label"] if kind == "label" else fonts["body"]
        draw.text((28, y), text, fill=color, font=font)

    if cursor is not None:
        kind, x, y = cursor
        color = KIND_COLOR.get(kind, COLORS["text"])
        font = fonts["body"]
        ch_w = max(8, int(draw.textlength("M", font=font)))
        ch_h = 16
        draw.rectangle((x, y + 2, x + max(2, ch_w // 3), y + ch_h), fill=color)

    return img


def _iter_animation(
    events: list[dict],
    *,
    width: int,
    height: int,
    fps: int,
    fonts: dict[str, ImageFont.ImageFont],
):
    probe = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(probe)
    bar_h = 42
    revealed: list[dict] = []
    hold_tail = int(fps * 0.9)

    for event in events:
        kind = event["kind"]
        if kind == "gap":
            revealed.append(event)
            rows = _layout_lines(
                revealed, width=width, body_top=bar_h, font=fonts["body"], label_font=fonts["label"], draw=draw
            )
            frame = render_frame(rows, width=width, height=height, fonts=fonts)
            for _ in range(max(1, fps // 8)):
                yield frame
            continue

        text = event.get("text", "")
        typing = bool(event.get("type")) and text
        if typing:
            # Type in chunks for snappier clips (~8–12s target).
            step = 3 if len(text) > 48 else 2
            for i in range(step, len(text) + 1, step):
                partial = dict(event, text=text[: min(i, len(text))])
                rows = _layout_lines(
                    revealed + [partial],
                    width=width,
                    body_top=bar_h,
                    font=fonts["body"],
                    label_font=fonts["label"],
                    draw=draw,
                )
                last_kind, last_text, last_y = rows[-1]
                cursor_x = 28 + int(draw.textlength(last_text, font=fonts["body"]))
                frame = render_frame(
                    rows,
                    width=width,
                    height=height,
                    fonts=fonts,
                    cursor=(last_kind, cursor_x + 2, last_y),
                )
                yield frame
            if len(text) % step != 0:
                partial = dict(event, text=text)
                rows = _layout_lines(
                    revealed + [partial],
                    width=width,
                    body_top=bar_h,
                    font=fonts["body"],
                    label_font=fonts["label"],
                    draw=draw,
                )
                yield render_frame(rows, width=width, height=height, fonts=fonts)
            revealed.append(event)
            rows = _layout_lines(
                revealed, width=width, body_top=bar_h, font=fonts["body"], label_font=fonts["label"], draw=draw
            )
            frame = render_frame(rows, width=width, height=height, fonts=fonts)
            for _ in range(max(2, fps // 6)):
                yield frame
        else:
            for _ in range(max(1, fps // 10)):
                rows = _layout_lines(
                    revealed, width=width, body_top=bar_h, font=fonts["body"], label_font=fonts["label"], draw=draw
                )
                yield render_frame(rows, width=width, height=height, fonts=fonts)
            revealed.append(event)
            rows = _layout_lines(
                revealed, width=width, body_top=bar_h, font=fonts["body"], label_font=fonts["label"], draw=draw
            )
            frame = render_frame(rows, width=width, height=height, fonts=fonts)
            pause = fps // 5 if kind in {"meta", "dim", "accent", "label"} else fps // 7
            for _ in range(max(1, pause)):
                yield frame

    rows = _layout_lines(
        revealed, width=width, body_top=bar_h, font=fonts["body"], label_font=fonts["label"], draw=draw
    )
    final = render_frame(rows, width=width, height=height, fonts=fonts)
    for _ in range(hold_tail):
        yield final


def render_demo(name: str, events: list[dict], *, width: int, height: int, fps: int, out_dir: Path) -> None:
    import imageio.v2 as imageio

    prefer_cjk = any(_needs_cjk(e.get("text", "")) for e in events if e.get("kind") != "gap")
    body_size = 15 if width <= 800 else 17
    fonts = {
        "body": _load_font(body_size, prefer_cjk=prefer_cjk),
        "label": _load_font(13, prefer_cjk=prefer_cjk),
        "title": _load_font(12, prefer_cjk=False),
    }

    frames = list(
        _iter_animation(events, width=width, height=height, fps=fps, fonts=fonts)
    )
    if not frames:
        raise RuntimeError(f"no frames for {name}")

    # Cap duration ~12s by dropping frames if needed.
    max_frames = fps * 12
    if len(frames) > max_frames:
        step = math.ceil(len(frames) / max_frames)
        frames = frames[::step]

    out_dir.mkdir(parents=True, exist_ok=True)
    mp4_path = out_dir / f"{name}.mp4"
    poster_path = out_dir / f"{name}.poster.jpg"

    # Poster from a late frame so reduced-motion / loading still shows content.
    poster_idx = min(len(frames) - 1, max(0, int(len(frames) * 0.82)))
    frames[poster_idx].save(poster_path, quality=72, optimize=True)

    # imageio-ffmpeg writes H.264.
    writer = imageio.get_writer(
        mp4_path,
        fps=fps,
        codec="libx264",
        quality=8,
        pixelformat="yuv420p",
        macro_block_size=None,
    )
    try:
        for frame in frames:
            writer.append_data(_to_even(frame))
    finally:
        writer.close()

    size_kb = mp4_path.stat().st_size / 1024
    print(f"wrote {mp4_path.name} ({size_kb:.0f} KiB, {len(frames)} frames) + poster")


def _to_even(img: Image.Image) -> "object":
    import numpy as np

    w, h = img.size
    ew, eh = w - (w % 2), h - (h % 2)
    if (ew, eh) != (w, h):
        img = img.crop((0, 0, ew, eh))
    return np.asarray(img)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        nargs="*",
        help="Optional demo keys, e.g. setup.en memory.zh",
    )
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)

    data = json.loads(SCENES_PATH.read_text(encoding="utf-8"))
    width = int(data["width"])
    height = int(data["height"])
    fps = int(data["fps"])
    demos: dict = data["demos"]

    keys = args.only or sorted(demos.keys())
    for key in keys:
        if key not in demos:
            print(f"unknown demo: {key}", file=sys.stderr)
            return 1
        render_demo(key, demos[key], width=width, height=height, fps=fps, out_dir=args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
