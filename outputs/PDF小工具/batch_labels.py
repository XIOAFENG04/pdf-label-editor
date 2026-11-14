"""Generate separate label PDFs from one selected page and barcode PDFs."""
import math
import re
import io
import string

import fitz


def label_fields(page):
    """Read the product description and printed lower SKU from a label page."""
    words = page.get_text('words')
    numbers = [(fitz.Rect(w[:4]), w[4]) for w in words if re.fullmatch(r'\d{8,24}', w[4])]
    numbers.sort(key=lambda item: (item[0].y0, item[0].x0))
    if len(numbers) < 2 or numbers[-1][0].y0 <= numbers[0][0].y1:
        return {'名称': '', 'SKU': ''}
    top, bottom = numbers[0][0], numbers[-1][0]
    candidates = []
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', []):
            rect = fitz.Rect(line['bbox'])
            text = ''.join(span['text'] for span in line['spans']).strip()
            if (text and rect.x0 >= top.x1 and rect.y0 < top.y1
                    and rect.y1 > top.y0 and not re.fullmatch(r'[\d\s]+', text)):
                candidates.append((rect.x0, text))
    # Multiple separate lines in this position are ambiguous; never guess a filename.
    title = candidates[0][1] if len(candidates) == 1 else ''
    return {'名称': title, 'SKU': numbers[-1][1]}


def format_label_names(rule, records):
    """Validate a user naming template before producing safe, unique filenames."""
    allowed = {'名称', 'SKU', '原文件名', '页码'}
    try:
        parts = list(string.Formatter().parse(rule.strip()))
    except ValueError as exc:
        raise ValueError('命名规则中的花括号不完整。') from exc
    fields = []
    for _, field, spec, conversion in parts:
        if field is not None:
            if field not in allowed or spec or conversion:
                raise ValueError('命名规则只支持 {名称}、{SKU}、{原文件名}、{页码}。')
            fields.append(field)
    if not rule.strip():
        raise ValueError('请输入命名规则。')
    names = []
    for record in records:
        missing = [field for field in fields if not str(record.get(field, '')).strip()]
        if missing:
            raise ValueError(f"{record.get('来源', '条码')}：未识别到 {'、'.join(missing)}。请检查 PDF 文字，或更改命名规则。")
        names.append(rule.strip().format_map(record))
    return output_names(names)


def output_names(names):
    used = set()
    result = []
    for name in names:
        base = str(name).strip()
        if base.lower().endswith('.pdf'): base = base[:-4]
        base = base.rstrip('. ')
        base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', base)[:160].rstrip('. ')
        if not base: base = '标签'
        if re.fullmatch(r'(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])', base): base = '_'+base
        candidate = base
        i = 2
        while candidate.casefold() in used:
            candidate = f'{base} ({i})'; i += 1
        used.add(candidate.casefold())
        result.append(candidate+'.pdf')
    return result


def detect_bitmap_labels(page):
    """Conservatively locate horizontal barcode labels embedded as page images."""
    import numpy as np
    from PIL import Image
    results = []
    for info in page.get_image_info(xrefs=True):
        xref = info.get('xref',0)
        w,h = info.get('width',0),info.get('height',0)
        if not xref or not w or not h or w*h > 20_000_000 or w/h < 1.8: continue
        try:
            pix = fitz.Pixmap(page.parent,xref)
            if pix.colorspace and pix.colorspace.n > 3: pix = fitz.Pixmap(fitz.csRGB,pix)
            image = Image.open(io.BytesIO(pix.tobytes('png'))).convert('RGB')
            if image.width > 1200:
                image = image.resize((1200,max(1,round(image.height*1200/image.width))),Image.Resampling.LANCZOS)
            grey = np.asarray(image.convert('L'))
            dark = grey < 96
            if dark.shape[0] < 20 or dark.shape[1] < 80: continue
            transitions = np.count_nonzero(dark[:,1:] != dark[:,:-1],axis=1)
            best = run = 0
            for y in range(1,dark.shape[0]):
                if transitions[y] >= 30 and np.count_nonzero(dark[y] != dark[y-1]) <= max(3,dark.shape[1]*.01):
                    run += 1; best = max(best,run)
                else: run = 0
            if best < max(8,round(dark.shape[0]*.08)): continue
            ys,xs = np.where(grey < 245)
            if not len(xs): continue
            matrix = fitz.Matrix(info['transform'])
            iw,ih = image.size
            points = [fitz.Point(x/iw,y/ih)*matrix for x,y in
                      ((xs.min(),ys.min()),(xs.max()+1,ys.min()),(xs.max()+1,ys.max()+1),(xs.min(),ys.max()+1))]
            rect = fitz.Rect(min(p.x for p in points),min(p.y for p in points),max(p.x for p in points),max(p.y for p in points))
            rect = (rect+(-.5,-.5,.5,.5)) & page.rect
            if not rect.is_empty: results.append(rect)
        except (ValueError,RuntimeError,MemoryError):
            continue
    return results


