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


def layout(page, width, height, scaling):
    pw, ph = page.rect.width, page.rect.height
    paper_w, paper_h = width * 72 / 25.4, height * 72 / 25.4
    if scaling == '实际大小': factor = 1
    elif scaling == '缩小过大页面': factor = min(1, paper_w / pw, paper_h / ph)
    else: factor = min(paper_w / pw, paper_h / ph)
    return factor, (paper_w-pw*factor)/2, (paper_h-ph*factor)/2


def print_pages(app, printer, width, height, scaling, pages, copies, mode, oversample, density=100):
    dc = app.printer_dc(printer, width, height, mode)
    try:
        dpi_x, dpi_y = dc.GetDeviceCaps(88), dc.GetDeviceCaps(90)
        if dpi_x <= 0 or dpi_y <= 0:
            raise ValueError('打印机驱动没有报告有效的分辨率，请检查打印机连接和驱动。')
        physical_w, physical_h = dc.GetDeviceCaps(110), dc.GetDeviceCaps(111)
        offset_x, offset_y = dc.GetDeviceCaps(112), dc.GetDeviceCaps(113)
        actual_w, actual_h = physical_w*25.4/dpi_x, physical_h*25.4/dpi_y
        if abs(actual_w-width)>1.5 or abs(actual_h-height)>1.5:
            raise ValueError(f'打印机报告纸张为 {actual_w:.1f}×{actual_h:.1f} 毫米，未接受所选尺寸。请在打印机属性中设置纸张尺寸。')
        cache = OrderedDict()
        cache_bytes = 0
        cache_limit = 96 * 1024 * 1024
        def dimensions(index):
            page = app.doc[index]
            factor, left, top = layout(page, width, height, scaling)
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


def show_print_dialog(app, printer_dc, printer_mode):
    printers = [p[2] for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]
    if not printers:
        messagebox.showerror('打印', '没有找到打印机，请先在 Windows 中添加。')
        return
    try: default = win32print.GetDefaultPrinter()
    except Exception: default = printers[0]
    dialog = tk.Toplevel(app.root)
    dialog.withdraw()
    dialog.title('打印设置')
    dialog.transient(app.root)
    frame = ttk.Frame(dialog, padding=12)
    frame.pack(fill='both', expand=True)
    chosen = tk.StringVar(value=default if default in printers else printers[0])
    width, height = tk.StringVar(value='70'), tk.StringVar(value='70')
    scaling = tk.StringVar(value='适合纸张')
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
            if result is not None: modes[chosen.get()] = result
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
    status = ttk.Label(frame, text='滚轮缩放预览，按住拖动查看细节，双击恢复。打印浓度请在“打印机属性”中设置。')
    status.grid(row=6, column=0, columnspan=3)
    def dimensions():
        w, h = float(width.get()), float(height.get())
        if not all(math.isfinite(n) and 10 <= n <= 500 for n in (w, h)): raise ValueError('纸张宽和高必须在 10 到 500 毫米之间。')
        return w, h
    view = {'zoom': 1.0, 'settled': False, 'size': None}
    def preview(*args):
        try:
            w, h = dimensions(); page=app.doc[app.page_index]
            factor,left,top=layout(page,w,h,scaling.get())
            canvas_w, canvas_h = canvas.winfo_width(), canvas.winfo_height()
            if canvas_w <= 1 or canvas_h <= 1:
                canvas_w, canvas_h = 460, 460
            # Fit the sheet to whatever room the dialog currently has, so resizing
            # the window grows (or shrinks) the preview instead of leaving a fixed
            # 350 px page in the corner.
            paper_scale=min((canvas_w-28)/w,(canvas_h-28)/h)*view['zoom']
            paper_w=max(1,round(w*paper_scale)); paper_h=max(1,round(h*paper_scale))
            pixels_per_point=paper_scale*25.4/72
            pix=page.get_pixmap(matrix=fitz.Matrix(factor*pixels_per_point, factor*pixels_per_point),alpha=False)
            image=Image.open(io.BytesIO(pix.tobytes('png'))).convert('RGB')
            sheet=Image.new('RGB',(paper_w,paper_h),'white')
            sheet.paste(image,(round(left*pixels_per_point),round(top*pixels_per_point)))
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
    for var in (width,height,scaling): var.trace_add('write',preview)
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
    preview()
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
    dialog.geometry(f'{width_px}x{height_px}')
    dialog.deiconify()
    dialog.update_idletasks()
    try:
        hwnd = win32gui.GetParent(dialog.winfo_id()) or dialog.winfo_id()
        parent_hwnd = win32gui.GetParent(root.winfo_id()) or root.winfo_id()
        parent_left, parent_top, parent_right, parent_bottom = win32gui.GetWindowRect(parent_hwnd)
        dlg_left, dlg_top, dlg_right, dlg_bottom = win32gui.GetWindowRect(hwnd)
        actual_width, actual_height = dlg_right-dlg_left, dlg_bottom-dlg_top
        x = parent_left+(parent_right-parent_left-actual_width)//2
        y = parent_top+(parent_bottom-parent_top-actual_height)//2
        monitor = win32api.MonitorFromWindow(parent_hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        left,top,right,bottom = win32api.GetMonitorInfo(monitor)['Work']
        x = max(left,min(x,right-actual_width))
        y = max(top,min(y,bottom-actual_height))
        win32gui.SetWindowPos(hwnd,0,x,y,0,0,win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
    except Exception:
        dialog.geometry(f'{width_px}x{height_px}{x:+d}{y:+d}')
    dialog.grab_set()
