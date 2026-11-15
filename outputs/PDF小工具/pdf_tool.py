import os
import sys
import io
import time
import tempfile
import subprocess
import ctypes
from ctypes import wintypes
import math
import hashlib
import re
import json
import sqlite3
import queue
from pathlib import Path

if sys.platform == 'win32':
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try: ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError): pass

RESOURCE_BASE = Path(__file__).resolve().parent
BASE = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else RESOURCE_BASE
sys.path.insert(0, str(RESOURCE_BASE / '依赖'))
for subdir in ('win32', 'win32/lib', 'pythonwin', 'pywin32_system32'):
    sys.path.insert(0, str(RESOURCE_BASE / '依赖' / subdir))
if hasattr(os, 'add_dll_directory') and (RESOURCE_BASE / '依赖' / 'pywin32_system32').is_dir():
    os.add_dll_directory(str(RESOURCE_BASE / '依赖' / 'pywin32_system32'))
import fitz
from kanzonas import text_edit, page_objects, text_styles, added_text
import settings
import theme
import instance
from PIL import Image, ImageTk, ImageWin, ImageGrab
import win32print
import win32ui
import win32gui
import win32con
import win32clipboard
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk, colorchooser, font as tkfont


class RoundButton(tk.Canvas):
    """Compact rounded toolbar button with keyboard, focus and hover support."""
    def __init__(self, parent, text, command, accent=False, min_width=0):
        from tkinter import font as tkfont
        self.label, self.command, self.accent = text, command, accent
        self.button_font = tkfont.Font(family='Microsoft YaHei UI', size=9)
        self.button_width = max(min_width, self.button_font.measure(text)+22)
        self.button_height = max(32, self.button_font.metrics('linespace')+10)
        self.hover = False
        self.pressed = False
        self.focused = False
        super().__init__(parent, width=self.button_width, height=self.button_height,
                         background=theme.c('bg'), highlightthickness=0, borderwidth=0,
                         cursor='hand2', takefocus=True)
        self.bind('<Enter>', lambda e:self.set_state('hover', True))
        self.bind('<Leave>', lambda e:self.set_state('hover', False))
        self.bind('<FocusIn>', lambda e:self.set_state('focused', True))
        self.bind('<FocusOut>', lambda e:self.set_state('focused', False))
        self.bind('<ButtonPress-1>', self.on_press)
        self.bind('<ButtonRelease-1>', self.on_release)
        # Space is reserved for grab-and-drag panning, so only Enter activates
        # a toolbar button from the keyboard.
        self.bind('<Return>', self.on_key)
        self.paint()

    def set_state(self, key, value):
        setattr(self, key, value)
        self.paint()

    def paint(self):
        self.delete('all')
        w, h = self.button_width, self.button_height
        if self.accent:
            fill = theme.c('accent_press') if self.pressed else theme.c('accent_hover') if self.hover else theme.c('accent')
        else:
            fill = theme.c('btn_press') if self.pressed else theme.c('btn_hover') if self.hover else theme.c('btn')
        border = theme.c('accent') if self.focused or self.accent else theme.c('border')
        radius = 7
        points = (1,radius,1,1,radius,1,w-radius,1,w-1,1,w-1,radius,
                  w-1,h-radius,w-1,h-1,w-radius,h-1,radius,h-1,1,h-1,1,h-radius)
        self.create_polygon(*points, smooth=True, splinesteps=20, fill=fill, outline=border, width=1)
        self.create_text(w/2, h/2, text=self.label, font=self.button_font,
                         fill='white' if self.accent else theme.c('btn_fg'))

    def on_press(self, event):
        self.focus_set()
        self.set_state('pressed', True)

    def on_release(self, event):
        was_pressed = self.pressed
        self.set_state('pressed', False)
        if was_pressed and 0 <= event.x < self.button_width and 0 <= event.y < self.button_height:
            self.invoke()

    def on_key(self, event):
        self.invoke()
        return 'break'

    def invoke(self):
        return self.command()


class SlimScrollbar(tk.Canvas):
    """A compact rounded scrollbar compatible with Tk's scroll callbacks."""
    def __init__(self, parent, orient='vertical', command=None, **kwargs):
        self.vertical = orient == 'vertical'
        self.scroll_command = command
        self.first = 0.0; self.last = 1.0
        self.drag_offset = None; self.hover = False
        super().__init__(parent, width=12 if self.vertical else 1, height=1 if self.vertical else 12,
                         background=theme.c('scroll_bg'), highlightthickness=0, borderwidth=0, **kwargs)
        self.bind('<Configure>', lambda e:self.paint())
        self.bind('<Enter>', lambda e:self.set_hover(True))
        self.bind('<Leave>', lambda e:self.set_hover(False))
        self.bind('<ButtonPress-1>', self.press)
        self.bind('<B1-Motion>', self.drag)
        self.bind('<ButtonRelease-1>', lambda e:setattr(self, 'drag_offset', None))

    def configure(self, cnf=None, **kwargs):
        if 'command' in kwargs: self.scroll_command = kwargs.pop('command')
        return super().configure(cnf, **kwargs)
    config = configure

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self.paint()

    def bounds(self):
        length = max(1, self.winfo_height() if self.vertical else self.winfo_width())
        span = min(length, max(18, (self.last-self.first)*length))
        start = min(length-span, max(0, self.first*length))
        return length, start, span

    def set_hover(self, value):
        self.hover = value; self.paint()

    def paint(self):
        if not self.winfo_exists(): return
        self.delete('thumb')
        if self.first <= 0 and self.last >= 1: return
        length, start, span = self.bounds()
        if length <= 1: return
        mid = start+span/2; half = max(0, (span-6)/2)
        color = theme.c('scroll_hot') if self.hover or self.drag_offset is not None else theme.c('scroll')
        if self.vertical:
            self.create_line(6, mid-half, 6, mid+half, fill=color, width=6, capstyle='round', tags='thumb')
        else:
            self.create_line(mid-half, 6, mid+half, 6, fill=color, width=6, capstyle='round', tags='thumb')

    def press(self, event):
        length, start, span = self.bounds()
        pos = event.y if self.vertical else event.x
        if start <= pos <= start+span:
            self.drag_offset = pos-start
        elif self.scroll_command:
            self.scroll_command('scroll', -1 if pos < start else 1, 'pages')
        self.paint()

    def drag(self, event):
        if self.drag_offset is None or not self.scroll_command: return
        length, _, span = self.bounds()
        pos = event.y if self.vertical else event.x
        fraction = max(0, min(1, (pos-self.drag_offset)/max(1, length-span)))
        self.scroll_command('moveto', fraction*max(0, 1-(self.last-self.first)))

def annotate_block_ids(page, lines):
    """Tag each line with the PDF text block it belongs to.

    Two blocks dragged on top of each other still live in different text objects,
    so the block id is what lets a click pick the block it landed on instead of
    merging both into one.
    """
    if not lines:
        return
    try:
        data = page.get_text('dict', clip=fitz.INFINITE_RECT())
    except Exception:
        return
    boxes = []
    for index, block in enumerate(data.get('blocks') or []):
        if block.get('type') != 0:
            continue
        for line in block.get('lines') or []:
            boxes.append((fitz.Rect(line.get('bbox') or (0, 0, 0, 0)), index))
    if not boxes:
        return
    for _rect, line in lines:
        target = fitz.Rect(line['bbox'])
        line['block_id'] = None
        for box, index in boxes:
            if (abs(box.y0 - target.y0) <= 0.8 and abs(box.x0 - target.x0) <= 0.8
                    and abs(box.y1 - target.y1) <= 1.2):
                line['block_id'] = index
                break


def full_text_lines(page):
    """Read full text outside the page box without treating annotations as page text."""
    annotations = list(page.annots() or [])
    widgets = list(page.widgets() or [])
    clone = None
    source = page
    if annotations or widgets:
        clone = fitz.open(stream=page.parent.tobytes(garbage=0, deflate=True), filetype='pdf')
        source = clone[page.number]
        for annot in list(source.annots() or []): source.delete_annot(annot)
        for widget in list(source.widgets() or []): source.delete_widget(widget)
    old_reader = text_edit.page_text_dict
    try:
        def read_all(current, flags):
            from kanzonas import text_guard
            flags = text_guard.flags_for(current, flags & ~fitz.TEXT_MEDIABOX_CLIP)
            return current.get_text('dict', flags=flags, clip=fitz.INFINITE_RECT())
        text_edit.page_text_dict = read_all
        found = text_edit.text_lines(source)
        annotate_block_ids(source, found)
        return found
    finally:
        text_edit.page_text_dict = old_reader
        if clone: clone.close()

class PrinterMode(ctypes.Structure):
    _fields_ = [('name', wintypes.WCHAR * 32), ('spec', wintypes.WORD),
                ('driver', wintypes.WORD), ('size', wintypes.WORD),
                ('extra', wintypes.WORD), ('fields', wintypes.DWORD),
                ('orientation', ctypes.c_short), ('paper_size', ctypes.c_short),
                ('paper_length', ctypes.c_short), ('paper_width', ctypes.c_short)]

def printer_mode(printer_name, previous=None, parent=None):
    spool = ctypes.WinDLL('winspool.drv', use_last_error=True)
    spool.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
    spool.DocumentPropertiesW.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
    spool.DocumentPropertiesW.restype = ctypes.c_long
    spool.ClosePrinter.argtypes = [wintypes.HANDLE]
    handle = wintypes.HANDLE()
    if not spool.OpenPrinterW(printer_name, ctypes.byref(handle), None): raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = spool.DocumentPropertiesW(None, handle, printer_name, None, None, 0)
        if size <= 0: raise ValueError('无法获取打印机纸张设置。')
        buffer = ctypes.create_string_buffer(size)
        if previous is not None and len(previous) == size:
            ctypes.memmove(buffer, previous, size)
        elif spool.DocumentPropertiesW(None, handle, printer_name, buffer, None, 2) != 1:
            raise ValueError('无法读取打印机纸张设置。')
        if parent is not None:
            result = spool.DocumentPropertiesW(parent, handle, printer_name, buffer, buffer, 14)
            if result == 2: return None
            if result != 1: raise ValueError('无法打开打印机属性。')
        return bytes(buffer)
    finally:
        spool.ClosePrinter(handle)

def printer_dc(printer_name, width_mm=70, height_mm=70, settings=None):
    spool = ctypes.WinDLL('winspool.drv', use_last_error=True)
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    spool.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
    spool.DocumentPropertiesW.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
    spool.DocumentPropertiesW.restype = ctypes.c_long
    spool.ClosePrinter.argtypes = [wintypes.HANDLE]
    gdi.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
    gdi.CreateDCW.restype = wintypes.HDC
    data = settings if settings is not None else printer_mode(printer_name)
    buffer = ctypes.create_string_buffer(data, len(data))
    handle = wintypes.HANDLE()
    if not spool.OpenPrinterW(printer_name, ctypes.byref(handle), None): raise ctypes.WinError(ctypes.get_last_error())
    try:
        mode = PrinterMode.from_buffer(buffer)
        mode.fields |= win32con.DM_PAPERSIZE | win32con.DM_PAPERWIDTH | win32con.DM_PAPERLENGTH | win32con.DM_ORIENTATION
        mode.paper_size, mode.paper_width, mode.paper_length, mode.orientation = 0, round(width_mm*10), round(height_mm*10), 1
        if spool.DocumentPropertiesW(None, handle, printer_name, buffer, buffer, 10) != 1:
            raise ValueError('打印机驱动未接受纸张设置。')
        raw = gdi.CreateDCW('WINSPOOL', printer_name, None, buffer)
        if not raw: raise ctypes.WinError(ctypes.get_last_error())
        return win32ui.CreateDCFromHandle(raw)
    finally:
        spool.ClosePrinter(handle)

