"""Per-clip thumbnails in the Leonida Nights v4 style.

Template (from the reference 01-speed-gta6-60s-thumb-v4.jpg): a neon sunset
background (procedural gradient sky, sun, skyline), the circular Leonida
Nights logo centred on top, a laptop mockup in the middle showing a frame
grabbed from the clip itself, and a bottom strip with two lines of big bold
white text with a pink outline.

Three sizes: 9:16 (1080x1920, Shorts), 16:9 (1920x1080, standard YouTube),
1:1 (1080x1080, square). Same style in each, layout adapted per ratio.

Local only: PIL compositing + ffmpeg frame grabs. Pillow is in
requirements.txt; everything else was already required. No API key, no web.
"""
import json
import math
import random
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
DEFAULT_LOGO = HERE / "assets" / "leonida-logo-circle.png"

SIZES = {
    "9x16": (1080, 1920),
    "16x9": (1920, 1080),
    "1x1": (1080, 1080),
}

# Sunset palette: deep purple top, magenta middle, orange horizon.
GRADIENT_STOPS = [
    (0.00, (16, 6, 42)),
    (0.35, (74, 16, 92)),
    (0.60, (164, 19, 107)),
    (0.78, (255, 90, 60)),
    (1.00, (255, 170, 80)),
]
SUN_COLOR = (255, 196, 90)
SUN_GLOW = (255, 120, 60)
SKYLINE_COLOR = (13, 6, 24)
WINDOW_COLORS = [(255, 214, 130), (255, 120, 170), (140, 220, 255)]
NEON_PINK = (255, 46, 136)
TEXT_WHITE = (255, 255, 255)
STRIP_FILL = (12, 6, 26)
STRIP_ALPHA = 225

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _load_font(size):
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if not path.is_file():
            continue
        try:
            return ImageFont.truetype(str(path), int(size))
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


def _gradient(size):
    """Vertical sunset gradient from GRADIENT_STOPS (numpy is a dependency)."""
    import numpy as np

    width, height = size
    stops = sorted(GRADIENT_STOPS)
    positions = np.array([p for p, _ in stops], dtype=float)
    colors = np.array([c for _, c in stops], dtype=float)
    rows = np.linspace(0.0, 1.0, height)
    channels = [np.interp(rows, positions, colors[:, i]) for i in range(3)]
    band = np.stack(channels, axis=1).astype("uint8")
    array = np.repeat(band[:, None, :], width, axis=1)
    return Image.fromarray(array, "RGB").convert("RGBA")


def _sunset_background(size, seed=7, sun_r=None, sun_cy=None):
    """Procedural neon-sunset scene: sky, glowing sun, skyline, stars."""
    width, height = size
    rng = random.Random(seed)
    base = _gradient(size)
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    if sun_r is None:
        sun_r = int(min(width * 0.46, height * 0.42))
    if sun_cy is None:
        sun_cy = int(height * 0.40)
    sun_cx = width // 2
    glow_draw.ellipse([sun_cx - sun_r * 2, sun_cy - sun_r * 2,
                       sun_cx + sun_r * 2, sun_cy + sun_r * 2],
                      fill=SUN_GLOW + (90,))
    glow = glow.filter(ImageFilter.GaussianBlur(int(sun_r * 0.55)))
    base.alpha_composite(glow)
    draw = ImageDraw.Draw(base)
    draw.ellipse([sun_cx - sun_r, sun_cy - sun_r,
                  sun_cx + sun_r, sun_cy + sun_r], fill=SUN_COLOR + (255,))
    # Thin darker slats across the lower sun, synthwave style.
    for i, frac in enumerate((0.55, 0.68, 0.80, 0.90)):
        y = sun_cy + int(sun_r * frac)
        thick = 2 + i * 2
        draw.rectangle([sun_cx - sun_r, y, sun_cx + sun_r, y + thick],
                       fill=(164, 19, 107, 255))
    # Stars in the upper sky.
    for _ in range(int(width * height / 9000)):
        x = rng.randint(0, width - 1)
        y = rng.randint(0, int(height * 0.30))
        r = rng.choice((1, 1, 2))
        alpha = rng.randint(90, 220)
        draw.ellipse([x - r, y - r, x + r, y + r],
                     fill=(255, 255, 255, alpha))
    # Skyline silhouette along the lower third, with lit windows.
    horizon = int(height * 0.66)
    x = -20
    while x < width + 20:
        bw = rng.randint(int(width * 0.05), int(width * 0.13))
        bh = rng.randint(int(height * 0.06), int(height * 0.24))
        top = horizon - bh
        draw.rectangle([x, top, x + bw, horizon + 2], fill=SKYLINE_COLOR + (255,))
        for _ in range(bh * bw // 2600):
            wx = rng.randint(x + 4, max(x + 5, x + bw - 8))
            wy = rng.randint(top + 6, max(top + 7, horizon - 10))
            draw.rectangle([wx, wy, wx + 3, wy + 5],
                           fill=rng.choice(WINDOW_COLORS) + (255,))
        x += bw + rng.randint(2, 14)
    draw.rectangle([0, horizon, width, height], fill=(8, 4, 18, 255))
    return base


def _circular_image(path, diameter):
    """Open an image, centre-crop to square, resize, and mask to a circle."""
    image = Image.open(path).convert("RGBA")
    side = min(image.size)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    image = image.crop((left, top, left + side, top + side))
    image = image.resize((diameter, diameter), Image.LANCZOS)
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, diameter, diameter], fill=255)
    out = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    out.paste(image, (0, 0), mask)
    return out


