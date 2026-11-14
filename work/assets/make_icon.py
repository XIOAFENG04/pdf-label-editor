"""Draw the application icon and the PDF document icon.

Both are generated so the build is reproducible. The design follows the Adobe
PDF convention (white page + folded corner + red PDF wordmark) with a barcode
strip that ties it to label editing:

  app.ico      rounded red square, page, PDF wordmark, barcode  -> EXE + windows
  pdf_doc.ico  the page alone on transparency                   -> .pdf documents

Run: python work\\assets\\make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SLICED = [16, 24, 32, 48, 64, 128, 256]
SIZE = 1024
RED = (216, 35, 42)
RED_DARK = (150, 18, 24)
PAGE = (255, 255, 255)
FOLD = (226, 231, 238)
INK = (27, 32, 40)
BORDER = (203, 210, 220)


def font(size):
    for name in ('arialbd.ttf', 'segoeuib.ttf', 'arial.ttf'):
        path = Path('C:/Windows/Fonts') / name
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def ui_font(size):
    path = Path('C:/Windows/Fonts/msyhbd.ttc')
    if path.is_file():
        return ImageFont.truetype(str(path), size)
    return font(size)


def page_shape(draw, box, radius, fill, outline=None, width=0):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_page(image, box, fold, radius, outline=None):
    """White page with a folded top-right corner, drawn at 4x for clean edges."""
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = box
    page_shape(draw, box, radius, PAGE, outline, 6 if outline else 0)
    # Fold: cut the corner and paint the turned-back triangle.
    fold_poly = [(x1 - fold, y0), (x1, y0 + fold), (x1, y0), (x1 - fold, y0)]
    draw.polygon([(x1 - fold, y0 + 2), (x1 - 2, y0 + fold), (x1 - fold, y0 + fold)], fill=FOLD)
    draw.polygon([(x1 - fold, y0), (x1, y0 + fold), (x1 - fold, y0 + fold)], fill=FOLD)
    draw.line([(x1 - fold, y0), (x1 - fold, y0 + fold), (x1, y0 + fold)], fill=(196, 203, 214), width=4)
    return draw


def draw_contents(draw, box, fold):
    """PDF wordmark plus a barcode strip inside the page."""
    x0, y0, x1, y1 = box
    width = x1 - x0
    f = font(round(width * 0.40))
    text = 'PDF'
    tx, ty, tw, th = draw.textbbox((0, 0), text, font=f)
    draw.text((x0 + (width - tw) / 2 - tx, y0 + width * 0.30 - ty), text, font=f, fill=RED)

    # Barcode: four groups of bars, centred above the bottom edge.
    bars = [0.030, 0.016, 0.030, 0.016, 0.046, 0.016, 0.030, 0.016, 0.030]
    total = sum(bars) * width + 0.012 * width * (len(bars) - 1)
    bx = x0 + (width - total) / 2
    by = y0 + width * 0.78
    bh = width * 0.20
    for index, part in enumerate(bars):
        w = part * width
        if index % 2 == 0:
            draw.rounded_rectangle([bx, by, bx + w, by + bh], radius=w * 0.25, fill=INK)
        bx += w + 0.012 * width


def app_icon():
    image = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for y in range(SIZE):
        ratio = y / (SIZE - 1)
        color = tuple(round(RED[i] + (RED_DARK[i] - RED[i]) * ratio) for i in range(3)) + (255,)
        draw.line([(0, y), (SIZE, y)], fill=color)
    mask = Image.new('L', (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=int(SIZE * 0.235), fill=255)
    image.putalpha(mask)
    draw = ImageDraw.Draw(image)

    box = (int(SIZE * 0.245), int(SIZE * 0.165), int(SIZE * 0.755), int(SIZE * 0.835))
    draw = draw_page(image, box, int(SIZE * 0.13), int(SIZE * 0.035))
    draw_contents(draw, box, int(SIZE * 0.13))
    return image


def document_icon():
    """Page with a red header carrying the wordmark: readable even at 16 px,
    where a white page on a white Explorer background would otherwise vanish."""
    image = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    box = (int(SIZE * 0.145), int(SIZE * 0.075), int(SIZE * 0.855), int(SIZE * 0.925))
    radius = int(SIZE * 0.045)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(box, radius=radius, fill=PAGE, outline=BORDER, width=7)
    x0, y0, x1, y1 = box
    band = int((y1 - y0) * 0.30)
    draw.rounded_rectangle([x0, y0, x1, y0 + band], radius=radius, fill=RED)
    draw.rectangle([x0, y0 + band // 2, x1, y0 + band], fill=RED)
    f = font(round(band * 0.58))
    tx, ty, tw, th = draw.textbbox((0, 0), 'PDF', font=f)
    draw.text((x0 + (x1 - x0 - tw) / 2 - tx, y0 + (band - th) / 2 - ty), 'PDF', font=f, fill=PAGE)
    # Barcode strip under the band.
    width = x1 - x0
    bars = [0.040, 0.020, 0.040, 0.020, 0.060, 0.020, 0.040, 0.020, 0.040]
    total = sum(bars) * width + 0.015 * width * (len(bars) - 1)
    bx = x0 + (width - total) / 2
    by = y0 + band + (y1 - y0 - band) * 0.30
    bh = (y1 - y0 - band) * 0.40
    for index, part in enumerate(bars):
        w = part * width
        if index % 2 == 0:
            draw.rounded_rectangle([bx, by, bx + w, by + bh], radius=w * 0.25, fill=INK)
        bx += w + 0.015 * width
    return image


def write_icon(image, path):
    image.save(path, format='ICO', sizes=[(s, s) for s in SLICED])
    print('wrote', path)


def preview(app, doc, path):
    """Contact sheet: both icons at 256 on light/dark, plus small sizes."""
    sheet = Image.new('RGB', (1120, 420), 'white')
    draw = ImageDraw.Draw(sheet)
    draw.rectangle([0, 0, 1120, 260], fill=(255, 255, 255))
    draw.rectangle([0, 260, 1120, 420], fill=(32, 36, 44))
    label = ui_font(20)
    for index, (icon, caption) in enumerate(((app, '应用图标 app.ico'), (doc, 'PDF 文档图标 pdf_doc.ico'))):
        big = icon.resize((180, 180), Image.Resampling.LANCZOS)
        x = 60 + index * 340
        sheet.paste(big, (x, 40), big)
        draw.text((x, 232), caption, font=label, fill=(40, 40, 40))
        for small_index, small_size in enumerate((48, 32, 16)):
            small = icon.resize((small_size, small_size), Image.Resampling.LANCZOS)
            sheet.paste(small, (x + 220 + small_index * 56, 120 - small_size // 2), small)
    for index, (icon, caption) in enumerate(((app, 'app.ico'), (doc, 'pdf_doc.ico'))):
        big = icon.resize((120, 120), Image.Resampling.LANCZOS)
        x = 60 + index * 340
        sheet.paste(big, (x, 290), big)
        for small_index, small_size in enumerate((48, 32, 16)):
            small = icon.resize((small_size, small_size), Image.Resampling.LANCZOS)
            sheet.paste(small, (x + 150 + small_index * 56, 330 - small_size // 2), small)
    sheet.save(path)
    print('wrote', path)


def main():
    app, doc = app_icon(), document_icon()
    write_icon(app, HERE / 'app.ico')
    write_icon(doc, HERE / 'pdf_doc.ico')
    app.resize((256, 256), Image.Resampling.LANCZOS).save(HERE / 'app.png')
    doc.resize((256, 256), Image.Resampling.LANCZOS).save(HERE / 'pdf_doc.png')
    preview(app, doc, HERE / 'icon-preview.png')
    # Keep a copy beside the sources so a source run shows the window icon too.
    target = HERE.parent.parent / 'outputs' / 'PDF小工具'
    if target.is_dir():
        app.save(target / 'app.ico', format='ICO', sizes=[(s, s) for s in SLICED])
        print('wrote', target / 'app.ico')


if __name__ == '__main__':
    main()