class PDFTool:
    def restore_window_state(self):
        """Restore the window size/position and panel widths from the last session."""
        match = re.fullmatch(r'(\d+)x(\d+)(?:([+-]\d+)([+-]\d+))?', str(self.prefs.get('geometry') or ''))
        if match:
            width = max(1160, min(int(match.group(1)), self.root.winfo_screenwidth()))
            height = max(640, min(int(match.group(2)), self.root.winfo_screenheight()))
            if match.group(3):
                x = max(0, min(int(match.group(3)), self.root.winfo_screenwidth()-width))
                y = max(0, min(int(match.group(4)), self.root.winfo_screenheight()-height))
                self.root.geometry(f'{width}x{height}+{x}+{y}')
            else:
                self.root.geometry(f'{width}x{height}')
    def restore_panel_widths(self):
        for key, widget, low, high in (('thumb_width', 'thumbnail_panel', 170, 420),
                                       ('assets_width', 'assets_panel', 170, 560)):
            try:
                value = int(self.prefs.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value:
                getattr(self, widget).configure(width=max(low, min(high, value)))

    def save_window_state(self):
        try:
            geometry = self.root.geometry()
            if self.root.state() == 'zoomed':
                geometry = f'{self.root.winfo_width()}x{self.root.winfo_height()}'
            self.prefs['geometry'] = geometry
            self.prefs['thumb_width'] = self.thumbnail_panel.winfo_width()
            self.prefs['assets_width'] = self.assets_panel.winfo_width()
            settings.save(self.prefs)
        except tk.TclError:
            pass

    def set_window_icon(self):
        """Use the application icon for the title bar, taskbar and every dialog.

        Tk defaults to its feather icon; the .ico ships next to the sources and
        is bundled into the EXE (sys._MEIPASS) by the build script.
        """
        path = RESOURCE_BASE / 'app.ico'
        if not path.is_file(): return
        try:
            self.root.iconbitmap(str(path))            # this window
            self.root.iconbitmap(default=str(path))    # and its dialogs
        except tk.TclError:
            pass

    def __init__(self, root):
        self.root = root
        self.prefs = settings.load()
        self.saved_scale = self.prefs.get('last_scale', 1.0)
        theme.set_mode(theme.resolve(self.prefs.get('theme', 'system')))
        self.root.title('PDF 标签编辑器')
        self.root.geometry('1280x850')
        self.root.minsize(1160, 640)
        self.restore_window_state()
        self.root.configure(background=theme.c('bg'))
        self.set_window_icon()
        self.doc = None
        self.tabs = {}
        self.active_tab = None
        self.changing_tab = False
        self.page_index = 0
        self.scale = 1.5
        self.origin_x = 0
        self.origin_y = 0
        self.page_width = 0
        self.page_height = 0
        self.last_file_stat = None
        self.selection = None
        self.selection_lines = []
        self.moved_text_marks = []
        self.space_pan = False
        self.drag_start = None
        self.drag_kind = None
        self.drag_origin_rect = None
        self.drag_origin_quad = None
        self.edit_on_release = False
        self.resize_corner = None
        self.selected_object = None
        self.dirty = False
        self.undo_data = []
        self.redo_data = []
        self.clipboard_pdf = None
        self.clipboard_box = None
        self.clipboard_box_geometry = None
        self.clipboard_size = None
        self.clipboard_sequence = None
        self.thumbnail_clipboard = None
        self.asset_db = None
        self.assets = []
        self.batch_imported_ids = set()
        self.batch_mode = None
        self.batch_waiting_for_selection = False
        self.selection_type = tk.StringVar(value='自动选择')
        self.snap_enabled = tk.BooleanVar(value=True)
        self.snap_candidates = None
        self.placing_text = False
        self.selected_kind = None
        self.selected_line = None
        self.selected_paragraph = None
        self.selected_block = None
        self.inline_editor = None
        self.inline_state = None
        self.font_size_value = tk.StringVar(value='10')
        self.font_size_dirty = False
        self.font_bold_value = tk.BooleanVar(value=False)
        self.font_italic_value = tk.BooleanVar(value=False)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 9))
        style.configure('TButton', padding=(8, 5), focusthickness=1)
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 15, 'bold'))
        style.configure('Hint.TLabel', font=('Microsoft YaHei UI', 9))
        theme.apply_ttk(style)
        self.style = style
        bar = ttk.Frame(root, padding=(12, 8, 12, 4))
        bar.pack(fill='x')
        # Row 1: file -> print -> page/zoom, with the panel toggles on the right.
        for label, action, accent in [('打开', self.open, False), ('保存', self.save, False), ('另存为', self.save_as, False)]:
            RoundButton(bar, text=label, command=action, accent=accent, min_width=56).pack(side='left', padx=(0, 4))
        RoundButton(bar, text='打印', command=self.print_pdf, accent=True, min_width=56).pack(side='left', padx=(6, 0))
        ttk.Separator(bar, orient='vertical').pack(side='left', fill='y', padx=8, pady=3)
        RoundButton(bar, text='上一页', command=lambda: self.turn(-1), min_width=30).pack(side='left', padx=2)
        RoundButton(bar, text='−', command=lambda: self.zoom(1/1.1), min_width=28).pack(side='left', padx=2)
        self.zoom_value = tk.StringVar(value='150%')
        zoom_entry = ttk.Entry(bar, textvariable=self.zoom_value, width=6)
        zoom_entry.pack(side='left', padx=2)
        zoom_entry.bind('<Return>', self.set_zoom)
        zoom_entry.bind('<FocusIn>', lambda e: zoom_entry.select_range(0, 'end'))
        RoundButton(bar, text='+', command=lambda: self.zoom(1.1), min_width=28).pack(side='left', padx=2)
        RoundButton(bar, text='下一页', command=lambda: self.turn(1), min_width=30).pack(side='left', padx=2)
        RoundButton(bar, text='适合页面', command=self.fit_page, min_width=56).pack(side='left', padx=(6, 0))
        RoundButton(bar, text='设置', command=self.open_settings, min_width=44).pack(side='right', padx=(4, 12))
        pdf_tools_menu = theme.menu(root)
        pdf_tools_menu.add_command(label='合并 PDF…', command=self.merge_pdf_dialog)
        pdf_tools_menu.add_separator()
        pdf_tools_menu.add_command(label='批量替换标签…', command=lambda:self.start_batch_mode('single'))
        pdf_tools_menu.add_command(label='多页条码批量替换…', command=lambda:self.start_batch_mode('multi'))
        pdf_tools_menu.add_command(label='旧标签批量更新…', command=lambda:self.start_batch_mode('legacy'))
        pdf_tools_menu.add_separator()
        pdf_tools_menu.add_command(label='设为默认 PDF 应用…', command=self.set_default_pdf_app)
        pdf_tools_menu.add_command(label='检查更新…', command=lambda: self.check_updates())
        def show_pdf_tools():
            self.popup_menu(pdf_tools_menu, pdf_tools_button.winfo_rootx(),
                            pdf_tools_button.winfo_rooty()+pdf_tools_button.winfo_height(),
                            right=pdf_tools_button.winfo_rootx()+pdf_tools_button.winfo_width())
        pdf_tools_button = RoundButton(bar, text='PDF 工具 ▾', command=show_pdf_tools, min_width=76, accent=True)
        pdf_tools_button.pack(side='right', padx=(4, 0))
        RoundButton(bar, text='素材', command=self.toggle_assets, min_width=44).pack(side='right', padx=(4, 0))
        self.toolbar_pages_button = RoundButton(bar, text='页面', command=self.toggle_page_thumbnails, min_width=44)
        self.toolbar_pages_button.pack(side='right', padx=(4, 0))
        self.toolbar = bar
        self.toolbar_tools_button = pdf_tools_button
        self.batch_mode_bar = ttk.Frame(bar)
        self.batch_mode_label = tk.StringVar(value='')
        ttk.Button(self.batch_mode_bar, textvariable=self.batch_mode_label, style='Primary.TButton', command=self.continue_batch_mode).pack(side='left')
        ttk.Button(self.batch_mode_bar, text='×', width=2, command=self.exit_batch_mode).pack(side='left', padx=(3, 0))
        editbar = ttk.Frame(root, padding=(12, 3, 12, 7))
        editbar.pack(fill='x')
        # Row 2: select -> edit -> history -> text format, with 更多 on the right.
        ttk.Label(editbar, text='选择', style='Hint.TLabel').pack(side='left', padx=(0, 4))
        ttk.Combobox(editbar, textvariable=self.selection_type, values=['自动选择', '整块文字', '框选区域', '选择文字', '选择文本框', '选择图片', '选择图形'], state='readonly', width=8).pack(side='left')
        ttk.Separator(editbar, orient='vertical').pack(side='left', fill='y', padx=8, pady=3)
        for label, action in [('编辑', self.replace), ('文本框', self.add_text), ('图片', self.add_image), ('删除', self.delete_selected)]:
            RoundButton(editbar, text=label, command=action, min_width=44).pack(side='left', padx=(4, 0))
        ttk.Separator(editbar, orient='vertical').pack(side='left', fill='y', padx=8, pady=3)
        for label, action in [('撤销', self.undo), ('重做', self.redo)]:
            RoundButton(editbar, text=label, command=action, min_width=44).pack(side='left', padx=(4, 0))
        ttk.Separator(editbar, orient='vertical').pack(side='left', fill='y', padx=8, pady=3)
        more_menu = theme.menu(root)
        for label, action in [('裁剪图片', self.crop_image), ('删除框选内容', self.delete_area), ('删除框选文字', self.delete), ('完成文字编辑  Ctrl+Enter', self.apply_inline), ('取消文字编辑  Esc', self.cancel_inline)]:
            more_menu.add_command(label=label, command=action)
        more_menu.add_separator()
        more_menu.add_checkbutton(label='拖动时吸附对齐', variable=self.snap_enabled)
        def show_more():
            self.popup_menu(more_menu, more_button.winfo_rootx(),
                            more_button.winfo_rooty()+more_button.winfo_height(),
                            right=more_button.winfo_rootx()+more_button.winfo_width())
        more_button = RoundButton(editbar, text='更多 ▾', command=show_more, min_width=56)
        formatbar = editbar
        families = sorted({name for name in tkfont.families() if not name.startswith('@')}, key=str.lower)
        self.font_family_value = tk.StringVar(value='')
        family_box = ttk.Combobox(formatbar, textvariable=self.font_family_value, state='readonly', width=12,
                                  values=['（默认字体）'] + families)
        family_box.pack(side='left', padx=(0, 4))
        family_box.bind('<<ComboboxSelected>>', lambda e: self.change_text_style('family', self.current_family()))
        ttk.Label(formatbar, text='字号').pack(side='left', padx=(6, 0))
        sizes = ('6','7','8','9','10','10.5','11','12','14','16','18','20','22','24','26','28','36','48','72')
        font_size_box = ttk.Combobox(formatbar, textvariable=self.font_size_value, values=sizes, width=5)
        font_size_box.pack(side='left', padx=4)
        font_size_box.bind('<KeyRelease>', self.font_size_typed)
        font_size_box.bind('<FocusOut>', self.font_size_focus_out)
        font_size_box.bind('<<ComboboxSelected>>', lambda e:self.change_text_size())
        font_size_box.bind('<Return>', lambda e:self.change_text_size())
        RoundButton(formatbar, text='A−', min_width=30, command=lambda:self.step_text_size(-1)).pack(side='left')
        RoundButton(formatbar, text='A+', min_width=30, command=lambda:self.step_text_size(1)).pack(side='left', padx=(3, 6))
        ttk.Checkbutton(formatbar, text='加粗', variable=self.font_bold_value, command=lambda:self.change_text_style('bold')).pack(side='left', padx=4)
        ttk.Checkbutton(formatbar, text='斜体', variable=self.font_italic_value, command=lambda:self.change_text_style('italic')).pack(side='left', padx=4)
        self.font_color = (0, 0, 0)
        self.font_color_explicit = False
        self.font_color_hex = tk.StringVar(value='#000000')
        RoundButton(formatbar, text='颜色', min_width=44, command=self.pick_font_color).pack(side='left', padx=(6, 3))
        self.color_swatch = tk.Canvas(formatbar, width=22, height=18, highlightthickness=1,
                                      highlightbackground=theme.c('border'), background='#000000')
        self.color_swatch.pack(side='left', padx=(0, 4))
        more_button.pack(side='left', padx=(16, 0))
        tabbar = ttk.Frame(root, padding=(10,0,10,0))
        tabbar.pack(fill='x')
        self.tabbar = tabbar
        self.batch_mode_narrow_bar = ttk.Frame(root, padding=(12, 0, 12, 4))
        ttk.Button(self.batch_mode_narrow_bar, textvariable=self.batch_mode_label, style='Primary.TButton', command=self.continue_batch_mode).pack(side='left')
        ttk.Button(self.batch_mode_narrow_bar, text='×', width=2, command=self.exit_batch_mode).pack(side='left', padx=(3, 0))
        bar.bind('<Configure>', lambda e:self.root.after_idle(self.adjust_batch_mode_position), add='+')
        self.tab_control = ttk.Notebook(tabbar, height=1, style='Document.TNotebook')
        self.tab_control.pack(side='left', fill='x', expand=True)
        self.tab_control.bind('<<NotebookTabChanged>>', self.on_tab_change)

        def tab_close_click(event):
            try:
                index = self.tab_control.index('@%d,%d' % (event.x, event.y))
            except tk.TclError:
                return None
            tabs = self.tab_control.tabs()
            if not tabs or index >= len(tabs):
                return None
            # ttk.Notebook.bbox() returns (0,0,0,0) for tabs on Windows.
            # Find this tab's actual right edge with Tk's own hit testing.
            if self.tab_control.identify(event.x, event.y) != 'label':
                return None
            right = event.x
            while right + 1 < self.tab_control.winfo_width():
                try: next_index = self.tab_control.index('@%d,%d' % (right+1, event.y))
                except tk.TclError: break
                if next_index != index: break
                right += 1
            padding = ttk.Style().lookup('Document.TNotebook.Tab', 'padding')
            try:
                parts = self.root.tk.splitlist(padding)
                pad_right = int(str(parts[2] if len(parts) >= 3 else parts[0])) if parts else 0
            except (ValueError, tk.TclError): pad_right = 0
            from tkinter import font as tkfont
            font_spec = ttk.Style().lookup('Document.TNotebook.Tab', 'font')
            glyph_width = tkfont.Font(root=self.root, font=font_spec).measure('×')
            glyph_right = right - pad_right + 2
            if glyph_right-glyph_width-3 <= event.x <= glyph_right:
                self.close_tab_by(tabs[index])
                return 'break'
            return None

        self.tab_control.bind('<Button-1>', tab_close_click, add='+')
        self.tab_control.bind('<Button-2>', lambda event: self.close_tab_by(
            self.tab_control.tabs()[self.tab_control.index('@%d,%d' % (event.x, event.y))])
            if self.tab_control.identify(event.x, event.y) == 'label' else None, add='+')
        RoundButton(tabbar, text='关闭标签', command=self.close_tab).pack(side='right', padx=(5,0))
        self.status = ttk.Label(root, text='打开 PDF 后，点击文字编辑；拖动边框移动或缩放。', style='Status.TLabel')
        self.status.pack(fill='x')
        frame = ttk.Frame(root)
        frame.pack(fill='both', expand=True)
        self.thumbnail_panel = ttk.Frame(frame, width=210, padding=(8, 8))
        self.thumbnail_panel.pack(side='left', fill='y')
        self.thumbnail_panel.pack_propagate(False)
        self.thumbnail_splitter = tk.Frame(frame, width=7, background='#dce4ec', cursor='sb_h_double_arrow')
        self.thumbnail_splitter.pack(side='left', fill='y')
        self.thumbnail_splitter.pack_propagate(False)
        self.thumbnail_resize_state = None
        self.thumbnail_resize_job = None
        self.thumbnail_splitter.bind('<ButtonPress-1>', self.start_thumbnail_resize)
        self.thumbnail_splitter.bind('<B1-Motion>', self.drag_thumbnail_resize)
        self.thumbnail_splitter.bind('<ButtonRelease-1>', self.finish_thumbnail_resize)
        self.thumbnail_splitter.bind('<Enter>', lambda e:self.thumbnail_splitter.config(background='#a8bcd0'))
        self.thumbnail_splitter.bind('<Leave>', lambda e:self.thumbnail_splitter.config(background='#dce4ec'))
        thumb_header = ttk.Frame(self.thumbnail_panel); thumb_header.pack(fill='x', pady=(0, 6))
        ttk.Label(thumb_header, text='页面缩略图', font=('Microsoft YaHei UI', 10, 'bold')).pack(side='left')
        ttk.Button(thumb_header, text='×', width=3, command=self.toggle_page_thumbnails).pack(side='right')
        thumb_tools = ttk.Frame(self.thumbnail_panel); thumb_tools.pack(fill='x', pady=(0, 6))
        thumb_options = theme.menu(root)
        thumb_options.add_command(label='缩小页面缩略图', command=lambda:self.zoom_thumbnails(1/1.2))
        thumb_options.add_command(label='放大页面缩略图', command=lambda:self.zoom_thumbnails(1.2))
        options_button = ttk.Menubutton(thumb_tools, text='▦ ▾', menu=thumb_options, width=5)
        options_button.pack(side='left', padx=(0, 3))
        for label, action in [('删', self.delete_thumbnail_page), ('裁', self.crop_thumbnail_page),
                              ('↶', lambda:self.rotate_thumbnail_page(-90)), ('↷', lambda:self.rotate_thumbnail_page(90))]:
            ttk.Button(thumb_tools, text=label, width=3, command=action).pack(side='left', padx=(0, 1))
        self.thumbnail_scale = 1.0
        self.thumbnail_canvas = tk.Canvas(self.thumbnail_panel, background='#eef2f7', highlightthickness=0, width=150)
        thumb_scroll = SlimScrollbar(self.thumbnail_panel, orient='vertical', command=self.thumbnail_canvas.yview)
        thumb_scroll.pack(side='right', fill='y'); self.thumbnail_canvas.pack(side='left', fill='both', expand=True)
        self.thumbnail_photos = {}
        self.thumbnail_job = None
        def thumb_scrolled(first, last):
            thumb_scroll.set(first, last)
            if self.thumbnail_job is None:
                self.thumbnail_job = self.root.after_idle(self.render_visible_thumbnails)
        self.thumbnail_canvas.configure(yscrollcommand=thumb_scrolled)
        self.thumbnail_canvas.bind('<Button-1>', self.thumbnail_click)
        self.thumbnail_canvas.bind('<Button-3>', self.thumbnail_context_menu)
        self.thumbnail_canvas.bind('<Control-c>', lambda e:(self.copy_thumbnail_page(), 'break')[1])
        self.thumbnail_canvas.bind('<Control-v>', lambda e:(self.paste_thumbnail_page(False), 'break')[1])
        self.thumbnail_canvas.bind('<MouseWheel>', lambda e:(self.thumbnail_canvas.yview_scroll(-int(math.copysign(max(1, abs(e.delta)//40), e.delta)), 'units'), 'break')[1] if e.delta else 'break')
        self.assets_panel = ttk.Frame(frame, padding=(10,8,10,8), width=225)
        self.assets_panel.pack(side='right', fill='y')
        self.assets_panel.pack_propagate(False)
        self.assets_splitter = tk.Frame(frame, width=7, background=theme.c('split'), cursor='sb_h_double_arrow')
        self.assets_splitter.pack(side='right', fill='y')
        self.assets_splitter.pack_propagate(False)
        self.assets_resize_state = None
        self.assets_splitter.bind('<ButtonPress-1>', self.start_assets_resize)
        self.assets_splitter.bind('<B1-Motion>', self.drag_assets_resize)
        self.assets_splitter.bind('<ButtonRelease-1>', lambda e: setattr(self, 'assets_resize_state', None))
        self.assets_splitter.bind('<Enter>', lambda e: self.assets_splitter.config(background=theme.c('split_hover')))
        self.assets_splitter.bind('<Leave>', lambda e: self.assets_splitter.config(background=theme.c('split')))
        self.restore_panel_widths()
        asset_heading = ttk.Frame(self.assets_panel)
        asset_heading.pack(fill='x')
        asset_title = ttk.Label(asset_heading, text='备用素材', font=('Microsoft YaHei UI', 11, 'bold'))
        asset_title.pack(side='left')
        self.asset_count = tk.StringVar(value='0 项')
        ttk.Label(asset_heading, textvariable=self.asset_count, style='Hint.TLabel').pack(side='right')
        asset_hint = ttk.Label(self.assets_panel, text='点击此栏后按 Ctrl+V 添加复制内容', style='Hint.TLabel', wraplength=205)
        asset_hint.pack(anchor='w', pady=(3,6))
        RoundButton(self.assets_panel, text='点击粘贴剪贴板', command=self.add_asset, accent=True).pack(anchor='w', pady=(0,6))
        self.asset_preview_frame = tk.Frame(self.assets_panel, height=190, background='white', highlightbackground='#d4dce6', highlightthickness=1)
        self.asset_preview_frame.pack(fill='x', pady=(0,6))
        self.asset_preview_frame.pack_propagate(False)
        self.asset_preview = tk.Canvas(self.asset_preview_frame, background='white', highlightthickness=0, cursor='hand2')
        self.asset_preview_scroll = SlimScrollbar(self.asset_preview_frame, orient='horizontal', command=self.asset_preview.xview)
        self.asset_preview_scroll.pack(side='bottom', fill='x')
        self.asset_preview_vscroll = SlimScrollbar(self.asset_preview_frame, orient='vertical', command=self.asset_preview.yview)
        self.asset_preview_vscroll.pack(side='right', fill='y')
        self.asset_preview.configure(xscrollcommand=self.asset_preview_scroll.set, yscrollcommand=self.asset_preview_vscroll.set)
        self.asset_preview.pack(fill='both', expand=True)
        self.asset_preview_zoom = 1.0
        self.asset_preview_id = None
        preview_controls = ttk.Frame(self.assets_panel)
        preview_controls.pack(fill='x', pady=(0,5))
        ttk.Label(preview_controls, text='预览').pack(side='left')
        ttk.Button(preview_controls, text='−', width=3, command=lambda:self.zoom_asset_preview(1/1.4)).pack(side='left', padx=(5,2))
        ttk.Button(preview_controls, text='+', width=3, command=lambda:self.zoom_asset_preview(1.4)).pack(side='left', padx=2)
        ttk.Button(preview_controls, text='完整', width=4, command=self.fit_asset_preview).pack(side='left', padx=2)
        self.asset_drag_state = None
        self.asset_panning = False
        ttk.Label(self.assets_panel, text='素材列表  ·  双击放入，或拖到页面', style='Hint.TLabel').pack(anchor='w', pady=(2,4))
        asset_list_frame = ttk.Frame(self.assets_panel)
        asset_list_frame.pack(fill='both', expand=True)
        asset_scroll = SlimScrollbar(asset_list_frame, orient='vertical')
        asset_scroll.pack(side='right', fill='y')
        self.asset_list = tk.Listbox(asset_list_frame, height=9, selectmode='extended', exportselection=False,
                                     font=('Microsoft YaHei UI',9), activestyle='none',
                                     background='white', foreground='#253449', borderwidth=0,
                                     highlightthickness=1, highlightbackground='#d4dce6',
                                     highlightcolor='#0f6cbd', selectborderwidth=0,
                                     selectbackground='#0f6cbd', selectforeground='white', yscrollcommand=asset_scroll.set)
        self.asset_list.pack(side='left', fill='both', expand=True)
        asset_scroll.config(command=self.asset_list.yview)
        def scroll_assets(event):
            if not event.delta: return 'break'
            self.asset_list.yview_scroll(-int(math.copysign(max(1, abs(event.delta)//40), event.delta)), 'units')
            return 'break'
        self.asset_list.bind('<MouseWheel>', scroll_assets, add='+')
        self.assets_panel.bind('<MouseWheel>', scroll_assets, add='+')
        self.asset_list.bind('<<ListboxSelect>>', self.show_asset_preview)
        self.asset_list.bind('<Double-Button-1>', lambda e:self.paste_asset())
        self.asset_list.bind('<Control-v>', lambda e:(self.add_asset(), 'break')[1])
        self.asset_list.bind('<Button-1>', lambda e:self.asset_list.focus_set(), add='+')
        for widget in (self.assets_panel, asset_title, asset_hint, asset_list_frame, self.asset_preview_frame):
            widget.bind('<Button-1>', lambda e:self.asset_list.focus_set(), add='+')
        for widget in (self.asset_list, self.asset_preview):
            widget.bind('<ButtonPress-1>', self.asset_drag_start, add='+')
            widget.bind('<B1-Motion>', self.asset_drag_move, add='+')
            widget.bind('<ButtonRelease-1>', self.asset_drag_end, add='+')
        self.asset_list.bind('<Button-3>', self.asset_context_menu)
        asset_actions = ttk.Frame(self.assets_panel)
        asset_actions.pack(fill='x')
        RoundButton(asset_actions, text='放入 PDF', command=self.paste_asset, accent=True).pack(side='left')
        asset_more = ttk.Frame(self.assets_panel)
        asset_more.pack(fill='x', pady=(5,0))
        RoundButton(asset_more, text='重命名', command=self.rename_asset).pack(side='left')
        RoundButton(asset_more, text='删除', command=self.delete_asset).pack(side='left', padx=4)
        RoundButton(asset_more, text='清空', command=self.clear_assets).pack(side='left')
        asset_actions.pack_forget()
        asset_more.pack_forget()
        asset_more.pack(side='bottom', fill='x', pady=(5,10), before=asset_list_frame)
        asset_actions.pack(side='bottom', fill='x', before=asset_list_frame)
        self.asset_preview_photo = None
        self.canvas = tk.Canvas(frame, background='#677689', highlightthickness=0)
        sy = SlimScrollbar(frame, orient='vertical', command=self.canvas.yview)
        self.page_scrollbar = sy
        sx = SlimScrollbar(root, orient='horizontal', command=self.canvas.xview)
        self.page_layout = []
        self.page_photos = {}
        self.page_render_job = None
        def scroll_updated(first, last):
            sy.set(first, last)
            if self.page_render_job is None:
                self.page_render_job = self.root.after_idle(self.update_visible_pages)
        self.canvas.configure(yscrollcommand=scroll_updated, xscrollcommand=sx.set)
        sy.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        sx.pack(fill='x')
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.canvas.bind('<Button-3>', self.context_menu)
        self.canvas.bind('<Double-Button-1>', self.double_click)
        self.canvas.bind('<Triple-Button-1>', self.triple_click)
        self.canvas.bind('<MouseWheel>', self.mouse_wheel)
        self.canvas.bind('<Shift-MouseWheel>', self.horizontal_wheel)
        self.canvas.bind('<Control-MouseWheel>', self.zoom_wheel)
        self.root.bind('<KeyPress-space>', self.begin_space_pan)
        self.root.bind('<KeyRelease-space>', self.end_space_pan)
        self.canvas.bind('<ButtonPress-2>', lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind('<B2-Motion>', lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind('<Configure>', self.resized)
        self.resize_job = None
        self.root.after_idle(self.show_empty_workspace)
        self.enable_pdf_drop()
        self.root.bind('<Control-Shift-Z>', lambda event: self.shortcut(event, self.redo))
        for key, action in [('z', self.undo), ('y', self.redo), ('o', self.open), ('s', self.save), ('c', self.copy_area), ('x', self.cut_area), ('v', self.paste_area)]:
            self.root.bind('<Control-'+key+'>', lambda event, fn=action: self.shortcut(event, fn))
        for event, action in [('<Control-Shift-S>', self.save_as), ('<Control-p>', self.print_pdf), ('<Control-plus>', lambda:self.zoom(1.1)), ('<Control-equal>', lambda:self.zoom(1.1)), ('<Control-minus>', lambda:self.zoom(1/1.1)), ('<Control-0>', self.fit_page), ('<Prior>', lambda:self.turn(-1)), ('<Next>', lambda:self.turn(1)), ('<Left>', lambda:self.canvas.xview_scroll(-3,'units')), ('<Right>', lambda:self.canvas.xview_scroll(3,'units')), ('<Up>', lambda:self.canvas.yview_scroll(-3,'units')), ('<Down>', lambda:self.canvas.yview_scroll(3,'units'))]:
            self.root.bind(event, lambda e, fn=action: self.shortcut(e, fn))
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.bind('<Delete>', lambda event: self.shortcut(event, self.delete_selected))
        self.root.bind('<BackSpace>', lambda event: self.shortcut(event, self.delete_selected))
        self.root.bind('<Control-w>', lambda event: self.shortcut(event, self.close_tab))
        self.load_assets()
        self.remote_paths = None
        # Every secondary window (dialogs, pickers) opens centred on the main one.
        self.root.bind_class('Toplevel', '<Map>', self.on_dialog_map, add='+')
        if theme.is_dark():
            theme.restyle_tree(self.root)
        if self.prefs.get('theme') == 'system':
            self.root.after(3000, self.watch_system_theme)

    def enable_pdf_drop(self):
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
            TkinterDnD._require(self.root)
            self.canvas.drop_target_register(DND_FILES)
            self.canvas.dnd_bind('<<Drop>>', self.on_pdf_drop)
        except (ImportError, RuntimeError, tk.TclError) as exc:
            self.status.config(text='文件拖放暂不可用，可使用“打开”选择 PDF：'+str(exc))

    def on_pdf_drop(self, event):
        try:
            paths = list(self.root.tk.splitlist(event.data))
        except tk.TclError:
            messagebox.showerror('拖入文件失败', '无法读取拖入的文件路径。', parent=self.root)
            return 'refuse_drop'
        self.root.after_idle(lambda:self.open_dropped_pdfs(paths))
        return 'copy'

    def open_dropped_pdfs(self, paths):
        if self.inline_editor and not self.apply_inline(): return
        valid = [path for path in paths if Path(path).suffix.lower() == '.pdf' and Path(path).is_file()]
        ignored = [path for path in paths if path not in valid]
        if ignored:
            messagebox.showinfo('拖入文件', f'已跳过 {len(ignored)} 个不是有效 PDF 的项目。', parent=self.root)
        opened = []
        for path in valid:
            self.open_path(path)
            if self.doc and os.path.normcase(os.path.abspath(self.path)) == os.path.normcase(os.path.abspath(path)):
                opened.append(path)
        if opened:
            self.status.config(text=f'已打开 {len(opened)} 个 PDF；需要打印时请点击“打印”。')

    def toggle_assets(self):
        if self.assets_panel.winfo_manager():
            self.assets_panel.pack_forget()
            self.assets_splitter.pack_forget()
        else:
            self.assets_panel.pack(side='right', fill='y', before=self.page_scrollbar)
            self.assets_splitter.pack(side='right', fill='y', before=self.page_scrollbar)

    def start_assets_resize(self, event):
        self.assets_resize_state = (event.x_root, self.assets_panel.winfo_width())

    def drag_assets_resize(self, event):
        if not self.assets_resize_state: return
        start_x, start_width = self.assets_resize_state
        width = max(170, min(560, start_width - (event.x_root - start_x)))
        self.assets_panel.configure(width=width)
        # Re-render the preview at the new width instead of leaving a stale image.
        job = getattr(self, '_assets_preview_job', None)
        if job:
            try: self.root.after_cancel(job)
            except tk.TclError: pass
        self._assets_preview_job = self.root.after(120, self.show_asset_preview)

    def load_assets(self):
        try:
            self.asset_db = sqlite3.connect(str(BASE / '素材库.sqlite3'))
            self.asset_db.execute('CREATE TABLE IF NOT EXISTS assets (id INTEGER PRIMARY KEY, name TEXT NOT NULL, pdf BLOB NOT NULL, meta TEXT NOT NULL)')
            self.asset_db.commit()
            self.refresh_assets()
        except Exception as exc:
            self.asset_db = None
            self.status.config(text='素材栏无法打开：'+str(exc))

    def refresh_assets(self):
        if not self.asset_db: return
        self.assets = self.asset_db.execute('SELECT id,name,pdf,meta FROM assets ORDER BY id DESC').fetchall()
        self.asset_count.set(f'{len(self.assets)} 项')
        self.asset_list.delete(0, 'end')
        for _, name, _, _ in self.assets: self.asset_list.insert('end', name)
        self.asset_preview.delete('all')
        self.asset_preview.create_text(95,75,text='选择素材可预览\n可拖到 PDF 中',fill='#637189',justify='center')
        self.asset_preview.config(scrollregion=(0,0,190,1))
        self.asset_preview_photo = None
        self.asset_preview_id = None

    def show_asset_preview(self, event=None):
        chosen = self.asset_list.curselection()
        if not chosen: return
        try:
            asset_id, _, data, raw = self.assets[chosen[0]]
            meta = json.loads(raw)
            if self.asset_preview_id != asset_id:
                self.asset_preview_id = asset_id
                # Always start at "whole asset visible"; the + button zooms in.
                self.asset_preview_zoom = 1.0
            if meta.get('box'):
                doc = fitz.open()
                width, height = meta['size']
                page = doc.new_page(width=width, height=height)
                box = meta['box']
                contents = (box['text'], [text_styles.Style(**key) for key in box['keys']], box['step'])
                geometry = self.asset_geometry(meta.get('geometry'))
                self.write_clipboard_text(page, fitz.Rect(0,0,width,height), contents, geometry)
            else:
                doc = fitz.open(stream=data, filetype='pdf')
            with doc:
                page = doc[0]
                view_width = self.asset_preview.winfo_width()
                view_height = self.asset_preview.winfo_height()
                view_width = view_width if view_width > 30 else 190
                view_height = view_height if view_height > 30 else 160
                factor = min((view_width-8)/max(page.rect.width,1), (view_height-8)/max(page.rect.height,1), 4)
                factor = min(factor*self.asset_preview_zoom, 2400/max(page.rect.width,page.rect.height,1))
                pix = page.get_pixmap(matrix=fitz.Matrix(factor,factor), alpha=False)
                self.asset_preview_photo = ImageTk.PhotoImage(Image.open(io.BytesIO(pix.tobytes('png'))))
            width, height = self.asset_preview_photo.width(), self.asset_preview_photo.height()
            x, y = max(0,(view_width-width)/2), max(0,(view_height-height)/2)
            self.asset_preview.delete('all')
            self.asset_preview.create_image(x,y,image=self.asset_preview_photo,anchor='nw')
            self.asset_preview.configure(scrollregion=(0,0,max(view_width,width),max(view_height,height)))
            self.asset_preview.xview_moveto(0)
            self.asset_preview.yview_moveto(0)
        except Exception:
            self.asset_preview.delete('all')
            self.asset_preview.create_text(95,75,text='无法预览素材',fill='#637189')

    def zoom_asset_preview(self, factor):
        self.asset_preview_zoom = max(.5,min(5,self.asset_preview_zoom*factor))
        self.show_asset_preview()

    def fit_asset_preview(self):
        self.asset_preview_zoom = 1.0
        self.show_asset_preview()

    def asset_clipboard_data(self):
        seq = ctypes.windll.user32.GetClipboardSequenceNumber()
        if self.clipboard_pdf is not None and seq == self.clipboard_sequence:
            geometry = self.clipboard_box_geometry
            meta = {'size':list(self.clipboard_size), 'box':None, 'geometry':None}
            if self.clipboard_box:
                text, keys, step = self.clipboard_box
                meta['box'] = {'text':text, 'keys':[k._asdict() for k in keys], 'step':step}
                if geometry:
                    meta['geometry'] = {'box':list(geometry['box']), 'origin':list(geometry['origin']),
                                        'rotation':geometry['rotation'], 'bounds':list(geometry['bounds'])}
                name = '文字：'+ ' '.join(text.split())[:18]
            else:
                name = '图片' if self.selected_kind == '图片' else '图形 / 条码'
            return name, self.clipboard_pdf, meta
        try:
            image = ImageGrab.grabclipboard()
        except (OSError, ValueError):
            image = None
        if isinstance(image, list):
            paths = [Path(p) for p in image if Path(p).suffix.lower() in ('.png','.jpg','.jpeg','.bmp','.tif','.tiff','.webp','.gif')]
            if paths: image = Image.open(paths[0])
        if isinstance(image, Image.Image):
            if image.width*image.height > 40_000_000: raise ValueError('图片过大，请先缩小。')
            scale = min(1, 240/max(image.width,image.height))
            w,h = max(1,image.width*scale),max(1,image.height*scale)
            if image.mode not in ('1','L','LA','P','RGB','RGBA'):
                image = image.convert('RGBA' if 'A' in image.getbands() else 'RGB')
            raw = io.BytesIO(); image.save(raw,format='PNG')
            with fitz.open() as doc:
                doc.new_page(width=w,height=h).insert_image((0,0,w,h),stream=raw.getvalue())
                data = doc.tobytes(garbage=4,deflate=True)
            return '剪贴板图片', data, {'size':[w,h], 'box':None,'geometry':None}
        text = None
        try:
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                    text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            try: text = self.root.clipboard_get()
            except tk.TclError: text = None
        return self.text_asset_data(text)

    def text_asset_data(self, text):
        if not text or not text.strip(): raise ValueError('剪贴板没有可添加的文字或图片。')
        if len(text)>10000: raise ValueError('文字超过 10000 字，请分成多个素材。')
        size, w = 10, 200
        h = max(35, min(5000, (len(text)//24+text.count('\n')+2)*size*1.3))
        key = text_styles.add_style(size=size)
        with fitz.open() as doc:
            page = doc.new_page(width=w,height=h)
            added_text.write(page,(0,size),0,text,[key]*len(text),size*1.2,w,box=fitz.Rect(0,0,w,h))
            data = doc.tobytes(garbage=4,deflate=True)
        meta = {'size':[w,h], 'box':{'text':text,'keys':[key._asdict() for _ in text],'step':size*1.2},
                'geometry':{'box':[0,0,w,h],'origin':[0,size],'rotation':0,'bounds':[0,0,w,h]}}
        return '文字：'+' '.join(text.split())[:18], data, meta

    def asset_geometry(self, geom):
        return {'box':fitz.Rect(geom['box']), 'origin':fitz.Point(geom['origin']),
                'rotation':geom['rotation'], 'bounds':fitz.Rect(geom['bounds'])} if geom else None

    def write_clipboard_text(self, page, rect, contents, geometry, fit_selection=False):
        text, keys, step = contents
        if geometry:
            bounds = geometry['bounds']
            offset = (rect.tl+rect.br)/2 - (bounds.tl+bounds.br)/2
            box = geometry['box'] + (offset.x,offset.y,offset.x,offset.y)
            origin = geometry['origin'] + offset
            if fit_selection and abs(geometry['rotation'] % 360) < .01:
                origin = fitz.Point(rect.x0+geometry['origin'].x-geometry['box'].x0,
                                    rect.y0+geometry['origin'].y-geometry['box'].y0)
                box = fitz.Rect(rect)
            added_text.write(page, origin, geometry['rotation'], text, keys, step, box.width, box=box)
        else:
            size = max(k.size for k in keys)
            added_text.write(page, (rect.x0,rect.y0+size), 0, text, keys, step, rect.width, box=rect)

    def asset_context_menu(self, event):
        self.asset_list.focus_set()
        menu = theme.menu(self.root)
        menu.add_command(label='粘贴到素材栏    Ctrl+V', command=self.add_asset)
        menu.add_command(label='放入当前 PDF', command=self.paste_asset)
        menu.add_separator()
        menu.add_command(label='重命名', command=self.rename_asset)
        menu.add_command(label='删除', command=self.delete_asset)
        menu.add_command(label='清空素材栏', command=self.clear_assets)
        try: menu.tk_popup(event.x_root,event.y_root)
        finally: menu.grab_release()
        return 'break'

    def batch_replace_assets(self):
        """Replace the framed label on the page with every selected asset, one PDF each."""
        from batch_labels import replace_label
        chosen = self.asset_list.curselection()
        if not chosen:
            messagebox.showinfo('批量替换', '请先在素材列表选择要替换的素材（按住 Ctrl 多选）。', parent=self.root)
            return
        if not self.doc:
            messagebox.showinfo('批量替换', '请先打开要替换的 PDF。', parent=self.root)
            return
        target = self.get_batch_target()
        if target is None: return
        folder = filedialog.askdirectory(title='选择生成文件保存位置', parent=self.root)
        if not folder: return
        snapshot = self.doc.tobytes(garbage=0, deflate=True)
        page_index = self.page_index
        prepared = []
        for index in chosen:
            asset_id, name, data, raw = self.assets[index]
            try:
                prepared.append((name, replace_label(snapshot, page_index, target, data, fill_frame=True)))
            except Exception as exc:
                messagebox.showerror('批量替换失败', f'{name}：{exc}', parent=self.root)
                return
        folder_path = Path(folder)
        used = set()
        written = []
        for name, payload in prepared:
            base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(name))[:80].rstrip('. ') or '标签'
            candidate = f'{base}.pdf'
            number = 2
            while candidate.casefold() in used or (folder_path/candidate).exists():
                candidate = f'{base} ({number}).pdf'; number += 1
            used.add(candidate.casefold())
            destination = folder_path/candidate
            with destination.open('xb') as handle:
                handle.write(payload)
            written.append(destination.name)
            self.status.config(text=f'已生成 {len(written)} / {len(prepared)}：{destination.name}')
            self.root.update_idletasks()
        self.status.config(text=f'批量替换完成：{len(written)} 个 PDF 已保存到 {folder}')
        messagebox.showinfo('批量替换完成', f'已生成 {len(written)} 个 PDF：\n{folder}\n\n' + '\n'.join(written[:8]), parent=self.root)

    def read_label_rows(self, paths):
        """Read label PDFs into memory rows for one batch run (no asset-library write)."""
        rows = []
        for path in paths:
            with fitz.open(path) as doc:
                if doc.needs_pass or not len(doc):
                    raise ValueError(f'{Path(path).name} 无法读取或需要密码。')
                if len(rows) + len(doc) > 500:
                    raise ValueError('单次最多处理 500 页标签。')
                for i in range(len(doc)):
                    if doc[i].rotation:
                        raise ValueError(f'{Path(path).name} 第 {i+1} 页有旋转属性，请先调整页面方向。')
                    with fitz.open() as single:
                        single.insert_pdf(doc, from_page=i, to_page=i)
                        rect = single[0].rect
                        data = single.tobytes(garbage=4, deflate=True)
                    name = Path(path).stem + (f'_第{i+1}页' if len(doc) > 1 else '')
                    meta = {'size': [rect.width, rect.height], 'box': None, 'geometry': None, 'imported_label': True}
                    rows.append((None, name, data, json.dumps(meta, ensure_ascii=False)))
        return rows

    def import_label_pdfs(self, title='导入条码标签 PDF'):
        if not self.asset_db:
            messagebox.showerror('导入标签','素材库无法使用。',parent=self.root)
            return False
        paths = filedialog.askopenfilenames(title=title,filetypes=[('PDF 文件','*.pdf')],parent=self.root)
        if not paths: return False
        rows = []
        try:
            for path in paths:
                with fitz.open(path) as doc:
                    if doc.needs_pass or not len(doc): raise ValueError(f'{Path(path).name} 无法读取或需要密码。')
                    if len(rows)+len(doc) > 500: raise ValueError('单次最多导入 500 页标签。')
                    for i in range(len(doc)):
                        if doc[i].rotation: raise ValueError(f'{Path(path).name} 第 {i+1} 页有旋转属性，请先调整页面方向。')
                        with fitz.open() as single:
                            single.insert_pdf(doc,from_page=i,to_page=i)
                            rect = single[0].rect
                            data = single.tobytes(garbage=4,deflate=True)
                        name = Path(path).stem + (f'_第{i+1}页' if len(doc)>1 else '')
                        meta = {'size':[rect.width,rect.height],'box':None,'geometry':None,'imported_label':True}
                        rows.append((name,sqlite3.Binary(data),json.dumps(meta,ensure_ascii=False)))
            imported_ids = set()
            with self.asset_db:
                for row in rows:
                    cursor = self.asset_db.execute('INSERT INTO assets(name,pdf,meta) VALUES(?,?,?)',row)
                    imported_ids.add(cursor.lastrowid)
            self.batch_imported_ids = imported_ids
            self.refresh_assets()
            self.status.config(text=f'已导入 {len(rows)} 个标签；框选原标签后点击“批量替换”。')
            return True
        except Exception as exc:
            messagebox.showerror('导入标签失败',str(exc),parent=self.root)
            return False

    def start_batch_mode(self, mode):
        if mode not in ('single', 'multi', 'legacy'): return
        self.batch_mode = mode
        self.batch_waiting_for_selection = False
        self.batch_mode_label.set({'single':'批量替换 · 继续', 'multi':'多页条码 · 继续', 'legacy':'旧标签更新 · 继续'}[mode])
        self.batch_mode_bar.pack(side='right', padx=(8, 6), before=self.toolbar_tools_button)
        self.root.update_idletasks()
        self.adjust_batch_mode_position()
        self.continue_batch_mode()

    def adjust_batch_mode_position(self):
        """Show the "continue" control on the right, next to the menu it was opened from."""
        if not self.batch_mode: return
        self.batch_mode_bar.pack_forget()
        self.batch_mode_narrow_bar.pack_forget()
        if self.toolbar.winfo_width() >= 1000:
            self.batch_mode_bar.pack(side='left', padx=(14, 6))
        else:
            self.batch_mode_narrow_bar.pack(fill='x', before=self.tabbar)

    def continue_batch_mode(self):
        if not self.doc:
            messagebox.showinfo('批量处理', '请先打开完整产品标签 PDF，再选择原条码区域。', parent=self.root); return
        if self.batch_mode == 'single': self.batch_labels_dialog(choose_files=True)
        elif self.batch_mode == 'multi': self.multipage_labels_dialog()
        elif self.batch_mode == 'legacy': self.legacy_labels_dialog()

    def exit_batch_mode(self):
        self.batch_mode = None
        self.batch_waiting_for_selection = False
        self.batch_mode_bar.pack_forget()
        self.batch_mode_narrow_bar.pack_forget()
        self.status.config(text='已退出批量处理模式。')

    def get_batch_target(self):
        if self.inline_editor and not self.apply_inline(): return
        if not self.doc: return
        if self.selected_kind != '区域' or not self.selection:
            from batch_labels import detect_full_label_barcodes
            self.root.update_idletasks()
            if self.resize_job:
                self.root.after_cancel(self.resize_job)
                self.redraw_after_resize()
            try: detected = detect_full_label_barcodes(self.doc[self.page_index])
            except Exception: detected = []
            if len(detected) != 1:
                self.selection_type.set('框选区域')
                self.batch_waiting_for_selection = bool(self.batch_mode)
                messagebox.showinfo('批量替换','无法唯一确定原条码位置。已切换为框选区域，请完整框选原标签，完成后将自动继续。',parent=self.root)
                return
            target = fitz.Rect(detected[0])
            source_doc, source_page = self.doc, self.page_index
            self.selection_type.set('框选区域')
            self.selection = fitz.Rect(target)
            self.selected_kind = '区域'
            self.selected_object = None
            self.draw_selection(self.selection)
            self.root.update_idletasks()
            if not messagebox.askyesno('确认原标签位置','已自动定位原条码，蓝框显示将被替换的区域。\n\n请确认蓝框完整包含要替换的标签；若不准确，选择“否”后手动框选。',parent=self.root):
                self.selection = self.selected_kind = None
                self.canvas.delete('selection')
                self.batch_waiting_for_selection = bool(self.batch_mode)
                return
            if self.doc is not source_doc or self.page_index != source_page:
                messagebox.showinfo('批量替换', '当前页面已变化，请重新选择条码区域。', parent=self.root)
                return
            self.selection = fitz.Rect(target)
            self.selected_kind = '区域'
            self.draw_selection(self.selection)
        self.batch_waiting_for_selection = False
        return fitz.Rect(self.selection)

    def toggle_page_thumbnails(self):
        if self.thumbnail_panel.winfo_manager():
            self.thumbnail_panel.pack_forget()
            self.thumbnail_splitter.pack_forget()
        else:
            self.thumbnail_panel.pack(side='left', fill='y', before=self.canvas)
            self.thumbnail_splitter.pack(side='left', fill='y', before=self.canvas)
            self.refresh_thumbnails()

    def start_thumbnail_resize(self, event):
        self.thumbnail_resize_state = (event.x_root, self.thumbnail_panel.winfo_width())
        self.thumbnail_splitter.config(background='#7e9dbb')

    def drag_thumbnail_resize(self, event):
        if self.thumbnail_resize_state is None: return
        start_x, start_width = self.thumbnail_resize_state
        available = self.thumbnail_panel.master.winfo_width()
        right_width = self.assets_panel.winfo_width() if self.assets_panel.winfo_manager() else 0
        max_width = max(210, min(630, available-right_width-320))
        width = max(210, min(max_width, start_width + event.x_root-start_x))
        self.thumbnail_panel.configure(width=width)
        self.thumbnail_scale = width/210.0
        if self.thumbnail_resize_job is not None: self.root.after_cancel(self.thumbnail_resize_job)
        self.thumbnail_resize_job = self.root.after(70, self.apply_thumbnail_resize)

    def apply_thumbnail_resize(self):
        self.thumbnail_resize_job = None
        self.refresh_thumbnails()

    def finish_thumbnail_resize(self, event):
        if self.thumbnail_resize_state is None: return
        self.drag_thumbnail_resize(event)
        self.thumbnail_resize_state = None
        self.thumbnail_splitter.config(background='#a8bcd0')
        if self.thumbnail_resize_job is not None:
            self.root.after_cancel(self.thumbnail_resize_job)
            self.apply_thumbnail_resize()

    def show_empty_workspace(self):
        if self.doc: return
        canvas = self.canvas
        canvas.delete('empty-workspace')
        width, height = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        cx, cy = width/2, height/2
        canvas.create_rectangle(cx-34, cy-102, cx+34, cy-18, fill='#f9fbfd', outline='#d4e0ed', width=2, tags='empty-workspace')
        for offset in (0, 12, 24):
            canvas.create_line(cx-20, cy-72+offset, cx+20, cy-72+offset, fill='#bfd0e2', width=3, tags='empty-workspace')
        canvas.create_text(cx, cy+22, text='打开 PDF，开始编辑标签', fill='white', font=('Microsoft YaHei UI', 15, 'bold'), tags='empty-workspace')
        canvas.create_text(cx, cy+54, text='使用上方“打开”选择文件 · 支持多页预览、编辑和打印', fill='#d9e3ee', font=('Microsoft YaHei UI', 9), tags='empty-workspace')

    def refresh_thumbnails(self):
        canvas = self.thumbnail_canvas
        canvas.delete('all'); self.thumbnail_photos = {}
        count = len(self.doc) if self.doc else 0
        canvas.configure(scrollregion=(0, 0, 190*self.thumbnail_scale, max(1, count*160*self.thumbnail_scale)))
        if self.thumbnail_job is None:
            self.thumbnail_job = self.root.after_idle(self.render_visible_thumbnails)

    def render_visible_thumbnails(self):
        self.thumbnail_job = None
        if not self.doc or not self.thumbnail_panel.winfo_manager(): return
        canvas = self.thumbnail_canvas
        top = canvas.canvasy(0); bottom = top + max(1, canvas.winfo_height())
        unit = 160*self.thumbnail_scale
        first = max(0, int(top//unit)-1); last = min(len(self.doc), int(bottom//unit)+2)
        wanted = set(range(first, last))
        for index in list(self.thumbnail_photos):
            if index not in wanted:
                canvas.delete(f'thumb-{index}'); del self.thumbnail_photos[index]
        for index in range(first, last):
            if index in self.thumbnail_photos: continue
            page = self.doc[index]; rect = page.rect
            scale = min(116*self.thumbnail_scale/max(rect.width, 1), 117*self.thumbnail_scale/max(rect.height, 1))
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            photo = ImageTk.PhotoImage(Image.open(io.BytesIO(pix.tobytes('png'))))
            self.thumbnail_photos[index] = photo
            s = self.thumbnail_scale; cx, cy = 90*s, index*unit+72*s
            tags = (f'thumb-{index}',)
            canvas.create_rectangle(cx-pix.width/2-1, cy-pix.height/2-1, cx+pix.width/2+1, cy+pix.height/2+1, fill='white', outline='#d4dfeb', tags=tags)
            canvas.create_image(cx, cy, image=photo, tags=tags)
            canvas.create_text(cx, index*unit+149*s, text=str(index+1), fill='#42566c', tags=tags)
        self.highlight_thumbnail()

    def highlight_thumbnail(self):
        canvas = self.thumbnail_canvas
        canvas.delete('thumb-highlight')
        if self.doc and self.page_index in self.thumbnail_photos:
            i = self.page_index
            s = self.thumbnail_scale
            photo = self.thumbnail_photos[i]
            cx, cy = 90*s, i*160*s+72*s
            canvas.create_rectangle(cx-photo.width()/2-2, cy-photo.height()/2-2, cx+photo.width()/2+2, cy+photo.height()/2+2, outline='#0f6cbd', width=3, tags='thumb-highlight')

    def thumbnail_at(self, event):
        index = int(self.thumbnail_canvas.canvasy(event.y)//(160*self.thumbnail_scale))
        return index if self.doc and 0 <= index < len(self.doc) else None

    def thumbnail_click(self, event):
        index = self.thumbnail_at(event)
        if index is None: return
        if self.inline_editor and not self.apply_inline(): return
        self.thumbnail_canvas.focus_set()
        self.page_index = index; self.page_width = 0; self.show()

    def thumbnail_context_menu(self, event):
        index = self.thumbnail_at(event)
        if index is None: return
        if self.inline_editor and not self.apply_inline(): return
        self.page_index = index; self.page_width = 0; self.show()
        menu = theme.menu(self.root)
        insert = theme.menu(menu)
        insert.add_command(label='从 PDF 文件插入到此页之前…', command=lambda:self.insert_pdf_pages(index, True))
        insert.add_command(label='从 PDF 文件插入到此页之后…', command=lambda:self.insert_pdf_pages(index, False))
        insert.add_separator()
        insert.add_command(label='插入复制的页面到此页之前', state='normal' if self.thumbnail_clipboard else 'disabled', command=lambda:self.paste_thumbnail_page(True))
        insert.add_command(label='插入复制的页面到此页之后', state='normal' if self.thumbnail_clipboard else 'disabled', command=lambda:self.paste_thumbnail_page(False))
        menu.add_cascade(label='插入页面', menu=insert)
        menu.add_command(label='提取页面…', command=self.extract_thumbnail_page)
        menu.add_command(label='替换页面…', command=self.replace_thumbnail_page)
        menu.add_separator()
        menu.add_command(label='裁剪页面…', command=self.crop_thumbnail_page)
        rotation = theme.menu(menu)
        rotation.add_command(label='逆时针旋转 90°', command=lambda:self.rotate_thumbnail_page(-90))
        rotation.add_command(label='顺时针旋转 90°', command=lambda:self.rotate_thumbnail_page(90))
        menu.add_cascade(label='旋转页面', menu=rotation)
        menu.add_command(label='页面过渡（暂不支持）', state='disabled')
        menu.add_separator()
        menu.add_command(label='复制页面（软件内）  Ctrl+C', command=self.copy_thumbnail_page)
        if self.thumbnail_clipboard:
            menu.add_command(label='粘贴页面到此页之前', command=lambda:self.paste_thumbnail_page(True))
            menu.add_command(label='粘贴页面到此页之后  Ctrl+V', command=lambda:self.paste_thumbnail_page(False))
        else:
            menu.add_command(label='粘贴页面（先复制一页）', state='disabled')
        menu.add_command(label='删除页面…', command=self.delete_thumbnail_page)
        menu.add_command(label='上移此页', command=lambda:self.move_thumbnail_page(-1))
        menu.add_command(label='下移此页', command=lambda:self.move_thumbnail_page(1))
        menu.add_separator()
        menu.add_command(label='页面标签（暂不支持）', state='disabled')
        menu.add_command(label='打印页面…', command=self.print_pdf)
        menu.add_separator()
        menu.add_command(label='嵌入所有页面缩略图（暂不支持）', state='disabled')
        menu.add_command(label='删除嵌入的页面缩略图（暂不支持）', state='disabled')
        menu.add_separator()
        menu.add_command(label='缩小页面缩略图', command=lambda:self.zoom_thumbnails(1/1.2))
        menu.add_command(label='放大页面缩略图', command=lambda:self.zoom_thumbnails(1.2))
        menu.add_separator()
        menu.add_command(label='页面属性…', command=self.thumbnail_page_properties)
        try: menu.tk_popup(event.x_root, event.y_root)
        finally: menu.grab_release()

    def zoom_thumbnails(self, factor):
        available = self.thumbnail_panel.master.winfo_width()
        right_width = self.assets_panel.winfo_width() if self.assets_panel.winfo_manager() else 0
        max_scale = max(1, min(3, (available-right_width-320)/210))
        self.thumbnail_scale = max(.75, min(max_scale, self.thumbnail_scale*factor))
        self.thumbnail_panel.configure(width=max(210, round(210*self.thumbnail_scale)))
        self.refresh_thumbnails()

    def copy_thumbnail_page(self):
        if self.inline_editor and not self.apply_inline(): return
        if not self.doc: return
        try:
            with fitz.open() as copied:
                copied.insert_pdf(self.doc, from_page=self.page_index, to_page=self.page_index, links=True, annots=True, widgets=True)
                self.thumbnail_clipboard = copied.tobytes(garbage=3, deflate=True)
            self.status.config(text='已复制页面；在任意标签页的缩略图上右键即可“粘贴页面到此前/此后”，或按 Ctrl+V。')
        except Exception as exc:
            messagebox.showerror('复制页面失败', str(exc), parent=self.root)

    def paste_thumbnail_page(self, before):
        if not self.doc or not self.thumbnail_clipboard: return
        index = self.page_index if before else self.page_index+1
        with fitz.open(stream=self.thumbnail_clipboard, filetype='pdf') as copied:
            self.change_thumbnail_page(lambda doc:doc.insert_pdf(copied, start_at=index, links=True, annots=True, widgets=True), index)
        self.status.config(text='已粘贴复制的页面；也可以到其他标签页的缩略图上继续粘贴。')

    def crop_thumbnail_page(self):
        if self.inline_editor and not self.apply_inline(): return
        if not self.doc: return
        page = self.doc[self.page_index]
        if page.rotation:
            messagebox.showinfo('裁剪页面', '请先将此页面旋转回 0° 再裁剪。', parent=self.root); return
        index = self.page_index
        dialog = tk.Toplevel(self.root); dialog.title('裁剪页面'); dialog.transient(self.root)
        area = ttk.Frame(dialog, padding=16); area.pack(fill='both', expand=True)
        ttk.Label(area, text=f'裁剪第 {index+1} 页', font=('Microsoft YaHei UI', 11, 'bold')).pack(anchor='w')
        ttk.Label(area, text='设置从当前页面四边裁去的距离（毫米）。\n裁剪只改变显示和打印范围，不删除范围外的内容。', style='Hint.TLabel').pack(anchor='w', pady=(5, 10))
        fields = ttk.Frame(area); fields.pack(fill='x')
        values = []
        for row, label in enumerate(('上', '下', '左', '右')):
            ttk.Label(fields, text=label).grid(row=row, column=0, padx=(0, 10), pady=3, sticky='w')
            value = tk.StringVar(value='0'); values.append(value)
            ttk.Entry(fields, textvariable=value, width=12).grid(row=row, column=1, pady=3)
            ttk.Label(fields, text='mm').grid(row=row, column=2, padx=5)
        def apply():
            try:
                top, bottom, left, right = [float(v.get())*72/25.4 for v in values]
                if any(not math.isfinite(n) or n < 0 for n in (top,bottom,left,right)): raise ValueError('请输入大于或等于 0 的数字。')
                box = fitz.Rect(self.doc[index].cropbox)
                box = fitz.Rect(box.x0+left, box.y0+top, box.x1-right, box.y1-bottom)
                if box.is_empty or box.width < 1 or box.height < 1: raise ValueError('裁剪后页面尺寸太小，请调整数值。')
                if self.change_thumbnail_page(lambda doc:doc[index].set_cropbox(box), index): dialog.destroy()
            except ValueError as exc:
                messagebox.showerror('裁剪页面', str(exc), parent=dialog)
        row = ttk.Frame(area); row.pack(fill='x', pady=(12, 0))
        ttk.Button(row, text='取消', command=dialog.destroy).pack(side='right')
        ttk.Button(row, text='裁剪', command=apply).pack(side='right', padx=8)
        dialog.grab_set()

    def change_thumbnail_page(self, operation, target_index=None):
        if self.inline_editor and not self.apply_inline(): return False
        if not self.doc: return False
        original = self.doc.tobytes(garbage=0, deflate=True)
        try:
            with fitz.open(stream=original, filetype='pdf') as updated:
                operation(updated)
                result = updated.tobytes(garbage=0, deflate=True)
            replacement = fitz.open(stream=result, filetype='pdf')
            old = self.doc; self.doc = replacement; old.close()
            self.undo_data.append((original, self.dirty, self.page_index))
            self.undo_data = self.undo_data[-10:]; self.redo_data.clear(); self.dirty = True
            if target_index is not None:
                self.page_index = max(0, min(target_index, len(self.doc)-1))
            self.page_width = 0; self.show()
            return True
        except Exception as exc:
            messagebox.showerror('页面操作失败', str(exc), parent=self.root)
            return False

    def delete_thumbnail_page(self):
        if not self.doc: return
        if len(self.doc) <= 1:
            messagebox.showinfo('删除页面', 'PDF 至少需要保留一页。', parent=self.root); return
        index = self.page_index
        if not messagebox.askyesno('确认删除页面', f'删除第 {index+1} 页？\n\n保存前可以使用撤销恢复。', parent=self.root): return
        self.change_thumbnail_page(lambda doc:doc.delete_page(index), min(index, len(self.doc)-2))

    def rotate_thumbnail_page(self, angle):
        if not self.doc: return
        index = self.page_index
        self.change_thumbnail_page(lambda doc:doc[index].set_rotation((doc[index].rotation+angle)%360), index)

    def move_thumbnail_page(self, direction):
        if not self.doc: return
        index = self.page_index; dest = index+direction
        if not 0 <= dest < len(self.doc): return
        target = dest if direction < 0 else (-1 if dest+1 == len(self.doc) else dest+1)
        self.change_thumbnail_page(lambda doc:doc.move_page(index, target), dest)

    def extract_thumbnail_page(self):
        if self.inline_editor and not self.apply_inline(): return
        if not self.doc: return
        index = self.page_index
        path = filedialog.asksaveasfilename(title='提取页面到新 PDF', initialfile=f'{Path(self.path).stem}_第{index+1}页.pdf',
                                            defaultextension='.pdf', filetypes=[('PDF 文件','*.pdf')], parent=self.root)
        if not path: return
        dest = Path(path)
        if dest.resolve() == Path(self.path).resolve():
            messagebox.showerror('无法保存', '提取文件不能覆盖当前打开的 PDF。', parent=self.root); return
        tmp_path = None
        try:
            with fitz.open() as output:
                output.insert_pdf(self.doc, from_page=index, to_page=index, links=True, annots=True, widgets=True)
                with tempfile.NamedTemporaryFile(suffix='.pdf', prefix='.pdfextract-', dir=str(dest.parent), delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                output.save(str(tmp_path), garbage=3, deflate=True)
            os.replace(tmp_path, dest); tmp_path = None
            messagebox.showinfo('提取完成', f'第 {index+1} 页已保存到：\n{dest}', parent=self.root)
        except Exception as exc:
            messagebox.showerror('提取页面失败', str(exc), parent=self.root)
        finally:
            if tmp_path is not None:
                try: tmp_path.unlink(missing_ok=True)
                except OSError: pass

    def replace_thumbnail_page(self):
        if self.inline_editor and not self.apply_inline(): return
        if not self.doc: return
        index = self.page_index
        path = filedialog.askopenfilename(title='选择用于替换的 PDF', filetypes=[('PDF 文件','*.pdf')], parent=self.root)
        if not path: return
        try:
            with fitz.open(path) as source:
                if source.needs_pass or not len(source): raise ValueError('文件需要密码或没有页面。')
                count = len(source)
                if not messagebox.askyesno('确认替换页面', f'将第 {index+1} 页替换为“{Path(path).name}”的全部 {count} 页？\n\n可以使用撤销恢复。', parent=self.root): return
                def replace(doc):
                    doc.delete_page(index)
                    doc.insert_pdf(source, start_at=index, links=True, annots=True, widgets=True)
                self.change_thumbnail_page(replace, index)
        except Exception as exc:
            messagebox.showerror('替换页面失败', str(exc), parent=self.root)

    def thumbnail_page_properties(self):
        if not self.doc: return
        page = self.doc[self.page_index]; rect = page.rect
        messagebox.showinfo('页面属性', f'第 {self.page_index+1} 页 / 共 {len(self.doc)} 页\n\n宽：{rect.width*25.4/72:.2f} mm\n高：{rect.height*25.4/72:.2f} mm\n旋转：{page.rotation}°', parent=self.root)

    def insert_pdf_pages(self, index, before):
        if self.inline_editor and not self.apply_inline(): return
        if not self.doc:
            messagebox.showinfo('插入 PDF 页面', '请先打开要插入页面的目标 PDF。', parent=self.root); return
        if not 0 <= index < len(self.doc): return
        path = filedialog.askopenfilename(title='选择要插入的 PDF', filetypes=[('PDF 文件', '*.pdf')], parent=self.root)
        if not path: return
        try:
            with fitz.open(path) as source:
                if source.needs_pass or not len(source): raise ValueError('文件需要密码或没有页面。')
                count = len(source)
                position = index if before else index+1
                direction = '之前' if before else '之后'
                if not messagebox.askyesno('确认插入', f'将“{Path(path).name}”的全部 {count} 页插入到第 {index+1} 页{direction}。\n\n是否继续？', parent=self.root): return
                original = self.doc.tobytes(garbage=0, deflate=True)
                with fitz.open(stream=original, filetype='pdf') as updated:
                    updated.insert_pdf(source, start_at=position, links=True, annots=True, widgets=True)
                    new_data = updated.tobytes(garbage=0, deflate=True)
            replacement = fitz.open(stream=new_data, filetype='pdf')
            old = self.doc; self.doc = replacement; old.close()
            self.commit(original, self.dirty)
            self.page_index = position; self.page_width = 0; self.show()
            self.status.config(text=f'已插入 {count} 页；可继续编辑，保存修改后写入文件。')
        except Exception as exc:
            messagebox.showerror('插入 PDF 失败', str(exc), parent=self.root)

    def merge_pdf_dialog(self):
        if self.inline_editor and not self.apply_inline(): return
        self.store_tab()
        dialog = tk.Toplevel(self.root); dialog.title('合并 PDF'); dialog.transient(self.root)
        dialog.geometry('820x590'); dialog.minsize(620, 440)
        self.root.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width()-820)//2
        y = self.root.winfo_rooty() + (self.root.winfo_height()-590)//2
        dialog.geometry(f'820x590{max(0, x):+d}{max(0, y):+d}')
        content = ttk.Frame(dialog, padding=16); content.pack(fill='both', expand=True)
        header = ttk.Frame(content); header.pack(fill='x')
        ttk.Label(header, text='合并 PDF', font=('Microsoft YaHei UI', 15, 'bold')).pack(side='left')
        ttk.Label(header, text='将多个文件合并为一个多页 PDF', style='Hint.TLabel').pack(side='left', padx=12)
        buttons = ttk.Frame(content); buttons.pack(fill='x', pady=(14, 10))
        body = ttk.Frame(content); body.pack(fill='both', expand=True)
        empty = ttk.Frame(body)
        empty.place(relx=.5, rely=.48, anchor='center')
        icon = tk.Canvas(empty, width=90, height=80, highlightthickness=0, background='#f4f6f9')
        icon.pack(pady=(0, 16))
        for x, y in ((12, 20), (35, 5), (57, 24)):
            icon.create_rectangle(x, y, x+25, y+40, fill='white', outline='#56708e', width=2)
            icon.create_line(x+6, y+17, x+19, y+17, fill='#8ba1bb', width=2)
            icon.create_line(x+6, y+24, x+19, y+24, fill='#8ba1bb', width=2)
        ttk.Label(empty, text='将 PDF 文件合并到一起', font=('Microsoft YaHei UI', 13, 'bold')).pack(pady=(0, 7))
        ttk.Label(empty, text='从电脑添加文件，或选择当前已打开的 PDF。', style='Hint.TLabel').pack(pady=(0, 17))
        frame = ttk.Frame(body)
        scroll = SlimScrollbar(frame, orient='vertical'); scroll.pack(side='right', fill='y')
        listing = tk.Listbox(frame, selectmode='extended', exportselection=False, width=75, height=10, yscrollcommand=scroll.set,
                             background='white', foreground='#253449', selectbackground='#0f6cbd', relief='flat', borderwidth=8,
                             font=('Microsoft YaHei UI', 10), activestyle='none')
        listing.pack(side='left', fill='both', expand=True); scroll.config(command=listing.yview)
        files = []
        status = ttk.Label(content, text='尚未添加文件', style='Hint.TLabel')
        def refresh(indices=()):
            listing.delete(0, 'end')
            for i, (path, pages, data) in enumerate(files):
                source = '已打开的文件（含当前修改）' if data is not None else '电脑文件'
                listing.insert('end', f'{i+1}.  {Path(path).name}   ·   {pages} 页   ·   {source}')
            for i in indices: listing.selection_set(i)
            if files:
                empty.place_forget(); frame.pack(fill='both', expand=True)
            else:
                frame.pack_forget(); empty.place(relx=.5, rely=.48, anchor='center')
            status.config(text=f'共 {len(files)} 个文件，{sum(item[1] for item in files)} 页；按列表顺序合并。')
        def add_files():
            paths = filedialog.askopenfilenames(title='选择要合并的 PDF', filetypes=[('PDF 文件','*.pdf')], parent=dialog)
            if not paths: return
            errors = []
            for path in paths:
                try:
                    with fitz.open(path) as source:
                        if source.needs_pass: raise ValueError('文件需要密码')
                        if not len(source): raise ValueError('文件没有页面')
                        files.append((path, len(source), None))
                except Exception as exc:
                    errors.append(f'{Path(path).name}：{exc}')
            refresh()
            if errors: messagebox.showerror('部分文件未添加', '\n'.join(errors), parent=dialog)
        def add_open_files():
            if not self.tabs:
                messagebox.showinfo('添加已打开的文件', '当前没有打开的 PDF。', parent=dialog); return
            picker = tk.Toplevel(dialog); picker.title('选择已打开的文件'); picker.transient(dialog)
            picker.geometry('540x380'); picker.minsize(400, 260)
            box = ttk.Frame(picker, padding=16); box.pack(fill='both', expand=True)
            ttk.Label(box, text='选择要合并的已打开文件', font=('Microsoft YaHei UI', 11, 'bold')).pack(anchor='w')
            ttk.Label(box, text='将包含当前编辑内容，包括尚未保存的修改。', style='Hint.TLabel').pack(anchor='w', pady=(4, 8))
            choices = list(self.tabs.items())
            items = tk.Listbox(box, selectmode='extended', exportselection=False, height=10)
            items.pack(fill='both', expand=True)
            for tab, state in choices:
                items.insert('end', f"{Path(state['path']).name}    {len(state['doc'])} 页" + ('    已修改' if state['dirty'] else ''))
            if self.active_tab in self.tabs:
                items.selection_set(next(i for i, (tab, _) in enumerate(choices) if tab == self.active_tab))
            def add_selected():
                selected = items.curselection()
                if not selected:
                    messagebox.showinfo('添加已打开的文件', '请先选择文件，可按 Ctrl 多选。', parent=picker); return
                try:
                    snapshots = []
                    for i in selected:
                        state = choices[i][1]; doc = state['doc']
                        snapshots.append((state['path'], len(doc), doc.tobytes(garbage=0, deflate=True)))
                    files.extend(snapshots)
                except Exception as exc:
                    messagebox.showerror('无法添加文件', str(exc), parent=picker); return
                refresh(); picker.destroy()
            ttk.Button(box, text='添加选中文件', command=add_selected).pack(anchor='e', pady=(10, 0))
            picker.grab_set(); picker.wait_window(); dialog.grab_set()
        ttk.Button(empty, text='添加文件', command=add_files).pack(fill='x', pady=(0, 8), ipady=4)
        ttk.Button(empty, text='添加已打开的文件', command=add_open_files).pack(fill='x', ipady=4)
        def remove_files():
            for i in reversed(listing.curselection()): del files[i]
            refresh()
        def move(direction):
            selected = set(listing.curselection())
            if not selected: return
            for i in sorted(selected, reverse=direction > 0):
                j = i + direction
                if 0 <= j < len(files) and j not in selected:
                    files[i], files[j] = files[j], files[i]
                    selected.remove(i); selected.add(j)
            refresh(sorted(selected))
        for label, action in [('添加文件', add_files), ('添加已打开的文件', add_open_files), ('移除', remove_files), ('上移', lambda:move(-1)), ('下移', lambda:move(1))]:
            ttk.Button(buttons, text=label, command=action).pack(side='left', padx=(0, 5))
        status.pack(anchor='w', pady=(8, 0))
        def generate():
            if not files:
                messagebox.showinfo('合并 PDF', '请先添加要合并的 PDF 文件。', parent=dialog); return
            destination = filedialog.asksaveasfilename(title='保存合并后的 PDF', defaultextension='.pdf', initialfile='合并后的文件.pdf', filetypes=[('PDF 文件','*.pdf')], parent=dialog)
            if not destination: return
            destination = Path(destination)
            if any(destination.resolve() == Path(path).resolve() for path, _, _ in files):
                messagebox.showerror('无法保存', '保存位置不能与任何源文件相同，请选择其他文件名。', parent=dialog); return
            if not messagebox.askyesno('确认合并', f'将按列表顺序合并 {len(files)} 个文件，共 {sum(item[1] for item in files)} 页。\n\n保存到：{destination}\n\n是否继续？', parent=dialog): return
            temp_path = None
            try:
                with fitz.open() as merged:
                    for path, expected_pages, snapshot in files:
                        with (fitz.open(stream=snapshot, filetype='pdf') if snapshot is not None else fitz.open(path)) as source:
                            if source.needs_pass or len(source) != expected_pages:
                                raise ValueError(f'{Path(path).name} 已更改或需要密码，请重新添加。')
                            merged.insert_pdf(source, links=True, annots=True, widgets=True)
                    with tempfile.NamedTemporaryFile(suffix='.pdf', prefix='.pdfmerge-', dir=str(destination.parent), delete=False) as tmp:
                        temp_path = Path(tmp.name)
                    merged.save(str(temp_path), garbage=3, deflate=True)
                os.replace(temp_path, destination)
                temp_path = None
                messagebox.showinfo('合并完成', f'已合并 {sum(item[1] for item in files)} 页：\n{destination}', parent=dialog)
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror('合并失败', str(exc), parent=dialog)
            finally:
                if temp_path is not None:
                    try: temp_path.unlink(missing_ok=True)
                    except OSError: pass
        ttk.Button(content, text='选择位置并合并', command=generate).pack(anchor='e', pady=(8, 0))
        dialog.grab_set()

    def legacy_labels_dialog(self):
        target = self.get_batch_target()
        if target is None: return
        paths = filedialog.askopenfilenames(title='选择旧版完整标签 PDF（可多选）', filetypes=[('PDF 文件','*.pdf')], parent=self.root)
        if not paths: return
        from batch_labels import detect_full_label_barcodes, extract_label_region, label_fields, format_label_names, replace_label
        records, skipped = [], []
        for path in paths:
            try:
                with fitz.open(path) as source:
                    if source.needs_pass or not len(source): raise ValueError('文件需要密码或没有页面')
                    if len(source) > 500: raise ValueError('单个文件最多处理 500 页')
                    for i, page in enumerate(source):
                        try:
                            candidates = detect_full_label_barcodes(page)
                            if len(candidates) != 1:
                                raise ValueError('未找到条码' if not candidates else f'找到 {len(candidates)} 个条码区域')
                            clip = extract_label_region(page, candidates[0])
                            with fitz.open(stream=clip, filetype='pdf') as label:
                                fields = label_fields(label[0])
                            fields.update({'原文件名':Path(path).stem, '页码':i+1,
                                           '来源':f'{Path(path).name} 第 {i+1} 页'})
                            records.append({'name':Path(path).name, 'page':i+1, 'data':clip, 'fields':fields})
                        except Exception as exc:
                            skipped.append(f'{Path(path).name} 第 {i+1} 页：{exc}')
            except Exception as exc:
                skipped.append(f'{Path(path).name}：{exc}')
        if not records:
            messagebox.showerror('没有可用的旧标签', '未能唯一识别条码区域。\n\n'+'\n'.join(skipped[:12]), parent=self.root); return
        snapshot = self.doc.tobytes(garbage=0, deflate=True)
        page_index = self.page_index
        dialog = tk.Toplevel(self.root); dialog.title('旧标签批量更新'); dialog.transient(self.root)
        dialog.minsize(760, 560)
        content = ttk.Frame(dialog, padding=14); content.pack(fill='both', expand=True)
        ttk.Label(content, text='旧标签批量更新', font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w')
        ttk.Label(content, text='将旧标签的整块条码放入当前新版模板；左侧选择生成项，右侧下拉选择预览。', style='Hint.TLabel').pack(anchor='w', pady=(3, 8))
        hint = ttk.Frame(content)
        hint.pack(fill='x', pady=(0, 6))
        ttk.Label(hint, text='使用说明', font=('Microsoft YaHei UI', 10, 'bold')).pack(anchor='w')
        ttk.Label(hint, text='1. 先框选当前模板中要放入新标签的位置（或自动识别条码区）。', style='Hint.TLabel', wraplength=700).pack(anchor='w')
        ttk.Label(hint, text='2. 选择旧标签 PDF（可多选），程序会提取整块条码。', style='Hint.TLabel', wraplength=700).pack(anchor='w')
        ttk.Label(hint, text='3. 右侧预览确认后点“选择位置并批量生成”；原 PDF 不修改。', style='Hint.TLabel', wraplength=700).pack(anchor='w')
        body = ttk.Frame(content); body.pack(fill='both', expand=True)
        left = ttk.Frame(body); left.pack(side='left', fill='both', expand=True)
        right = ttk.Frame(body, padding=(10, 0, 0, 0)); right.pack(side='right', fill='y')
        scroll = SlimScrollbar(left, orient='vertical'); scroll.pack(side='right', fill='y')
        listing = tk.Listbox(left, selectmode='extended', exportselection=False, width=42, height=14, yscrollcommand=scroll.set)
        listing.pack(fill='both', expand=True); scroll.config(command=listing.yview)
        for i, record in enumerate(records):
            listing.insert('end', f"{record['name']}  ·  第 {record['page']} 页")
            listing.selection_set(i)
        ttk.Label(right, text='合成预览', font=('Microsoft YaHei UI', 10, 'bold')).pack(anchor='w')
        preview_choice = ttk.Combobox(right, state='readonly', width=27,
                                     values=[f"{entry['name']} · 第 {entry['page']} 页" for entry in records])
        preview_choice.pack(fill='x', pady=(6, 0)); preview_choice.current(0)
        right.configure(width=340); right.pack_propagate(False)
        # Reserve the hint strip before the canvas claims all the space.
        ttk.Label(right, text='滚轮放大 · 拖动平移 · 双击复位', style='Hint.TLabel').pack(side='bottom', anchor='w', pady=(4, 0))
        preview = tk.Canvas(right, width=280, height=320, background='#e9eef5', highlightthickness=0, cursor='fleur')
        preview.pack(fill='both', expand=True, pady=(7, 2)); preview.image = None
        zoom = {'value': 1.0}
        fill_frame = tk.BooleanVar(value=True)
        def update_preview(event=None):
            preview.delete('all'); preview.image = None
            selected = preview_choice.current()
            if selected < 0: return
            width = max(1, preview.winfo_width()); height = max(1, preview.winfo_height())
            try:
                result = replace_label(snapshot, page_index, target, records[selected]['data'], fill_frame=fill_frame.get())
                with fitz.open(stream=result, filetype='pdf') as doc:
                    rect = doc[0].rect
                    scale = min((width-10)/rect.width, (height-10)/rect.height) * zoom['value']
                    pix = doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                    preview.image = ImageTk.PhotoImage(Image.open(io.BytesIO(pix.tobytes('png'))))
                image_w, image_h = preview.image.width(), preview.image.height()
                x = max(0, (width-image_w)/2); y = max(0, (height-image_h)/2)
                preview.create_image(x, y, anchor='nw', image=preview.image)
                preview.configure(scrollregion=(0, 0, max(width, image_w), max(height, image_h)))
                preview.xview_moveto(0); preview.yview_moveto(0)
            except Exception as exc:
                preview.create_text(width/2, height/2, text='无法预览：\n'+str(exc), fill='#a63030', width=max(120, width-20))
        def zoom_preview(event):
            if not event.delta: return 'break'
            zoom['value'] = max(.6, min(5.0, zoom['value']*(1.15 if event.delta > 0 else 1/1.15)))
            update_preview()
            return 'break'
        def reset_preview(event=None):
            zoom['value'] = 1.0; update_preview()
            return 'break'
        preview.bind('<MouseWheel>', zoom_preview)
        preview.bind('<Double-Button-1>', reset_preview)
        preview.bind('<Button-3>', reset_preview)
        preview.bind('<ButtonPress-1>', lambda e: preview.scan_mark(e.x, e.y))
        preview.bind('<B1-Motion>', lambda e: preview.scan_dragto(e.x, e.y, gain=1))
        preview_job = {'id': None}
        def schedule_preview(event=None):
            if preview_job['id']:
                try: dialog.after_cancel(preview_job['id'])
                except tk.TclError: pass
            preview_job['id'] = dialog.after(140, update_preview)
        preview.bind('<Configure>', schedule_preview, add='+')
        preview_choice.bind('<<ComboboxSelected>>', update_preview)
        actions = ttk.Frame(left); actions.pack(fill='x', pady=(6, 0))
        ttk.Button(actions, text='全选', command=lambda:listing.selection_set(0, 'end')).pack(side='left')
        ttk.Button(actions, text='清除选择', command=lambda:listing.selection_clear(0, 'end')).pack(side='left', padx=5)
        if skipped:
            ttk.Label(content, text=f'已跳过 {len(skipped)} 页，原因：'+('；'.join(skipped[:2])), style='Hint.TLabel', wraplength=850).pack(anchor='w', pady=(5, 0))
            ttk.Button(content, text='查看未识别页面', command=lambda:messagebox.showinfo('未处理的页面', '\n'.join(skipped[:50]), parent=dialog)).pack(anchor='w')
        naming = tk.StringVar(value='{原文件名}')
        row = ttk.Frame(content); row.pack(fill='x', pady=(8, 0))
        ttk.Label(row, text='文件命名').pack(side='left')
        ttk.Combobox(row, textvariable=naming, width=30, values=('{原文件名}', '{原文件名}_{页码}', '{名称}_{SKU}', '{SKU}')).pack(side='left', padx=8)
        ttk.Label(row, text='可用 {原文件名} {页码} {名称} {SKU}', style='Hint.TLabel').pack(side='left')
        ttk.Checkbutton(content, text='按新版框选宽高填满（比例不同时会拉伸）', variable=fill_frame, command=update_preview).pack(anchor='w', pady=(5, 0))
        status = ttk.Label(content, text='默认使用旧标签文件名；重名自动编号。', style='Hint.TLabel'); status.pack(anchor='w', pady=(4, 0))
        def generate():
            chosen = [records[i] for i in listing.curselection()]
            if not chosen:
                messagebox.showinfo('旧标签批量更新', '请至少选择一个旧标签。', parent=dialog); return
            legacy_records = [entry['fields'] for entry in chosen]
            try: names = format_label_names(naming.get(), legacy_records)
            except ValueError as exc:
                if not messagebox.askyesno('命名规则', f'{exc}\n\n改用“原文件名”命名？', parent=dialog):
                    return
                names = format_label_names('{原文件名}', legacy_records)
            folder = filedialog.askdirectory(title='选择新标签保存位置', parent=dialog)
            if not folder: return
            outputs = [Path(folder)/name for name in names]
            exists = [path.name for path in outputs if path.exists()]
            if exists:
                messagebox.showerror('文件已存在', '不会覆盖已有文件：\n'+'\n'.join(exists[:8])+'\n请选择其他文件夹。', parent=dialog); return
            if not messagebox.askyesno('确认生成', f'将生成 {len(chosen)} 个独立 PDF 到：\n{folder}\n\n文件名示例：{names[0]}\n请先检查右侧预览。是否继续？', parent=dialog): return
            done = []
            try:
                for i, (record, dest) in enumerate(zip(chosen, outputs)):
                    status.config(text=f'正在生成 {i+1} / {len(chosen)}：{dest.name}'); dialog.update_idletasks()
                    data = replace_label(snapshot, page_index, target, record['data'], fill_frame=fill_frame.get())
                    created = False
                    try:
                        with dest.open('xb') as file:
                            created = True; file.write(data)
                    except Exception:
                        if created:
                            try: dest.unlink()
                            except OSError: pass
                        raise
                    done.append(dest)
                messagebox.showinfo('生成完成', f'已生成 {len(done)} 个 PDF：\n{folder}', parent=dialog)
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror('生成中止', f'已生成 {len(done)} 个文件，其余未完成。\n{exc}', parent=dialog)
        footer = ttk.Frame(content); footer.pack(side='bottom', fill='x', pady=(10, 0))
        ttk.Button(footer, text='选择位置并批量生成', command=generate).pack(side='right')
        dialog.minsize(760, 560)
        dialog.update_idletasks()
        dialog.geometry(f'{min(max(dialog.winfo_reqwidth(), 820), self.root.winfo_screenwidth()-80)}x{min(max(dialog.winfo_reqheight(), 600), self.root.winfo_screenheight()-120)}')
        dialog.after_idle(update_preview); dialog.grab_set()

    def multipage_labels_dialog(self):
        target = self.get_batch_target()
        if target is None: return
        path = filedialog.askopenfilename(title='选择包含多个条码页的 PDF',filetypes=[('PDF 文件','*.pdf')],parent=self.root)
        if not path: return
        try:
            source_data = Path(path).read_bytes()
            from batch_labels import inspect_multipage_barcodes, format_label_names, replace_label
            with fitz.open(stream=source_data,filetype='pdf') as source:
                if source.needs_pass or not len(source): raise ValueError('条码 PDF 无法读取或需要密码。')
                if len(source)>500: raise ValueError('单次最多处理 500 页。')
                records = inspect_multipage_barcodes(source)
        except Exception as exc:
            messagebox.showerror('读取多页条码失败',str(exc),parent=self.root)
            return
        snapshot = self.doc.tobytes(garbage=0,deflate=True)
        page_index = self.page_index
        dialog = tk.Toplevel(self.root); dialog.title('多页条码批量替换'); dialog.transient(self.root)
        dialog.geometry('860x640'); dialog.minsize(760, 560)
        content = ttk.Frame(dialog,padding=14); content.pack(fill='both',expand=True)
        ttk.Label(content,text=f'条码文件：{Path(path).name}').pack(anchor='w')
        ttk.Label(content,text='已预选识别到的产品条码页，提示页未选；可手动调整。',style='Hint.TLabel').pack(anchor='w',pady=(3,6))
        hint = ttk.Frame(content)
        hint.pack(fill='x', pady=(0, 6))
        ttk.Label(hint, text='使用说明', font=('Microsoft YaHei UI', 10, 'bold')).pack(anchor='w')
        ttk.Label(hint, text='1. 选择一个含多页条码的 PDF（例如整本产品条码页）。', style='Hint.TLabel', wraplength=700).pack(anchor='w')
        ttk.Label(hint, text='2. 程序会预选识别到的条码页，可手动增减。', style='Hint.TLabel', wraplength=700).pack(anchor='w')
        ttk.Label(hint, text='3. 确认命名后点“选择文件夹并生成”；每页生成一个独立 PDF，原文件不修改。', style='Hint.TLabel', wraplength=700).pack(anchor='w')
        listframe = ttk.Frame(content);listframe.pack(fill='both',expand=True)
        scroll = SlimScrollbar(listframe,orient='vertical');scroll.pack(side='right',fill='y')
        listing = tk.Listbox(listframe,selectmode='extended',exportselection=False,width=70,height=12,yscrollcommand=scroll.set)
        listing.pack(side='left',fill='both',expand=True);scroll.config(command=listing.yview)
        for i,entry in enumerate(records):
            mark = '条码' if entry['product'] else '未识别 / 提示'
            listing.insert('end',f"第 {entry['page']+1} 页  |  {mark}  |  {entry['number'] or '无下方数字'}  |  {entry['title'][:48]}")
            if entry['product']: listing.selection_set(i)
        naming = tk.StringVar(value='{名称}_{SKU}')
        naming_row = ttk.Frame(content); naming_row.pack(fill='x',pady=(8,0))
        ttk.Label(naming_row,text='批量命名规则').pack(side='left')
        ttk.Combobox(naming_row,textvariable=naming,values=('{名称}_{SKU}','{SKU}','{原文件名}_{页码}'),width=30).pack(side='left',padx=8,fill='x',expand=True)
        ttk.Label(content,text='可使用 {名称}、{SKU}、{原文件名}、{页码}；名称取标签右上角。',style='Hint.TLabel').pack(anchor='w',pady=(3,0))
        fill_frame = tk.BooleanVar(value=True)
        ttk.Checkbutton(content,text='按原标签框选宽高填满（比例不同时会拉伸）',variable=fill_frame).pack(anchor='w',pady=(7,0))
        controls = ttk.Frame(content);controls.pack(fill='x',pady=(8,0))
        ttk.Button(controls,text='选择识别的条码',command=lambda:(listing.selection_clear(0,'end'),[listing.selection_set(i) for i,e in enumerate(records) if e['product']])).pack(side='left')
        ttk.Button(controls,text='清除选择',command=lambda:listing.selection_clear(0,'end')).pack(side='left',padx=4)
        status = ttk.Label(content,text='同名文件自动编号；原始 PDF 不会修改。',style='Hint.TLabel');status.pack(anchor='w',pady=(6,0))
        def generate():
            chosen = [records[i] for i in listing.curselection()]
            if not chosen:
                messagebox.showinfo('多页条码','请至少选择一个产品条码页。',parent=dialog);return
            multi_records = [{'名称':e['title'],'SKU':e['number'],
                '原文件名':Path(path).stem,'页码':e['page']+1,'来源':f"第 {e['page']+1} 页"} for e in chosen]
            try:
                names = format_label_names(naming.get(), multi_records)
            except ValueError as exc:
                if not messagebox.askyesno('命名规则', f'{exc}\n\n改用“原文件名_页码”命名？', parent=dialog):
                    return
                names = format_label_names('{原文件名}_{页码}', multi_records)
            folder = filedialog.askdirectory(title='选择输出文件夹',parent=dialog)
            if not folder:return
            paths = [Path(folder)/name for name in names]
            existing = [p.name for p in paths if p.exists()]
            if existing:
                messagebox.showerror('文件已存在','不会覆盖已有文件：\n'+'\n'.join(existing[:8])+'\n请选择其他文件夹。',parent=dialog);return
            method = '按框选宽高填满，可能拉伸' if fill_frame.get() else '等比例适配，可能留白'
            if not messagebox.askyesno('确认生成',f'将为 {len(chosen)} 个条码生成独立 PDF，到：\n{folder}\n\n命名示例：{names[0]}\n{method}。是否继续？',parent=dialog):return
            completed = []
            try:
                with fitz.open(stream=source_data,filetype='pdf') as source:
                    for i,(entry,outpath) in enumerate(zip(chosen,paths)):
                        status.config(text=f'正在生成 {i+1} / {len(chosen)}：{outpath.name}');dialog.update_idletasks()
                        with fitz.open() as part:
                            part.insert_pdf(source,from_page=entry['page'],to_page=entry['page'])
                            data = replace_label(snapshot,page_index,target,part.tobytes(garbage=4,deflate=True),fill_frame=fill_frame.get())
                        created_here = False
                        try:
                            with outpath.open('xb') as file:
                                created_here = True;file.write(data)
                        except Exception:
                            if created_here:
                                try:outpath.unlink()
                                except OSError:pass
                            raise
                        completed.append(outpath)
                messagebox.showinfo('生成完成',f'已生成 {len(completed)} 个 PDF：\n{folder}',parent=dialog)
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror('生成中止',f'已生成 {len(completed)} 个文件，剩余文件未完成。\n{exc}',parent=dialog)
        ttk.Button(controls,text='选择文件夹并生成',command=generate).pack(side='right')
        dialog.grab_set()

    def batch_labels_dialog(self, choose_files=False):
        target = self.get_batch_target()
        if target is None: return
        rows = [(entry[0], entry[1], entry[2], entry[3]) for entry in self.assets]
        snapshot = self.doc.tobytes(garbage=0, deflate=True)
        page_index = self.page_index
        dialog = tk.Toplevel(self.root); dialog.title('批量替换产品标签'); dialog.transient(self.root)
        dialog.geometry('800x660'); dialog.minsize(720, 580)
        content = ttk.Frame(dialog,padding=14); content.pack(fill='both',expand=True)
        ttk.Label(content,text='选择要生成的条码素材，每个素材生成一个 PDF。').pack(anchor='w')
        ttk.Label(content,text='替换区域以当前页面的框选范围为准，原 PDF 不会改动。',style='Hint.TLabel').pack(anchor='w',pady=(2,6))
        hint = ttk.Frame(content)
        hint.pack(fill='x', pady=(0, 6))
        ttk.Label(hint, text='使用说明', font=('Microsoft YaHei UI', 10, 'bold')).pack(anchor='w')
        ttk.Label(hint, text='1. 先在当前页框选或自动定位要替换的区域（旧标签所在位置）。', style='Hint.TLabel', wraplength=700).pack(anchor='w')
        ttk.Label(hint, text='2. 点“导入标签…”或直接选列表里的素材，可多选。', style='Hint.TLabel', wraplength=700).pack(anchor='w')
        ttk.Label(hint, text='3. 确认命名规则后点“选择文件夹并生成”；每个素材生成一个独立 PDF，原文件不修改。', style='Hint.TLabel', wraplength=700).pack(anchor='w')
        listframe = ttk.Frame(content); listframe.pack(fill='both',expand=True)
        scroll = SlimScrollbar(listframe, orient='vertical'); scroll.pack(side='right', fill='y')
        listing = tk.Listbox(listframe,selectmode='extended',exportselection=False,width=52,height=14,yscrollcommand=scroll.set)
        listing.pack(side='left',fill='both',expand=True); scroll.config(command=listing.yview)
        status = ttk.Label(content,text='同名文件自动编号；原始 PDF 不会修改。',style='Hint.TLabel')
        def refresh_listing():
            listing.delete(0, 'end')
            for _, name, _, _ in rows:
                listing.insert('end', name)
            if rows: listing.selection_set(0, 'end')
        refresh_listing()
        source_row = ttk.Frame(content); source_row.pack(fill='x', pady=(6,0))
        def import_more():
            paths = filedialog.askopenfilenames(title='选择要加入本次批量替换的条码 PDF',
                                                filetypes=[('PDF 文件', '*.pdf')], parent=dialog)
            if not paths: return
            try:
                added = self.read_label_rows(paths)
            except Exception as exc:
                messagebox.showerror('导入标签失败', str(exc), parent=dialog); return
            rows.extend(added); refresh_listing()
            status.config(text=f'已加入 {len(added)} 个标签，只用于本次批量替换，不会写进右侧素材栏。')
        def clear_labels():
            if not rows:
                messagebox.showinfo('清空标签', '本次批量替换的列表已经是空的。', parent=dialog); return
            if not messagebox.askyesno('清空标签', '清空本次批量替换的标签列表？（右侧素材栏不受影响）', parent=dialog): return
            rows.clear(); refresh_listing()
            status.config(text='已清空本次批量的标签列表。')
        ttk.Button(source_row, text='导入标签…', command=import_more).pack(side='left')
        ttk.Button(source_row, text='清空标签', command=clear_labels).pack(side='left', padx=6)
        ttk.Label(source_row, text='导入只影响这个列表，和右侧素材栏互不影响', style='Hint.TLabel').pack(side='left', padx=8)
        naming = tk.StringVar(value='{名称}_{SKU}')
        naming_row = ttk.Frame(content); naming_row.pack(fill='x',pady=(8,0))
        ttk.Label(naming_row,text='批量命名规则').pack(side='left')
        ttk.Combobox(naming_row,textvariable=naming,values=('{名称}_{SKU}','{SKU}','{原文件名}'),width=30).pack(side='left',padx=8,fill='x',expand=True)
        ttk.Label(content,text='可使用 {名称}、{SKU}、{原文件名}、{页码}；名称取标签右上角。',style='Hint.TLabel').pack(anchor='w',pady=(3,0))
        fill_frame = tk.BooleanVar(value=True)
        ttk.Checkbutton(content,text='按框选宽高填满（去除多余白边，可能改变宽高比例）',variable=fill_frame).pack(anchor='w',pady=(7,0))
        controls = ttk.Frame(content); controls.pack(fill='x',pady=(8,0))
        ttk.Button(controls,text='全选',command=lambda:listing.selection_set(0,'end')).pack(side='left')
        ttk.Button(controls,text='清除选择',command=lambda:listing.selection_clear(0,'end')).pack(side='left',padx=4)
        status.pack(anchor='w',pady=(6,0))
        def generate():
            selected = [rows[i] for i in listing.curselection()]

            if not selected:
                messagebox.showinfo('批量替换','请至少选择一个素材。',parent=dialog); return
            from batch_labels import label_fields, format_label_names, replace_label
            try:
                records = []
                for entry in selected:
                    with fitz.open(stream=bytes(entry[2]),filetype='pdf') as asset:
                        if asset.needs_pass or not len(asset): raise ValueError(f'{entry[1]}：无法读取 PDF。')
                        fields = label_fields(asset[0])
                    fields.update({'原文件名':Path(entry[1]).stem,'页码':1,'来源':entry[1]})
                    records.append(fields)
                names = format_label_names(naming.get(),records)
            except ValueError as exc:
                # Image-only labels often carry no 名称/SKU text; fall back to file names.
                if not messagebox.askyesno('命名规则', f'{exc}\n\n这些标签可能是图片，识别不到名称/SKU。改用“原文件名”命名？', parent=dialog):
                    return
                names = format_label_names('{原文件名}', records)
            except Exception as exc:
                messagebox.showerror('命名规则或识别结果有误',str(exc),parent=dialog);return
            folder = filedialog.askdirectory(title='选择输出文件夹',parent=dialog)
            if not folder: return
            paths = [Path(folder)/name for name in names]
            exists = [p.name for p in paths if p.exists()]
            if exists:
                messagebox.showerror('文件已存在','以下文件已存在，不会覆盖：\n'+'\n'.join(exists[:8])+'\n请选择其他文件夹。',parent=dialog); return
            placement = '按框选宽高填满，比例不一致时会拉伸，请打印后检查扫码。' if fill_frame.get() else '等比例适配框选区域，可能留白。'
            if not messagebox.askyesno('确认批量生成',f'将使用当前框选区域，生成 {len(selected)} 个 PDF 到：\n{folder}\n\n命名示例：{names[0]}\n每个文件含当前页面的一份标签；{placement}\n是否继续？',parent=dialog): return
            created = []
            try:
                for i, (entry,path) in enumerate(zip(selected,paths)):
                    status.config(text=f'正在生成 {i+1} / {len(selected)}：{path.name}')
                    dialog.update_idletasks()
                    data = replace_label(snapshot,page_index,target,bytes(entry[2]),fill_frame=fill_frame.get())
                    created_here = False
                    try:
                        with path.open('xb') as file:
                            created_here = True
                            file.write(data)
                    except Exception:
                        if created_here:
                            try: path.unlink()
                            except OSError: pass
                        raise
                    created.append(path)
                messagebox.showinfo('批量生成完成',f'已生成 {len(created)} 个 PDF：\n{folder}',parent=dialog)
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror('批量生成中止',f'已生成 {len(created)} 个文件；当前文件未完成。\n{exc}',parent=dialog)
        ttk.Button(controls,text='选择文件夹并生成',command=generate).pack(side='right')
        dialog.grab_set()

    def add_asset(self):
        if not self.asset_db:
            messagebox.showerror('素材栏', '素材库无法使用，请检查程序目录是否可写。')
            return
        try:
            name, data, meta = self.asset_clipboard_data()
            self.save_asset(name, data, meta)
            self.status.config(text='已添加到素材栏，双击素材可粘贴到当前 PDF。')
        except Exception as exc:
            messagebox.showerror('添加素材失败',str(exc))

    def save_asset(self, name, data, meta):
        if not self.asset_db: raise ValueError('素材库无法使用，请检查程序目录是否可写。')
        with self.asset_db:
            self.asset_db.execute('INSERT INTO assets(name,pdf,meta) VALUES(?,?,?)',
                                  (name,sqlite3.Binary(data),json.dumps(meta,ensure_ascii=False)))
        self.refresh_assets()
        self.asset_list.selection_set(0)
        self.show_asset_preview()

    def auto_add_copied_asset(self, data):
        try:
            self.save_asset(*data)
            if not self.assets_panel.winfo_manager(): self.toggle_assets()
            self.status.config(text='已复制并加入素材栏，可继续粘贴，或从素材栏再次使用。')
            return True
        except Exception as exc:
            self.status.config(text='已复制，但未能加入素材栏：'+str(exc))
            return False

    def capture_inline_copy(self, event):
        try: text = event.widget.get('sel.first', 'sel.last')
        except tk.TclError: return
        if not text.strip(): return
        try: self.auto_add_copied_asset(self.text_asset_data(text))
        except Exception as exc: self.status.config(text='文字复制到剪贴板，但未能加入素材栏：'+str(exc))

    def asset_drag_start(self, event):
        self.asset_drag_state = None
        # Zoomed-in preview: dragging moves the picture, it does not start a
        # drag-to-page, which keeps working at 100% and via double-click.
        if event.widget is self.asset_preview and self.asset_preview_zoom > 1.001:
            self.asset_panning = True
            self.asset_preview.scan_mark(event.x, event.y)
            return 'break'
        if event.widget is self.asset_list:
            index = self.asset_list.nearest(event.y)
            bbox = self.asset_list.bbox(index)
            if not bbox or not bbox[1] <= event.y < bbox[1]+bbox[3]: return
            self.asset_list.selection_clear(0, 'end')
            self.asset_list.selection_set(index)
            self.asset_list.focus_set()
            self.show_asset_preview()
        else:
            self.asset_list.focus_set()
            chosen = self.asset_list.curselection()
            if not chosen: return
            index = chosen[0]
        if 0 <= index < len(self.assets):
            self.asset_drag_state = {'id':self.assets[index][0], 'x':event.x_root, 'y':event.y_root,
                                     'moving':False, 'cursor':self.canvas.cget('cursor'),
                                     'size':json.loads(self.assets[index][3])['size']}

    def asset_drag_move(self, event):
        if getattr(self, 'asset_panning', False):
            self.asset_preview.scan_dragto(event.x, event.y, gain=1)
            return 'break'
        state = self.asset_drag_state
        if not state: return
        if not state['moving'] and math.hypot(event.x_root-state['x'],event.y_root-state['y']) >= 5:
            state['moving'] = True
            self.canvas.config(cursor='crosshair')
            self.status.config(text='拖到 PDF 页面后松开鼠标，即可放入素材。')
        if state['moving']:
            self.canvas.delete('asset-drag-preview')
            if self.doc and self.root.winfo_containing(event.x_root,event.y_root) is self.canvas:
                x = self.canvas.canvasx(event.x_root-self.canvas.winfo_rootx())
                y = self.canvas.canvasy(event.y_root-self.canvas.winfo_rooty())
                w,h = state['size'][0]*self.scale,state['size'][1]*self.scale
                self.canvas.create_rectangle(x-w/2,y-h/2,x+w/2,y+h/2,outline='#0f6cbd',width=2,dash=(5,3),tags='asset-drag-preview')

    def asset_drag_end(self, event):
        if getattr(self, 'asset_panning', False):
            self.asset_panning = False
            return 'break'
        state = self.asset_drag_state
        self.asset_drag_state = None
        if not state: return
        self.canvas.config(cursor=state['cursor'])
        self.canvas.delete('asset-drag-preview')
        if not state['moving']: return
        target = self.root.winfo_containing(event.x_root,event.y_root)
        if target is not self.canvas:
            self.status.config(text='请将素材拖到 PDF 页面区域。')
            return 'break'
        if not self.doc:
            messagebox.showinfo('素材栏', '请先打开目标 PDF。')
            return 'break'
        x = self.canvas.canvasx(event.x_root-self.canvas.winfo_rootx())
        y = self.canvas.canvasy(event.y_root-self.canvas.winfo_rooty())
        page = self.page_at_canvas_point(x, y)
        if page is None:
            self.status.config(text='请将素材拖到白色 PDF 页面内。'); return 'break'
        if self.inline_editor and not self.apply_inline(): return 'break'
        if page != self.page_index: self.activate_canvas_page(page)
        point = fitz.Point((x-self.origin_x)/self.scale,(y-self.origin_y)/self.scale)
        if not self.doc[self.page_index].rect.contains(point):
            self.status.config(text='请将素材拖到白色 PDF 页面内。')
            return 'break'
        self.paste_asset(asset_id=state['id'], drop_point=point)
        return 'break'

    def paste_asset(self, asset_id=None, drop_point=None):
        chosen = self.asset_list.curselection()
        index = next((i for i,asset in enumerate(self.assets) if asset[0] == asset_id), None) if asset_id is not None else (chosen[0] if chosen else None)
        if index is None:
            messagebox.showinfo('素材栏','请先选择一个素材。')
            return
        if not self.doc:
            messagebox.showinfo('素材栏','请先打开目标 PDF。')
            return
        if self.inline_editor and not self.apply_inline(): return
        try:
            _, _, data, raw = self.assets[index]
            meta = json.loads(raw)
            self.clipboard_pdf = bytes(data)
            self.clipboard_size = tuple(meta['size'])
            box = meta.get('box')
            self.clipboard_box = (box['text'],[text_styles.Style(**key) for key in box['keys']],box['step']) if box else None
            geom = meta.get('geometry')
            self.clipboard_box_geometry = self.asset_geometry(geom)
            self.clipboard_sequence = ctypes.windll.user32.GetClipboardSequenceNumber()
            page = self.doc[self.page_index].rect
            center = drop_point if drop_point is not None else (page.tl+page.br)/2
            self.paste_area(fitz.Point(center.x-self.clipboard_size[0]/2,center.y-self.clipboard_size[1]/2))
        except Exception as exc:
            messagebox.showerror('粘贴素材失败',str(exc))

    def delete_asset(self):
        chosen = self.asset_list.curselection()
        if not chosen or not self.asset_db: return
        asset = self.assets[chosen[0]]
        if not messagebox.askyesno('删除素材',f'确定从素材栏删除“{asset[1]}”吗？',parent=self.root): return
        self.asset_db.execute('DELETE FROM assets WHERE id=?',(asset[0],))
        self.asset_db.commit()
        self.refresh_assets()

    def clear_assets(self):
        if not self.asset_db: return
        count = len(self.assets)
        if not count:
            messagebox.showinfo('清空素材栏','素材栏已经是空的。',parent=self.root)
            return
        if not messagebox.askyesno('清空素材栏', f'确定删除素材栏中的全部 {count} 项素材吗？\n\n此操作无法撤销，不会删除 PDF 文件。', parent=self.root):
            return
        try:
            with self.asset_db:
                self.asset_db.execute('DELETE FROM assets')
            self.refresh_assets()
            self.status.config(text='素材栏已清空。')
        except sqlite3.Error as exc:
            messagebox.showerror('清空素材栏失败',str(exc),parent=self.root)

    def rename_asset(self):
        chosen = self.asset_list.curselection()
        if not chosen or not self.asset_db: return
        index = chosen[0]
        asset = self.assets[index]
        name = simpledialog.askstring('重命名素材', '请输入素材名称：', initialvalue=asset[1], parent=self.root)
        if name is None: return
        name = name.strip()
        if not name:
            messagebox.showinfo('重命名素材','名称不能为空。',parent=self.root)
            return
        self.asset_db.execute('UPDATE assets SET name=? WHERE id=?',(name[:100],asset[0]))
        self.asset_db.commit()
        self.refresh_assets()
        self.asset_list.selection_set(index)
        self.show_asset_preview()

    def discard(self):
        if self.inline_editor and not self.apply_inline(): return False
        return not self.dirty or messagebox.askyesno('未保存', '当前修改尚未保存，确定放弃修改吗？')

    def shortcut(self, event, action):
        widget = event.widget
        # Inside the inline editor every key belongs to the text widget (it has
        # its own undo stack); everywhere else Ctrl+Z / Ctrl+Y must undo the PDF.
        if self.inline_editor is not None and widget is self.inline_editor:
            return
        if isinstance(widget, (tk.Text, tk.Entry, ttk.Entry, ttk.Combobox)):
            if action == self.undo or action == self.redo:
                action()
                return 'break'
            return
        action()
        return 'break'

    OPEN_MODES = {'同一窗口，新标签页': 'same_window', '每次打开新窗口': 'new_window'}
    ZOOM_MODES = {'320%（标签常用）': 'percent', '实际大小 100%': 'actual', '适合页面': 'fit', '适合宽度': 'fit_width', '记住上次比例': 'last'}
    THEME_MODES = {'跟随系统': 'system', '浅色': 'light', '深色': 'dark'}

    def center_dialog(self, window):
        """Place a secondary window in the middle of the main window."""
        try:
            if not window.winfo_exists(): return
            window.update_idletasks()
            width, height = window.winfo_width(), window.winfo_height()
            if width <= 1 or height <= 1:
                width, height = window.winfo_reqwidth(), window.winfo_reqheight()
            x = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
            y = self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2
            x = max(0, min(x, window.winfo_screenwidth() - width))
            y = max(0, min(y, window.winfo_screenheight() - height))
            window.geometry(f'+{x}+{y}')
        except tk.TclError:
            pass

    def fit_dialog(self, window, min_width=0, min_height=0):
        """Never show a dialog smaller than its content: clipped buttons are worse
        than a slightly bigger window."""
        try:
            if not window.winfo_exists(): return
            window.update_idletasks()
            width = max(window.winfo_width(), window.winfo_reqwidth(), min_width)
            height = max(window.winfo_height(), window.winfo_reqheight(), min_height)
            width = min(width, window.winfo_screenwidth() - 60)
            height = min(height, window.winfo_screenheight() - 100)
            window.minsize(min(width, window.winfo_screenwidth()-60), min(height, window.winfo_screenheight()-100))
            window.geometry(f'{width}x{height}')
            self.center_dialog(window)
        except tk.TclError:
            pass

    def on_dialog_map(self, event):
        window = event.widget
        if not isinstance(window, tk.Toplevel) or getattr(window, '_centered', False): return
        window._centered = True
        self.root.after_idle(lambda: self.fit_dialog(window))

    def check_updates(self, parent=None, silent_if_current=False):
        """Ask GitHub for the latest release without blocking the UI."""
        import threading
        import updater
        repo = str(self.prefs.get('update_repo') or '').strip() or updater.DEFAULT_REPO
        window = parent or self.root
        self.status.config(text='正在检查更新…')

        def work():
            try:
                self._update_result = ('ok', updater.check(repo))
            except Exception as exc:
                self._update_result = ('error', str(exc))

        def poll():
            # Tk calls stay on the main thread; the worker only stores its result.
            result = getattr(self, '_update_result', None)
            if result is None:
                self.root.after(150, poll)
                return
            self._update_result = None
            if result[0] == 'ok':
                newer, release = result[1]
                self._update_done(newer, release, silent_if_current)
            else:
                self._update_failed(result[1], silent_if_current)

        self._update_result = None
        threading.Thread(target=work, daemon=True).start()
        self.root.after(150, poll)

    def _update_failed(self, message, silent_if_current):
        self.status.config(text='检查更新失败。')
        if silent_if_current:
            return
        messagebox.showinfo('检查更新', message, parent=self.root)

    def _update_done(self, newer, release, silent_if_current):
        import updater
        if not newer:
            self.status.config(text=f'已是最新版本 {updater.APP_VERSION}。')
            if not silent_if_current:
                messagebox.showinfo('检查更新', f'当前已是最新版本（{updater.APP_VERSION}）。', parent=self.root)
            return
        self.status.config(text=f'发现新版本 {release["version"]}。')
        notes = (release.get('notes') or '').strip()
        if len(notes) > 600:
            notes = notes[:600] + '…'
        asset = updater.installer_asset(release)
        text = f'发现新版本 {release["version"]}（当前 {updater.APP_VERSION}）。'
        if notes:
            text += '\n\n更新内容：\n' + notes
        if asset:
            text += f'\n\n安装包：{asset["name"]}（{asset["size"]/1048576:.1f} MB）'
        if messagebox.askyesno('发现新版本', text + '\n\n现在打开下载页面吗？', parent=self.root):
            import webbrowser
            webbrowser.open(asset['url'] if asset and asset.get('url') else release.get('page') or 'https://github.com')

    def set_default_pdf_app(self):
        """Register as a PDF handler, then let Windows ask the user to confirm."""
        if not getattr(sys, 'frozen', False):
            messagebox.showinfo('设为默认 PDF 应用', '请使用打包后的程序或安装版设置默认应用。', parent=self.root)
            return
        exe = Path(sys.executable)
        try:
            import pdf_association
            pdf_association.register(exe, exe.with_name('app.ico'))
        except Exception as exc:
            messagebox.showerror('设为默认 PDF 应用', f'写入文件关联失败：{exc}', parent=self.root)
            return
        messagebox.showinfo('设为默认 PDF 应用',
                            '已把本程序加入 PDF 的“打开方式”。\n\n'
                            'Windows 要求由你确认默认应用：接下来会打开「默认应用」设置，'
                            '请在 PDF 处选择「PDF 标签编辑器」，之后双击 PDF 就会用本程序打开。',
                            parent=self.root)
        pdf_association.open_default_apps()

    def open_settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title('设置')
        dialog.transient(self.root)
        dialog.configure(background=theme.c('bg'))
        dialog.withdraw()
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill='both', expand=True)
        current = {
            'open_mode': next((k for k, v in self.OPEN_MODES.items() if v == self.prefs.get('open_mode')), '同一窗口，新标签页'),
            'zoom': next((k for k, v in self.ZOOM_MODES.items() if v == self.prefs.get('default_zoom')), '320%（标签常用）'),
            'theme': next((k for k, v in self.THEME_MODES.items() if v == self.prefs.get('theme')), '跟随系统'),
        }
        open_mode = tk.StringVar(value=current['open_mode'])
        zoom_mode = tk.StringVar(value=current['zoom'])
        theme_mode = tk.StringVar(value=current['theme'])
        update_repo = tk.StringVar(value=str(self.prefs.get('update_repo') or ''))
        rows = [
            ('打开 PDF 时', open_mode, list(self.OPEN_MODES), '同一窗口时，双击多个 PDF 只保留一个窗口，后打开的进新标签页。'),
            ('打开时缩放', zoom_mode, list(self.ZOOM_MODES), '影响之后打开的每一份 PDF。'),
            ('界面主题', theme_mode, list(self.THEME_MODES), '跟随系统会随 Windows 的深色设置自动切换；PDF 页面本身始终是白色。'),
        ]
        for index, (label, variable, values, hint) in enumerate(rows):
            base = index * 2
            ttk.Label(frame, text=label).grid(row=base, column=0, sticky='w', pady=(10, 0))
            ttk.Combobox(frame, textvariable=variable, values=values, state='readonly', width=20).grid(
                row=base, column=1, sticky='w', padx=(14, 0), pady=(10, 0))
            ttk.Label(frame, text=hint, style='Hint.TLabel', wraplength=420).grid(
                row=base + 1, column=0, columnspan=2, sticky='w')

        ttk.Label(frame, text='更新仓库').grid(row=len(rows)*2, column=0, sticky='w', pady=(10, 0))
        ttk.Entry(frame, textvariable=update_repo, width=24).grid(
            row=len(rows)*2, column=1, sticky='w', padx=(14, 0), pady=(10, 0))
        ttk.Label(frame, text='填 GitHub 的“用户名/仓库名”，例如 someone/pdf-label-editor；用于检查更新。',
                  style='Hint.TLabel', wraplength=420).grid(
            row=len(rows)*2+1, column=0, columnspan=2, sticky='w')

        def check_updates_now():
            self.prefs['update_repo'] = update_repo.get().strip()
            settings.save(self.prefs)
            self.check_updates(parent=dialog)

        def save():
            self.prefs['open_mode'] = self.OPEN_MODES[open_mode.get()]
            self.prefs['update_repo'] = update_repo.get().strip()
            self.prefs['default_zoom'] = self.ZOOM_MODES[zoom_mode.get()]
            wanted = self.THEME_MODES[theme_mode.get()]
            theme_changed = wanted != self.prefs.get('theme')
            self.prefs['theme'] = wanted
            settings.save(self.prefs)
            if theme_changed:
                self.apply_theme(wanted)
            self.status.config(text='设置已保存。' + ('主题已切换。' if theme_changed else ''))
            dialog.destroy()

        buttons = ttk.Frame(frame)
        buttons.grid(row=len(rows) * 2 + 2, column=0, columnspan=2, sticky='e', pady=(18, 0))
        ttk.Button(buttons, text='保存', style='Primary.TButton', command=save).pack(side='right')
        ttk.Button(buttons, text='检查更新', command=check_updates_now).pack(side='right', padx=(0, 8))
        ttk.Button(buttons, text='取消', command=dialog.destroy).pack(side='right', padx=(0, 8))
        dialog.update_idletasks()
        dialog.geometry(f'+{self.root.winfo_rootx() + 90}+{self.root.winfo_rooty() + 90}')
        dialog.resizable(False, False)
        dialog.deiconify()
        dialog.grab_set()

    def apply_theme(self, mode):
        """Switch light/dark live: ttk styles, tk widgets, menus and the canvas chrome."""
        theme.set_mode(theme.resolve(mode))
        theme.apply_ttk(self.style)
        theme.restyle_tree(self.root)
        self.root.configure(background=theme.c('bg'))
        self.canvas.configure(background=theme.c('canvas'))
        if self.doc:
            self.show()
        else:
            self.show_empty_workspace()

    def watch_system_theme(self):
        if self.prefs.get('theme') == 'system':
            wanted = theme.resolve('system')
            if wanted != ('dark' if theme.is_dark() else 'light'):
                self.apply_theme('system')
        self.root.after(3000, self.watch_system_theme)

    def start_single_instance(self):
        """Accept files forwarded by later launches (double-clicked PDFs)."""
        self.remote_paths = queue.Queue()
        instance.listen(self.remote_paths)
        self.root.after(400, self.poll_remote_paths)

    def poll_remote_paths(self):
        if self.remote_paths is None: return
        try:
            while True:
                for path in self.remote_paths.get_nowait():
                    self.open_path(path)
                self.root.deiconify()
                # A file dropped on the desktop shortcut launches another
                # process, so Windows may deny a normal focus request.
                self.root.attributes('-topmost', True)
                self.root.lift()
                self.root.focus_force()
                self.root.after(250, lambda: self.root.attributes('-topmost', False) if self.root.winfo_exists() else None)
        except queue.Empty:
            pass
        self.root.after(400, self.poll_remote_paths)

    def close(self):
        if getattr(self, 'closing', False):
            return
        self.closing = True
        try:
            self.save_window_state()
            if self.inline_editor and not self.apply_inline(): return
            while self.tabs:
                if self.active_tab not in self.tabs:
                    self.activate_tab(next(iter(self.tabs)))
                before = len(self.tabs)
                if not self.close_tab(): return
                if len(self.tabs) >= before:
                    raise RuntimeError('无法关闭 PDF 标签，请重试。')
            if self.doc: self.doc.close(); self.doc = None
            if self.asset_db:
                self.asset_db.close()
                self.asset_db = None
            self.root.destroy()
        finally:
            self.closing = False

    def open(self):
        if self.inline_editor and not self.apply_inline(): return
        paths = filedialog.askopenfilenames(filetypes=[('PDF 文件', '*.pdf')])
        if not paths: return
        for path in paths:
            self.open_path(path)

    def popup_menu(self, menu, x, y, right=None):
        """Show a menu fully on screen; near an edge it is aligned to the button's right edge."""
        try:
            self.root.update_idletasks()
            width, height = menu.winfo_reqwidth(), menu.winfo_reqheight()
            if right is not None:
                x = int(right) - width
            x = min(int(x), self.root.winfo_screenwidth() - width - 8)
            y = min(int(y), self.root.winfo_screenheight() - height - 48)
            x, y = max(0, x), max(0, y)
            menu.tk_popup(x, y)
        finally:
            try: menu.grab_release()
            except tk.TclError: pass

    def store_tab(self):
        if self.active_tab not in self.tabs: return
        state = self.tabs[self.active_tab]
        for name in ('doc','path','page_index','scale','last_file_stat','dirty','undo_data','redo_data'):
            state[name] = getattr(self,name)
        state['anchor'] = self.view_anchor() if self.doc and self.page_width else None
        self.tab_control.tab(self.active_tab, text=Path(self.path).name + (' *' if self.dirty else '') + '  ×')

    def open_path(self, path):
        canonical = os.path.normcase(os.path.abspath(path))
        self.store_tab()
        for tab, state in self.tabs.items():
            if os.path.normcase(os.path.abspath(state['path'])) == canonical:
                self.tab_control.select(tab)
                self.activate_tab(tab)
                return
        try:
            data = Path(path).read_bytes()
            doc = fitz.open(stream=data, filetype='pdf')
            if doc.needs_pass or not doc.page_count:
                doc.close()
                raise ValueError('暂不支持需要密码或没有页面的文件')
            frame = ttk.Frame(self.tab_control)
            self.tab_control.add(frame, text=Path(path).name + '  ×')
            tab = str(frame)
            self.tabs[tab] = {'doc':doc,'path':path,'page_index':0,'scale':1.5,
                              'last_file_stat':hashlib.sha256(data).hexdigest(),'dirty':False,
                              'undo_data':[],'redo_data':[],'anchor':None}
            self.tab_control.select(tab)
            self.activate_tab(tab)
            self.root.update_idletasks()
            self.apply_open_zoom()
        except FileNotFoundError:
            messagebox.showerror('无法打开', f'文件不存在或已被移动：\n{path}')
        except PermissionError:
            messagebox.showerror('无法打开', f'没有权限读取该文件，或它正被其他程序占用：\n{path}')
        except Exception as exc: messagebox.showerror('无法打开', str(exc))

    def on_tab_change(self, event=None):
        tab = self.tab_control.select()
        if tab and tab != self.active_tab and not self.changing_tab:
            if self.inline_editor and not self.apply_inline():
                self.changing_tab = True
                self.tab_control.select(self.active_tab)
                self.changing_tab = False
                return
            self.store_tab()
            self.activate_tab(tab)

    def activate_tab(self, tab):
        if tab not in self.tabs: return
        self.active_tab = tab
        state = self.tabs[tab]
        for name in ('doc','path','page_index','scale','last_file_stat','dirty','undo_data','redo_data'):
            setattr(self,name,state[name])
        self.placing_text = False
        self.canvas.config(cursor='')
        self.page_width = self.page_height = 0
        self.show(anchor=state.get('anchor'))

    def close_tab(self):
        if not self.active_tab or self.active_tab not in self.tabs: return True
        if self.inline_editor and not self.apply_inline(): return False
        if self.dirty:
            answer = messagebox.askyesnocancel('未保存的修改', f'是否保存对“{Path(self.path).name}”的修改？', parent=self.root)
            if answer is None: return False
            if answer:
                self.save()
                if self.dirty: return False
        tab = self.active_tab
        self.doc.close()
        self.doc = None
        self.changing_tab = True
        self.tab_control.forget(tab)
        del self.tabs[tab]
        self.active_tab = None
        self.changing_tab = False
        next_tab = self.tab_control.select()
        if next_tab:
            self.activate_tab(next_tab)
        else:
            self.canvas.delete('all')
            self.page_width = self.page_height = 0
            self.refresh_thumbnails()
            self.status.config(text='打开 PDF 后，点击文字编辑；拖动边框移动或缩放。')
            self.show_empty_workspace()
        return True

    def close_tab_by(self, tab):
        if not tab or tab not in self.tabs:
            return False
        if self.active_tab != tab:
            if self.inline_editor and not self.apply_inline(): return False
            self.store_tab()
            self.changing_tab = True
            try:
                self.tab_control.select(tab)
                self.activate_tab(tab)
            finally:
                self.changing_tab = False
        return self.close_tab()

    def view_anchor(self, screen_x=None, screen_y=None):
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        x = width/2 if screen_x is None else screen_x
        y = height/2 if screen_y is None else screen_y
        return ((self.canvas.canvasx(x)-self.origin_x)/self.scale,
                (self.canvas.canvasy(y)-self.origin_y)/self.scale, x, y)

    def activate_canvas_page(self, index):
        if not self.page_layout or not 0 <= index < len(self.page_layout): return
        if index != self.page_index:
            self.canvas.delete('selection'); self.canvas.delete('snap-guide')
            self.selection = self.selected_kind = self.selected_line = None
            self.selected_paragraph = self.selected_block = self.selected_object = None
        self.page_index = index
        self.origin_x, self.origin_y, self.page_width, self.page_height = self.page_layout[index]
        self.status.config(text=f'{Path(self.path).name}   第 {index+1} / {len(self.doc)} 页    点击文字编辑，拖动对象移动' + ('    已修改' if self.dirty else ''))
        self.highlight_thumbnail()

    def page_at_canvas_point(self, x, y):
        for i, (left, top, width, height) in enumerate(self.page_layout):
            if left <= x <= left+width and top <= y <= top+height: return i
        return None

    def update_visible_pages(self, change_page=True):
        self.page_render_job = None
        if not self.doc or not self.page_layout: return
        top = self.canvas.canvasy(0); height = max(1, self.canvas.winfo_height())
        bottom = top + height
        wanted = {i for i, (_, y, _, h) in enumerate(self.page_layout) if y+h >= top-height*.3 and y <= bottom+height*.3}
        for i in list(self.page_photos):
            if i not in wanted:
                self.canvas.delete(f'pdf-page-{i}'); self.canvas.delete(f'page-shadow-{i}'); del self.page_photos[i]
        for i in sorted(wanted):
            if i in self.page_photos: continue
            x, y, _, _ = self.page_layout[i]
            pix = self.doc[i].get_pixmap(matrix=fitz.Matrix(self.scale, self.scale), alpha=False)
            photo = ImageTk.PhotoImage(Image.open(io.BytesIO(pix.tobytes('png'))))
            self.page_photos[i] = photo
            # A soft drop shadow makes the page read as paper on the workspace.
            self.canvas.create_rectangle(x+5, y+6, x+photo.width()+5, y+photo.height()+6,
                                         fill=theme.c('shadow'), outline='', tags=('page-shadow', f'page-shadow-{i}'))
            self.canvas.create_image(x, y, image=photo, anchor='nw', tags=('pdf-page', f'pdf-page-{i}'))
            self.canvas.tag_lower(f'pdf-page-{i}')
            self.canvas.tag_lower(f'page-shadow-{i}', f'pdf-page-{i}')
        if self.inline_editor and self.inline_state:
            self.canvas.tag_raise('inline-editor')
            self.inline_state['frame'].lift()
            self.draw_inline_box()
        if change_page and not self.inline_editor and self.drag_start is None:
            center = top+height/2
            index = min(range(len(self.page_layout)), key=lambda i: abs(center-(self.page_layout[i][1]+self.page_layout[i][3]/2)))
            if index != self.page_index: self.activate_canvas_page(index)

    def show(self, anchor=None):
        if not self.doc: return
        if self.active_tab in self.tabs:
            self.tab_control.tab(self.active_tab, text=Path(self.path).name + (' *' if self.dirty else '') + '  ×')
        if anchor is None and self.page_width:
            anchor = self.view_anchor()
        self.canvas.delete('all')
        self.page_photos = {}
        view_w, view_h = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        sizes = [(math.ceil(page.rect.width*self.scale), math.ceil(page.rect.height*self.scale)) for page in self.doc]
        total_h = sum(h for _, h in sizes) + 24*max(0, len(sizes)-1)
        region_w, region_h = max(view_w, max(w for w, _ in sizes)+32), max(view_h, total_h+32)
        y = (region_h-total_h)/2
        self.page_layout = []
        for w, h in sizes:
            self.page_layout.append(((region_w-w)/2, y, w, h)); y += h+24
        self.activate_canvas_page(self.page_index)
        self.canvas.configure(scrollregion=(0, 0, region_w, region_h))
        if anchor:
            self.canvas.xview_moveto(max(0, (self.origin_x+anchor[0]*self.scale-anchor[2])/region_w))
            self.canvas.yview_moveto(max(0, (self.origin_y+anchor[1]*self.scale-anchor[3])/region_h))
        else:
            self.canvas.xview_moveto(.5-view_w/(2*region_w))
            self.canvas.yview_moveto(max(0, (self.origin_y+self.page_height/2-view_h/2)/region_h))
        self.zoom_value.set(f'{self.scale*100:.0f}%')
        self.selection = None
        self.selected_kind = None
        self.selected_line = None
        self.selected_paragraph = None
        self.selected_block = None
        self.update_visible_pages(change_page=False)
        self.refresh_thumbnails()
        self.remember_scale()

    def turn(self, delta):
        if self.inline_editor and not self.apply_inline(): return
        if self.doc:
            self.page_index = max(0, min(len(self.doc)-1, self.page_index+delta))
            self.page_width = 0
            self.show()

    def zoom(self, factor, x=None, y=None):
        if self.inline_editor and not self.apply_inline(): return
        if not self.doc: return
        anchor = self.view_anchor(x, y)
        self.scale = max(.1, min(8, self.scale*factor))
        self.show(anchor)
        self.status.config(text=f'缩放 {self.scale*100:.0f}% · Ctrl+滚轮缩放，中键按住可平移')

    def set_zoom(self, event=None):
        try:
            value = float(self.zoom_value.get().strip().rstrip('%')) / 100
            if not math.isfinite(value) or not .1 <= value <= 8: raise ValueError()
            self.zoom(value/self.scale)
        except ValueError:
            messagebox.showinfo('缩放', '请输入 10% 到 800% 的数值。')
        return 'break'

    def fit_page(self):
        if not self.doc: return
        if self.inline_editor and not self.apply_inline(): return
        self.root.update_idletasks()
        page = self.doc[self.page_index]
        self.scale = max(.1, min(8, (self.canvas.winfo_width()-32)/page.rect.width, (self.canvas.winfo_height()-32)/page.rect.height))
        self.page_width = 0
        self.show()

    def fit_width(self):
        if not self.doc: return
        if self.inline_editor and not self.apply_inline(): return
        self.root.update_idletasks()
        page = self.doc[self.page_index]
        self.scale = max(.1, min(8, (self.canvas.winfo_width()-32)/page.rect.width))
        self.page_width = 0
        self.show()

    def apply_open_zoom(self):
        """Apply the '打开时缩放' preference to the freshly opened tab."""
        mode = self.prefs.get('default_zoom', 'percent')
        if mode == 'percent':
            try: value = float(self.prefs.get('default_percent', 320)) / 100
            except (TypeError, ValueError): value = 3.2
            self.scale = max(.1, min(8, value))
            self.page_width = 0
            self.show()
        elif mode == 'actual':
            self.scale = 1.0
            self.page_width = 0
            self.show()
        elif mode == 'last':
            try: value = float(self.saved_scale)
            except (TypeError, ValueError): value = 1.0
            self.scale = max(.1, min(8, value))
            self.page_width = 0
            self.show()
        elif mode == 'fit_width':
            self.fit_page_when_ready(kind='width')
        else:
            self.fit_page_when_ready()

    def fit_page_when_ready(self, attempts=20, doc=None, kind='page'):
        """Fit the page once the canvas has a real size.

        When a PDF is passed on the command line the window is not mapped yet, so
        the canvas still reports 1x1 and fitting would clamp to the 10% minimum.
        Retry briefly through the event loop; abandon the fit if another document
        or tab became active meanwhile.
        """
        if not self.doc: return
        if doc is None: doc = self.doc
        if self.doc is not doc: return
        if self.canvas.winfo_width() > 100 and self.canvas.winfo_height() > 100:
            (self.fit_width if kind == 'width' else self.fit_page)(); return
        if attempts > 0:
            self.root.after(50, lambda: self.fit_page_when_ready(attempts-1, doc, kind))

    def remember_scale(self):
        """Persist the zoom for the '记住上次比例' option without hammering the disk."""
        if not hasattr(self, 'prefs'): return
        self.prefs['last_scale'] = round(float(self.scale), 4)
        if getattr(self, '_scale_job', None):
            try: self.root.after_cancel(self._scale_job)
            except tk.TclError: pass
        self._scale_job = self.root.after(1500, lambda: settings.save(self.prefs))

    def resized(self, event):
        if not self.doc:
            self.show_empty_workspace(); return
        if self.inline_editor: return
        if self.resize_job: self.root.after_cancel(self.resize_job)
        self.resize_job = self.root.after(100, self.redraw_after_resize)

    def redraw_after_resize(self):
        self.resize_job = None
        if not (self.doc and not self.inline_editor): return
        # show() rebuilds the page and clears the selection; a window resize (or a
        # toolbar reflow right after a format change) must not lose what the user
        # had selected.
        keep = {
            'selection': fitz.Rect(self.selection) if self.selection else None,
            'kind': self.selected_kind, 'block': self.selected_block,
            'line': self.selected_line, 'paragraph': self.selected_paragraph,
            'object': self.selected_object,
        }
        self.show()
        self.selection, self.selected_kind = keep['selection'], keep['kind']
        self.selected_block, self.selected_line = keep['block'], keep['line']
        self.selected_paragraph, self.selected_object = keep['paragraph'], keep['object']
        if self.selection and not self.selection.is_empty:
            self.draw_selection(self.selection)

    def mouse_wheel(self, event):
        if event.delta:
            self.canvas.yview_scroll(-int(math.copysign(max(1, abs(event.delta)//40), event.delta)), 'units')
        return 'break'

    def horizontal_wheel(self, event):
        if event.delta:
            self.canvas.xview_scroll(-int(math.copysign(max(1, abs(event.delta)//40), event.delta)), 'units')
        return 'break'

    def zoom_wheel(self, event):
        self.zoom(1.1 ** (event.delta/120), event.x, event.y)
        return 'break'

    def press(self, event):
        if not self.doc: return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if self.inline_editor:
            prior = fitz.Rect(self.selection) if self.selection else None
            point = fitz.Point((x-self.origin_x)/self.scale, (y-self.origin_y)/self.scale)
            if not self.apply_inline(): return
            x, y = self.origin_x+point.x*self.scale, self.origin_y+point.y*self.scale
            if prior and (prior + (-45/self.scale,-45/self.scale,45/self.scale,45/self.scale)).contains(point):
                self.select_object((prior.tl+prior.br)/2)
        if self.space_pan:
            # Space held: grab and drag anywhere on the workspace, page or margin.
            self.drag_start = (x, y)
            self.drag_kind = 'pan'
            self.canvas.scan_mark(event.x, event.y)
            return
        page = self.page_at_canvas_point(x, y)
        if page is None:
            if not self.placing_text:
                self.drag_start = (x, y)
                self.drag_kind = 'outside_select'
                self.canvas.delete('selection')
            return
        if page != self.page_index: self.activate_canvas_page(page)
        self.drag_start = (x, y)
        point = fitz.Point((x-self.origin_x)/self.scale, (y-self.origin_y)/self.scale)
        self.drag_kind = 'select'
        self.snap_candidates = None
        self.drag_origin_rect = None
        self.edit_on_release = False
        if self.placing_text:
            self.drag_kind = 'new_text'
            self.canvas.delete('selection')
            return
        if self.selection and not self.selection.is_empty:
            if self.rotation_handle_at(x, y):
                self.drag_kind = 'rotate'
                self.drag_origin_rect = fitz.Rect(self.selection)
                self.drag_origin_quad = self.selection_quad()
                return
            self.resize_corner = self.handle_at(x, y)
            if self.resize_corner:
                self.drag_kind = 'resize'
                self.drag_origin_rect = fitz.Rect(self.selection)
                self.drag_origin_quad = self.selection_quad()
                return
            hit = fitz.Rect(self.selection) + (-4/self.scale, -4/self.scale, 4/self.scale, 4/self.scale)
            if hit.contains(point) and self.selected_kind in ('文字', '图片', '图形', '区域'):
                self.drag_kind = 'move'
                self.drag_origin_rect = fitz.Rect(self.selection)
                if self.selected_kind == '文字':
                    lines = self.selected_paragraph or ([self.selected_line] if self.selected_line else [])
                    self.edit_on_release = any(fitz.Rect(line['bbox']).contains(point) for line in lines)
                return
        if self.selection_type.get() != '框选区域':
            # Alt+click ignores a block that was dragged on top of another one.
            self.select_object(point, below=bool(event.state & 0x00020000))
            if self.selection is not None:
                self.drag_kind = 'move'
                self.drag_origin_rect = fitz.Rect(self.selection)
                if self.selected_kind == '文字':
                    # A plain click on text edits it straight away (like Acrobat's Edit
                    # tool); dragging moves the object instead because release() sees
                    # movement and skips the editor.
                    self.edit_on_release = True
                return
        self.canvas.delete('selection')

    def drag(self, event):
        if self.drag_start is None: return
        if self.drag_kind == 'pan':
            self.canvas.scan_dragto(event.x, event.y, gain=1)
            return
        self.canvas.delete('selection')
        self.canvas.delete('snap-guide')
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if self.drag_kind == 'rotate' and self.drag_origin_rect:
            angle = self.rotation_delta(x, y, bool(event.state & 1))
            r = self.drag_origin_rect
            cx, cy = self.origin_x+(r.x0+r.x1)*self.scale/2, self.origin_y+(r.y0+r.y1)*self.scale/2
            c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            points = []
            for px, py in self.drag_origin_quad:
                dx, dy = self.origin_x+px*self.scale-cx, self.origin_y+py*self.scale-cy
                points.extend((cx+dx*c-dy*s, cy+dx*s+dy*c))
            self.canvas.create_polygon(*points, outline='#1677ff', fill='', width=2, tags='selection')
            self.status.config(text=f'旋转 {angle:.1f}°；按住 Shift 按 15° 对齐。')
        elif self.drag_kind == 'resize' and self.drag_origin_rect:
            if self.is_oriented(self.drag_origin_quad):
                quad = self.resize_quad(self.drag_origin_quad, (x-self.drag_start[0])/self.scale, (y-self.drag_start[1])/self.scale, bool(event.state & 1))
                self.draw_selection_quad(quad)
            else:
                target = self.resize_bounds(self.drag_origin_rect, (x-self.drag_start[0])/self.scale, (y-self.drag_start[1])/self.scale, bool(event.state & 1))
                self.draw_selection(target, '#1677ff')
        elif self.drag_kind == 'move' and self.drag_origin_rect:
            dx, dy = x-self.drag_start[0], y-self.drag_start[1]
            r = self.drag_origin_rect
            dx, dy, gx, gy = self.snap_movement(dx/self.scale, dy/self.scale)
            self.draw_selection(r + (dx, dy, dx, dy), '#1677ff')
            page = self.doc[self.page_index].rect
            if gx is not None:
                xx = self.origin_x+gx*self.scale
                self.canvas.create_line(xx,self.origin_y+page.y0*self.scale,xx,self.origin_y+page.y1*self.scale,fill='#e64980',dash=(5,3),width=2,tags='snap-guide')
            if gy is not None:
                yy = self.origin_y+gy*self.scale
                self.canvas.create_line(self.origin_x+page.x0*self.scale,yy,self.origin_x+page.x1*self.scale,yy,fill='#e64980',dash=(5,3),width=2,tags='snap-guide')
        else:
            self.canvas.create_rectangle(*self.drag_start, x, y, outline='#ff3030', width=2, tags='selection')

    def release(self, event):
        if self.drag_start is None: return
        if self.drag_kind == 'pan':
            self.drag_kind = None
            self.drag_start = None
            self.canvas.config(cursor='hand2' if self.space_pan else '')
            return
        self.canvas.delete('snap-guide')
        x0,y0 = self.drag_start
        x1,y1 = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if self.drag_kind == 'rotate':
            angle = self.rotation_delta(x1, y1, bool(event.state & 1))
            self.drag_start = None
            self.drag_kind = None
            if abs(angle) >= .1: self.rotate_selected(angle)
            else: self.draw_selection(self.selection)
            return
        self.drag_start = None
        if self.drag_kind == 'outside_select':
            self.drag_kind = None
            self.canvas.delete('selection')
            if abs(x1-x0) < 5 or abs(y1-y0) < 5:
                return
            area = fitz.Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            overlaps = []
            for index, (left, top, width, height) in enumerate(self.page_layout):
                overlap = area & fitz.Rect(left, top, left+width, top+height)
                if not overlap.is_empty:
                    overlaps.append((overlap.get_area(), index, overlap))
            if not overlaps:
                return
            _, page, overlap = max(overlaps, key=lambda item: (item[0], item[1] == self.page_index))
            if page != self.page_index:
                self.activate_canvas_page(page)
            x0, y0, x1, y1 = overlap
        if self.drag_kind == 'new_text':
            self.drag_kind = None
            self.placing_text = False
            self.canvas.config(cursor='')
            px, py = (x0-self.origin_x)/self.scale, (y0-self.origin_y)/self.scale
            if abs(x1-x0)<5 and abs(y1-y0)<5:
                rect = fitz.Rect(px, py, px+100, py+35)
            else:
                rect = fitz.Rect((min(x0,x1)-self.origin_x)/self.scale, (min(y0,y1)-self.origin_y)/self.scale,
                                 (max(x0,x1)-self.origin_x)/self.scale, (max(y0,y1)-self.origin_y)/self.scale)
            rect &= self.doc[self.page_index].rect
            if rect.is_empty or rect.width < 5 or rect.height < 5:
                messagebox.showinfo('添加文本框', '请在页面内点击或拖出一个文本框。')
                return
            self.start_new_text_inline(rect)
            return
        if self.drag_kind == 'resize':
            # A hairline has a degenerate quad; an oriented matrix would erase it,
            # so route it through the rect-based path instead.
            object_rect = fitz.Rect((self.selected_object or {}).get('rect', self.selection))
            oriented = self.is_oriented(self.drag_origin_quad) and \
                min(object_rect.width, object_rect.height) >= .5
            target = self.resize_quad(self.drag_origin_quad, (x1-x0)/self.scale, (y1-y0)/self.scale, bool(event.state & 1)) if oriented else self.resize_bounds(self.drag_origin_rect, (x1-x0)/self.scale, (y1-y0)/self.scale, bool(event.state & 1))
            self.drag_kind = None
            if abs(x1-x0)>=3 or abs(y1-y0)>=3:
                if oriented: self.transform_oriented(target, proportional=bool(event.state & 1))
                else: self.transform_selected(target, proportional=bool(event.state & 1))
            else:
                self.draw_selection(self.selection, '#1677ff')
            return
        if self.drag_kind == 'move':
            self.drag_kind = None
            if abs(x1-x0)>=5 or abs(y1-y0)>=5:
                dx,dy,_,_ = self.snap_movement((x1-x0)/self.scale, (y1-y0)/self.scale)
                self.move_selected(dx, dy)
            elif self.edit_on_release and self.selected_kind == '文字':
                group = len(self.selected_paragraph or []) > 1
                self.start_inline((x1, y1), explicit_group=group)
            return
        if abs(x1-x0)<5 and abs(y1-y0)<5 and self.selection_type.get() != '框选区域':
            self.select_object(fitz.Point((x1-self.origin_x)/self.scale,(y1-self.origin_y)/self.scale))
            return
        self.selection = fitz.Rect((min(x0,x1)-self.origin_x)/self.scale, (min(y0,y1)-self.origin_y)/self.scale, (max(x0,x1)-self.origin_x)/self.scale, (max(y0,y1)-self.origin_y)/self.scale)
        self.selection &= self.doc[self.page_index].rect
        self.selected_kind = '区域' if not self.selection.is_empty else None
        self.selected_object = None
        if self.selected_kind: self.draw_selection(self.selection, '#1677ff')
        self.status.config(text='拖动框内移动；拖动角点缩放，按住 Shift 保持比例。')
        if self.batch_waiting_for_selection and self.selected_kind == '区域':
            target = fitz.Rect(self.selection)
            doc, page, mode = self.doc, self.page_index, self.batch_mode
            self.batch_waiting_for_selection = False
            def resume():
                if self.doc is not doc or self.page_index != page or self.batch_mode != mode: return
                self.selection = fitz.Rect(target); self.selected_kind = '区域'
                self.draw_selection(self.selection)
                self.continue_batch_mode()
            self.root.after_idle(resume)

    def collect_snap_candidates(self):
        page = self.doc[self.page_index]
        rect = page.rect
        xs = [rect.x0, (rect.x0+rect.x1)/2, rect.x1]
        ys = [rect.y0, (rect.y0+rect.y1)/2, rect.y1]
        selected = self.drag_origin_rect
        def add(bounds):
            if bounds.is_empty or bounds.is_infinite or not all(math.isfinite(v) for v in bounds): return
            xs.extend((bounds.x0,(bounds.x0+bounds.x1)/2,bounds.x1))
            ys.extend((bounds.y0,(bounds.y0+bounds.y1)/2,bounds.y1))
        page_lines = full_text_lines(page)
        selected_lines = self.selected_paragraph or ([self.selected_line] if self.selected_line else [])
        selected_boxes = {tuple(round(float(v),3) for v in line['bbox']) for line in selected_lines}
        marked_lines = set()
        for block in added_text.find(page, page_lines):
            if not block.props.get('box'): continue
            for bounds, _ in block.lines:
                marked_lines.add(tuple(round(float(v),3) for v in bounds))
            bounds = self.block_bounds(block)
            if selected and self.selected_kind == '文字' and self.selected_block and \
                    tuple(block.props['box']) == tuple(self.selected_block.props['box']):
                continue
            if selected and self.selected_kind == '区域' and selected.contains(bounds): continue
            add(bounds)
        for bounds, _line in page_lines:
            key = tuple(round(float(v),3) for v in bounds)
            if key in marked_lines or key in selected_boxes: continue
            if selected and self.selected_kind == '区域' and selected.contains(bounds): continue
            add(bounds)
        objects = page_objects.Objects(page)
        grouped = set()
        for item in objects.items:
            bounds = fitz.Rect(item['rect'])
            if item.get('background') or item.get('whole'): continue
            if self.selected_object and (item.get('n') == self.selected_object.get('n') or item.get('n') in self.selected_object.get('members', [])): continue
            if selected and self.selected_kind == '区域' and selected.intersects(bounds): continue
            if item.get('n') in grouped: continue
            if item.get('kind') == 'shape' and item.get('fill') and bounds.height >= 8 and 0 < bounds.width <= bounds.height*.30:
                group = self.barcode_group_at(objects, (bounds.tl+bounds.br)/2)
                if group:
                    grouped.update(group[1]['members'])
                    add(group[0])
                    continue
            add(bounds)
        return xs, ys

    def snap_movement(self, dx, dy):
        if not self.snap_enabled.get() or not self.doc or not self.drag_origin_rect:
            return dx,dy,None,None
        if self.snap_candidates is None:
            self.snap_candidates = self.collect_snap_candidates()
        r = self.drag_origin_rect
        # The screen-space tolerance remains usable at normal zoom, but is capped
        # at 1 mm so zooming out cannot pull a label a large physical distance.
        tolerance = min(6/max(self.scale,.01), 72/25.4)
        def nearest(edges, candidates):
            choices = ((line-edge,line) for edge in edges for line in candidates if abs(line-edge) <= tolerance)
            return min(choices, key=lambda pair:abs(pair[0]), default=(0,None))
        ox, gx = nearest((r.x0+dx,(r.x0+r.x1)/2+dx,r.x1+dx),self.snap_candidates[0])
        oy, gy = nearest((r.y0+dy,(r.y0+r.y1)/2+dy,r.y1+dy),self.snap_candidates[1])
        return dx+ox,dy+oy,gx,gy

    def draw_selection(self, rect, color='#1677ff'):
        if not rect or rect.is_empty: return
        quad = self.selection_quad()
        if self.selection and self.selection.width and self.selection.height:
            sx, sy = rect.width/self.selection.width, rect.height/self.selection.height
            quad = [fitz.Point(rect.x0+(p.x-self.selection.x0)*sx, rect.y0+(p.y-self.selection.y0)*sy) for p in quad]
        self.draw_selection_quad(quad, color)
        self.draw_selection_lines()

    def selection_quad(self):
        r = self.selection
        if self.selected_kind == '文字' and self.selected_block and self.selected_block.props.get('box'):
            box = fitz.Rect(self.selected_block.props['box'])
            matrix = self.box_rotation_matrix(box, self.selected_block.props['rotate'])
            return [p * matrix for p in (box.tl, box.tr, box.br, box.bl)]
        if self.selected_kind in ('图片', '图形') and self.selected_object:
            try:
                q = self.selected_object['quad']
                points = [fitz.Point(p) for p in (q.ll, q.lr, q.ur, q.ul)]
                # The object quad starts at the lower-left corner; for an unrotated
                # object re-order it to tl/tr/br/bl so the handle names (n/s/e/w)
                # match what the user sees at each edge.
                xs = sorted({round(p.x, 3) for p in points})
                ys = sorted({round(p.y, 3) for p in points})
                if len(xs) <= 2 and len(ys) <= 2:
                    x0, x1 = xs[0], xs[-1]
                    y0, y1 = ys[0], ys[-1]
                    return [fitz.Point(x0, y0), fitz.Point(x1, y0),
                            fitz.Point(x1, y1), fitz.Point(x0, y1)]
                return points
            except (KeyError, TypeError, ValueError):
                pass
        return [fitz.Point(p) for p in (r.tl,r.tr,r.br,r.bl)]

    def is_oriented(self, quad):
        if not quad: return False
        a, b = quad[0], quad[1]
        c = quad[3]
        return abs(b.y-a.y) > .01 or abs(c.x-a.x) > .01 or b.x < a.x or c.y < a.y

    def quad_handle_positions(self, quad):
        a,b,c,d = quad
        return [('nw',a),('ne',b),('se',c),('sw',d),('n',(a+b)/2),('e',(b+c)/2),('s',(c+d)/2),('w',(d+a)/2)]

    def rotation_handle_position(self, quad):
        top = (quad[0]+quad[1])/2
        center = (quad[0]+quad[2])/2
        v = top-center
        length = math.hypot(v.x,v.y)
        if length < .001: return top + fitz.Point(0,-24/self.scale)
        return top + v*(24/(self.scale*length))

    def draw_selection_quad(self, quad, color='#1677ff'):
        self.canvas.delete('selection')
        points = [(self.origin_x+p.x*self.scale, self.origin_y+p.y*self.scale) for p in quad]
        self.canvas.create_polygon(*[v for p in points for v in p],outline=color,fill='',width=2,tags='selection')
        for _,p in self.quad_handle_positions(quad):
            x, y = self.origin_x+p.x*self.scale, self.origin_y+p.y*self.scale
            self.canvas.create_rectangle(x-4,y-4,x+4,y+4,outline=color,fill='white',tags='selection')
        if self.selected_kind in ('文字', '图片', '图形'):
            top = (quad[0]+quad[1])/2
            p = self.rotation_handle_position(quad)
            x,y = self.origin_x+p.x*self.scale,self.origin_y+p.y*self.scale
            self.canvas.create_line(self.origin_x+top.x*self.scale,self.origin_y+top.y*self.scale,x,y,fill=color,width=2,tags='selection')
            self.canvas.create_oval(x-5,y-5,x+5,y+5,outline=color,fill='white',width=2,tags='selection')

    def rotation_handle_at(self, x, y):
        r = self.selection
        if not r or self.selected_kind not in ('文字', '图片', '图形'): return False
        p = self.rotation_handle_position(self.selection_quad())
        cx = self.origin_x+p.x*self.scale
        cy = self.origin_y+p.y*self.scale
        return abs(x-cx) <= 9 and abs(y-cy) <= 9

    def rotation_delta(self, x, y, snap=False):
        r = self.drag_origin_rect
        cx = self.origin_x+(r.x0+r.x1)*self.scale/2
        cy = self.origin_y+(r.y0+r.y1)*self.scale/2
        delta = math.degrees(math.atan2(y-cy,x-cx)-math.atan2(self.drag_start[1]-cy,self.drag_start[0]-cx)) if self.drag_start else math.degrees(math.atan2(y-cy,x-cx)+math.pi/2)
        delta = (delta+180) % 360-180
        return round(delta/15)*15 if snap else delta

    def handle_at(self, x, y):
        r = self.selection
        if not r or r.is_empty or self.selected_kind not in ('文字', '图片', '图形', '区域'): return None
        # Thin selections put every handle within a few pixels of each other, so
        # pick the nearest one instead of the first match. A hairline only exposes
        # its two end points as handles; the middle stays draggable to move it.
        obj = self.selected_object or {}
        object_rect = fitz.Rect(obj.get('rect', r))
        thin = object_rect.width < 1 or object_rect.height < 1
        best, best_distance = None, None
        for name, p in self.quad_handle_positions(self.selection_quad()):
            if thin and name in ('n', 's', 'e', 'w'): continue
            dx = abs(x - (self.origin_x + p.x*self.scale))
            dy = abs(y - (self.origin_y + p.y*self.scale))
            if dx <= 8 and dy <= 8:
                distance = dx*dx + dy*dy
                if best_distance is None or distance < best_distance:
                    best, best_distance = name, distance
        return best

    def resize_quad(self, quad, dx, dy, keep_ratio):
        a,b,c,d = quad
        u,v = b-a,d-a
        w,h = math.hypot(u.x,u.y),math.hypot(v.x,v.y)
        if min(w,h) < .01: return quad
        ux,uy = u/w,v/h
        det = ux.x*uy.y-ux.y*uy.x
        if abs(det) < .001: return quad
        lx,ly = (dx*uy.y-dy*uy.x)/det,(dy*ux.x-dx*ux.y)/det
        corner = self.resize_corner
        left,top = 'w' in corner,'n' in corner
        nw = max(2,w+((-lx if left else lx) if 'w' in corner or 'e' in corner else 0))
        nh = max(2,h+((-ly if top else ly) if 'n' in corner or 's' in corner else 0))
        if keep_ratio:
            sx,sy = nw/w,nh/h
            factor = sx if abs(sx-1)>=abs(sy-1) else sy
            nw,nh = w*factor,h*factor
        start = a + ux*(w-nw if left else 0) + uy*(h-nh if top else 0)
        return [start,start+ux*nw,start+ux*nw+uy*nh,start+uy*nh]

    def resize_bounds(self, rect, dx, dy, keep_ratio):
        corner = self.resize_corner
        left = 'w' in corner
        top = 'n' in corner
        width = max(2, rect.width + ((-dx if left else dx) if 'w' in corner or 'e' in corner else 0))
        height = max(2, rect.height + ((-dy if top else dy) if 'n' in corner or 's' in corner else 0))
        if keep_ratio:
            sx, sy = width/rect.width, height/rect.height
            factor = sx if abs(sx-1) >= abs(sy-1) else sy
            factor = max(.02, min(20, factor))
            width, height = rect.width*factor, rect.height*factor
        anchor_x = rect.x1 if left else rect.x0
        anchor_y = rect.y1 if top else rect.y0
        return fitz.Rect(anchor_x-width if left else anchor_x, anchor_y-height if top else anchor_y,
                         anchor_x if left else anchor_x+width, anchor_y if top else anchor_y+height)

    def box_rotation_matrix(self, box, angle):
        center = (box.tl + box.br) / 2
        return fitz.Matrix(1,0,0,1,-center.x,-center.y) * fitz.Matrix(-angle) * fitz.Matrix(1,0,0,1,center.x,center.y)

    def block_bounds(self, block):
        box = fitz.Rect(block.props['box'])
        return box * self.box_rotation_matrix(box, block.props['rotate'])

    def barcode_group_at(self, objects, point):
        """Find a conservative cluster of parallel filled bars; leave borders separate."""
        eligible = []
        for item in objects.items:
            if item.get('kind') != 'shape' or not item.get('fill'): continue
            rect = fitz.Rect(item['rect'])
            if rect.height < 8 or rect.width <= 0 or rect.width > rect.height*.30: continue
            if not (rect.y0-2 <= point.y <= rect.y1+2): continue
            eligible.append((rect,item))
        eligible.sort(key=lambda pair:pair[0].x0)
        for anchor, _ in sorted(eligible, key=lambda pair:abs((pair[0].x0+pair[0].x1)/2-point.x))[:12]:
            if not (anchor.y0-2 <= point.y <= anchor.y1+2): continue
            similar = [(r,it) for r,it in eligible if abs(r.height-anchor.height) <= anchor.height*.20
                       and abs((r.y0+r.y1)-(anchor.y0+anchor.y1)) <= anchor.height*.25]
            clusters, group = [], []
            for r,it in similar:
                if group and r.x0-group[-1][0].x1 > anchor.height*.30:
                    clusters.append(group); group=[]
                group.append((r,it))
            if group: clusters.append(group)
            for group in clusters:
                if len(group) < 12: continue
                bounds = fitz.Rect(group[0][0])
                for r,_ in group[1:]: bounds |= r
                if bounds.width < bounds.height*.7 or not bounds.contains(point): continue
                return bounds, {'kind':'barcode', 'members':[item['n'] for _,item in group]}
        return None

    def selected_graphic_numbers(self, objects):
        selected = self.selected_object or {}
        numbers = selected.get('members', [selected.get('n')])
        available = {item['n'] for item in objects.items}
        if not numbers or any(n not in available for n in numbers):
            raise ValueError('对象已发生变化，请重新选择。')
        return numbers

    def matrix_group_at(self, objects, point):
        squares = []
        for item in objects.items:
            if item.get('kind') != 'shape' or not item.get('fill'): continue
            r = fitz.Rect(item['rect'])
            if r.width > .15 and r.height > .15 and .8 <= r.width/r.height <= 1.25:
                squares.append((r,item))
        if len(squares) < 60 or len(squares) > 10000: return None
        anchors = [(r,it) for r,it in squares if (r+(-.5,-.5,.5,.5)).contains(point)]
        if not anchors: return None
        anchor = min(anchors,key=lambda pair:pair[0].get_area())[0]
        unit = (anchor.width+anchor.height)/2
        candidates = [(r,it) for r,it in squares if .70*unit <= r.width <= 1.35*unit and .70*unit <= r.height <= 1.35*unit]
        cell = unit*2.5
        grid = {}
        for i,(r,_) in enumerate(candidates):
            x,y = (r.x0+r.x1)/2,(r.y0+r.y1)/2
            grid.setdefault((math.floor(x/cell),math.floor(y/cell)),[]).append(i)
        seed = min(range(len(candidates)),key=lambda i:abs(candidates[i][0].x0-anchor.x0)+abs(candidates[i][0].y0-anchor.y0))
        seen, stack = {seed}, [seed]
        while stack:
            i = stack.pop(); r = candidates[i][0]
            x,y = (r.x0+r.x1)/2,(r.y0+r.y1)/2
            gx,gy = math.floor(x/cell),math.floor(y/cell)
            for xx in range(gx-1,gx+2):
                for yy in range(gy-1,gy+2):
                    for j in grid.get((xx,yy),[]):
                        if j in seen: continue
                        q = candidates[j][0]
                        if abs((q.x0+q.x1)/2-x) <= 2.1*unit and abs((q.y0+q.y1)/2-y) <= 2.1*unit:
                            seen.add(j); stack.append(j)
        if len(seen) < 60: return None
        bounds = fitz.Rect(candidates[seed][0])
        for i in seen: bounds |= candidates[i][0]
        if min(bounds.width,bounds.height) < 8*unit or not .6 <= bounds.width/bounds.height <= 1.65: return None
        members = {candidates[i][1]['n'] for i in seen}
        # Include merged dark modules entirely inside the detected matrix, without its border.
        for item in objects.items:
            if item.get('kind') == 'shape' and item.get('fill') and bounds.contains(fitz.Rect(item['rect'])):
                members.add(item['n'])
        return bounds, {'kind':'barcode', 'members':sorted(members)}

    @staticmethod
    def rect_distance(rect, point):
        """Distance from a point to a rectangle (0 when inside)."""
        dx = max(rect.x0 - point.x, 0.0, point.x - rect.x1)
        dy = max(rect.y0 - point.y, 0.0, point.y - rect.y1)
        return math.hypot(dx, dy)

    def nearest_text_lines(self, page_lines, point, tolerance=None):
        """Text lines near the click, nearest first.

        Adobe-like behaviour: clicking just above/below a line still picks that
        line instead of requiring the pointer to be inside its box.
        """
        ranked = []
        for rect, line in page_lines:
            if not text_edit.visible(line):
                continue
            ranked.append((self.rect_distance(rect, point), rect.get_area(), rect, line))
        if not ranked:
            return []
        ranked.sort(key=lambda item: (item[0], item[1]))
        if tolerance is None:
            height = min(16.0, max(4.0, ranked[0][2].height))
            tolerance = max(3.0, height * 0.85)
        return [(rect, line) for distance, _, rect, line in ranked if distance <= tolerance]

    def word_at_point(self, point):
        """The word under the pointer, as (rect, text)."""
        page = self.doc[self.page_index]
        try:
            words = page.get_text('words', clip=fitz.INFINITE_RECT())
        except Exception:
            words = page.get_text('words')
        best = None
        for item in words:
            rect = fitz.Rect(item[:4])
            if (rect + (-1.2, -1.2, 1.2, 1.2)).contains(point):
                if best is None or rect.get_area() < best[0].get_area():
                    best = (rect, str(item[4]))
        return best

    def draw_selection_lines(self):
        """Thin outline per selected text line so a multi-line pick reads clearly."""
        lines = getattr(self, 'selection_lines', None) or []
        for line_rect in lines:
            self.canvas.create_rectangle(
                self.origin_x + line_rect.x0 * self.scale, self.origin_y + line_rect.y0 * self.scale,
                self.origin_x + line_rect.x1 * self.scale, self.origin_y + line_rect.y1 * self.scale,
                outline='#8fbcff', width=1, tags='selection')

    def remember_moved_text(self, page_index, entries):
        """Remember where a moved block now sits, so it stays selectable after overlap.

        entries: [(rect, text)] already shifted to the new position. Storing geometry
        instead of re-reading the page keeps the mark exact even when two blocks share
        the same left edge.
        """
        marks = [{'rect': fitz.Rect(rect), 'text': str(value)}
                 for rect, value in entries if rect and not rect.is_empty]
        if marks:
            self.moved_text_marks = [mark for mark in self.moved_text_marks
                                     if mark['page'] != page_index] + [{'page': page_index, 'lines': marks}]

    def is_moved_line(self, rect, line):
        """True when this line belongs to a block the user dragged on top of another."""
        page_index = self.page_index
        for mark in self.moved_text_marks:
            if mark['page'] != page_index:
                continue
            for entry in mark['lines']:
                if (abs(rect.y0 - entry['rect'].y0) <= 2.5 and abs(rect.x0 - entry['rect'].x0) <= 4
                        and text_edit.line_text(line) == entry['text']):
                    return True
        return False

    def moved_text_at(self, point, page_lines):
        """Return the lines of a previously moved block that is under the pointer."""
        page_index = self.page_index
        for mark in self.moved_text_marks:
            if mark['page'] != page_index:
                continue
            if not any((entry['rect'] + (-2, -2, 2, 2)).contains(point) for entry in mark['lines']):
                continue
            found = []
            for entry in mark['lines']:
                best = None
                nearest = None
                for rect, line in page_lines:
                    if abs(rect.y0 - entry['rect'].y0) > 3 or abs(rect.x0 - entry['rect'].x0) > 4:
                        continue
                    if nearest is None:
                        nearest = line
                    if text_edit.line_text(line) == entry['text']:
                        best = line
                        break
                chosen = best if best is not None else nearest
                if chosen is not None:
                    found.append(chosen)
            if len(found) >= max(1, len(mark['lines']) // 2):
                return found
        return None

    def select_object(self, point, below=False):
        page = self.doc[self.page_index]
        if page.rotation:
            messagebox.showinfo('暂不能编辑', '此页带有旋转属性，当前版本不能安全选择对象。')
            return
        candidates = []
        mode = self.selection_type.get()
        self.selected_block = None
        page_lines = full_text_lines(page) if mode in ('自动选择', '整块文字', '选择文字', '选择文本框') else []
        if mode in ('自动选择', '选择文字', '选择文本框'):
            blocks = [b for b in added_text.find(page, page_lines) if b.props.get('box') and
                      b.props['box'].contains(point * ~self.box_rotation_matrix(b.props['box'], b.props['rotate']))]
            if blocks:
                block = min(blocks, key=lambda b:b.props['box'].get_area())
                self.selection = self.block_bounds(block)
                self.selected_kind, self.selected_block = '文字', block
                self.selected_paragraph = [line for _, line in block.lines]
                self.selected_line = self.selected_paragraph[0]
                self.selected_object = None
                self.sync_text_format(page, block)
                self.draw_selection(self.selection)
                self.status.config(text='已选中文本框，拖动边框移动或调整大小，双击编辑文字。')
                return
        if mode in ('自动选择', '整块文字', '选择文字', '选择文本框') and not below:
            remembered = self.moved_text_at(point, page_lines)
            if remembered:
                self.canvas.delete('selection')
                self.selected_block = None
                self.selected_object = None
                self.selected_kind = '文字'
                self.selected_line = remembered[0]
                self.selected_paragraph = remembered
                self.selection = fitz.Rect(remembered[0]['bbox'])
                for item in remembered[1:]:
                    self.selection |= fitz.Rect(item['bbox'])
                self.selection_lines = [fitz.Rect(item['bbox']) for item in remembered]
                self.sync_text_format(page, None)
                self.draw_selection(self.selection)
                self.status.config(text=f'已选中之前移动的文字块（{len(remembered)} 行）；按住 Alt 点击可选中下面的块。')
                return

        if mode in ('自动选择', '整块文字', '选择文字', '选择文本框'):
            for rect, line in self.nearest_text_lines(page_lines, point):
                if below and self.is_moved_line(rect, line):
                    continue          # Alt+click reaches the block underneath
                candidates.append((rect, '文字', line))
        if mode in ('自动选择', '选择图片', '选择图形') and not candidates:
            objects = page_objects.Objects(page)
            barcode = (self.barcode_group_at(objects, point) or self.matrix_group_at(objects, point)) if mode != '选择图片' else None
            if barcode:
                candidates.append((barcode[0], '图形', barcode[1]))
            elif mode == '选择图片':
                for item in objects.items:
                    if item.get('kind') not in ('picture', 'group'): continue
                    rect = fitz.Rect(item['rect'])
                    if (rect + (-2, -2, 2, 2)).contains(point): candidates.append((rect, '图片', item))
            else:
                item = objects.at(point, max(1.5, 3/self.scale))
                if item and (mode != '选择图形' or item.get('kind') == 'shape'):
                    rect = fitz.Rect(item['rect'])
                    if rect.width < 2: rect.x0 -= 1; rect.x1 += 1
                    if rect.height < 2: rect.y0 -= 1; rect.y1 += 1
                    candidates.append((rect, '图形' if item.get('kind') == 'shape' else '图片', item))
        self.canvas.delete('selection')
        if not candidates:
            self.selection = None
            self.selection_lines = []
            self.selected_kind = None
            self.selected_line = None
            self.selected_paragraph = None
            self.status.config(text='没有选中对象，请点击文字或图片。')
            return
        # Overlapping text: repeated clicks on the same spot cycle through the
        # candidates, so a block moved on top of another stays reachable.
        candidates.sort(key=lambda item: (self.rect_distance(item[0], point), item[0].get_area()))
        spot = (round(point.x, 1), round(point.y, 1))
        ids = [id(item[2]) for item in candidates]
        cycle = getattr(self, '_click_cycle', None)
        if cycle and cycle[0] == spot and cycle[1] == ids:
            index = (cycle[2] + 1) % len(ids)
        else:
            index = 0
        self._click_cycle = (spot, ids, index)
        self.selection, self.selected_kind, selected = candidates[index]
        self.selected_line = selected if self.selected_kind == '文字' else None
        self.selected_object = selected if self.selected_kind in ('图片', '图形') else None
        self.selection = fitz.Rect(self.selection)
        self.selected_paragraph = None
        if self.selected_kind == '文字' and mode == '自动选择':
            # Auto mode behaves like Adobe: one click picks the whole cell/block.
            self.selected_paragraph = self.text_block_lines(page_lines, self.selected_line, page)
            if not self.selected_paragraph:
                self.selected_paragraph = text_edit.paragraph_at(full_text_lines(page), self.selected_line)
            if self.selected_paragraph:
                self.selection = fitz.Rect(self.selected_paragraph[0]['bbox'])
                for line in self.selected_paragraph[1:]:
                    self.selection |= fitz.Rect(line['bbox'])
                self.status.config(text=f'已选中整块文字（{len(self.selected_paragraph)} 行），拖动移动，双击整段编辑。')
        if self.selected_kind == '文字' and mode == '选择文本框':
            self.selected_paragraph = text_edit.paragraph_at(full_text_lines(page), self.selected_line)
            if self.selected_paragraph:
                for line in self.selected_paragraph:
                    self.selection |= fitz.Rect(line['bbox'])
        if self.selected_kind == '文字' and mode == '整块文字':
            self.selected_paragraph = self.text_block_lines(page_lines, self.selected_line, page)
            if self.selected_paragraph:
                self.selection = fitz.Rect(self.selected_paragraph[0]['bbox'])
                for line in self.selected_paragraph[1:]:
                    self.selection |= fitz.Rect(line['bbox'])
                self.status.config(text=f'已选中整块文字（{len(self.selected_paragraph)} 行），再点一下即可整段编辑。')
        if self.selected_kind == '文字': self.sync_text_format(page, None)
        if self.selected_kind == '文字':
            self.selection_lines = [fitz.Rect(item['bbox']) for item in (self.selected_paragraph or [self.selected_line]) if item]
        else:
            self.selection_lines = []
        r = self.selection
        self.draw_selection(r)
        if self.selected_object and self.selected_object.get('kind') == 'barcode':
            self.status.config(text='已选中条码图形整体，可拖动移动；边框保持独立。')
        else:
            self.status.config(text=f'已选中{self.selected_kind}。拖动框内移动；拖动角点缩放，Shift 保持比例。')

    def move_selected(self, dx, dy):
        if not self.doc or not self.selection or self.doc[self.page_index].rotation:
            return
        page = self.doc[self.page_index]
        old = fitz.Rect(self.selection)
        target = old + (dx, dy, dx, dy)
        original = self.doc.tobytes(garbage=0, deflate=True)
        try:
            if self.selected_kind == '文字':
                lines = self.selected_paragraph or [self.selected_line]
                if self.selected_block:
                    self.move_text_without_clipping(page, lines, (dx, dy), self.selected_block)
                else:
                    self.move_text_without_clipping(page, lines, (dx, dy))
            elif self.selected_kind in ('图片', '图形'):
                objects = page_objects.Objects(page)
                page_objects.move_to(page, self.selected_graphic_numbers(objects), old, target, objects)
            elif self.selected_kind == '区域':
                objects, ns, lines = self.area_contents(page, old)
                if not ns and not lines: raise ValueError('框内没有可移动的完整对象，请扩大选框。')
                if ns: page_objects.move_to(page, ns, old, target, objects)
                if lines: self.move_text_without_clipping(page, lines, (dx, dy))
            else:
                raise ValueError('请先选择对象。')
            kind = self.selected_kind
            was_box = self.selected_block is not None
            self.commit(original, self.dirty)
            if kind in ('图片', '图形') and self.reselect_graphic(target, kind):
                pass
            elif kind == '文字' and was_box:
                visible = target & self.doc[self.page_index].rect
                if not visible.is_empty:
                    self.select_object((visible.tl+visible.br)/2)
            elif kind == '文字':
                # Identify the moved lines by their own text and shifted baseline:
                # overlapping blocks share left edges, so geometry alone picks up
                # lines belonging to the block underneath.
                expected = [(fitz.Rect(ln['bbox']) + (dx, dy, dx, dy), text_edit.line_text(ln)) for ln in lines]
                current = full_text_lines(self.doc[self.page_index])
                moved = []
                for shifted, label in expected:
                    found = None
                    for rect, candidate in current:
                        if text_edit.line_text(candidate) == label and abs(rect.y0 - shifted.y0) <= 3:
                            found = candidate
                            break
                    if found is None:
                        for rect, candidate in current:
                            if text_edit.line_text(candidate) == label:
                                found = candidate
                                break
                    if found is not None:
                        moved.append(found)
                if moved:
                    self.remember_moved_text(self.page_index, expected)
                    self.selected_paragraph = moved
                    self.selected_line = moved[0]
                    self.selection = fitz.Rect(moved[0]['bbox'])
                    for ln in moved[1:]: self.selection |= fitz.Rect(ln['bbox'])
                    self.draw_selection(self.selection)
                elif self.reselect_text(target):
                    pass
            elif kind in ('文字', '图片', '图形'):
                visible = target & self.doc[self.page_index].rect
                if not visible.is_empty:
                    self.select_object(fitz.Point((visible.x0+visible.x1)/2, (visible.y0+visible.y1)/2))
                else:
                    self.status.config(text='内容已移到页面外，页面外部分不会显示；可用 Ctrl+Z 撤销。')
            else:
                self.selection, self.selected_kind = target, '区域'
                self.draw_selection(target)
        except Exception as exc:
            self.doc.close(); self.doc = fitz.open(stream=original, filetype='pdf'); self.show()
            messagebox.showerror('移动失败', str(exc))

    def move_text_without_clipping(self, page, lines, offset, block=None):
        """Expand page bounds during text removal so off-page glyphs are not lost."""
        bounds = fitz.Rect()
        for line in lines: bounds |= fitz.Rect(line['bbox'])
        if page.rect.contains(bounds):
            if block:
                styled, _ = added_text.contents(page, block)
                box = block.props['box'] + (*offset, *offset)
                added_text.rewrite(page, block, styled.text,
                    text_styles.runs_of(styled.text, styled.keys), box.width,
                    offset=offset, styled=styled, box=box)
            else:
                text_edit.move_lines(page, lines, offset)
            return
        doc, index = page.parent, page.number
        original_rect = fitz.Rect(page.rect)
        original_media = fitz.Rect(page.mediabox)
        original_crop = fitz.Rect(page.cropbox)
        box_keys = ('MediaBox', 'CropBox', 'BleedBox', 'TrimBox', 'ArtBox')
        saved_boxes = {key: doc.xref_get_key(page.xref, key) for key in box_keys}
        old_matrix = fitz.Matrix(page.transformation_matrix)
        pdf_bounds = bounds * ~old_matrix
        expanded = original_media | (pdf_bounds + (-8, -8, 8, 8))
        try:
            page.set_mediabox(expanded)
            new_matrix = fitz.Matrix(page.transformation_matrix)
            shift = fitz.Point(0, 0) * ~old_matrix * new_matrix
            def translate_markers(delta):
                by_stream = {}
                for marker in added_text.markers(page):
                    by_stream.setdefault(marker['xref'], []).append(marker)
                for xref, markers in by_stream.items():
                    data = doc.xref_stream(xref)
                    for marker in reversed(markers):
                        props = marker['props']
                        props['origin'] += delta
                        if props.get('box'):
                            props['box'] += (delta.x, delta.y, delta.x, delta.y)
                        start, end = marker['bdc']
                        data = data[:start] + added_text.marker(props) + data[end:]
                    doc.update_stream(xref, data)
            translate_markers(shift)
            candidates = full_text_lines(page)
            mapped = []
            for line in lines:
                old_box = fitz.Rect(line['bbox'])
                center = fitz.Point((old_box.x0+old_box.x1)/2, (old_box.y0+old_box.y1)/2)
                new_point = center * ~old_matrix * new_matrix
                expected = text_edit.line_text(line)
                options = [(r, candidate) for r, candidate in candidates
                           if (r + (-2,-2,2,2)).contains(new_point)
                           and text_edit.line_text(candidate) == expected]
                if not options: raise ValueError('无法完整定位页面外的文字，未进行移动。')
                chosen = min(options, key=lambda item:item[0].get_area())[1]
                mapped.append(chosen)
            if block:
                origin = fitz.Point(block.props['origin']) * ~old_matrix * new_matrix
                choices = added_text.find(page, candidates)
                mapped_block = min(choices, key=lambda item: abs(fitz.Point(item.props['origin'])-origin), default=None)
                if not mapped_block or abs(fitz.Point(mapped_block.props['origin'])-origin) > 2:
                    raise ValueError('无法完整定位页面外的文本框，未进行移动。')
                styled, _ = added_text.contents(page, mapped_block)
                box = mapped_block.props['box'] + (*offset, *offset)
                added_text.rewrite(page, mapped_block, styled.text,
                    text_styles.runs_of(styled.text, styled.keys), box.width,
                    offset=offset, styled=styled, box=box)
            else:
                text_edit.move_lines(page, mapped, offset)
        finally:
            xref = page.xref
            if 'new_matrix' in locals():
                translate_markers(-shift)
            page.set_mediabox(original_media)
            if page.cropbox != original_crop:
                page.set_cropbox(original_crop)
            for key, (kind, value) in saved_boxes.items():
                doc.xref_set_key(xref, key, value if kind != 'null' else 'null')
        if doc[index].rect != original_rect:
            raise ValueError('无法恢复页面尺寸，未进行移动。')

    def area_contents(self, page, rect):
        objects = page_objects.Objects(page)
        # Hairlines (page borders, table rules) have a zero-width/height rect; scaling
        # them through a matrix erases them, so they are never part of a box scale.
        selected = [item for item in objects.items
                    if rect.contains(fitz.Rect(item['rect']))
                    and fitz.Rect(item['rect']).width >= .5 and fitz.Rect(item['rect']).height >= .5]
        # Page-edge clipping must not exclude a line whose visible portion was
        # fully selected, even when its PDF glyph bounds extend off the page.
        text = [(bounds, line) for bounds, line in full_text_lines(page)
                if not (bounds & page.rect).is_empty and rect.contains(bounds & page.rect)]
        groups = [fitz.Rect(item['rect']) for item in selected if item.get('kind') == 'group']
        if any(group.intersects(bounds) for group in groups for bounds, line in text):
            raise ValueError('框内的组合对象与文字重叠，暂不能安全整体处理。请在“选择图片”模式下单独选择该对象。')
        return objects, [item['n'] for item in selected], [line for bounds, line in text]

    def text_block_lines(self, page_lines, line, page=None):
        """The contiguous text block around a line, for Adobe-like block select.

        Blocks stop at table rules and at lines with a different left edge, so a
        block moved on top of another one can still be picked separately.
        """
        base = fitz.Rect(line['bbox'])
        base_block = line.get('block_id')
        block_top = block_bottom = None
        if base_block is not None:
            extents = [fitz.Rect(item['bbox']) for rect, item in page_lines
                       if item.get('block_id') == base_block]
            if extents:
                block_top = min(item.y0 for item in extents)
                block_bottom = max(item.y1 for item in extents)
        rules = []
        if page is not None:
            for drawing in page.get_drawings():
                rect = fitz.Rect(drawing['rect'])
                if rect.height < 2.5 and rect.width > 20:
                    rules.append(rect)

        def separated(a, b):
            for rule in rules:
                if rule.y0 >= a.y1 - 1 and rule.y1 <= b.y0 + 1.5 and \
                        min(rule.x1, b.x1) - max(rule.x0, a.x0) > 0.4*min(a.width, b.width):
                    return True
            return False

        chosen = [line]
        changed = True
        while changed:
            changed = False
            bounds = fitz.Rect(chosen[0]['bbox'])
            for item in chosen[1:]:
                bounds |= fitz.Rect(item['bbox'])
            for rect, candidate in page_lines:
                if any(candidate is existing for existing in chosen): continue
                other_block = candidate.get('block_id')
                if base_block is not None and other_block is not None and other_block != base_block:
                    # Each PDF text block stays its own selectable block. Grouping
                    # across text objects is what merged a dragged block with the
                    # block underneath it; Adobe keeps them separate for the same
                    # reason, so do the same.
                    continue
                if abs(rect.x0 - base.x0) > max(3.0, 0.06*rect.width): continue
                gap = max(rect.y0 - bounds.y1, bounds.y0 - rect.y1)
                overlap = min(rect.x1, bounds.x1) - max(rect.x0, bounds.x0)
                if gap > max(6, rect.height*0.9): continue
                if overlap <= 0.3*min(rect.width, bounds.width): continue
                if rect.y1 < bounds.y0:
                    if separated(rect, bounds): continue
                else:
                    if separated(bounds, rect): continue
                chosen.append(candidate)
                changed = True
                break
        # Keep top-to-bottom order: the discovery loop can append lines out of order
        # and the editor would then write them back in the wrong order.
        chosen.sort(key=lambda item: (round(fitz.Rect(item['bbox']).y0, 1), fitz.Rect(item['bbox']).x0))
        return chosen
    def area_lines_partial(self, page, rect):
        """Text lines whose centre falls inside the box, even when they stick out.

        A hand-drawn box rarely contains a whole line, and refusing to scale then
        looks like 'vertical resize does nothing'. Scaling those lines keeps the
        common case (drag a box over a text block, then stretch it) working.
        """
        result = []
        for bounds, line in full_text_lines(page):
            centre = fitz.Point((bounds.x0+bounds.x1)/2, (bounds.y0+bounds.y1)/2)
            if rect.contains(centre):
                result.append(line)
        return result

    def scale_text_lines(self, page, lines, old, target):
        if any(not page.rect.contains(fitz.Rect(line['bbox'])) for line in lines):
            raise ValueError('文字有一部分在页面外，请先拖回页面内再缩放。')
        text_edit.refuse_with_marks(page)
        plans, styled, decor = text_edit._plan_lines(page, lines)
        text_edit._remove_lines(page, lines, decor=decor)
        previous_streams = set(page.get_contents())
        text_edit._write_lines(page, plans, styled, (0, 0))
        new_streams = [xref for xref in page.get_contents() if xref not in previous_streams]
        if not new_streams:
            raise ValueError('无法安全缩放这组文字，请撤销后单独选择。')
        sx, sy = target.width/old.width, target.height/old.height
        page_matrix = fitz.Matrix(1,0,0,1,-old.x0,-old.y0) * fitz.Matrix(sx,0,0,sy,target.x0,target.y0)
        to_page = page_objects.pdfcoords.to_page(page)
        pdf_matrix = to_page * page_matrix * ~to_page
        wrapper = ('q ' + ' '.join(f'{number:.10f}' for number in pdf_matrix) + ' cm\n').encode('ascii')
        for xref in new_streams:
            stream = page.parent.xref_stream(xref)
            page.parent.update_stream(xref, wrapper + stream + b'\nQ\n')

    def transform_selected(self, target, proportional=False):
        if not self.doc or not self.selection or self.doc[self.page_index].rotation:
            return
        if self.selected_object and self.selected_object.get('kind') == 'barcode':
            messagebox.showinfo('保护条码', '为避免改变条码线宽，请使用“框选区域”模式明确框选后再缩放。')
            self.draw_selection(self.selection)
            return
        old = fitz.Rect(self.selection)
        target = fitz.Rect(target)
        # A border line is a zero-width rect; dividing by it would produce an
        # infinite scale and erase the object. Give both rects a minimum size so
        # a pure vertical (or horizontal) stretch of a thin line works.
        def inflate(rect):
            if rect.width < .5:
                rect = fitz.Rect(rect.x0-(.5-rect.width)/2, rect.y0, rect.x1+(.5-rect.width)/2, rect.y1)
            if rect.height < .5:
                rect = fitz.Rect(rect.x0, rect.y0-(.5-rect.height)/2, rect.x1, rect.y1+(.5-rect.height)/2)
            return rect
        old, target = inflate(old), inflate(target)
        sx, sy = target.width/old.width, target.height/old.height
        if not all(math.isfinite(v) for v in (sx, sy)) or not (.02 <= sx <= 20 and .02 <= sy <= 20):
            messagebox.showinfo('无法缩放', '单次缩放比例需在 2% 到 2000% 之间。')
            self.selection = fitz.Rect(old)
            self.draw_selection(self.selection)
            return
        page = self.doc[self.page_index]
        original = self.doc.tobytes(garbage=0, deflate=True)
        converted_box = False
        kind_before = self.selected_kind
        selection_before = fitz.Rect(self.selection)
        try:
            if self.selected_kind == '文字':
                lines = self.selected_paragraph or [self.selected_line]
                if self.selected_block:
                    if any(not page.rect.contains(fitz.Rect(line['bbox'])) for line in lines):
                        raise ValueError('文本已有部分在页面外，暂不能安全调整；请使用撤销恢复。')
                    styled, _ = added_text.contents(page, self.selected_block)
                    size = styled.main.size * sx if proportional else None
                    rotation = self.selected_block.props['rotate'] % 360
                    if min(rotation, 360-rotation) > .01:
                        box = fitz.Rect(self.selected_block.props['box'])
                        old_center, new_center = (box.tl+box.br)/2, (target.tl+target.br)/2
                        new_box = fitz.Rect(new_center.x-box.width*sx/2, new_center.y-box.height*sy/2,
                                            new_center.x+box.width*sx/2, new_center.y+box.height*sy/2)
                        local = self.selected_block.props['origin'] * ~self.box_rotation_matrix(box, rotation)
                        local = fitz.Point(new_center.x+(local.x-old_center.x)*sx,
                                           new_center.y+(local.y-old_center.y)*sy)
                        origin = local * self.box_rotation_matrix(new_box, rotation)
                        added_text.rewrite(page, self.selected_block, styled.text,
                            text_styles.runs_of(styled.text, styled.keys), new_box.width,
                            size=size, styled=styled, box=new_box, origin_override=origin)
                    else:
                        added_text.rewrite(page, self.selected_block, styled.text,
                            text_styles.runs_of(styled.text, styled.keys), target.width,
                            offset=(target.x0-old.x0, target.y0-old.y0), size=size, styled=styled, box=target)
                elif proportional:
                    self.scale_text_lines(page, lines, old, target)
                else:
                    if any(not page.rect.contains(fitz.Rect(line['bbox'])) for line in lines):
                        raise ValueError('文字部分位于页面外，请先移回页面内再调整文本框。')
                    if any(abs(line['dir'][1]) > .01 for line in lines):
                        raise ValueError('旋转文字暂不能转换为可调整的文本框。')
                    styled = text_styles.read_paragraph(page, lines)
                    fonts, text, keys = text_styles.resolve_all(page, styled.text, styled.keys)
                    origin = fitz.Point(lines[0]['spans'][0]['origin']) + (target.x0-old.x0, target.y0-old.y0)
                    step = text_edit.paragraph_layout(lines)['step']
                    text_edit.refuse_with_marks(page)
                    text_edit._remove_lines(page, lines, decor=styled.decor)
                    added_text.write(page, origin, 0, text, keys, step, target.width, fonts=fonts, box=target)
                    converted_box = True
            elif self.selected_kind in ('图片', '图形'):
                object_rect = fitz.Rect((self.selected_object or {}).get('rect', self.selection))
                zero_w, zero_h = object_rect.width < .5, object_rect.height < .5
                # A zero-width border line may be stretched along its own axis (a
                # degenerate matrix would erase it), never across that axis.
                if (zero_w and abs(sx-1) > .01) or (zero_h and abs(sy-1) > .01):
                    raise ValueError('这条线是页面图形的一部分，暂不支持横向拉伸；请框选整块内容后再缩放。')
                objects = page_objects.Objects(page)
                page_objects.move_to(page, self.selected_graphic_numbers(objects), old, target, objects)
            elif self.selected_kind == '区域':
                objects, ns, lines = self.area_contents(page, old)
                partial = False
                if not ns and not lines:
                    # Nothing sat fully inside; fall back to the text whose centre is
                    # in the box so a hand-drawn box can still be stretched.
                    lines = self.area_lines_partial(page, old)
                    partial = bool(lines)
                if not ns and not lines: raise ValueError('框内没有可缩放的内容，请把框拉大一点再试。')
                if ns: page_objects.move_to(page, ns, old, target, objects)
                if lines: self.scale_text_lines(page, lines, old, target)
                if partial: self.status.config(text='已按框内文字缩放；要整块缩放请把框拉大包住完整内容。')
            else:
                raise ValueError('请先选择对象。')
            kind = self.selected_kind
            was_box = self.selected_block is not None or converted_box
            self.commit(original, self.dirty)
            if kind in ('图片', '图形') and self.reselect_graphic(target, kind):
                pass
            elif kind == '文字' and was_box:
                self.select_object((target.tl+target.br)/2)
            elif kind == '文字' and self.reselect_text(target):
                self.selection |= target
                self.draw_selection(self.selection)
            elif kind in ('文字', '图片', '图形'):
                visible = target & self.doc[self.page_index].rect
                if not visible.is_empty:
                    self.select_object(fitz.Point((visible.x0+visible.x1)/2, (visible.y0+visible.y1)/2))
                if not self.selection:
                    # A thin line cannot always be picked again by its centre; keep the
                    # box on the scaled area so it does not look like it vanished.
                    self.selection, self.selected_kind = fitz.Rect(target), kind
                    self.selected_object = None
                    self.draw_selection(self.selection)
            else:
                self.selection, self.selected_kind = target, '区域'
                self.draw_selection(target)
            self.status.config(text='调整完成。文字会随宽度换行；Shift 拖动角点等比例缩放。')
        except Exception as exc:
            self.doc.close(); self.doc = fitz.open(stream=original, filetype='pdf'); self.show()
            # Keep the box visible so the user can retry instead of losing the selection.
            self.selection, self.selected_kind = selection_before, kind_before
            if self.selection and not self.selection.is_empty: self.draw_selection(self.selection)
            messagebox.showerror('缩放失败', str(exc))

    def transform_oriented(self, quad, proportional=False):
        if not self.doc or not self.selection: return
        old_quad = self.drag_origin_quad
        a,b,_,d = old_quad
        x,y = b-a,d-a
        # A border line has a degenerate quad (zero area); inverting it would
        # destroy the path, so refuse instead of scaling.
        if abs(x.x*y.y - x.y*y.x) < 1e-6:
            messagebox.showinfo('无法缩放', '这条线是页面图形的一部分，暂不支持单独拉伸；请框选整块内容后再缩放。', parent=self.root)
            self.draw_selection(self.selection)
            return
        old_matrix = fitz.Matrix(x.x,x.y,y.x,y.y,a.x,a.y)
        a2,b2,_,d2 = quad
        x2,y2 = b2-a2,d2-a2
        if abs(x2.x*y2.y - x2.y*y2.x) < 1e-6:
            messagebox.showinfo('无法缩放', '拉伸后的选区过窄，请换一个方向拖动。', parent=self.root)
            self.draw_selection(self.selection)
            return
        new_matrix = fitz.Matrix(x2.x,x2.y,y2.x,y2.y,a2.x,a2.y)
        transform = ~old_matrix * new_matrix
        target = fitz.Rect(min(p.x for p in quad),min(p.y for p in quad),max(p.x for p in quad),max(p.y for p in quad))
        page = self.doc[self.page_index]
        original = self.doc.tobytes(garbage=0, deflate=True)
        kind = self.selected_kind
        try:
            if kind == '文字' and self.selected_block:
                block = self.selected_block
                if any(not page.rect.contains(fitz.Rect(line['bbox'])) for _,line in block.lines):
                    raise ValueError('文字部分在页面外，暂不能安全调整。')
                styled,_ = added_text.contents(page, block)
                box = fitz.Rect(block.props['box'])
                sx,sy = math.hypot(x2.x,x2.y)/math.hypot(x.x,x.y),math.hypot(y2.x,y2.y)/math.hypot(y.x,y.y)
                center = (quad[0]+quad[2])/2
                new_box = fitz.Rect(center.x-box.width*sx/2,center.y-box.height*sy/2,
                                    center.x+box.width*sx/2,center.y+box.height*sy/2)
                added_text.rewrite(page,block,styled.text,text_styles.runs_of(styled.text,styled.keys),
                    new_box.width,styled=styled,box=new_box,origin_override=block.props['origin']*transform,
                    size=styled.main.size*sx if proportional else None)
            elif kind in ('图片','图形'):
                objects = page_objects.Objects(page)
                page_objects.transform(page,self.selected_graphic_numbers(objects),transform,objects)
            else:
                raise ValueError('此对象暂不能沿旋转方向调整大小。')
            self.commit(original,self.dirty)
            if kind == '文字': self.select_object((quad[0]+quad[2])/2)
            else: self.reselect_graphic(target,kind)
            self.status.config(text='已沿对象方向调整大小，按 Ctrl+Z 可撤销。')
        except Exception as exc:
            self.doc.close(); self.doc = fitz.open(stream=original,filetype='pdf'); self.show()
            messagebox.showerror('调整大小失败',str(exc))

    def rotate_selected(self, degrees):
        if not self.doc or not self.selection or self.selected_kind not in ('文字', '图片', '图形'):
            return
        if self.selected_object and self.selected_object.get('kind') == 'barcode':
            messagebox.showinfo('保护条码', '如需旋转，请使用“框选区域”模式明确框选条码后操作。')
            self.draw_selection(self.selection)
            return
        page = self.doc[self.page_index]
        if page.rotation:
            messagebox.showinfo('无法旋转', '带页面旋转属性的 PDF 暂不支持对象旋转。')
            return
        old = fitz.Rect(self.selection)
        center = (old.tl + old.br) / 2
        matrix = fitz.Matrix(1,0,0,1,-center.x,-center.y) * fitz.Matrix(degrees) * fitz.Matrix(1,0,0,1,center.x,center.y)
        turned = [p * matrix for p in self.selection_quad()]
        target = fitz.Rect(min(p.x for p in turned),min(p.y for p in turned),max(p.x for p in turned),max(p.y for p in turned))
        original = self.doc.tobytes(garbage=0, deflate=True)
        kind = self.selected_kind
        try:
            if kind in ('图片', '图形'):
                objects = page_objects.Objects(page)
                page_objects.rotate(page, self.selected_graphic_numbers(objects), old, degrees, objects)
            else:
                lines = self.selected_paragraph or [self.selected_line]
                if any(not page.rect.contains(fitz.Rect(line['bbox'])) for line in lines):
                    raise ValueError('文字部分在页面外，暂不能安全旋转；请先将文字移回页面。')
                if self.selected_block:
                    block = self.selected_block
                    styled, _ = added_text.contents(page, block)
                    added_text.rewrite(page, block, styled.text, text_styles.runs_of(styled.text, styled.keys),
                        block.props['box'].width, styled=styled, box=block.props['box'],
                        rotation=block.props['rotate']-degrees, origin_override=block.props['origin'] * matrix)
                else:
                    if any(abs(line['dir'][1]) > .01 for line in lines):
                        raise ValueError('当前文字已倾斜，暂不能安全转换为文本框。')
                    styled = text_styles.read_paragraph(page, lines)
                    fonts, text, keys = text_styles.resolve_all(page, styled.text, styled.keys)
                    origin = fitz.Point(lines[0]['spans'][0]['origin']) * matrix
                    step = text_edit.paragraph_layout(lines)['step']
                    text_edit.refuse_with_marks(page)
                    text_edit._remove_lines(page, lines, decor=styled.decor)
                    added_text.write(page, origin, -degrees, text, keys, step, old.width, fonts=fonts, box=old)
            self.commit(original, self.dirty)
            if kind == '文字':
                self.select_object(center)
            else:
                self.reselect_graphic(target, kind)
            self.status.config(text='旋转完成；拖动上方圆点可继续旋转，按住 Shift 按 15° 对齐。')
        except Exception as exc:
            self.doc.close(); self.doc = fitz.open(stream=original, filetype='pdf'); self.show()
            messagebox.showerror('旋转失败', str(exc))

    def double_click(self, event):
        if not self.doc: return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if self.selection and self.rotation_handle_at(x, y):
            quad = self.selection_quad()
            edge = quad[1]-quad[0]
            angle = math.degrees(math.atan2(edge.y, edge.x))
            self.drag_start = None
            self.drag_kind = None
            if abs(angle) > .01: self.rotate_selected(-angle)
            else: self.draw_selection(self.selection)
            return 'break'
        if self.selection_type.get() not in ('自动选择', '选择文字', '选择文本框'): return
        self.drag_start = None
        point = fitz.Point((x-self.origin_x)/self.scale, (y-self.origin_y)/self.scale)
        word = self.word_at_point(point)
        self.select_object(point)
        if self.selected_kind == '文字':
            self.start_inline((x, y))
            # Preselect the clicked word so typing replaces just that word.
            if word and self.inline_editor and len(self.selected_paragraph or []) <= 1:
                try:
                    line_text = self.inline_editor.get('1.0', 'end-1c')
                    start = line_text.find(word[1])
                    if start >= 0:
                        self.inline_editor.tag_add('sel', '1.0+%dc' % start, '1.0+%dc' % (start + len(word[1])))
                        self.inline_editor.mark_set('insert', '1.0+%dc' % (start + len(word[1])))
                except tk.TclError:
                    pass

    def triple_click(self, event):
        """Triple click: select the text block (cell) around the pointer."""
        if not self.doc:
            return 'break'
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        point = fitz.Point((x - self.origin_x) / self.scale, (y - self.origin_y) / self.scale)
        page = self.doc[self.page_index]
        page_lines = full_text_lines(page)
        ranked = self.nearest_text_lines(page_lines, point)
        if not ranked:
            return 'break'
        rect, line = ranked[0]
        self.select_object(rect.tl + (0.5, 0.5))
        lines = self.text_block_lines(page_lines, line, page)
        if not lines:
            return 'break'
        self.selected_line = line
        self.selected_paragraph = lines
        self.selection = fitz.Rect(lines[0]['bbox'])
        for item in lines[1:]:
            self.selection |= fitz.Rect(item['bbox'])
        self.selection_lines = [fitz.Rect(item['bbox']) for item in lines]
        self.draw_selection(self.selection)
        self.status.config(text=f'已选中整块文字（{len(lines)} 行），双击整段编辑，拖动整块移动。')
        return 'break'

    def reselect_graphic(self, target, kind):
        if self.selected_object and self.selected_object.get('kind') == 'barcode':
            objects = page_objects.Objects(self.doc[self.page_index])
            group = self.barcode_group_at(objects, (target.tl+target.br)/2)
            if not group:
                possible = [item for item in objects.items if item.get('kind') == 'shape' and target.contains(fitz.Rect(item['rect']))]
                for item in possible[:20]:
                    rect = fitz.Rect(item['rect'])
                    group = self.matrix_group_at(objects, (rect.tl+rect.br)/2)
                    if group: break
            if group:
                self.selection, self.selected_kind, self.selected_object = group[0], kind, group[1]
                self.draw_selection(self.selection)
                return True
            return False
        wanted = ('shape',) if kind == '图形' else ('picture', 'group')
        objects = page_objects.Objects(self.doc[self.page_index])
        candidates = []
        for item in objects.items:
            if item.get('kind') not in wanted: continue
            rect = fitz.Rect(item['rect'])
            if rect.width < 2: rect.x0 -= 1; rect.x1 += 1
            if rect.height < 2: rect.y0 -= 1; rect.y1 += 1
            error = sum(abs(a-b) for a,b in zip(rect, target))
            candidates.append((error, rect, item))
        if not candidates: return False
        error, rect, item = min(candidates, key=lambda candidate:candidate[0])
        if error > 8: return False
        self.selection, self.selected_kind, self.selected_object = rect, kind, item
        self.draw_selection(rect)
        return True

    def reselect_text(self, target):
        candidates = [(rect, line) for rect, line in full_text_lines(self.doc[self.page_index])
                      if rect.intersects(target) and text_edit.visible(line)]
        if not candidates: return False
        rect, line = min(candidates, key=lambda item: abs(item[0].x0-target.x0)+abs(item[0].y0-target.y0))
        self.selection, self.selected_kind, self.selected_line = fitz.Rect(rect), '文字', line
        self.selected_object = None
        self.selected_paragraph = text_edit.paragraph_at(full_text_lines(self.doc[self.page_index]), line)
        for item in self.selected_paragraph or []:
            self.selection |= fitz.Rect(item['bbox'])
        self.draw_selection(self.selection)
        return True

    def selected_words(self):
        if self.inline_editor:
            messagebox.showinfo('正在编辑文字', '请先完成或取消文字编辑。')
            return []
        if not self.doc or not self.selection or self.selection.is_empty:
            messagebox.showinfo('框选文字', '请先用鼠标拖出矩形，框选需要编辑的文字。')
            return []
        if self.doc[self.page_index].rotation:
            messagebox.showinfo('暂不能编辑', '此页带有旋转属性，当前版本不能安全框选编辑。')
            return []
        words = [w for w in self.doc[self.page_index].get_text('words')
                 if self.selection.contains(fitz.Point((w[0]+w[2])/2, (w[1]+w[3])/2))]
        if not words:
            messagebox.showinfo('没有找到文字', '框选范围没有可编辑文字。扫描图片中的文字需要先识别。')
        return words

    def commit(self, original, previous_dirty):
        self.undo_data.append((original, previous_dirty, self.page_index))
        self.undo_data = self.undo_data[-10:]
        self.redo_data.clear()
        self.dirty = True
        self.show()

    def edit(self, replacement=None):
        words = self.selected_words()
        if not words: return
        page = self.doc[self.page_index]
        if replacement is not None and ('\n' in replacement or len({(w[5], w[6]) for w in words}) != 1):
            messagebox.showinfo('修改文字', '请只框选同一行的文字。')
            return
        if any(a.type[0] == fitz.PDF_ANNOT_REDACT for a in (page.annots() or [])):
            messagebox.showerror('暂不能编辑', '此页存在未应用的涂黑批注，请先用其他软件处理，避免误删内容。')
            return
        if replacement:
            bounds = fitz.Rect(words[0][:4])
            for word in words[1:]: bounds |= fitz.Rect(word[:4])
            size = max(5, bounds.height * .72)
            text_width = fitz.get_text_length(replacement, fontname='china-s', fontsize=size)
            if bounds.x0 + text_width > page.rect.x1:
                messagebox.showerror('文字过长', '新文字超出页面，请缩短文字。')
                return
            new_bounds = fitz.Rect(bounds.x0, bounds.y0, bounds.x0 + text_width, bounds.y1)
            other_words = [w for w in page.get_text('words') if w not in words]
            if any(new_bounds.intersects(fitz.Rect(w[:4])) for w in other_words):
                messagebox.showerror('文字过长', '新文字可能覆盖旁边的内容，请缩短文字或使用“添加文字”。')
                return
        original = self.doc.tobytes(garbage=0, deflate=True)
        previous_dirty = self.dirty
        try:
            rects = [fitz.Rect(w[:4]) for w in words]
            for rect in rects:
                rect.y0 += rect.height * .15
                rect.y1 -= rect.height * .15
                page.add_redact_annot(rect, fill=False, cross_out=False)
            page.apply_redactions(images=0, graphics=0)
            if replacement:
                rect = fitz.Rect(words[0][:4])
                for word in words[1:]: rect |= fitz.Rect(word[:4])
                size = max(5, rect.height * .72)
                page.insert_text((rect.x0, rect.y1-size*.2), replacement, fontsize=size, fontname='china-s')
            self.commit(original, previous_dirty)
        except Exception as exc:
            self.doc.close()
            self.doc = fitz.open(stream=original, filetype='pdf')
            self.show()
            messagebox.showerror('编辑失败', str(exc))

    def delete(self): self.edit()

    def delete_area(self):
        if self.inline_editor:
            messagebox.showinfo('正在编辑文字', '请先完成或取消文字编辑。')
            return
        if not self.doc or not self.selection or self.selection.is_empty:
            messagebox.showinfo('删除框选内容', '请先拖出矩形框选要删除的区域。')
            return
        page = self.doc[self.page_index]
        if page.rotation:
            messagebox.showinfo('暂不能编辑', '此页带有旋转属性，当前版本不能安全框选编辑。')
            return
        if any(a.type[0] == fitz.PDF_ANNOT_REDACT for a in (page.annots() or [])):
            messagebox.showerror('暂不能编辑', '此页存在未应用的涂黑批注，请先处理这些批注。')
            return
        if not messagebox.askyesno('删除框选内容', '删除框内完整包含的文字、图片和图形？\n部分碰到的内容会保留。'):
            return
        original = self.doc.tobytes(garbage=0, deflate=True)
        previous_dirty = self.dirty
        try:
            area = fitz.Rect(self.selection)
            objects = page_objects.Objects(page)
            numbers = [item['n'] for item in objects.items
                       if area.contains(fitz.Rect(item['rect']))]
            lines = [line for bounds, line in full_text_lines(page) if area.contains(bounds)]
            if not numbers and not lines:
                messagebox.showinfo('删除框选内容', '框内没有完整包含的内容，请调整框选范围。')
                return
            if numbers:
                page_objects.delete(page, numbers, objects)
            if lines:
                text_edit.refuse_with_marks(page)
                text_edit._remove_lines(page, lines)
            self.commit(original, previous_dirty)
        except Exception as exc:
            self.doc.close()
            self.doc = fitz.open(stream=original, filetype='pdf')
            self.show()
            messagebox.showerror('删除失败', str(exc))

    def replace(self):
        if self.inline_editor:
            self.inline_editor.focus_set()
            return
        if self.selected_kind == '文字' and self.selected_line is not None:
            self.start_inline()
            return
        if self.selected_kind == '文字' and self.selected_paragraph:
            self.replace_paragraph_dialog()
            return
        if self.selected_kind == '文字' and self.selected_line is not None:
            self.replace_line()
            return
        words = self.selected_words()
        if not words: return
        if len({(w[5], w[6]) for w in words}) != 1:
            self.edit_selected_text_group()
            return
        text = simpledialog.askstring('修改文字', '输入新文字（建议长度接近原文）：', initialvalue=' '.join(w[4] for w in words), parent=self.root)
        if text is not None: self.edit(text)

    def edit_selected_text_group(self):
        """Turn completely enclosed, horizontal PDF lines into one editable text box."""
        if not self.doc or not self.selection: return
        page = self.doc[self.page_index]
        area = fitz.Rect(self.selection)
        all_lines = full_text_lines(page)
        lines = []
        for bounds, line in all_lines:
            if not text_edit.visible(line): continue
            intersection = area & bounds
            if intersection.is_empty: continue
            if not (area + (-1,-1,1,1)).contains(bounds):
                messagebox.showinfo('框选多行文字', '框选范围切到了文字，请完整框住需要编辑的每一行。', parent=self.root)
                return
            if abs(line['dir'][0]-1) > .01 or abs(line['dir'][1]) > .01:
                messagebox.showinfo('框选多行文字', '暂时只能合并编辑水平文字，请先单独编辑旋转文字。', parent=self.root)
                return
            lines.append(line)
        if len(lines) < 2:
            messagebox.showinfo('框选多行文字', '请完整框选至少两行可识别的 PDF 文字。', parent=self.root); return
        for block in added_text.find(page, all_lines):
            if block.props.get('box') and self.block_bounds(block).intersects(area) and not (area+(-1,-1,1,1)).contains(self.block_bounds(block)):
                messagebox.showinfo('框选多行文字', '选区只包含现有文本框的一部分，请完整框选该文本框。', parent=self.root); return
        lines.sort(key=lambda line:(line['spans'][0]['origin'][1], fitz.Rect(line['bbox']).x0))
        self.selected_kind = '文字'; self.selected_line = lines[0]
        self.selected_paragraph = lines; self.selected_block = None; self.selected_object = None
        self.start_inline(explicit_group=True)

    def replace_line(self):
        line = self.selected_line
        old = text_edit.line_text(line)
        text = simpledialog.askstring('编辑文字', '修改选中的文字：', initialvalue=old, parent=self.root)
        if text is None or text == old: return
        page = self.doc[self.page_index]
        original = self.doc.tobytes(garbage=0, deflate=True)
        try:
            text_edit.replace_line(page, line, text, scan=None)
            self.commit(original, self.dirty)
        except Exception as exc:
            self.doc.close(); self.doc = fitz.open(stream=original, filetype='pdf'); self.show()
            messagebox.showerror('编辑失败', str(exc))

    def sync_text_format(self, page, block):
        try:
            style = added_text.contents(page, block)[0].main if block else text_styles.span_style(text_edit.main_span(self.selected_line))
            self.font_size_value.set(f'{style.size:g}')
            self.font_bold_value.set(bool(style.bold))
            self.font_italic_value.set(bool(style.italic))
        except (ValueError, TypeError, KeyError, AttributeError):
            pass

    def text_format_values(self):
        try:
            size = float(self.font_size_value.get())
            if not 3 <= size <= 200 or not math.isfinite(size): raise ValueError()
        except ValueError:
            raise ValueError('字号请输入 3 到 200 之间的数字。')
        return size, bool(self.font_bold_value.get()), bool(self.font_italic_value.get())

    def current_family(self):
        """The font family picked in the toolbar; '' means keep the original font."""
        value = (self.font_family_value.get() or '').strip()
        return '' if value in ('', '（默认字体）') else value

    RESOLVE_FALLBACKS = ('helv', 'tiro', 'cour', 'symb', 'zadb')

    def usable_family(self, page, text, family):
        """The family name that actually resolves for this text, '' when none does.

        Some families need their style word kept ("Times New Roman Regular"), and a
        Latin-only family cannot write Chinese at all; in that case returning '' keeps
        the text's own font instead of silently falling back to Helvetica.
        """
        if not family: return ''
        def resolves(name):
            try:
                font, _ = text_styles.resolve(page, text_styles.Style(family=name), text)
            except Exception:
                return False
            return not font.name.startswith(self.RESOLVE_FALLBACKS)
        if resolves(family): return family
        alternative = family + ' Regular'
        return alternative if resolves(alternative) else ''

    def font_color_int(self):
        return (self.font_color[0] << 16) | (self.font_color[1] << 8) | self.font_color[2]

    def set_font_color(self, rgb):
        self.font_color = tuple(int(v) for v in rgb)
        self.font_color_hex.set('#%02x%02x%02x' % self.font_color)
        self.font_color_explicit = True
        if hasattr(self, 'color_swatch'):
            self.color_swatch.configure(background=self.font_color_hex.get())
        self.change_text_style('color', self.font_color_int())

    def pick_font_color(self):
        chosen = colorchooser.askcolor(color=self.font_color_hex.get(), title='字体颜色', parent=self.root)
        if not chosen or not chosen[0]: return
        self.set_font_color(chosen[0])

    def change_text_size(self):
        self.font_size_dirty = False
        try:
            size, _, _ = self.text_format_values()
        except ValueError as exc:
            messagebox.showerror('文字格式', str(exc), parent=self.root)
            return
        self.change_text_style('size', size)

    def font_size_typed(self, event):
        if event.keysym not in ('Return', 'Tab', 'Up', 'Down', 'Left', 'Right', 'Escape'):
            self.font_size_dirty = True

    def font_size_focus_out(self, event):
        if self.font_size_dirty:
            self.change_text_size()

    def step_text_size(self, direction):
        try: size = float(self.font_size_value.get())
        except ValueError: size = 10
        sizes = [6,7,8,9,10,10.5,11,12,14,16,18,20,22,24,26,28,36,48,72,96,144,200]
        options = [n for n in sizes if n > size+0.001] if direction > 0 else [n for n in sizes if n < size-0.001]
        self.font_size_value.set(f'{(min(options) if direction > 0 else max(options)) if options else size:g}')
        self.change_text_size()

    def inline_style_tag(self, style):
        state, editor = self.inline_state, self.inline_editor
        tags = state.setdefault('style_tags', {})
        for name, value in tags.items():
            if value == style: return name
        name = 'fmt_' + str(len(tags))
        tags[name] = style
        color = '#%06x' % (style.color & 0xffffff)
        family = self.tk_family(style.family or style.font)
        display_scale = state.get('display_font_scale', 1.0)
        editor.tag_configure(name, foreground=color,
            font=(family, -max(1,round(style.size*self.scale*display_scale)),
                  'bold' if style.bold else 'normal', 'italic' if style.italic else 'roman'))
        editor.tag_raise('sel')
        return name

    def initialise_inline_styles(self, styled):
        state, editor = self.inline_state, self.inline_editor
        state['base_style'] = styled.main
        state['style_tags'] = {}
        pos = 0
        for part, style in text_styles.runs_of(styled.text, styled.keys):
            tag = self.inline_style_tag(style)
            editor.tag_add(tag, f'1.0+{pos}c', f'1.0+{pos+len(part)}c')
            pos += len(part)

    def inline_style_at(self, index):
        for name in reversed(self.inline_editor.tag_names(index)):
            if name in self.inline_state.get('style_tags', {}):
                return self.inline_state['style_tags'][name]
        defaults = self.inline_state.get('line_defaults')
        if defaults:
            row = max(0, int(self.inline_editor.index(index).split('.')[0])-1)
            return defaults[min(row, len(defaults)-1)]
        return self.inline_state['base_style']

    def change_text_style(self, field, value=None):
        if value is None:
            value = self.font_bold_value.get() if field == 'bold' else self.font_italic_value.get()
        if not self.inline_editor:
            self.apply_text_format()
            return
        editor, state = self.inline_editor, self.inline_state
        try:
            start, end = editor.index('sel.first'), editor.index('sel.last')
        except tk.TclError:
            messagebox.showinfo('文字格式', '请先在文字编辑区选中要修改的文字。', parent=self.root)
            editor.focus_set()
            return
        index = start
        while editor.compare(index, '<', end):
            following = editor.index(index+'+1c')
            style = self.inline_style_at(index)._replace(**{field:value})
            for name in state['style_tags']:
                editor.tag_remove(name, index, following)
            editor.tag_add(self.inline_style_tag(style), index, following)
            index = following
        state['format_changed'] = True
        editor.tag_add('sel', start, end)
        editor.focus_set()
        self.schedule_inline_layout()
        self.status.config(text='选中文字的格式已更新；点击页面空白处或按 Ctrl+Enter 完成编辑。')

    def inline_runs(self, text):
        keys = [self.inline_style_at(f'1.0+{i}c') for i in range(len(text))]
        return keys, text_styles.runs_of(text, keys)

    def apply_text_format(self):
        try:
            size, bold, italic = self.text_format_values()
        except ValueError as exc:
            messagebox.showerror('文字格式', str(exc), parent=self.root)
            return
        if self.inline_editor:
            self.inline_state['format'] = (size, bold, italic)
            self.inline_editor.config(font=('Arial', -max(1, round(size*self.scale)),
                                            'bold' if bold else 'normal', 'italic' if italic else 'roman'))
            self.inline_editor.focus_set()
            self.status.config(text='格式已设置；完成编辑后应用到整个文本框。')
            return
        if not self.doc or self.selected_kind != '文字' or not self.selected_line:
            messagebox.showinfo('文字格式', '请先选中文字或文本框，或先添加文本框。')
            return
        page = self.doc[self.page_index]
        original = self.doc.tobytes(garbage=0, deflate=True)
        target = fitz.Rect(self.selection)
        picked_family = self.current_family()
        color = self.font_color_int() if self.font_color_explicit else None
        def restyle(keys, text=''):
            family = self.usable_family(page, text, picked_family)
            changed = [k._replace(bold=bold, italic=italic) for k in keys]
            if family: changed = [k._replace(family=family) for k in changed]
            if color is not None: changed = [k._replace(color=color) for k in changed]
            return changed, family
        try:
            if self.selected_block:
                styled, _ = added_text.contents(page, self.selected_block)
                keys, family = restyle(styled.keys, styled.text)
                box = self.selected_block.props['box']
                added_text.rewrite(page, self.selected_block, styled.text, text_styles.runs_of(styled.text, keys),
                                   box.width, size=size, styled=styled, box=box)
                is_box = True
            else:
                lines = self.selected_paragraph or [self.selected_line]
                styled = text_styles.read_paragraph(page, lines)
                keys, family = restyle(styled.keys, styled.text)
                text_edit.replace_paragraph(page, lines, styled.text, wrap_width=max(target.width, 2),
                    size=size, runs=text_styles.runs_of(styled.text, keys), decor=styled.decor)
                is_box = False
            self.commit(original, self.dirty)
            if is_box: self.select_object((target.tl+target.br)/2)
            else: self.reselect_text(target)
            if picked_family and not family:
                self.status.config(text=f'字体“{picked_family}”写不出所选文字，已保持原字体；字号和颜色已应用。')
            else:
                self.status.config(text='文字格式已应用；可使用 Ctrl+Z 撤销。')
        except Exception as exc:
            self.doc.close(); self.doc = fitz.open(stream=original, filetype='pdf'); self.show()
            messagebox.showerror('文字格式设置失败', str(exc), parent=self.root)

    def tk_family(self, name):
        """Map a PDF font name ('ArialMT', 'ABCDEF+SegoeUI-Bold') to a Tk family."""
        raw = (name or '').split('+')[-1].split(',')[0].strip()
        families = {item.lower(): item for item in tkfont.families()}
        candidates = [raw]
        aliases = {'simhei': '黑体', 'simsun': '宋体', 'fangsong': '仿宋',
                   'kaiti': '楷体', 'microsoftyahei': 'Microsoft YaHei'}
        alias = aliases.get(raw.lower().replace(' ', '').replace('-', ''))
        if alias: candidates.insert(0, alias)
        if raw.lower().endswith('mt'): candidates.append(raw[:-2])
        candidates.append(raw.split('-')[0])
        for candidate in candidates:
            key = candidate.strip().lower()
            if key in families: return families[key]
        for key, display in families.items():
            if key and (key.startswith(raw.lower()) or raw.lower().startswith(key)):
                return display
        return 'Arial'

    def begin_space_pan(self, event=None):
        """Hold Space to grab the page and drag it, like Adobe/Photoshop."""
        if self.inline_editor is not None:
            return
        if event is not None and isinstance(event.widget, (tk.Text, tk.Entry, ttk.Entry, ttk.Combobox)):
            return
        self.space_pan = True
        self.canvas.config(cursor='hand2')
        return 'break'

    def end_space_pan(self, event=None):
        self.space_pan = False
        if self.drag_kind != 'pan':
            self.canvas.config(cursor='')

    def draw_inline_box(self):
        """Keep a visible frame around the text being edited."""
        state = self.inline_state
        if not state or 'window' not in state:
            return
        self.canvas.delete('inline-box')
        coords = self.canvas.coords(state['window'])
        if len(coords) < 2:
            return
        # Take the canvas window's actual pixel bounds. Its native child is
        # always above canvas items, so draw the dashes outside that window.
        left, top, right, bottom = self.canvas.bbox(state['window'])
        self.canvas.create_rectangle(left-1, top-1, right+1, bottom+1,
                                     outline='#0056b3', width=1, dash=(5, 3), tags='inline-box')
        self.canvas.tag_raise('inline-editor')
        state['frame'].lift()

    def fit_editor_font_size(self, sample, line_rect, family, guess):
        """Pick the pixel size whose rendered width best matches the page line.

        The editor draws the same words with a system font; if that font is a pixel
        wider or narrower than the PDF's, the overlay text slides away from the page
        text and the caret looks misplaced. Matching the measured width keeps the
        editor on top of the original letters.
        """
        from tkinter import font as tkfont
        if not sample or line_rect is None or line_rect.width <= 0:
            return guess
        target = line_rect.width * self.scale
        best, best_error = guess, None
        for size in range(max(6, guess - 4), guess + 5):
            try:
                width = tkfont.Font(family=family, size=-size).measure(sample)
            except tk.TclError:
                continue
            error = abs(width - target)
            if best_error is None or error < best_error:
                best, best_error = size, error
        return best

    def create_inline_widget(self, rect, font_size, wrap, family='Arial', color='#000000'):
        frame = tk.Frame(self.canvas, borderwidth=0, highlightthickness=0)
        editor = tk.Text(frame, wrap=wrap, undo=True, font=(family, -max(1, font_size)),
                         background='white', foreground=color, insertbackground='#0056b3',
                         selectbackground='#176bc0', selectforeground='#ffffff',
                         borderwidth=0, relief='flat', padx=1, pady=0,
                         highlightthickness=0, exportselection=False)
        editor.bind('<<Copy>>', self.capture_inline_copy, add='+')
        vbar = SlimScrollbar(frame, orient='vertical', command=editor.yview)
        editor.configure(yscrollcommand=vbar.set)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        editor.grid(row=0, column=0, sticky='nsew')
        width = max(24, round(rect.width*self.scale)+2)
        height = max(font_size+4, round(rect.height*self.scale)+2)
        left, top, right, bottom = self.inline_page_bounds(self.page_index)
        x = min(right-1, max(left, round(self.origin_x+rect.x0*self.scale)))
        y = min(bottom-1, max(top, round(self.origin_y+rect.y0*self.scale)))
        window = self.canvas.create_window(x, y, anchor='nw', window=frame,
            width=min(width, right-x), height=min(height, bottom-y), state='hidden', tags='inline-editor')
        return editor, {'frame':frame, 'window':window, 'vbar':vbar,
                        'base_width':width, 'base_height':height, 'wrap':wrap}

    def inline_page_bounds(self, page):
        x, y, w, h = self.page_layout[page]
        # Leave room for the dashed stroke so it doesn't spill into the margin.
        left, top = round(x)+2, round(y)+2
        return left, top, max(left+1, round(x)+w-2), max(top+1, round(y)+h-2)

    def schedule_inline_layout(self, event=None):
        if not self.inline_editor or not self.inline_state: return
        if event is not None and not self.inline_editor.edit_modified(): return
        state = self.inline_state
        if state.get('layout_job'): return
        state['layout_job'] = self.root.after_idle(self.update_inline_layout)

    def update_inline_layout(self):
        if not self.inline_editor or not self.inline_state: return
        editor, state = self.inline_editor, self.inline_state
        state['layout_job'] = None
        try:
            left, top, right, bottom = self.inline_page_bounds(state['page'])
            preview = state.get('original_view')
            value = editor.get('1.0', 'end-1c')
            unchanged = value == state['old'] and not state.get('format_changed')
            if not unchanged:
                for tag in editor.tag_names():
                    if tag.startswith('pdf_line_spacing_'):
                        editor.tag_remove(tag, '1.0', 'end')
            draft = self.inline_draft_preview(value) if preview is not None and not unchanged else None
            show_pdf = preview is not None and (unchanged or draft is not None)
            x, y = state.get('original_position' if show_pdf else 'input_position',
                             self.canvas.coords(state['window']))
            x, y = min(right-1, max(left, round(x))), min(bottom-1, max(top, round(y)))
            self.canvas.coords(state['window'], x, y)
            max_width, max_height = right-x, bottom-y
            width = min(max_width, state['base_width'])
            height = min(max_height, state['base_height'])
            state['vbar'].grid_remove()
            if draft:
                _, rows = draft
                rightmost = max(row[1].x1 for row in rows)
                lowest = max(row[1].y1 for row in rows)
                width = min(max_width, max(width, math.ceil(self.origin_x+rightmost*self.scale-x)+2))
                height = min(max_height, max(height, math.ceil(self.origin_y+lowest*self.scale-y)+2))
            if not show_pdf:
                if preview is not None:
                    preview.place_forget()
                # Native word wrapping also breaks tokens longer than an entire row.
                # Original PDF lines can use the remaining page width. Created
                # text boxes keep their own width.
                original_overflow = any(fitz.Rect(line['bbox']).x1 > self.doc[state['page']].rect.x1
                                        for line in state.get('lines', []))
                editor.configure(wrap='none' if original_overflow else 'word')
                if state.get('lines') and not state.get('block') and not unchanged:
                    width = max_width
                self.canvas.itemconfigure(state['window'], width=width, height=height)
                editor.update_idletasks()
                count = editor.count('1.0', 'end', 'ypixels')
                wanted_height = (count[0] if count else 0)+2
                height = min(max_height, max(height, wanted_height))
                self.canvas.itemconfigure(state['window'], height=height)
                editor.update_idletasks()
                if editor.yview() != (0.0, 1.0) and width > 20:
                    state['vbar'].grid(row=0, column=1, sticky='ns')
                editor.see('insert')
            else:
                editor.configure(wrap=state['wrap'])
            self.canvas.itemconfigure(state['window'], width=width, height=height)
            # A hidden canvas window has no bounding box. Map it before
            # cropping the PDF preview, otherwise the preview stays blank.
            self.canvas.itemconfigure(state['window'], state='normal')
            if show_pdf:
                state['rendered_rows'] = draft[1] if draft else state['original_rows']
                state['rendered_photo'] = draft[0] if draft else None
                preview.place(x=0, y=0, relwidth=1, relheight=1)
                preview.tk.call('raise', str(preview))
                self.draw_inline_original()
            self.draw_inline_box()
            editor.edit_modified(False)
        except tk.TclError:
            if self.inline_editor is editor:
                preview = state.get('original_view')
                if preview is not None:
                    preview.place_forget()
                self.draw_inline_box()

    def inline_pdf_chars(self, raw, line):
        expected = text_edit.line_text(line)
        bounds = fitz.Rect(line['bbox'])
        choices = []
        for block in raw.get('blocks', []):
            for item in block.get('lines', []):
                rect = fitz.Rect(item['bbox'])
                error = sum(abs(a-b) for a,b in zip(rect,bounds))
                if error > 2: continue
                chars = [char for span in item.get('spans', []) for char in span.get('chars', [])]
                if ''.join(c.get('c','') for c in chars) == expected:
                    choices.append((error, chars))
        return min(choices, key=lambda item:item[0])[1] if choices else []

    def precise_line_index(self, page, line, point):
        """Use PDF glyph geometry for a single line; fall back when extraction differs."""
        raw = page.get_text('rawdict', clip=fitz.INFINITE_RECT())
        chars = self.inline_pdf_chars(raw, line)
        if not chars:
            return text_edit.line_index(line, point)
        direction = fitz.Point(line['dir'])
        projected = point.x*direction.x + point.y*direction.y
        for i, char in enumerate(chars):
            rect = fitz.Rect(char['bbox'])
            center = (rect.tl+rect.br)/2
            if projected < center.x*direction.x+center.y*direction.y:
                return i
        return len(chars)

    def precise_block_index(self, page, starts, text, point):
        if not starts: return len(text)
        def distance(item):
            line = item[2]
            rect = fitz.Rect(line['bbox'])
            x = max(rect.x0-point.x, 0, point.x-rect.x1)
            y = max(rect.y0-point.y, 0, point.y-rect.y1)
            direction = fitz.Point(line['dir'])
            origin = fitz.Point(line['spans'][0]['origin'])
            perpendicular = abs((point.x-origin.x)*(-direction.y)+(point.y-origin.y)*direction.x)
            return (math.hypot(x,y), perpendicular)
        start, removed, line = min(starts, key=distance)
        offset = self.precise_line_index(page, line, point)-removed
        ends = [len(text)] + [s for s, _, _ in starts if s > start]
        newline = text.find('\n', start)
        if newline >= 0: ends.append(newline)
        return max(start, min(start+max(0,offset), min(ends)))

    def inline_pdf_rows(self, page, value, starts):
        raw = page.get_text('rawdict', flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES,
                            clip=fitz.INFINITE_RECT())
        rows = []
        for i, (start, skip, line) in enumerate(starts):
            text = text_edit.line_text(line)
            stop = starts[i+1][0] if i+1 < len(starts) else len(value)
            length = min(len(text)-skip, stop-start)
            while length > 0 and value[start+length-1] == '\n':
                length -= 1
            if length <= 0:
                continue
            chars = self.inline_pdf_chars(raw, line)[skip:skip+length]
            if not chars or abs(line['dir'][1]) > .01 or line['dir'][0] < .99:
                continue
            rect = fitz.Rect(line['bbox'])
            edges = [fitz.Rect(char['bbox']).x0 for char in chars]
            edges.append(fitz.Rect(chars[-1]['bbox']).x1)
            rows.append((start, rect, edges))
        return rows

    def setup_inline_original(self, page, starts):
        """Keep the same page pixels visible while the original text is untouched."""
        editor, state = self.inline_editor, self.inline_state
        if state['page'] not in self.page_photos:
            return
        rows = self.inline_pdf_rows(page, state['old'], starts)
        if not rows:
            return
        preview = tk.Canvas(state['frame'], borderwidth=0, highlightthickness=0, cursor='xterm',
                            takefocus=False)
        state.update(original_view=preview, original_rows=rows)
        for sequence, action in (('<Button-1>', 'click'), ('<Shift-Button-1>', 'extend'),
                                 ('<B1-Motion>', 'drag'), ('<Double-Button-1>', 'word'),
                                 ('<Triple-Button-1>', 'line')):
            preview.bind(sequence, lambda event, action=action: self.click_inline_original(event, action))
        preview.bind('<Button-3>', self.inline_context_menu)
        preview.bind('<MouseWheel>', self.mouse_wheel)
        editor.bind('<KeyRelease>', lambda event: self.draw_inline_original(), add='+')
        editor.bind('<<Selection>>', lambda event: self.draw_inline_original(), add='+')

    def inline_draft_preview(self, value):
        """Render straightforward replacements with the same PDF writer used for saving."""
        state = self.inline_state
        index = state['page']
        parts = value.split('\n')
        lines = state['lines']
        _, _, width, height = self.page_layout[index]
        if (len(parts) != len(lines) or any(not part.strip() for part in parts)
                or len(value) > 2000 or len(self.doc) > 8 or width*height > 4_000_000):
            return None
        try:
            keys, runs = self.inline_runs(value)
            cache_key = (value, tuple(keys))
            if state.get('draft_key') == cache_key:
                return state.get('draft')
            state.update(draft_key=cache_key, draft=None)
            if 'draft_base' not in state:
                state['draft_base'] = self.doc.tobytes(garbage=0)
            if len(state['draft_base']) > 12_000_000:
                return None
            with fitz.open(stream=state['draft_base'], filetype='pdf') as document:
                page = document[index]
                self.write_inline_text(page, state, value, keys, runs)
                candidates = [line for _, line in full_text_lines(page)]
                starts, start = [], 0
                previous_y = -math.inf
                for old, part in zip(lines, parts):
                    ox, oy = old['spans'][0]['origin']
                    offset = 0
                    while offset < len(part):
                        matches = []
                        for item in candidates:
                            gx, gy = item['spans'][0]['origin']
                            content = text_edit.line_text(item).rstrip()
                            if (gy <= previous_y+.1 or gy > page.rect.y1 or abs(gx-ox) >= 1
                                    or not content or not part.startswith(content, offset)):
                                continue
                            rank = abs(gy-oy) if offset == 0 else gy-previous_y
                            matches.append((rank, gy, item, len(content)))
                        if not matches:
                            return None
                        _, previous_y, line, length = min(matches, key=lambda item: item[:2])
                        starts.append((start+offset, 0, line))
                        offset += length
                        while offset < len(part) and part[offset] == ' ':
                            offset += 1
                    start += len(part)+1
                rows = self.inline_pdf_rows(page, value, starts)
                if len(rows) != len(starts) or any(rect.x1 > page.rect.x1+.5 for _, rect, _ in rows):
                    return None
                pix = page.get_pixmap(matrix=fitz.Matrix(self.scale, self.scale), alpha=False)
                photo = ImageTk.PhotoImage(Image.frombytes('RGB', (pix.width, pix.height), pix.samples))
            state['draft'] = (photo, rows)
            return state['draft']
        except (RuntimeError, ValueError, tk.TclError):
            return None

    def click_inline_original(self, event, action):
        editor, state = self.inline_editor, self.inline_state
        x, y = self.canvas.coords(state['window'])
        px = (x+event.x-self.origin_x)/self.scale
        py = (y+event.y-self.origin_y)/self.scale
        start, rect, edges = min(state['rendered_rows'],
                                 key=lambda row: abs(py-(row[1].y0+row[1].y1)/2))
        column = min(range(len(edges)), key=lambda i: abs(edges[i]-px))
        index = editor.index(f'1.0+{start+column}c')
        anchor = state.get('original_anchor', editor.index('insert'))
        editor.tag_remove('sel', '1.0', 'end')
        if action in ('extend', 'drag'):
            first, last = sorted((anchor, index), key=lambda item: tuple(map(int, item.split('.'))))
            editor.tag_add('sel', first, last)
        elif action == 'word':
            word = editor.index(index + ('-1c' if column == len(edges)-1 else ''))
            editor.tag_add('sel', word+' wordstart', word+' wordend')
            index = editor.index(word+' wordend')
        elif action == 'line':
            editor.tag_add('sel', index+' linestart', index+' lineend')
            index = editor.index(index+' lineend')
        if action != 'drag' and action != 'extend':
            state['original_anchor'] = index
        editor.mark_set('insert', index)
        editor.focus_set()
        self.draw_inline_original()
        return 'break'

    def draw_inline_original(self):
        editor, state = self.inline_editor, self.inline_state
        if not editor or not state:
            return
        preview = state.get('original_view')
        if preview is None or preview.winfo_manager() != 'place':
            return
        x, y, right, bottom = self.canvas.bbox(state['window'])
        page_x, page_y, _, _ = self.page_layout[state['page']]
        source = self.page_photos.get(state['page']) or state.get('original_photo_source')
        if source is None:
            return
        state['original_photo_source'] = source
        source = state.get('rendered_photo') or source
        crop = (x-round(page_x), y-round(page_y), right-round(page_x), bottom-round(page_y))
        if (source, crop) != state.get('original_crop'):
            photo = tk.PhotoImage(master=preview)
            photo.tk.call(str(photo), 'copy', str(source), '-from', *crop)
            state.update(original_crop=(source, crop), original_photo=photo)
            preview.delete('original')
            preview.create_image(0, 0, image=photo, anchor='nw', tags='original')
            preview.tag_lower('original')
        preview.delete('original-caret')
        def offset(index):
            count = editor.count('1.0', index, 'chars')
            return count[0] if count else 0
        insert = offset('insert')
        selected = editor.tag_ranges('sel')
        first, last = map(offset, selected[:2]) if selected else (0, 0)
        def local_x(value): return page_x+value*self.scale-x
        for start, rect, edges in state['rendered_rows']:
            end = start+len(edges)-1
            top = page_y+rect.y0*self.scale-y
            base = page_y+rect.y1*self.scale-y
            a, b = max(first, start), min(last, end)
            if a < b:
                preview.create_rectangle(local_x(edges[a-start]), top, local_x(edges[b-start]), base,
                                         fill='#176bc0', stipple='gray25', outline='', tags='original-caret')
            if start <= insert <= end and not selected:
                caret = local_x(edges[insert-start])
                preview.create_line(caret, top, caret, base, fill='#0056b3', width=2, tags='original-caret')

    def start_inline(self, click=None, explicit_group=False):
        if self.inline_editor or not self.selected_line or not self.selection:
            return
        lines = self.selected_paragraph or [self.selected_line]
        page = self.doc[self.page_index]
        block = self.selected_block
        block_content, starts = added_text.contents(page, block) if block else (None, [])
        # Any multi-line pick must be edited as a group; the single-line path joins
        # the lines with spaces and would destroy the block on write-back.
        if not explicit_group and not self.selected_block and len(lines) > 1:
            explicit_group = True
        if explicit_group:
            pieces = text_styles.read_lines(self.doc[self.page_index], lines)
            old = '\n'.join(part.text for part in pieces)
            keys, decor = [], []
            for i, part in enumerate(pieces):
                if i: keys.append(keys[-1] if keys else part.main)
                keys.extend(part.keys); decor.extend(part.decor)
            styled = text_styles.Styled(old, keys, decor, pieces[0].main)
        else:
            old = block_content.text if block else text_edit.line_text(lines[0])
        if not block:
            start = 0
            for line in lines:
                starts.append((start, 0, line))
                start += len(text_edit.line_text(line))+1
        rect = fitz.Rect(self.selection)
        main = text_edit.main_span(lines[0])
        font_size = max(10, round(main['size'] * self.scale))
        # Existing PDF lines already have positions; do not invent extra line
        # breaks just because the editor and PDF have slightly different metrics.
        # Explicit line breaks must stay on their original lines even when Tk's
        # glyph widths are a little larger than the PDF's, especially at 72 pt.
        # Keep word wrapping for blocks containing genuine soft-wrapped rows.
        wrap = 'word' if self.selected_block and len(lines) > len(old.split('\n')) else 'none'
        family = self.tk_family(main.get('font', ''))
        # Match the overlay width to the page line so the caret sits on the letter
        # the user clicked instead of drifting along the line. Compare the same
        # line on both sides: the widest line of the block and its own PDF box.
        text_parts = old.split('\n') if old else []
        probe_index, probe_width = 0, 0.0
        for index, item in enumerate(lines[:len(text_parts)]):
            width = fitz.Rect(item['bbox']).width
            if width > probe_width:
                probe_index, probe_width = index, width
        if text_parts and probe_index < len(text_parts):
            font_size = self.fit_editor_font_size(text_parts[probe_index], fitz.Rect(lines[probe_index]['bbox']),
                                                  family, font_size)
        color = '#%06x' % (int(main.get('color') or 0) & 0xffffff)
        editor, layout = self.create_inline_widget(rect, font_size, wrap, family, color)
        self.canvas.delete('selection')
        editor.insert('1.0', old)
        editor.edit_reset()
        editor.focus_set()
        if click:
            # The PDF glyph boxes say which letter the pointer is on; the editor's own
            # font metrics drift over a long line, so translate through the PDF first.
            point = fitz.Point((click[0]-self.origin_x)/self.scale, (click[1]-self.origin_y)/self.scale)
            if self.selected_block:
                index = self.precise_block_index(self.doc[self.page_index], starts, old, point)
            elif len(lines) == 1:
                index = self.precise_line_index(self.doc[self.page_index], lines[0], point)
            else:
                # Which line did the click land on? Measure that line's glyphs
                # (accurate) and add the offset of the line inside the block text.
                clicked_index, best_gap = 0, None
                for position, line in enumerate(lines):
                    box = fitz.Rect(line['bbox'])
                    gap = 0.0 if box.y0 - 2 <= point.y <= box.y1 + 2 else min(abs(point.y - box.y0),
                                                                             abs(point.y - box.y1))
                    if best_gap is None or gap < best_gap:
                        clicked_index, best_gap = position, gap
                offset = sum(len(text_edit.line_text(item)) + 1 for item in lines[:clicked_index])
                index = offset + self.precise_line_index(self.doc[self.page_index], lines[clicked_index], point)
            editor.mark_set('insert', f'1.0+{max(0, min(index, len(old)))}c')
        else:
            editor.mark_set('insert', 'end-1c')
        editor.bind('<Control-Return>', lambda event: (self.apply_inline(), 'break')[1])
        editor.bind('<Escape>', lambda event: (self.cancel_inline(), 'break')[1])
        editor.bind('<Button-3>', self.inline_context_menu)
        self.inline_editor = editor
        self.inline_state = {'lines': lines, 'old': old, 'page': self.page_index, 'block':self.selected_block,
                             'display_font_scale': font_size / max(1, main['size'] * self.scale), **layout}
        self.inline_state['original_position'] = self.canvas.coords(layout['window'])
        if explicit_group:
            bases = [float(line['spans'][0]['origin'][1]) for line in lines]
            steps = sorted(b-a for a,b in zip(bases,bases[1:]) if b-a > .1)
            self.inline_state.update({'kind':'group', 'rect':rect,
                'origin':fitz.Point(lines[0]['spans'][0]['origin']),
                'step':steps[len(steps)//2] if steps else styled.main.size*1.2,
                'decor':styled.decor, 'line_defaults':[part.main for part in pieces]})
        else:
            styled = block_content if block else text_styles.read_paragraph(page, lines)
        if styled.text != old:
            styled = styled._replace(text=old, keys=text_styles.restyle(styled.text, styled.keys, old, styled.main))
        self.initialise_inline_styles(styled)
        # PDF bounding boxes include font-dependent space above the baseline;
        # Tk uses different font metrics. Align the first baseline rather than
        # the top of the two bounding boxes so editing doesn't visibly jump.
        if lines and lines[0].get('spans'):
            try:
                first_tag = next((tag for tag in editor.tag_names('1.0')
                                  if tag in self.inline_state['style_tags']), None)
                face = tkfont.Font(font=editor.tag_cget(first_tag, 'font') if first_tag else editor.cget('font'))
                desired_y = self.origin_y + lines[0]['spans'][0]['origin'][1] * self.scale
                editor.update_idletasks()
                line_info = editor.dlineinfo('1.0')
                baseline = line_info[1] + line_info[4] if line_info else face.metrics('ascent')
                x, _ = self.canvas.coords(layout['window'])
                self.canvas.coords(layout['window'], x, desired_y - baseline)
                # A PDF may position lines farther apart than Tk's default line
                # height. Preserve that extra space for the original lines.
                for index, (line, following) in enumerate(zip(lines, lines[1:]), 1):
                    if not following.get('spans'): continue
                    row = editor.dlineinfo(f'{index}.0')
                    if not row: continue
                    advance = (following['spans'][0]['origin'][1] - line['spans'][0]['origin'][1]) * self.scale
                    extra = round(advance - row[3])
                    if extra > 0:
                        name = f'pdf_line_spacing_{index}'
                        editor.tag_configure(name, spacing3=extra)
                        editor.tag_add(name, f'{index}.0', f'{index}.end+1c')
            except (tk.TclError, ValueError, IndexError):
                pass
        self.inline_state['input_position'] = self.canvas.coords(layout['window'])
        self.setup_inline_original(page, starts)
        editor.edit_modified(False)
        editor.bind('<<Modified>>', self.schedule_inline_layout)
        self.schedule_inline_layout()
        self.status.config(text='在页面上直接修改文字；Enter 换行，Ctrl+Enter 完成，Esc 取消。')

    def start_new_text_inline(self, rect):
        self.canvas.config(cursor='')
        self.canvas.delete('selection')
        family = self.current_family() or 'Arial'
        color = self.font_color_hex.get() if self.font_color_explicit else '#000000'
        try: text_format = self.text_format_values()
        except ValueError: text_format = (10, False, False)
        # Type at the size the toolbar shows, so the preview and the committed text match.
        editor, layout = self.create_inline_widget(rect, max(8, round(text_format[0]*self.scale)), 'word', family, color)
        self.inline_editor = editor
        self.inline_state = {'kind':'new', 'rect':fitz.Rect(rect), 'old':'', 'page':self.page_index, 'format':text_format, **layout}
        size, bold, italic = text_format
        family = self.current_family()
        rgb = tuple(v / 255 for v in self.font_color) if self.font_color_explicit else (0, 0, 0)
        style = text_styles.add_style(family, bold, italic, size, rgb)
        if self.font_color_explicit:
            editor.configure(foreground=self.font_color_hex.get())
        if family:
            try: editor.configure(font=(family, -max(1, round(size*self.scale))))
            except tk.TclError: pass
        self.initialise_inline_styles(text_styles.Styled('', [], [], style))
        editor.edit_modified(False)
        editor.bind('<<Modified>>', self.schedule_inline_layout)
        self.schedule_inline_layout()
        editor.bind('<Control-Return>', lambda event: (self.apply_inline(), 'break')[1])
        editor.bind('<Escape>', lambda event: (self.cancel_inline(), 'break')[1])
        editor.bind('<Button-3>', self.inline_context_menu)
        editor.focus_set()
        self.status.config(text='输入文本，Ctrl+Enter 完成；Esc 取消。')

    def inline_context_menu(self, event):
        menu = theme.menu(self.root)
        for label, command in [('复制    Ctrl+C', '<<Copy>>'), ('粘贴    Ctrl+V', '<<Paste>>'), ('剪切    Ctrl+X', '<<Cut>>')]:
            menu.add_command(label=label, command=lambda cmd=command: self.inline_editor.event_generate(cmd))
        menu.add_command(label='删除    Delete', command=self.delete_inline_selection)
        menu.add_separator()
        menu.add_command(label='完成编辑', command=self.apply_inline)
        menu.add_command(label='取消编辑', command=self.cancel_inline)
        try: menu.tk_popup(event.x_root, event.y_root)
        finally: menu.grab_release()
        return 'break'

    def delete_inline_selection(self):
        if not self.inline_editor: return
        try:
            self.inline_editor.delete('sel.first', 'sel.last')
        except tk.TclError:
            self.inline_editor.delete('insert')
        self.inline_editor.focus_set()

    def cancel_inline(self):
        if self.inline_editor:
            state = self.inline_state or {}
            if state.get('layout_job'): self.root.after_cancel(state['layout_job'])
            state.get('frame', self.inline_editor).destroy()
            self.canvas.delete('inline-box')
            self.inline_editor = None
            self.inline_state = None
            self.show()
        return True

    def write_plain_inline_lines(self, page, lines, parts, available_width, follow_line=False):
        """Wrap at the page edge and preserve the original gaps inside this text block."""
        if follow_line and '\n' not in parts[0] and abs(lines[0]['dir'][1]) < .01:
            line = lines[0]
            width = available_width(line['spans'][0]['origin'][0])
            if text_edit.plain_line_row_count(page, line, parts[0], width) > 1:
                page_lines = full_text_lines(page)
                matching = next((item for _, item in page_lines
                                 if item['bbox'] == line['bbox'] and text_edit.line_text(item) == text_edit.line_text(line)), None)
                if matching is not None:
                    baseline = line['spans'][0]['origin'][1]
                    following = [item for item in self.text_block_lines(page_lines, matching, page)
                                 if item['spans'][0]['origin'][1] > baseline+.1]
                    lines = [line, *following]
                    parts = [parts[0], *(text_edit.line_text(item) for item in following)]
        changes = []
        offset = 0.0
        for line, part in zip(lines, parts):
            changed = part != text_edit.line_text(line)
            if not changed and not offset:
                continue
            origin = line['spans'][0]['origin']
            width = available_width(origin[0]) if changed else None
            changes.append((line, part, offset, width))
            count = text_edit.plain_line_row_count(page, line, part, width) if changed else 1
            extra = (count-1)*1.2*text_edit.main_span(line)['size']
            if (offset or extra) and origin[1]+offset+extra > page.rect.y1-.5:
                raise ValueError('自动换行后超出页面底部，请调小字号或把文字移到有足够空间的位置。')
            offset += extra
        # Move the lower original lines first, so their removal cannot touch a
        # newly written continuation from a line above them.
        for line, part, dy, width in reversed(changes):
            text_edit.replace_line(page, line, part, offset=(0, dy), scan=None, wrap_width=width)

    def write_inline_text(self, page, state, text, keys, runs):
        # Never write a paragraph back in a different order than it was read.
        if len(state.get('lines') or []) > 1:
            state = {**state, 'lines': sorted(state['lines'],
                                    key=lambda item: (round(fitz.Rect(item['bbox']).y0, 1),
                                                      fitz.Rect(item['bbox']).x0))}
        lines = state.get('lines', [])
        page_right = page.rect.x1 - 0.5
        def available_width(x):
            original_right = max((fitz.Rect(line['bbox']).x1 for line in lines
                                  if abs(line['spans'][0]['origin'][0]-x) < 1), default=page_right)
            # If the source already extends beyond the page, preserve its
            # existing line when inserting a small amount of text.
            right = max(page_right, original_right + (text_edit.main_span(lines[0])['size'] if original_right > page_right else 0))
            return max(1, right-x)
        para_wrap = available_width(min(line['spans'][0]['origin'][0] for line in lines)) if lines else None
        if state.get('kind') == 'new':
            size = state['base_style'].size
            rect = state['rect']
            added_text.write(page, (rect.x0, rect.y0+size), 0, text,
                             keys, size*1.2, rect.width, box=rect)
        elif state.get('kind') == 'group':
            text_edit.refuse_with_marks(page)
            parts = text.split('\n')
            # Fidelity first: when the line count did not change, rewrite every
            # line at its own baseline with its own font and size. Nothing but
            # the edited glyphs moves (measured: baseline/font/size deltas 0.000).
            keep_layout = (len(parts) == len(lines) and all(part.strip() for part in parts)
                           and not state.get('format_changed') and len(set(keys)) <= 1
                           and all(not text_edit.mixed_styles(line) for line in lines))
            if keep_layout:
                self.write_plain_inline_lines(page, lines, parts, available_width)
            else:
                if text:
                    added_text._refuse(text)
                    fonts, resolved_text, resolved_keys = text_styles.resolve_all(page, text, keys)
                text_edit._remove_lines(page, lines, decor=state.get('decor', ()))
                if text:
                    rect, origin = state['rect'], state['origin']
                    wrap = available_width(origin.x)
                    rect = fitz.Rect(rect)
                    rows = text_styles.wrap(list(zip(resolved_text, resolved_keys)), fonts, wrap)
                    widths = [pieces[-1][3] for row, _, _ in rows
                              if (pieces := text_styles.pieces(text_styles.strip_row(row), fonts))]
                    rect.x1 = min(page_right, max(rect.x1, origin.x+max(widths, default=0)))
                    rect.y1 = max(rect.y1, origin.y + (len(rows)-1)*state['step'] + keys[0].size*.3)
                    added_text.write(page, origin, 0, resolved_text, resolved_keys, state['step'],
                                     wrap, fonts=fonts, box=rect)
        elif state.get('block'):
            block = state['block']
            styled, _ = added_text.contents(page, block)
            box = block.props['box']
            width = box.width
            if not block.props['rotate']:
                width = min(width, available_width(block.props['origin'].x))
            added_text.rewrite(page, block, text, runs, width, styled=styled, box=box)
        elif state.get('format_changed') or len(set(keys)) > 1:
            styled = text_styles.read_paragraph(page, state['lines'])
            text_edit.replace_paragraph(page, state['lines'], text, runs=runs,
                                        decor=styled.decor, wrap_width=para_wrap)
        elif len(state['lines']) > 1:
            # Write the whole paragraph in reading order; the engine keeps the
            # line breaks. Wrap at the page edge (not at the original box width),
            # otherwise adding one character wraps a long line into two.
            text_edit.replace_paragraph(page, state['lines'], text, wrap_width=para_wrap)
        else:
            # Keep the edited line inside the page: without a wrap width a long
            # insertion becomes one line that runs off the paper.
            line = state['lines'][0]
            wrap = available_width(line['spans'][0]['origin'][0])
            body = text.rstrip('\n')
            if '\n' in body:
                # Enter inside a single-line edit means a real paragraph break;
                # writing it as one line would overflow and overlap the next line.
                text_edit.replace_paragraph(page, state['lines'], body, wrap_width=wrap)
            else:
                if body.strip():
                    self.write_plain_inline_lines(page, [line], [body], available_width, follow_line=True)
                else:
                    text_edit.replace_line(page, line, body, scan=None, wrap_width=wrap)

    def apply_inline(self):
        if not self.inline_editor: return True
        editor, state = self.inline_editor, self.inline_state
        text = editor.get('1.0', 'end-1c')
        if text == state['old'] and not state.get('format_changed'):
            return self.cancel_inline()
        original = self.doc.tobytes(garbage=0, deflate=True)
        previous_dirty = self.dirty
        try:
            page = self.doc[state['page']]
            keys, runs = self.inline_runs(text)
            self.write_inline_text(page, state, text, keys, runs)
            if state.get('layout_job'): self.root.after_cancel(state['layout_job'])
            state.get('frame', editor).destroy()
            self.canvas.delete('inline-box')
            self.inline_editor = None
            self.inline_state = None
            self.commit(original, previous_dirty)
            return True
        except Exception as exc:
            self.doc.close()
            self.doc = fitz.open(stream=original, filetype='pdf')
            messagebox.showerror('编辑失败', str(exc), parent=self.root)
            return False

    def replace_paragraph_dialog(self):
        lines = self.selected_paragraph
        old = text_edit.paragraph_text(lines)
        dialog = tk.Toplevel(self.root)
        dialog.title('编辑文本框')
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text='修改文本框内容：').pack(anchor='w', padx=10, pady=6)
        editor = tk.Text(dialog, width=65, height=8, wrap='word', undo=True)
        editor.pack(fill='both', expand=True, padx=10)
        editor.insert('1.0', old)
        editor.focus_set()
        def apply():
            text = editor.get('1.0', 'end-1c')
            if text == old:
                dialog.destroy()
                return
            original = self.doc.tobytes(garbage=0, deflate=True)
            try:
                text_edit.replace_paragraph(self.doc[self.page_index], lines, text)
                self.commit(original, self.dirty)
                dialog.destroy()
            except Exception as exc:
                self.doc.close(); self.doc = fitz.open(stream=original, filetype='pdf'); self.show()
                messagebox.showerror('编辑失败', str(exc), parent=dialog)
        buttons = ttk.Frame(dialog)
        buttons.pack(pady=10)
        ttk.Button(buttons, text='确定', command=apply).pack(side='left', padx=5)
        ttk.Button(buttons, text='取消', command=dialog.destroy).pack(side='left', padx=5)

    def _finish_editing_for_history(self):
        """Apply or drop an open inline editor; never block undo with a dialog."""
        if self.inline_editor is None:
            return True
        try:
            if not self.inline_editor.winfo_exists():
                self.inline_editor = None
                return True
            return bool(self.apply_inline())
        except tk.TclError:
            self.inline_editor = None
            return True
        except Exception:
            self.inline_editor = None
            return True

    def undo(self):
        if not self._finish_editing_for_history():
            return
        if not self.undo_data:
            self.status.config(text='没有可撤销的操作。')
            return
        try:
            self.redo_data.append((self.doc.tobytes(garbage=0, deflate=True), self.dirty, self.page_index))
            data, self.dirty, self.page_index = self.undo_data.pop()
            self.dirty = True
            self.moved_text_marks = []
            self.doc.close()
            self.doc = fitz.open(stream=data, filetype='pdf')
            self.show()
            self.canvas.focus_set()
            self.status.config(text=f'已撤销（还可撤销 {len(self.undo_data)} 步）。')
        except Exception as exc:
            self.status.config(text=f'撤销失败：{exc}')

    def redo(self):
        if not self._finish_editing_for_history():
            return
        if not self.redo_data:
            self.status.config(text='没有可重做的操作。')
            return
        try:
            self.undo_data.append((self.doc.tobytes(garbage=0, deflate=True), self.dirty, self.page_index))
            data, self.dirty, self.page_index = self.redo_data.pop()
            self.dirty = True
            self.moved_text_marks = []
            self.doc.close()
            self.doc = fitz.open(stream=data, filetype='pdf')
            self.show()
            self.canvas.focus_set()
            self.status.config(text=f'已重做（还可重做 {len(self.redo_data)} 步）。')
        except Exception as exc:
            self.status.config(text=f'重做失败：{exc}')

    def selected_rect(self):
        if self.inline_editor:
            messagebox.showinfo('正在编辑文字', '请先完成或取消文字编辑。')
            return None
        if not self.doc or not self.selection or self.selection.is_empty:
            messagebox.showinfo('请先框选', '请在页面上拖出要添加内容的位置。')
            return None
        if self.doc[self.page_index].rotation:
            messagebox.showinfo('暂不能编辑', '此页带有旋转属性，当前版本不能安全框选编辑。')
            return None
        return fitz.Rect(self.selection)

    def context_menu(self, event):
        if self.doc:
            page = self.page_at_canvas_point(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
            if page is not None and page != self.page_index:
                if self.inline_editor and not self.apply_inline(): return
                self.activate_canvas_page(page)
        point = fitz.Point((self.canvas.canvasx(event.x)-self.origin_x)/self.scale,
                           (self.canvas.canvasy(event.y)-self.origin_y)/self.scale) if self.doc else None
        paste_point = point if point is not None and (not self.selection or not self.selection.contains(point)) else None
        menu = theme.menu(self.root)
        menu.add_command(label='复制    Ctrl+C', command=self.copy_area)
        menu.add_command(label='粘贴    Ctrl+V', command=lambda:self.paste_area(paste_point))
        menu.add_command(label='剪切    Ctrl+X', command=self.cut_area)
        menu.add_command(label='删除    Delete', command=self.delete_selected)
        menu.add_separator()
        menu.add_command(label='裁剪选中图片', command=self.crop_image)
        menu.add_command(label='删除框选内容', command=self.delete_area)
        menu.add_command(label='删除选中图片', command=self.delete_selected_image)
        menu.add_command(label='修改框选文字', command=self.replace)
        menu.add_separator()
        menu.add_command(label='撤销    Ctrl+Z', command=self.undo)
        menu.add_command(label='重做    Ctrl+Y', command=self.redo)
        try: menu.tk_popup(event.x_root, event.y_root)
        finally: menu.grab_release()

    def copy_area(self):
        rect = self.selected_rect()
        if rect is None: return False
        try:
            self.clipboard_box = None
            self.clipboard_box_geometry = None
            if self.selected_kind == '文字' and self.selected_block:
                styled, _ = added_text.contents(self.doc[self.page_index], self.selected_block)
                self.clipboard_box = (styled.text, list(styled.keys), self.selected_block.props['step'])
                self.clipboard_box_geometry = {'box':fitz.Rect(self.selected_block.props['box']),
                    'origin':fitz.Point(self.selected_block.props['origin']),
                    'rotation':self.selected_block.props['rotate'], 'bounds':fitz.Rect(rect)}
            elif self.selected_kind == '文字' and self.selected_line:
                lines = self.selected_paragraph or [self.selected_line]
                if all(abs(line['dir'][1]) < .01 for line in lines):
                    styled = text_styles.read_paragraph(self.doc[self.page_index], lines)
                    self.clipboard_box = (styled.text, list(styled.keys), text_edit.paragraph_layout(lines)['step'])
                    self.clipboard_box_geometry = {'box':fitz.Rect(rect),
                        'origin':fitz.Point(lines[0]['spans'][0]['origin']), 'rotation':0, 'bounds':fitz.Rect(rect)}
            clip = fitz.open()
            target = clip.new_page(width=rect.width, height=rect.height)
            target.show_pdf_page(target.rect, self.doc, self.page_index, clip=rect)
            self.clipboard_pdf = clip.tobytes(garbage=4, deflate=True)
            clip.close()
            self.clipboard_size = (rect.width, rect.height)
            self.clipboard_sequence = ctypes.windll.user32.GetClipboardSequenceNumber()
            try:
                asset = self.asset_clipboard_data()
                self.auto_add_copied_asset(asset)
            except Exception as exc:
                self.status.config(text='已复制，但未能加入素材栏：'+str(exc))
            return True
        except Exception as exc:
            messagebox.showerror('复制失败', str(exc))
            return False

    def select_inserted(self, rect, kind):
        self.selection_type.set('选择文字' if kind == '文字' else '选择图片')
        point = fitz.Point((rect.x0+rect.x1)/2, (rect.y0+rect.y1)/2)
        self.select_object(point)

    def cut_area(self):
        if not self.copy_area(): return
        self.delete_selected()

    def delete_selected(self):
        if not self.doc or not self.selection:
            messagebox.showinfo('删除', '请先选中需要删除的内容。')
            return
        if self.selected_kind == '区域':
            self.delete_area()
            return
        if self.selected_kind not in ('文字', '图片', '图形'):
            return
        if not messagebox.askyesno('确认删除', '确定删除选中的内容吗？'):
            return
        page = self.doc[self.page_index]
        original = self.doc.tobytes(garbage=0, deflate=True)
        try:
            if self.selected_kind == '文字':
                lines = self.selected_paragraph or [self.selected_line]
                if any(not page.rect.contains(fitz.Rect(line['bbox'])) for line in lines):
                    raise ValueError('文字有部分在页面外，暂不能安全删除。')
                if self.selected_block:
                    styled, _ = added_text.contents(page, self.selected_block)
                    added_text.rewrite(page, self.selected_block, '', None, self.selection.width, styled=styled)
                else:
                    styled = text_styles.read_paragraph(page, lines)
                    text_edit.refuse_with_marks(page)
                    text_edit._remove_lines(page, lines, decor=styled.decor)
            else:
                objects = page_objects.Objects(page)
                page_objects.delete(page, self.selected_graphic_numbers(objects), objects)
            self.commit(original, self.dirty)
        except Exception as exc:
            self.doc.close(); self.doc = fitz.open(stream=original, filetype='pdf'); self.show()
            messagebox.showerror('删除失败', str(exc))

    def paste_area(self, target_point=None):
        if self.inline_editor:
            messagebox.showinfo('正在编辑文字', '请先完成或取消文字编辑。')
            return
        if not self.doc: return
        if self.doc[self.page_index].rotation:
            messagebox.showinfo('暂不能编辑', '此页带有旋转属性，当前版本不能安全粘贴。')
            return
        sequence = ctypes.windll.user32.GetClipboardSequenceNumber()
        internal = self.clipboard_pdf is not None and sequence == self.clipboard_sequence
        if target_point is None and self.selection and not self.selection.is_empty:
            rect = fitz.Rect(self.selection)
        else:
            width, height = self.clipboard_size if internal and self.clipboard_size else (100,50)
            page_rect = self.doc[self.page_index].rect
            if target_point is None:
                center = (page_rect.tl+page_rect.br)/2
                target_point = fitz.Point(center.x-width/2, center.y-height/2)
            rect = fitz.Rect(target_point.x,target_point.y,target_point.x+width,target_point.y+height)
        if self.clipboard_pdf is None or sequence != self.clipboard_sequence:
            self.paste_system_clipboard(rect)
            return
        if self.clipboard_pdf is None:
            messagebox.showinfo('粘贴', '请先在本程序中框选并复制内容。')
            return
        original = self.doc.tobytes(garbage=0, deflate=True)
        try:
            if self.clipboard_box:
                self.write_clipboard_text(self.doc[self.page_index],rect,self.clipboard_box,
                                          self.clipboard_box_geometry,fit_selection=target_point is None)
            else:
                clip = fitz.open(stream=self.clipboard_pdf, filetype='pdf')
                self.doc[self.page_index].show_pdf_page(rect, clip, 0, keep_proportion=True)
                clip.close()
            self.commit(original, self.dirty)
            if self.clipboard_box:
                self.selection_type.set('自动选择')
                self.select_object((rect.tl+rect.br)/2)
            else:
                self.select_inserted(rect, '图片')
        except Exception as exc:
            self.doc.close(); self.doc = fitz.open(stream=original, filetype='pdf'); self.show()
            messagebox.showerror('粘贴失败', str(exc))

    def paste_system_clipboard(self, rect):
        try:
            image = ImageGrab.grabclipboard()
            if isinstance(image, list):
                files = [Path(x) for x in image if Path(x).suffix.lower() in ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff')]
                if files: image = Image.open(files[0])
            if isinstance(image, Image.Image):
                if image.width * image.height > 40_000_000: raise ValueError('图片过大，请先缩小后再粘贴。')
                data = io.BytesIO()
                image.save(data, format='PNG')
                original = self.doc.tobytes(garbage=0, deflate=True)
                try:
                    self.doc[self.page_index].insert_image(rect, stream=data.getvalue(), keep_proportion=True)
                    self.commit(original, self.dirty)
                    self.select_inserted(rect, '图片')
                except Exception:
                    self.doc.close(); self.doc = fitz.open(stream=original, filetype='pdf'); self.show()
                    raise
                return
            text = None
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                    text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
            if not text:
                messagebox.showinfo('粘贴', '剪贴板中没有支持的文字或图片。')
                return
            size = simpledialog.askfloat('粘贴文字', '字号（磅）：', initialvalue=10, minvalue=3, maxvalue=100, parent=self.root)
            if size is None: return
            original = self.doc.tobytes(garbage=0, deflate=True)
            try:
                key = text_styles.add_style(size=size)
                with fitz.open() as probe:
                    test_page = probe.new_page(width=rect.width,height=rect.height)
                    added_text.write(test_page,(0,size),0,text,[key]*len(text),size*1.2,rect.width,
                                     box=fitz.Rect(0,0,rect.width,rect.height))
                    allowed = fitz.Rect(-1,-1,rect.width+1,rect.height+1)
                    if any(not allowed.contains(bounds) for bounds,_ in full_text_lines(test_page)):
                        raise ValueError('文字放不进选框，请增大选框或缩小字号。')
                added_text.write(self.doc[self.page_index],(rect.x0,rect.y0+size),0,text,
                                 [key]*len(text),size*1.2,rect.width,box=rect)
                self.commit(original, self.dirty)
                self.selection_type.set('自动选择')
                self.select_object((rect.tl+rect.br)/2)
            except Exception:
                self.doc.close(); self.doc = fitz.open(stream=original, filetype='pdf'); self.show()
                raise
        except Exception as exc:
            messagebox.showerror('粘贴失败', str(exc))

    def delete_selected_image(self):
        if self.selected_kind != '图片' or self.selection is None:
            messagebox.showinfo('选择图片', '请先选择“选择图片”模式，再点击图片。')
            return
        page = self.doc[self.page_index]
        if any(a.type[0] == fitz.PDF_ANNOT_REDACT for a in (page.annots() or [])):
            messagebox.showerror('暂不能编辑', '此页存在未应用的涂黑批注，请先处理这些批注。')
            return
        if not messagebox.askyesno('删除图片', '删除选中位置的图片？与其重叠的其他图片也可能受影响。'):
            return
        original = self.doc.tobytes(garbage=0, deflate=True)
        try:
            page.add_redact_annot(self.selection, fill=False, cross_out=False)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS, graphics=0, text=1)
            self.selected_kind = None
            self.commit(original, self.dirty)
        except Exception as exc:
            self.doc.close(); self.doc = fitz.open(stream=original, filetype='pdf'); self.show()
            messagebox.showerror('删除图片失败', str(exc))

    def add_text(self):
        if not self.doc:
            messagebox.showinfo('添加文本框', '请先打开 PDF。')
            return
        if self.inline_editor and not self.apply_inline(): return
        if self.selected_kind == '区域' and self.selection:
            self.start_new_text_inline(fitz.Rect(self.selection))
        else:
            self.placing_text = True
            self.canvas.config(cursor='crosshair')
            self.status.config(text='请在页面上点击或拖出文本框，然后直接输入文字。')

    def selected_image_pixels(self):
        item = self.selected_object or {}
        if self.selected_kind != '图片' or item.get('kind') not in ('picture','group') or not item.get('xref'):
            raise ValueError('请先在“选择图片”或“自动选择”模式下选择要裁剪的图片或粘贴内容。')
        if item.get('kind') == 'group':
            return self.render_group_preview(item['xref'])
        doc = self.doc
        xref = item['xref']
        info = doc.extract_image(xref)
        if not info: raise ValueError('无法读取这张图片。')
        pix = fitz.Pixmap(doc,xref)
        if pix.width*pix.height > 40_000_000:
            raise ValueError('图片超过 4000 万像素，暂不能安全裁剪。')
        if pix.colorspace and pix.colorspace.n > 3:
            pix = fitz.Pixmap(fitz.csRGB,pix)
        mask = info.get('smask',0)
        if mask and not pix.alpha:
            pix = fitz.Pixmap(pix,fitz.Pixmap(doc,mask))
        image = Image.open(io.BytesIO(pix.tobytes('png')))
        image.load()
        return image

    def render_group_preview(self, xref):
        """Render only this Form, never the page behind it, for the crop dialog."""
        with fitz.open(stream=self.doc.tobytes(garbage=0,deflate=True),filetype='pdf') as clone:
            box, matrix = page_objects._form_box(clone,xref)
            if box is None: raise ValueError('无法读取该粘贴对象的边界。')
            if abs(matrix.a*matrix.d-matrix.b*matrix.c) < 1e-10:
                raise ValueError('该对象的变换无法安全裁剪。')
            preview = clone.new_page(width=box.width,height=box.height)
            page_objects._set_resource(clone,preview.xref,'XObject','CropPreview',f'{xref} 0 R')
            transform = ~matrix * fitz.Matrix(1,0,0,1,-box.x0,-box.y0)
            content = ('q '+' '.join(f'{v:.12g}' for v in transform)+' cm /CropPreview Do Q').encode('ascii')
            stream = clone.get_new_xref(); clone.update_object(stream,'<<>>'); clone.update_stream(stream,content)
            preview.set_contents(stream)
            factor = min(3,2000/max(box.width,box.height),math.sqrt(4_000_000/(box.width*box.height)))
            pix = preview.get_pixmap(matrix=fitz.Matrix(factor,factor),alpha=True)
            image = Image.open(io.BytesIO(pix.tobytes('png')))
            image.load()
            return image

    def apply_image_crop(self, image, crop):
        if not self.doc or not self.selection or not self.selected_object: return False
        x0,y0,x1,y1 = map(int,crop)
        w,h = image.size
        if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
            raise ValueError('请选择图片内的有效裁剪区域。')
        if (x0,y0,x1,y1) == (0,0,w,h): return True
        page = self.doc[self.page_index]
        original = self.doc.tobytes(garbage=0,deflate=True)
        try:
            objects = page_objects.Objects(page)
            numbers = self.selected_graphic_numbers(objects)
            if len(numbers) != 1: raise ValueError('组合对象暂不能直接裁剪。')
            item = next((it for it in objects.items if it['n'] == numbers[0]),None)
            if not item or item.get('kind') not in ('picture','group') or not item.get('xref'):
                raise ValueError('当前对象不是可裁剪的图片或粘贴内容。')
            q = item['quad']
            top_left, top_right, bottom_left = q.ll, q.lr, q.ul
            ux,uy = top_right-top_left,bottom_left-top_left
            corners = [top_left+ux*(x/w)+uy*(y/h) for x,y in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))]
            target = fitz.Rect(min(p.x for p in corners),min(p.y for p in corners),
                               max(p.x for p in corners),max(p.y for p in corners))
            if item.get('kind') == 'group':
                form_box, _ = page_objects._form_box(self.doc,item['xref'])
                if form_box is None: raise ValueError('无法读取粘贴内容的边界。')
                new_box = fitz.Rect(form_box.x0+form_box.width*x0/w,
                                    form_box.y1-form_box.height*y1/h,
                                    form_box.x0+form_box.width*x1/w,
                                    form_box.y1-form_box.height*y0/h)
                new_xref = self.doc.get_new_xref()
                self.doc.update_object(new_xref,'<<>>')
                self.doc.xref_copy(item['xref'],new_xref)
                self.doc.xref_set_key(new_xref,'BBox','['+' '.join(f'{v:.12g}' for v in new_box)+']')
                page_objects._own_resources(page)
                taken = page_objects._res_entries(self.doc,page.xref,'Resources/XObject')
                key = f'Crop{new_xref}'
                while key in taken: key += 'x'
                page_objects._set_resource(self.doc,page.xref,'XObject',key,f'{new_xref} 0 R')
                name = ('/'+key).encode('ascii')
                def group_replacement(old, ctm):
                    state,_ = page_objects._split(old)
                    return state+b' '+name+b' Do\n'
                page_objects._edit(page,numbers,group_replacement,objects)
                self.commit(original,self.dirty)
                self.reselect_graphic(target,'图片')
                self.status.config(text='粘贴内容已裁剪；原有图形保持矢量，可按 Ctrl+Z 撤销。')
                return True
            output = io.BytesIO()
            image.crop((x0,y0,x1,y1)).save(output,format='PNG')
            new_xref = page.insert_image(fitz.Rect(0,0,10,10),stream=output.getvalue(),keep_proportion=False)
            updated = page_objects.Objects(page)
            new_items = [it for it in updated.items if it.get('kind') == 'picture' and it.get('xref') == new_xref]
            if not new_items: raise ValueError('无法建立裁剪后的图片。')
            added = new_items[-1]
            name = added['obj'].get('name')
            if not name: raise ValueError('无法定位裁剪后的图片资源。')
            page_objects.delete(page,[added['n']],updated)
            refreshed = page_objects.Objects(page)
            scale_x, scale_y = (x1-x0)/w, (y1-y0)/h
            left, bottom = x0/w, 1-y1/h
            def replacement(old, ctm):
                state, _ = page_objects._split(old)
                matrix = f'\nq {scale_x:.12g} 0 0 {scale_y:.12g} {left:.12g} {bottom:.12g} cm\n'.encode('ascii')
                return state+b' '+matrix+name+b' Do\nQ\n'
            page_objects._edit(page,numbers,replacement,refreshed)
            self.commit(original,self.dirty)
            self.reselect_graphic(target,'图片')
            self.status.config(text='图片已裁剪，可继续移动；按 Ctrl+Z 撤销。')
            return True
        except Exception:
            self.doc.close(); self.doc = fitz.open(stream=original,filetype='pdf'); self.show()
            raise

    def crop_image(self):
        if self.inline_editor and not self.apply_inline(): return
        if not self.doc: return
        try:
            if self.doc[self.page_index].rotation: raise ValueError('带页面旋转属性的 PDF 暂不能裁剪图片。')
            image = self.selected_image_pixels()
        except Exception as exc:
            messagebox.showinfo('裁剪图片',str(exc),parent=self.root)
            return
        dialog = tk.Toplevel(self.root)
        dialog.title('裁剪图片')
        dialog.transient(self.root)
        frame = ttk.Frame(dialog,padding=12); frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='在图片上拖框，选择要保留的部分；确认后可用 Ctrl+Z 撤销。').pack(anchor='w',pady=(0,6))
        w,h = image.size
        scale = min(850/w,520/h,4.0)
        vw,vh = max(1,round(w*scale)),max(1,round(h*scale))
        preview = ImageTk.PhotoImage(image.resize((vw,vh),Image.Resampling.LANCZOS))
        canvas = tk.Canvas(frame,width=vw,height=vh,background='#e6eaf0',highlightthickness=0,cursor='crosshair')
        canvas.pack()
        canvas.create_image(0,0,image=preview,anchor='nw')
        state = {'start':None,'rect':(0,0,vw,vh)}
        def draw():
            canvas.delete('crop')
            canvas.create_rectangle(*state['rect'],outline='#0878e8',width=2,tags='crop')
        def down(event):
            state['start'] = (max(0,min(vw,event.x)),max(0,min(vh,event.y)))
        def motion(event):
            if state['start'] is None: return
            x,y = max(0,min(vw,event.x)),max(0,min(vh,event.y))
            sx,sy = state['start']; state['rect']=(min(sx,x),min(sy,y),max(sx,x),max(sy,y)); draw()
        def apply():
            a,b,c,d = state['rect']
            crop = (max(0,int(a*w/vw)),max(0,int(b*h/vh)),min(w,math.ceil(c*w/vw)),min(h,math.ceil(d*h/vh)))
            try:
                if self.apply_image_crop(image,crop): dialog.destroy()
            except Exception as exc:
                messagebox.showerror('裁剪失败',str(exc),parent=dialog)
        canvas.bind('<ButtonPress-1>',down); canvas.bind('<B1-Motion>',motion); canvas.bind('<ButtonRelease-1>',motion)
        draw()
        buttons=ttk.Frame(frame);buttons.pack(pady=(8,0))
        ttk.Button(buttons,text='确认裁剪',command=apply).pack(side='left',padx=4)
        ttk.Button(buttons,text='取消',command=dialog.destroy).pack(side='left',padx=4)
        dialog.update_idletasks()
        x = self.root.winfo_rootx()+(self.root.winfo_width()-dialog.winfo_reqwidth())//2
        y = self.root.winfo_rooty()+(self.root.winfo_height()-dialog.winfo_reqheight())//2
        dialog.geometry(f'+{max(0,x)}+{max(0,y)}')
        dialog.grab_set()
        dialog._preview = preview

    def add_image(self):
        rect = self.selected_rect()
        if rect is None: return
        path = filedialog.askopenfilename(filetypes=[('图片', '*.png *.jpg *.jpeg'), ('所有文件', '*.*')])
        if not path: return
        original = self.doc.tobytes(garbage=0, deflate=True)
        try:
            self.doc[self.page_index].insert_image(rect, filename=path, keep_proportion=True)
            self.commit(original, self.dirty)
            self.select_inserted(rect, '图片')
        except Exception as exc:
            self.doc.close(); self.doc = fitz.open(stream=original, filetype='pdf'); self.show()
            messagebox.showerror('添加图片失败', str(exc))

    def save(self):
        if self.inline_editor and not self.apply_inline(): return
        if not self.doc: return
        if not self.dirty:
            messagebox.showinfo('保存', '当前文件没有需要保存的修改。')
            return
        if not messagebox.askyesno('确认保存', f'将修改保存到当前文件并覆盖原文件：\n\n{self.path}\n\n确认保存吗？', icon='question'):
            return
        self.write_pdf(self.path, check_existing=True)

    def save_as(self):
        if self.inline_editor and not self.apply_inline(): return
        if not self.doc: return
        path = filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[('PDF 文件', '*.pdf')], initialfile=Path(self.path).stem+'-编辑.pdf')
        if not path: return
        if not messagebox.askyesno('确认另存为', f'将当前内容保存为：\n\n{path}\n\n确认保存吗？', icon='question'):
            return
        if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(self.path)):
            self.write_pdf(path, check_existing=True)
            return
        self.write_pdf(path, check_existing=False)

    def write_pdf(self, path, check_existing):
        temporary = None
        try:
            if check_existing:
                current = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                if current != self.last_file_stat:
                    raise ValueError('原文件已被其他程序修改。请使用“另存为”，避免覆盖其他修改。')
            if self.doc.get_sigflags() > 0:
                if not messagebox.askyesno('数字签名', '保存修改会使 PDF 中原有的数字签名失效。是否继续？'):
                    return
            data = self.doc.tobytes(garbage=4, deflate=True)
            with fitz.open(stream=data, filetype='pdf') as check:
                if len(check) != len(self.doc): raise ValueError('保存前检查失败：页面数量不一致。')
            with tempfile.NamedTemporaryFile(mode='wb', dir=str(Path(path).parent), prefix='.pdf-edit-', suffix='.tmp', delete=False) as file:
                temporary = file.name
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            if check_existing and hashlib.sha256(Path(path).read_bytes()).hexdigest() != self.last_file_stat:
                raise ValueError('保存期间原文件已被其他程序修改，请使用“另存为”。')
            os.replace(temporary, path)
            temporary = None
            self.path = path
            self.last_file_stat = hashlib.sha256(data).hexdigest()
            self.dirty = False
            messagebox.showinfo('保存成功', '已保存到：\n'+path)
            self.show()
        except Exception as exc:
            messagebox.showerror('保存失败', str(exc))
        finally:
            if temporary:
                try: os.unlink(temporary)
                except OSError: pass

    def print_pdf(self):
        if self.inline_editor and not self.apply_inline(): return
        if not self.doc:
            return
        if getattr(self, '_print_job_active', False):
            messagebox.showinfo('打印', '已有打印任务正在提交，请等待完成。', parent=self.root); return
        from printing import show_print_dialog
        show_print_dialog(self, printer_dc, printer_mode)

def open_startup_files(app, arguments):
    """Open PDFs passed by Windows, for example when files are dropped on the EXE."""
    paths = [arg for arg in arguments if not arg.startswith('--')]
    for path in paths:
        if Path(path).suffix.lower() != '.pdf' or not Path(path).is_file():
            messagebox.showerror('无法打开', f'请选择有效的 PDF 文件：\n{path}', parent=app.root)
            continue
        app.open_path(path)
    if '--print' in arguments and app.doc:
        app.print_pdf()


if __name__ == '__main__':
    # A double-clicked PDF is handed to the window that is already open, so
    # several PDFs end up as tabs instead of several application windows.
    startup = [arg for arg in sys.argv[1:] if not arg.startswith('--')]
    prefs = settings.load()
    single = prefs.get('open_mode') == 'same_window'
    if single and startup:
        for attempt in range(4):
            if instance.forward(startup):
                sys.exit(0)
            if attempt < 3: time.sleep(0.25)
    root = tk.Tk()
    app = PDFTool(root)
    if single:
        app.start_single_instance()
    if len(sys.argv) > 1:
        root.after_idle(lambda:open_startup_files(app, sys.argv[1:]))
    root.mainloop()
