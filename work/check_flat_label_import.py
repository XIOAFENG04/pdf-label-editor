"""Flat (image barcode) labels must be imported as the whole label, not just the strip.

Regression for the two supplier styles that only ship the barcode as a picture with
vector text above and below it.
"""
exec(open('work/check_textbox_persistence.py', encoding='utf8').read().split('errors=[]')[0])
import fitz
import batch_labels as bl

errors = []
m.messagebox.showinfo = lambda *a, **k: None
m.messagebox.showerror = lambda *a, **k: errors.append(a)

flat = fitz.open('work/samples/flat_label_style.pdf')
page = flat[0]
print('flat label page', [round(v, 1) for v in page.rect])
regions = bl.detect_full_label_barcodes(page)
print('detected regions', [[round(v, 1) for v in r] for r in regions])
assert len(regions) == 1, regions
region = regions[0]
# The detected area must cover the title above the barcode and the code lines below it.
assert region.height >= page.rect.height * 0.7, region
assert region.width >= page.rect.width * 0.85, region
assert region.y0 <= page.rect.height * 0.15, region
assert region.y1 >= page.rect.height * 0.85, region

payload = bl.extract_label_region(page, region)
with fitz.open(stream=payload, filetype='pdf') as label:
    text = label[0].get_text('text')
    print('extracted label size', [round(v, 1) for v in label[0].rect])
    print('extracted text head:', repr(text[:60]))
    # Barcode image and both text bands are inside the clip.
    assert label[0].get_images(full=True), 'barcode image missing from the clip'
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    assert len(lines) >= 4, lines
flat.close()

# Replacing inside the matching template keeps the label inside the target frame.
# Second style: barcode drawn as vector bars, title/codes as text (skc_469806810096).
vector = fitz.open('work/samples/vector_label_style.pdf')
vector_page = vector[0]
vector_regions = bl.detect_full_label_barcodes(vector_page)
print('vector label page', [round(v, 1) for v in vector_page.rect],
      '-> regions', [[round(v, 1) for v in r] for r in vector_regions])
assert len(vector_regions) == 1, vector_regions
vector_region = vector_regions[0]
assert vector_region.height >= vector_page.rect.height * 0.7, vector_region
assert vector_region.width >= vector_page.rect.width * 0.85, vector_region
vector_fields = bl.label_fields(vector_page)
print('vector label fields', vector_fields)
assert vector_fields['SKU'], vector_fields
vector_payload = bl.extract_label_region(vector_page, vector_region)
with fitz.open(stream=vector_payload, filetype='pdf') as label:
    assert len([line for line in label[0].get_text('text').splitlines() if line.strip()]) >= 3
vector.close()

template = fitz.open('work/samples/template_14.pdf')
targets = bl.detect_full_label_barcodes(template[0])
print('template targets', [[round(v, 1) for v in r] for r in targets])
assert len(targets) == 1, targets
result = bl.replace_label(template.tobytes(garbage=0, deflate=True), 0, targets[0], payload, fill_frame=True)
with fitz.open(stream=result, filetype='pdf') as out:
    assert len(out) == 1
    pix = out[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    pix.save('work/label-import-check.png')
    print('replaced page rendered', pix.width, 'x', pix.height)
template.close()

assert not errors, errors
print('FLAT LABEL IMPORT PASS')
