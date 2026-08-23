"""The closing card, and the record that somebody actually wrote it.

Why this module exists, measured on 2026-08-23. Three drivers were given the
same footage. One of them produced an `endcard.png` that was a STILL GRABBED
FROM ITS OWN LAST CLIP — no title, no event name, nothing the footage did not
already say — and `gate_structure` passed it, because that gate asks two
questions and both were satisfied tautologically:

    endcard.png exists                          ✓  (a screenshot is a file)
    the last frame matches endcard.png          ✓  (0.99 — it IS that frame)

Screenshot your own ending, save it under the required name, and the check that
exists to make sure a video HAS an ending agrees that it does. The viewer's
verdict on that edit was "不知所云 … 完全沒有任何文字", which is exactly what the
gate was meant to prevent and could not see.

Pixels cannot settle it. The obvious discriminator — "a real card is a still,
so the tail should be frozen" — was measured across all three and does not
separate them: the card with authored text was held 0.1s and the screenshot 0.0s,
while the one held longest (4.9s) carried a caption that contradicted its own
photo. Freeze duration is a pacing choice, not evidence of authorship.

So authorship is DECLARED, the way every other node contract in this skill is:
`build()` writes `endcard_meta.json` next to the png, recording the text drawn
on it, and `gate_structure` fails when that declaration is missing or empty. A
build that draws its own card writes the same file — one line, the same deal as
`layout.json`. What it cannot do any more is claim an ending it never authored.

    from endcard import build
    build("group_photo.jpg", "全身濕透", "還是拍了一張", "WORK/endcard.png")
"""
import json
import os

from PIL import Image, ImageDraw, ImageOps

from cover import W, H, _font, _house_gold

TITLE_PT = 104
SUB_PT = 58
TITLE_Y_RATIO = 0.735      # low enough to clear faces in a group shot
SHADE_FROM = 0.58          # the gradient starts here and reaches full at the foot


def _fit(im):
    """Cover the 9:16 frame from the middle. EXIF first — a phone photo that has
    never been through a rotation-aware reader arrives on its side, and ffmpeg's
    mjpeg path is one of the readers that ignores the tag."""
    im = ImageOps.exif_transpose(im).convert("RGB")
    tw = int(im.height * W / H)
    if tw < im.width:
        x = (im.width - tw) // 2
        im = im.crop((x, 0, x + tw, im.height))
    else:
        th = int(im.width * H / W)
        y = (im.height - th) // 2
        im = im.crop((0, y, im.width, y + th))
    return im.resize((W, H), Image.LANCZOS)


def _shade(im):
    """Darken the lower third so type has something to sit on — a nudge, not a
    slab, because the photo is usually the point of the card."""
    grad = Image.new("L", (1, H))
    for y in range(H):
        f = max(0.0, (y - H * SHADE_FROM) / (H * (1 - SHADE_FROM)))
        grad.putpixel((0, y), int(200 * f ** 1.5))
    return Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), im,
                           grad.resize((W, H)))


def draw(im, title, subtitle):
    d = ImageDraw.Draw(im)
    gold = _house_gold()
    y = int(H * TITLE_Y_RATIO)
    drawn = []
    for text, font, fill in ((title, _font(TITLE_PT), (255, 255, 255)),
                             (subtitle, _font(SUB_PT), gold)):
        if not str(text or "").strip():
            continue
        bb = d.textbbox((0, 0), text, font=font)
        x = (W - (bb[2] - bb[0])) // 2 - bb[0]
        for ox, oy in ((4, 5), (-3, 4)):
            d.text((x + ox, y + oy - bb[1]), text, font=font, fill=(0, 0, 0))
        d.text((x, y - bb[1]), text, font=font, fill=fill)
        drawn.append(text)
        y += (bb[3] - bb[1]) + 44
    if not drawn:
        # The whole point. A card with nothing on it is the defect this module
        # was written for, and it fails here rather than three steps later at
        # the gate, where the message can only say the file is wrong.
        raise ValueError(
            "an end card with no text is not an end card — it is a frame of the "
            "footage. Give it at least a title: the closing card is where the "
            "viewer learns what the thing was called.")
    return im, drawn


def build(src_image, title, subtitle, out_path):
    """Render the card and DECLARE what is on it. Returns (path, lines)."""
    im, drawn = draw(_shade(_fit(Image.open(src_image))), title, subtitle)
    im.save(out_path)
    json.dump({"text": drawn, "source": os.path.basename(str(src_image)),
               "title_pt": TITLE_PT, "subtitle_pt": SUB_PT},
              open(os.path.join(os.path.dirname(os.path.abspath(out_path)),
                                "endcard_meta.json"), "w"),
              ensure_ascii=False, indent=1)
    return out_path, drawn
