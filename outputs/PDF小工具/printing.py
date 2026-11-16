import io
import math
import re
import ctypes
import queue
import threading
from types import SimpleNamespace
from collections import OrderedDict
import tkinter as tk
from tkinter import ttk, messagebox
import fitz
from PIL import Image, ImageTk, ImageWin
import win32print
import win32api
import win32gui
import win32con
import settings as app_settings


def page_range(value, total, current):
    if value == '当前页': return [current]
    if value == '全部页面': return list(range(total))
    raise ValueError('请选择打印范围。')


def parse_ranges(text, total):
    pages = []
    for section in text.replace('，', ',').split(','):
        section = section.strip()
        if not section: raise ValueError('请输入页码，例如 1,3-5。')
        ends = section.split('-')
        if len(ends) == 1 and ends[0].isdigit(): start = end = int(ends[0])
        elif len(ends) == 2 and all(x.strip().isdigit() for x in ends): start, end = map(int, ends)
        else: raise ValueError('页码格式不正确，请使用 1,3-5。')
        if start < 1 or end > total or start > end: raise ValueError(f'页码必须在 1 到 {total} 之间。')
        pages.extend(range(start-1, end))
        if len(pages) > 10000: raise ValueError('选择的页面太多。')
    return pages


def layout(page, width, height, scaling, printable=None):
    pw, ph = page.rect.width, page.rect.height
    paper_w, paper_h = width * 72 / 25.4, height * 72 / 25.4
    left, top, right, bottom = printable or (0, 0, paper_w, paper_h)
    available_w, available_h = right-left, bottom-top
    if scaling == '实际大小': factor = 1
    elif scaling == '缩小过大页面': factor = min(1, available_w / pw, available_h / ph)
    else: factor = min(available_w / pw, available_h / ph)
    return factor, left+(available_w-pw*factor)/2, top+(available_h-ph*factor)/2


def printer_metrics(dc, width, height):
    dpi_x, dpi_y = dc.GetDeviceCaps(88), dc.GetDeviceCaps(90)
    if dpi_x <= 0 or dpi_y <= 0: raise ValueError('打印机驱动没有报告有效的分辨率。')
    physical_w, physical_h = dc.GetDeviceCaps(110), dc.GetDeviceCaps(111)
    offset_x, offset_y = dc.GetDeviceCaps(112), dc.GetDeviceCaps(113)
    actual_w, actual_h = physical_w*25.4/dpi_x, physical_h*25.4/dpi_y
    if abs(actual_w-width)>1.5 or abs(actual_h-height)>1.5:
        raise ValueError(f'打印机报告纸张为 {actual_w:.1f}×{actual_h:.1f} 毫米，未接受所选尺寸。请在打印机属性中设置纸张尺寸。')
    try: usable_w, usable_h = dc.GetDeviceCaps(8), dc.GetDeviceCaps(10)
    except (KeyError, ValueError): usable_w, usable_h = 0, 0
    if usable_w <= 0 or usable_h <= 0:
        printable=(0,0,width*72/25.4,height*72/25.4)
    else:
        printable=(offset_x*72/dpi_x,offset_y*72/dpi_y,
                   (offset_x+usable_w)*72/dpi_x,(offset_y+usable_h)*72/dpi_y)
    return dpi_x, dpi_y, offset_x, offset_y, printable