def detect_full_label_barcodes(page):
    """Find full framed product barcodes; return all candidates for ambiguity checks."""
    if page.rotation:
        raise ValueError('旧标签页面带有旋转属性，请先调整页面方向。')
    candidates = detect_bitmap_labels(page)
    drawings = page.get_drawings()
    bars = []
    for item in drawings:
        rect = fitz.Rect(item['rect'])
        fill = item.get('fill')
        if (fill is not None and max(fill[:3]) < .35 and rect.height >= 4
                and 0 < rect.width <= rect.height*.35):
            bars.append(rect)
    for item in drawings:
        rect = fitz.Rect(item['rect'])
        stroke = item.get('color')
        if not stroke or max(stroke[:3]) > .35 or rect.is_empty or rect.width < rect.height*1.8:
            continue
        if rect.width < page.rect.width*.12 or rect.height < 8:
            continue
        contained = [bar for bar in bars if (rect + (-1,-1,1,1)).contains(bar)]
        if len(contained) < 12:
            continue
        group = fitz.Rect(contained[0])
        for bar in contained[1:]: group |= bar
        if group.width < rect.width*.3 or group.height > rect.height*.9:
            continue
        candidates.append((rect + (-.75,-.75,.75,.75)) & page.rect)
    # Nested borders or the white background surrounding the same barcode
    # identify one area; distinct areas remain separate and require review.
    unique = []
    for rect in sorted(candidates, key=lambda r:r.width*r.height):
        if any((rect & existing).get_area() >= .8*min(rect.get_area(), existing.get_area()) for existing in unique):
            continue
        unique.append(rect)
    return unique


def extract_label_region(page, rect):
    """Copy just the detected label into a one-page vector-preserving PDF."""
    rect = fitz.Rect(rect) & page.rect
    if rect.is_empty or not page.rect.contains(rect):
        raise ValueError('旧标签条码区域无效。')
    with fitz.open() as out:
        target = out.new_page(width=rect.width, height=rect.height)
        target.show_pdf_page(target.rect, page.parent, page.number, clip=rect)
        return out.tobytes(garbage=4, deflate=True)


def inspect_multipage_barcodes(doc):
    """Identify obvious product barcode pages and their printed lower number."""
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text('text')
        words = page.get_text('words')
        numbers = [(fitz.Rect(w[:4]),w[4]) for w in words if re.fullmatch(r'\d{8,24}',w[4])]
        numbers.sort(key=lambda pair:(pair[0].y1,pair[0].x0))
        bars = 0
        for drawing in page.get_drawings():
            r = drawing['rect']
            if drawing.get('fill') is not None and r.height >= 4 and 0 < r.width <= r.height*.35:
                bars += 1
        is_label = len(numbers) >= 2 and bars >= 12 and numbers[-1][0].y0 > numbers[0][0].y0
        if not is_label:
            # Many labels carry the barcode as an image, not vector bars; detect
            # those too so the page can be preselectable.
            try:
                if detect_bitmap_labels(page): is_label = True
            except Exception:
                pass
        fields = label_fields(page)
        code = fields['SKU']
        title = fields['名称']
        pages.append({'page':i,'number':code,'title':title,'product':is_label})
    return pages


def visible_label_bounds(page):
    """Measure non-white content for placement; PDF content itself remains vector."""
    import numpy as np
    rect = page.rect
    factor = min(3.0, math.sqrt(12_000_000/max(rect.width*rect.height,1)))
    pix = page.get_pixmap(matrix=fitz.Matrix(factor,factor),colorspace=fitz.csGRAY,alpha=False,annots=False)
    grey = np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.stride)[:,:pix.width]
    ink = grey < 250
    xs = np.flatnonzero(ink.any(axis=0))
    ys = np.flatnonzero(ink.any(axis=1))
    if not len(xs): raise ValueError('导入的标签页面没有检测到可见内容。')
    pad = .5
    clip = fitz.Rect(rect.x0+xs.min()/factor-pad,rect.y0+ys.min()/factor-pad,
                     rect.x0+(xs.max()+1)/factor+pad,rect.y0+(ys.max()+1)/factor+pad) & rect
    if clip.is_empty: raise ValueError('无法确定导入标签的有效范围。')
    return clip


def replace_label(template_bytes, page_index, target, replacement_bytes, fill_frame=False):
    target = fitz.Rect(target)
    with fitz.open(stream=template_bytes, filetype='pdf') as source, \
         fitz.open(stream=replacement_bytes, filetype='pdf') as replacement:
        if source.needs_pass or replacement.needs_pass: raise ValueError('暂不支持加密 PDF。')
        if not (0 <= page_index < len(source)) or not len(replacement): raise ValueError('PDF 没有可用页面。')
        if source[page_index].rotation or replacement[0].rotation:
            raise ValueError('带页面旋转属性的 PDF 暂不支持批量替换，请先调整页面方向。')
        page_rect = source[page_index].rect
        if target.is_empty or target.is_infinite or not all(math.isfinite(v) for v in target):
            raise ValueError('替换区域无效。')
        if not page_rect.contains(target): raise ValueError('替换区域必须完整位于页面内。')
        # Refuse a box cutting through text outside it: redaction would delete whole glyphs.
        for word in source[page_index].get_text('words'):
            box = fitz.Rect(word[:4])
            if target.intersects(box) and not (target + (-.5,-.5,.5,.5)).contains(box):
                raise ValueError('选区切到了旁边的文字，请重新框选完整标签。')
        with fitz.open() as output:
            output.insert_pdf(source,from_page=page_index,to_page=page_index)
            page = output[0]
            if any(a.type[0] == fitz.PDF_ANNOT_REDACT for a in (page.annots() or [])):
                raise ValueError('原页存在未应用的涂黑标记，请先处理。')
            page.add_redact_annot(target,fill=(1,1,1),cross_out=False)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS,
                graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                text=fitz.PDF_REDACT_TEXT_REMOVE)
            clip = visible_label_bounds(replacement[0]) if fill_frame else None
            page.show_pdf_page(target,replacement,0,clip=clip,keep_proportion=not fill_frame,overlay=True)
            return output.tobytes(garbage=4,deflate=True)
