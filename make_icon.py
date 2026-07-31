# -*- coding: utf-8 -*-
"""
Иконка приложения в языке дизайн-системы: маркер-заливка, чернильный знак.

До PIXEL_LIMIT глиф рендерится сразу в целевом разрешении: шрифтовой
растеризатор сам расставляет штрихи по пиксельной сетке, и знак выходит резче,
чем если уменьшать большую картинку. Крупные размеры собираются с запасом и
уменьшаются — там важнее гладкая дужка микрофона.

ICO собирается вручную, чтобы в файл попали именно отрисованные варианты,
а не пересемплированный оригинал.
"""

import io
import os
import struct

from PIL import Image, ImageDraw, ImageFont

ICON_FONT_PATH = r"C:\Windows\Fonts\SegoeIcons.ttf"
MIC_GLYPH = "\ue720"
ACCENT = (255, 220, 46, 255)
INK = (20, 20, 15, 255)
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
SUPER = 8
PIXEL_LIMIT = 32          # до этого размера включительно — рендер в целевом размере
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "groqer.ico")


def _pixel_mic(draw, size, ink=INK):
    """Запасная отрисовка микрофона, если системный шрифт иконок недоступен.

    Дужка обязательна — без неё капсула на подставке читается как монитор.
    """
    cx = size // 2
    thin = max(1, round(size * 0.07))

    cap_w = max(3, round(size * 0.22)) | 1          # нечётная — центрируется ровно
    cap_h = max(4, round(size * 0.40))
    top = max(1, round(size * 0.14))
    draw.rectangle([cx - cap_w // 2, top,
                    cx - cap_w // 2 + cap_w - 1, top + cap_h - 1], fill=ink)

    arm = max(2, round(size * 0.21))
    arm_top = top + round(cap_h * 0.55)
    arm_bottom = top + cap_h + max(1, round(size * 0.06))
    for sign in (-1, 1):
        x = cx + sign * arm - (thin // 2 if sign > 0 else thin - thin // 2 - 1)
        draw.rectangle([x, arm_top, x + thin - 1, arm_bottom], fill=ink)
    draw.rectangle([cx - arm - thin // 2, arm_bottom - thin + 1,
                    cx + arm + thin // 2, arm_bottom], fill=ink)

    stem_h = max(1, round(size * 0.10))
    stem_w = max(1, round(size * 0.07)) | 1
    stem_y = arm_bottom + 1
    draw.rectangle([cx - stem_w // 2, stem_y,
                    cx - stem_w // 2 + stem_w - 1, stem_y + stem_h - 1], fill=ink)

    base_w = max(5, round(size * 0.34)) | 1
    base_h = max(1, round(size * 0.07))
    base_y = stem_y + stem_h
    draw.rectangle([cx - base_w // 2, base_y,
                    cx - base_w // 2 + base_w - 1, base_y + base_h - 1], fill=ink)


def render(size, fill_alpha=255, ink_alpha=255):
    """Один размер иконки — системный глиф микрофона на маркере.

    fill_alpha и ink_alpha задаются раздельно: плавающему индикатору нужна
    почти прозрачная плашка при хорошо читаемом знаке, а равномерная
    прозрачность выцвечивает микрофон вместе с фоном.
    """
    fill = ACCENT[:3] + (fill_alpha,)
    ink = INK[:3] + (ink_alpha,)

    if size <= PIXEL_LIMIT:
        # знак и плашка рисуются слоями: иначе полупрозрачные чернила
        # смешиваются с жёлтым и знак сереет
        plate = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(plate).rectangle([0, 0, size - 1, size - 1], fill=fill)
        mark = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        md = ImageDraw.Draw(mark)
        if size >= 20:                                # на 16 рамка съедает знак
            md.rectangle([0, 0, size - 1, size - 1], outline=ink, width=1)
        try:
            font = ImageFont.truetype(ICON_FONT_PATH, round(size * 0.72))
            md.text((size / 2, size / 2), MIC_GLYPH, font=font, fill=ink,
                    anchor="mm")
        except Exception:
            _pixel_mic(md, size, ink)
        plate.alpha_composite(mark)
        return plate

    big = size * SUPER
    plate = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(plate).rectangle([0, 0, big - 1, big - 1], fill=fill)
    mark = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    md = ImageDraw.Draw(mark)
    md.rectangle([0, 0, big - 1, big - 1], outline=ink,
                 width=max(1, int(big * 0.045)))
    try:
        font = ImageFont.truetype(ICON_FONT_PATH, int(big * 0.62))
        md.text((big / 2, big / 2), MIC_GLYPH, font=font, fill=ink, anchor="mm")
    except Exception:
        _pixel_mic(md, big, ink)
    plate.alpha_composite(mark)
    return plate.resize((size, size), Image.LANCZOS)


def write_ico(path, images):
    """ICO с PNG внутри каждой записи — Windows Vista и новее это понимает."""
    blobs = []
    for img in images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        blobs.append(buf.getvalue())

    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = len(header) + 16 * len(blobs)
    entries, payload = b"", b""
    for img, blob in zip(images, blobs):
        side = 0 if img.width >= 256 else img.width
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32,
                               len(blob), offset)
        payload += blob
        offset += len(blob)

    with open(path, "wb") as f:
        f.write(header + entries + payload)


if __name__ == "__main__":
    write_ico(OUT_PATH, [render(s) for s in SIZES])
    print("written:", OUT_PATH, "|", ", ".join(f"{s}px" for s in SIZES))