def print_pages(app, printer, width, height, scaling, pages, copies, mode, oversample, density=100):
    dc = app.printer_dc(printer, width, height, mode)
    try:
        dpi_x, dpi_y, offset_x, offset_y, printable = printer_metrics(dc, width, height)
        cache = OrderedDict()
        cache_bytes = 0
        cache_limit = 96 * 1024 * 1024
        def dimensions(index):
            page = app.doc[index]
            factor, left, top = layout(page, width, height, scaling, printable)
            pixel_w = max(1, round(page.rect.width*factor*dpi_x/72))
            pixel_h = max(1, round(page.rect.height*factor*dpi_y/72))
            if pixel_w*pixel_h*oversample*oversample > 100_000_000:
                raise ValueError('页面过大，请选择更小的纸张尺寸。')
            return page, factor, left, top, pixel_w, pixel_h

        def rendered(index):
            nonlocal cache_bytes
            if index in cache:
                cache.move_to_end(index)
                return cache[index][0]
            page, factor, left, top, pixel_w, pixel_h = dimensions(index)
            render_x = pixel_w * oversample / page.rect.width
            render_y = pixel_h * oversample / page.rect.height
            pix = page.get_pixmap(matrix=fitz.Matrix(render_x, render_y), colorspace=fitz.csRGB, alpha=False)
            img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples, 'raw', 'RGB', pix.stride)
            if img.size != (pixel_w, pixel_h):
                img = img.resize((pixel_w, pixel_h), Image.Resampling.BOX)
            if density < 100:
                img = Image.blend(Image.new('RGB', img.size, 'white'), img, density / 100)
            value = (img, round(left*dpi_x/72)-offset_x, round(top*dpi_y/72)-offset_y, pixel_w, pixel_h)
            size = pixel_w*pixel_h*3
            if size <= cache_limit:
                while cache and cache_bytes+size > cache_limit:
                    _, (_, discarded) = cache.popitem(last=False); cache_bytes -= discarded
                cache[index] = (value, size); cache_bytes += size
            return value

        # Prepare small jobs completely before sending; for large ones prepare the
        # first page and keep a bounded cache. Never automatically retry a print job.
        unique = list(dict.fromkeys(pages))
        estimate = 0
        for index in unique:
            _, _, _, _, w, h = dimensions(index)
            estimate += w*h*3
            if estimate > cache_limit: break
        if estimate <= cache_limit:
            for index in unique: rendered(index)
        elif unique:
            rendered(unique[0])
        dc.StartDoc('PDF 标签打印')
        try:
            for index in pages * copies:
                img, x, y, pixel_w, pixel_h = rendered(index)
                dc.StartPage()
                ImageWin.Dib(img).draw(dc.GetHandleOutput(), (x, y, x+pixel_w, y+pixel_h))
                dc.EndPage()
            dc.EndDoc()
        except Exception:
            dc.AbortDoc()
            raise
    finally:
        dc.DeleteDC()


def list_printers():
    printers = [p[2] for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]
    try: default = win32print.GetDefaultPrinter()
    except Exception: default = printers[0] if printers else None
    return printers, default