def _neon_text(draw, center, text, font, fill=TEXT_WHITE,
               stroke=NEON_PINK, stroke_width=6):
    """White text with a pink outline, centred on ``center``."""
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    x = center[0] - width / 2 - bbox[0]
    y = center[1] - height / 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=fill + (255,),
              stroke_width=stroke_width, stroke_fill=stroke + (255,))


def _fit_font(draw, lines, max_width, start_size):
    """Largest bold font size at which every line fits ``max_width``."""
    size = int(start_size)
    while size > 24:
        font = _load_font(size)
        if all(draw.textlength(line, font=font) + 24 <= max_width
               for line in lines):
            return font, size
        size = int(size * 0.92)
    return _load_font(size), size


def _draw_laptop(base, frame, x, y, width):
    """Laptop mockup: dark bezel + screen + base, frame shown on the screen."""
    draw = ImageDraw.Draw(base)
    screen_h = int(width * 9 / 16)
    bezel = 14
    total_h = screen_h + bezel * 2
    # Screen bezel.
    draw.rounded_rectangle([x, y, x + width, y + total_h], radius=18,
                           fill=(10, 10, 14, 255), outline=(70, 70, 90, 255),
                           width=2)
    # Camera dot.
    draw.ellipse([x + width // 2 - 4, y + 5, x + width // 2 + 4, y + 13],
                 fill=(60, 60, 80, 255))
    # Frame, centre-cropped to 16:9.
    fw, fh = frame.size
    target_ratio = 16 / 9
    if fw / fh > target_ratio:
        new_w = int(fh * target_ratio)
        left = (fw - new_w) // 2
        frame = frame.crop((left, 0, left + new_w, fh))
    else:
        new_h = int(fw / target_ratio)
        top = (fh - new_h) // 2
        frame = frame.crop((0, top, fw, top + new_h))
    screen = frame.resize((width - bezel * 2, screen_h), Image.LANCZOS)
    base.paste(screen.convert("RGBA"), (x + bezel, y + bezel))
    # Base: a shallow trapezoid under the screen.
    base_y = y + total_h
    base_h = max(18, int(width * 0.028))
    draw.polygon([(x - int(width * 0.03), base_y + base_h),
                  (x + int(width * 0.03), base_y),
                  (x + width - int(width * 0.03), base_y),
                  (x + width + int(width * 0.03), base_y + base_h)],
                 fill=(16, 16, 22, 255))
    draw.polygon([(x + width // 2 - int(width * 0.09), base_y),
                  (x + width // 2 + int(width * 0.09), base_y),
                  (x + width // 2 + int(width * 0.07), base_y + base_h - 2),
                  (x + width // 2 - int(width * 0.07), base_y + base_h - 2)],
                 fill=(40, 40, 55, 255))
    return base_y + base_h


def _draw_text_strip(base, box, line1, line2):
    """Bottom strip: dark rounded panel, pink border, two stacked neon lines."""
    draw = ImageDraw.Draw(base)
    x0, y0, x1, y1 = box
    draw.rounded_rectangle([x0, y0, x1, y1], radius=28,
                           fill=STRIP_FILL + (STRIP_ALPHA,),
                           outline=NEON_PINK + (255,), width=4)
    lines = [line for line in (line1, line2) if line]
    if not lines:
        return
    inner_w = (x1 - x0) - 60
    start_size = int((y1 - y0) / (2.6 if len(lines) > 1 else 1.6))
    font, _ = _fit_font(draw, lines, inner_w, start_size)
    # Pink glow behind the text.
    glow_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    line_h = int(font.size * 1.12)
    total_h = line_h * len(lines)
    cy = (y0 + y1) / 2
    for i, line in enumerate(lines):
        center = ((x0 + x1) / 2, cy - total_h / 2 + line_h * (i + 0.5))
        _neon_text(glow_draw, center, line, font, fill=NEON_PINK,
                   stroke=NEON_PINK, stroke_width=10)
    base.alpha_composite(glow_layer.filter(ImageFilter.GaussianBlur(10)))
    draw = ImageDraw.Draw(base)
    for i, line in enumerate(lines):
        center = ((x0 + x1) / 2, cy - total_h / 2 + line_h * (i + 0.5))
        _neon_text(draw, center, line, font)


def _draw_name_text(base, center, name, diameter):
    """Custom channel name in place of the logo: big pink neon lettering."""
    draw = ImageDraw.Draw(base)
    font, _ = _fit_font(draw, [name], diameter * 2.2, int(diameter * 0.32))
    glow_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    _neon_text(ImageDraw.Draw(glow_layer), center, name, font,
               fill=NEON_PINK, stroke=NEON_PINK, stroke_width=10)
    base.alpha_composite(glow_layer.filter(ImageFilter.GaussianBlur(8)))
    _neon_text(ImageDraw.Draw(base), center, name, font, fill=TEXT_WHITE,
               stroke=NEON_PINK, stroke_width=5)


def _grab_frame(clip_path, at=None):
    """Grab one representative frame (middle of the clip by default)."""
    clip_path = Path(clip_path)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(clip_path)],
        capture_output=True, text=True, check=True)
    duration = float(probe.stdout.strip())
    moment = duration / 2 if at is None else min(max(float(at), 0), duration)
    out = clip_path.with_suffix(".thumb-frame.jpg")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{moment:.2f}",
         "-i", str(clip_path), "-frames:v", "1", "-q:v", "2", str(out)],
        check=True)
    try:
        return Image.open(out).convert("RGB")
    finally:
        try:
            out.unlink()
        except OSError:
            pass


def _split_lines(text, words_per_line=3):
    """Split a hook/title into two balanced uppercase lines."""
    words = str(text or "").strip().upper().split()
    if not words:
        return "", ""
    if len(words) <= words_per_line:
        return " ".join(words), ""
    half = math.ceil(len(words) / 2)
    return " ".join(words[:half]), " ".join(words[half:])


def default_lines(clip_path):
    """Default thumbnail lines from the clip's .meta.json hook, else filename."""
    clip_path = Path(clip_path)
    meta_path = clip_path.with_suffix(".meta.json")
    text = ""
    try:
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            text = str(meta.get("hook") or meta.get("title") or "")
    except (OSError, ValueError):
        text = ""
    if not text:
        text = clip_path.stem.replace("-", " ").replace("_", " ")
    return _split_lines(text)


def make_thumbnail(clip_path, out_path, size="9x16", line1=None, line2=None,
                   logo_path=None, name_text=None, frame_time=None):
    """Build one thumbnail; returns the output path."""
    if size not in SIZES:
        raise ValueError(f"Unknown thumbnail size: {size}. "
                         f"Choose from {', '.join(SIZES)}.")
    width, height = SIZES[size]
    if line1 is None and line2 is None:
        line1, line2 = default_lines(clip_path)
    line1 = (line1 or "").strip().upper()
    line2 = (line2 or "").strip().upper()
    if size == "16x9":
        # Landscape keeps the sun smaller so it reads as a sun, not a wall.
        base = _sunset_background((width, height),
                                  sun_r=int(height * 0.30),
                                  sun_cy=int(height * 0.38))
    elif size == "1x1":
        base = _sunset_background((width, height),
                                  sun_r=int(height * 0.30),
                                  sun_cy=int(height * 0.34))
    else:
        base = _sunset_background((width, height))
    frame = _grab_frame(clip_path, at=frame_time)

    if size == "16x9":
        # Landscape: small logo top-centre, laptop left, text panel right.
        logo_d = int(height * 0.22)
        top_y = int(height * 0.03)
        if name_text:
            _draw_name_text(base, (width // 2, top_y + logo_d // 2),
                            name_text, logo_d)
        else:
            logo = _circular_image(logo_path or DEFAULT_LOGO, logo_d)
            base.alpha_composite(logo, ((width - logo_d) // 2, top_y))
        content_y = top_y + logo_d + int(height * 0.04)
        laptop_w = int(width * 0.55)
        laptop_h = int(laptop_w * 9 / 16) + 28 + max(18, int(laptop_w * 0.028))
        laptop_y = content_y + max(0, (height - content_y - int(height * 0.03) - laptop_h) // 2)
        _draw_laptop(base, frame, int(width * 0.035), laptop_y, laptop_w)
        # Text panel about half the laptop height, centred on it, so the
        # two lines fill it instead of floating in a tall empty box.
        panel_h = laptop_h // 2
        panel_y = laptop_y + (laptop_h - panel_h) // 2
        strip = (int(width * 0.62), panel_y,
                 int(width * 0.965), panel_y + panel_h)
        _draw_text_strip(base, strip, line1, line2)
    else:
        # Vertical + square: stacked — logo top, laptop middle, strip bottom.
        logo_d = int(width * (0.52 if size == "9x16" else 0.30))
        top_y = int(height * (0.03 if size == "9x16" else 0.02))
        if name_text:
            _draw_name_text(base, (width // 2, top_y + logo_d // 2),
                            name_text, logo_d)
        else:
            logo = _circular_image(logo_path or DEFAULT_LOGO, logo_d)
            base.alpha_composite(logo, ((width - logo_d) // 2, top_y))
        laptop_w = int(width * (0.87 if size == "9x16" else 0.80))
        laptop_x = (width - laptop_w) // 2
        if size == "9x16":
            laptop_y = int(height * 0.36)
            strip = (int(width * 0.04), int(height * 0.72),
                     int(width * 0.96), int(height * 0.94))
        else:
            laptop_y = int(height * 0.36)
            strip = (int(width * 0.05), int(height * 0.68),
                     int(width * 0.95), int(height * 0.96))
        _draw_laptop(base, frame, laptop_x, laptop_y, laptop_w)
        _draw_text_strip(base, strip, line1, line2)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(out_path, "JPEG", quality=90)
    return out_path


def make_thumbnails(clip_path, line1=None, line2=None, sizes=("9x16",),
                    logo_path=None, name_text=None, frame_time=None,
                    out_dir=None):
    """Build thumbnails in each requested size; returns [paths]."""
    clip_path = Path(clip_path)
    if not clip_path.is_file():
        raise ValueError(f"Clip not found: {clip_path}")
    if logo_path:
        logo = Path(str(logo_path)).expanduser()
        if not logo.is_file():
            raise ValueError(f"Logo image not found: {logo}")
        logo_path = logo
    out_dir = Path(out_dir) if out_dir else clip_path.parent
    made = []
    for size in sizes:
        out = out_dir / f"{clip_path.stem}-thumb-{size}.jpg"
        made.append(make_thumbnail(
            clip_path, out, size=size, line1=line1, line2=line2,
            logo_path=logo_path, name_text=name_text, frame_time=frame_time))
    return made


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Make Leonida Nights v4-style thumbnails for a clip.")
    parser.add_argument("clip", help="rendered clip file (MP4)")
    parser.add_argument("--line1", default=None, help="top text line")
    parser.add_argument("--line2", default=None, help="bottom text line")
    parser.add_argument("--sizes", default="9x16",
                        help="comma-separated sizes: 9x16,16x9,1x1")
    parser.add_argument("--logo", default=None,
                        help="your own logo image (default: Leonida logo)")
    parser.add_argument("--name", default=None,
                        help="your own name text instead of a logo")
    parser.add_argument("--frame-time", type=float, default=None,
                        help="seconds into the clip to grab the frame from")
    parser.add_argument("--out-dir", default=None,
                        help="output folder (default: next to the clip)")
    args = parser.parse_args()
    sizes = [s.strip() for s in args.sizes.split(",") if s.strip()]
    made = make_thumbnails(
        args.clip, line1=args.line1, line2=args.line2, sizes=sizes,
        logo_path=args.logo, name_text=args.name,
        frame_time=args.frame_time, out_dir=args.out_dir)
    for path in made:
        image = Image.open(path)
        print(f"{path}  {image.size[0]}x{image.size[1]}")


if __name__ == "__main__":
    main()