def show_print_dialog(app, printer_dc, printer_mode, printer_list=None):
    printers, default = printer_list if printer_list is not None else list_printers()
    if not printers:
        messagebox.showerror('打印', '没有找到打印机，请先在 Windows 中添加。')
        return
    dialog = tk.Toplevel(app.root)
    dialog.withdraw()
    dialog.title('打印设置')
    dialog.transient(app.root)
    frame = ttk.Frame(dialog, padding=12)
    frame.pack(fill='both', expand=True)
    saved = app.prefs.get('print_defaults', {})
    if not isinstance(saved, dict): saved = {}
    remembered_printer = saved.get('printer')
    chosen = tk.StringVar(value=remembered_printer if remembered_printer in printers else default if default in printers else printers[0])
    page_rect = app.doc[app.page_index].rect
    page_w, page_h = page_rect.width*25.4/72, page_rect.height*25.4/72
    initial_w = page_w if 10 <= page_w <= 500 else 70
    initial_h = page_h if 10 <= page_h <= 500 else 70
    try:
        sw, sh = float(saved.get('width')), float(saved.get('height'))
        if all(math.isfinite(v) and 10 <= v <= 500 for v in (sw,sh)): initial_w, initial_h = sw, sh
    except (TypeError, ValueError): pass
    width, height = tk.StringVar(value=f'{initial_w:.2f}'.rstrip('0').rstrip('.')), tk.StringVar(value=f'{initial_h:.2f}'.rstrip('0').rstrip('.'))
    scaling = tk.StringVar(value=saved.get('scaling') if saved.get('scaling') in ('适合纸张','实际大小','缩小过大页面') else '缩小过大页面')
    scope, custom_range = tk.StringVar(value='当前页'), tk.StringVar()
    copies = tk.StringVar(value='1')
    modes = {}
    ttk.Label(frame, text='打印机').grid(row=0, column=0, sticky='w')
    ttk.Combobox(frame, textvariable=chosen, values=printers, state='readonly', width=36).grid(row=0, column=1, sticky='ew')
    def properties():
        try:
            dialog.update_idletasks()
            parent = ctypes.windll.user32.GetParent(dialog.winfo_id()) or dialog.winfo_id()
            result = printer_mode(chosen.get(), modes.get(chosen.get()), parent)
            if result is not None:
                modes[chosen.get()] = result
                schedule_metrics()
        except Exception as exc: messagebox.showerror('打印机属性', str(exc), parent=dialog)
    ttk.Button(frame, text='打印机属性…', command=properties).grid(row=0, column=2, padx=5)
    row = ttk.Frame(frame); row.grid(row=1, column=0, columnspan=3, sticky='w', pady=6)
    ttk.Label(row, text='纸张宽').pack(side='left')
    ttk.Entry(row, textvariable=width, width=7).pack(side='left', padx=4)
    ttk.Label(row, text='高').pack(side='left')
    ttk.Entry(row, textvariable=height, width=7).pack(side='left', padx=4)
    ttk.Label(row, text='毫米').pack(side='left')
    # 常用标签纸尺寸，选一下就填好宽高，省得每次手输
    presets = ['70×70', '60×40', '50×30', '40×30', '100×100', '100×150',
               '80×100', '60×80', 'A5 148×210', 'A4 210×297']
    preset_button = ttk.Combobox(row, values=presets, state='readonly', width=12)
    preset_button.pack(side='left', padx=6)
    def apply_preset(event=None):
        numbers = re.findall(r'\d+(?:\.\d+)?', preset_button.get())
        if len(numbers) >= 2:
            width.set(numbers[-2]); height.set(numbers[-1])
    preset_button.bind('<<ComboboxSelected>>', apply_preset)
    def save_defaults():
        try: w,h=dimensions()
        except ValueError as exc: messagebox.showerror('保存默认尺寸', str(exc), parent=dialog); return
        app.prefs['print_defaults']={'printer':chosen.get(),'width':w,'height':h,'scaling':scaling.get()}
        if app_settings.save(app.prefs): messagebox.showinfo('默认打印设置', f'已保存 {w:g} × {h:g} 毫米。', parent=dialog)
        else: messagebox.showerror('保存失败', '无法保存默认打印设置。', parent=dialog)
    ttk.Button(row,text='设为默认',command=save_defaults).pack(side='left',padx=4)
    row2 = ttk.Frame(frame); row2.grid(row=2, column=0, columnspan=3, sticky='w')
    ttk.Label(row2, text='页面缩放').pack(side='left')
    ttk.Combobox(row2, textvariable=scaling, values=['适合纸张', '实际大小', '缩小过大页面'], state='readonly', width=14).pack(side='left', padx=5)
    row3=ttk.Frame(frame); row3.grid(row=3, column=0, columnspan=3, sticky='w', pady=6)
    ttk.Label(row3, text='页面').pack(side='left')
    ttk.Combobox(row3, textvariable=scope, values=['当前页', '全部页面', '指定页码'], state='readonly', width=10).pack(side='left', padx=4)
    ttk.Entry(row3, textvariable=custom_range, width=12).pack(side='left')
    ttk.Label(row3, text='例如 1,3-5    份数').pack(side='left')
    ttk.Entry(row3, textvariable=copies, width=5).pack(side='left', padx=5)
    canvas = tk.Canvas(frame, width=460, height=460, bg='#777', highlightthickness=0, cursor='fleur')
    canvas.grid(row=5, column=0, columnspan=3, pady=8, sticky='nsew')
    frame.rowconfigure(5, weight=1)
    frame.columnconfigure(1, weight=1)
    info = tk.StringVar(value='正在读取纸张和打印机信息……\n请确认实际装纸尺寸与设置一致。')
    ttk.Label(frame, textvariable=info, wraplength=710, justify='left').grid(row=4,column=0,columnspan=3,sticky='w')
    status = ttk.Label(frame, text='纸张尺寸须与打印机实际装入的标签纸一致；浓度请在打印机属性中设置。')
    status.grid(row=6, column=0, columnspan=3)
    def dimensions():
        w, h = float(width.get()), float(height.get())
        if not all(math.isfinite(n) and 10 <= n <= 500 for n in (w, h)): raise ValueError('纸张宽和高必须在 10 到 500 毫米之间。')
        return w, h
    view = {'zoom': 1.0, 'settled': False, 'size': None, 'metrics':None, 'key':None, 'job':None, 'generation':0, 'ready':False}
    def preview(*args):
        try:
            w, h = dimensions(); page=app.doc[app.page_index]
            key=(chosen.get(),w,h)
            printable=view['metrics'] if view['key']==key else None
            factor,left,top=layout(page,w,h,scaling.get(),printable)
            pw_mm,ph_mm=page.rect.width*factor*25.4/72,page.rect.height*factor*25.4/72
            extra='已读取驱动可打印范围' if printable else '尚未确认驱动可打印范围'
            info.set(f'纸张 {w:g} × {h:g} 毫米；内容 {pw_mm:.1f} × {ph_mm:.1f} 毫米（缩放 {factor*100:.0f}%）。{extra}。\n请确认实际装纸尺寸一致；适合纸张可能放大内容。')
            if not view['ready']: return
            canvas_w, canvas_h = canvas.winfo_width(), canvas.winfo_height()
            if canvas_w <= 1 or canvas_h <= 1:
                canvas_w, canvas_h = 460, 460
            # Fit the sheet to whatever room the dialog currently has, so resizing
            # the window grows (or shrinks) the preview instead of leaving a fixed
            # 350 px page in the corner.
            paper_scale=min((canvas_w-28)/w,(canvas_h-28)/h)*view['zoom']
            paper_w=max(1,round(w*paper_scale)); paper_h=max(1,round(h*paper_scale))
            pixels_per_point=paper_scale*25.4/72
            sheet=Image.new('RGB',(paper_w,paper_h),'white')
            # Render only the part visible on the sheet. A huge PDF at actual
            # size must not allocate an enormous off-paper preview bitmap.
            printable_rect=printable or (0,0,w*72/25.4,h*72/25.4)
            visible = fitz.Rect(max(0,(printable_rect[0]-left)/factor), max(0,(printable_rect[1]-top)/factor),
                                min(page.rect.width,(printable_rect[2]-left)/factor),
                                min(page.rect.height,(printable_rect[3]-top)/factor))
            if not visible.is_empty:
                pix=page.get_pixmap(matrix=fitz.Matrix(factor*pixels_per_point, factor*pixels_per_point),clip=visible,alpha=False)
                image=Image.open(io.BytesIO(pix.tobytes('png'))).convert('RGB')
                sheet.paste(image,(round((left+visible.x0*factor)*pixels_per_point),round((top+visible.y0*factor)*pixels_per_point)))
            if printable:
                from PIL import ImageDraw
                x0,y0,x1,y1=printable
                ImageDraw.Draw(sheet).rectangle((max(0,round(x0*pixels_per_point)),max(0,round(y0*pixels_per_point)),min(paper_w-1,round(x1*pixels_per_point)),min(paper_h-1,round(y1*pixels_per_point))),outline='#cbd5e1',width=1)
            photo=ImageTk.PhotoImage(sheet)
            keep=(canvas.xview()[0], canvas.yview()[0]) if view['settled'] else None
            canvas.delete('all')
            canvas.create_image(max(0,(canvas_w-paper_w)/2), max(0,(canvas_h-paper_h)/2), anchor='nw', image=photo)
            canvas.image=photo
            region_w, region_h = max(canvas_w, paper_w), max(canvas_h, paper_h)
            canvas.configure(scrollregion=(0, 0, region_w, region_h))
            if keep:
                canvas.xview_moveto(keep[0]); canvas.yview_moveto(keep[1])
            else:
                canvas.xview_moveto(0); canvas.yview_moveto(0)
                view['settled'] = True
        except (ValueError, tk.TclError): pass
    def schedule_metrics(*args):
        view['generation'] += 1
        generation = view['generation']
        view['metrics']=None; view['key']=None
        if view['job']:
            try: dialog.after_cancel(view['job'])
            except tk.TclError: pass
        def start():
            try: w,h=dimensions()
            except ValueError: return
            key=(chosen.get(),w,h); current_mode=modes.get(key[0]); results=queue.Queue()
            def worker():
                dc=None
                try:
                    dc=printer_dc(key[0],w,h,current_mode)
                    results.put(printer_metrics(dc,w,h)[4])
                except Exception: results.put(None)
                finally:
                    if dc:
                        try: dc.DeleteDC()
                        except Exception: pass
            def poll():
                try: result=results.get_nowait()
                except queue.Empty:
                    if dialog.winfo_exists(): dialog.after(150,poll)
                    return
                try:
                    if generation == view['generation'] and (chosen.get(),*dimensions())==key:
                        view['key']=key; view['metrics']=result; view['ready']=True
                        dialog.update_idletasks(); preview()
                except (ValueError,tk.TclError): pass
            threading.Thread(target=worker,daemon=True).start(); dialog.after(150,poll)
        view['job']=dialog.after(300,start)
    for var in (width,height,scaling): var.trace_add('write',preview)
    for var in (width,height,chosen): var.trace_add('write',schedule_metrics)
    def zoom_preview(event):
        if not event.delta: return 'break'
        view['zoom'] = max(.6, min(5.0, view['zoom'] * (1.15 if event.delta > 0 else 1/1.15)))
        preview()
        return 'break'
    def reset_preview(event=None):
        view['zoom'] = 1.0; view['settled'] = False
        preview()
        return 'break'
    canvas.bind('<MouseWheel>', zoom_preview)
    canvas.bind('<Double-Button-1>', reset_preview)
    canvas.bind('<Button-3>', reset_preview)
    canvas.bind('<ButtonPress-1>', lambda e: canvas.scan_mark(e.x, e.y))
    canvas.bind('<B1-Motion>', lambda e: canvas.scan_dragto(e.x, e.y, gain=1))
    resize_job = {'id': None}
    def on_canvas_resize(event=None):
        if resize_job['id']:
            try: dialog.after_cancel(resize_job['id'])
            except tk.TclError: pass
        def run():
            resize_job['id'] = None
            view['settled'] = False   # re-centre at the new size
            preview()
        resize_job['id'] = dialog.after(140, run)
    canvas.bind('<Configure>', on_canvas_resize, add='+')
    schedule_metrics()
    def initial_preview_timeout():
        if not view['ready']:
            view['ready']=True
            dialog.update_idletasks(); preview()
    dialog.after(1500, initial_preview_timeout)
    def submit():
        try:
            w,h=dimensions(); count=int(copies.get())
            if not 1 <= count <= 999: raise ValueError('份数必须为 1 到 999。')
            pages=parse_ranges(custom_range.get(),len(app.doc)) if scope.get()=='指定页码' else page_range(scope.get(),len(app.doc),app.page_index)
            if len(pages)*count > 10000: raise ValueError('打印页数过多，请减少份数。')
            if getattr(app, '_print_job_active', False):
                messagebox.showinfo('打印', '已有打印任务正在提交，请等待完成。', parent=dialog); return
            source = app.doc.tobytes(garbage=0, deflate=True)
            printer = chosen.get(); settings = modes.get(printer)
            selected_scaling = scaling.get(); sample = 1
            amount = 100
            results = queue.Queue()
            app._print_job_active = True
            print_button.config(state='disabled')
            status.config(text='正在准备并提交打印任务，请勿重复点击；关闭窗口不会取消任务。')
            def send():
                try:
                    with fitz.open(stream=source, filetype='pdf') as document:
                        session = SimpleNamespace(doc=document, printer_dc=printer_dc)
                        print_pages(session, printer, w, h, selected_scaling, pages, count, settings, sample, amount)
                    results.put(None)
                except Exception as exc:
                    results.put(exc)
            def poll():
                try: result = results.get_nowait()
                except queue.Empty:
                    app.root.after(150, poll); return
                app._print_job_active = False
                try: visible = bool(dialog.winfo_exists())
                except tk.TclError: visible = False
                if result is None:
                    if visible: dialog.destroy()
                    messagebox.showinfo('打印', '任务已提交到 Windows 打印队列，实际完成情况请查看打印机。', parent=app.root)
                else:
                    if visible:
                        print_button.config(state='normal')
                        status.config(text='提交失败；请检查连接或打印机状态。')
                    messagebox.showerror('打印失败', str(result), parent=dialog if visible else app.root)
            threading.Thread(target=send, daemon=True).start()
            app.root.after(150, poll)
        except Exception as exc: messagebox.showerror('打印失败',str(exc),parent=dialog)
    buttons=ttk.Frame(frame);buttons.grid(row=7,column=0,columnspan=3,pady=8)
    print_button=ttk.Button(buttons,text='开始打印',command=submit);print_button.pack(side='left',padx=6)
    ttk.Button(buttons,text='取消',command=dialog.destroy).pack(side='left',padx=6)
    dialog.update_idletasks()
    width_px, height_px = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
    # A roomy default so the preview is usable, clamped to the screen.
    width_px = max(width_px, 760)
    height_px = max(height_px, 880)
    height_px = min(height_px, max(600, dialog.winfo_screenheight() - 120))
    width_px = min(width_px, max(600, dialog.winfo_screenwidth() - 120))
    dialog.minsize(620, 720)
    root = app.root
    x = root.winfo_rootx() + (root.winfo_width()-width_px)//2
    y = root.winfo_rooty() + (root.winfo_height()-height_px)//2
    try:
        parent_hwnd = win32gui.GetParent(root.winfo_id()) or root.winfo_id()
        monitor = win32api.MonitorFromWindow(parent_hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        left, top, right, bottom = win32api.GetMonitorInfo(monitor)['Work']
        x = max(left, min(x, right-width_px))
        y = max(top, min(y, bottom-height_px))
    except Exception:
        x = max(0,min(x,root.winfo_screenwidth()-width_px))
        y = max(0,min(y,root.winfo_screenheight()-height_px))
    dialog.geometry(f'{width_px}x{height_px}{x:+d}{y:+d}')
    dialog.update_idletasks()
    dialog.deiconify()
    dialog.update_idletasks()
    view['settled'] = False
    if canvas.winfo_width() > 1 and canvas.winfo_height() > 1:
        preview()
    dialog.grab_set()
