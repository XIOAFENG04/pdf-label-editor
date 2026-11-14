"""Light and dark palettes for the application chrome.

Only the chrome is themed; the PDF page itself stays white, like other editors.
Widgets created with the light literals below are converted in place by
`restyle_tree`, and the ttk styles are rebuilt by `apply_ttk`, so switching
between modes needs nothing more than those two calls plus a repaint of the
custom Canvas widgets (RoundButton / SlimScrollbar).
"""
import tkinter as tk
from tkinter import ttk

LIGHT = {
    'bg': '#f5f7fa', 'panel': '#ffffff', 'bar': '#edf2f7', 'canvas': '#677689',
    'thumb': '#eef2f7', 'fg': '#253449', 'fg_dim': '#637189', 'border': '#d8e0ea',
    'btn': '#ffffff', 'btn_hover': '#eef4fb', 'btn_press': '#dfe9f4', 'btn_fg': '#253449',
    'accent': '#176bc0', 'accent_hover': '#1266af', 'accent_press': '#0c508e',
    'sel': '#0f6cbd', 'split': '#dce4ec', 'split_hover': '#a8bcd0',
    'scroll_bg': '#f0f3f6', 'scroll': '#929ba5', 'scroll_hot': '#6f7882',
    'menu_bg': '#ffffff', 'menu_fg': '#253449', 'menu_active': '#eaf2ff',
    'entry': '#ffffff', 'list': '#ffffff', 'shadow': '#5b6a7d',
}

DARK = {
    'bg': '#1b1f26', 'panel': '#242a33', 'bar': '#151a20', 'canvas': '#0e1217',
    'thumb': '#171c23', 'fg': '#dfe6ef', 'fg_dim': '#93a0b1', 'border': '#39424f',
    'btn': '#242a33', 'btn_hover': '#2d3540', 'btn_press': '#39424f', 'btn_fg': '#dfe6ef',
    'accent': '#2f6fd0', 'accent_hover': '#3a7ade', 'accent_press': '#255db3',
    'sel': '#3f8cff', 'split': '#39424f', 'split_hover': '#5a6675',
    'scroll_bg': '#202730', 'scroll': '#7c8794', 'scroll_hot': '#9aa5b2',
    'menu_bg': '#262d36', 'menu_fg': '#dfe6ef', 'menu_active': '#33475e',
    'entry': '#242a33', 'list': '#242a33', 'shadow': '#05070a',
}

# Every light literal that appears in the UI, and what it becomes in dark mode.
# Used to walk the existing widget tree when the theme changes at runtime.
TO_DARK = {
    'white': '#242a33', '#ffffff': '#242a33',
    '#f5f7fa': '#1b1f26', '#f9fbfd': '#1f242c', '#f4f6f9': '#1d232b',
    '#eef2f7': '#171c23', '#edf2f7': '#151a20', '#e9eef5': '#232932',
    '#e6eaf0': '#232932', '#f0f3f6': '#202730',
    '#253449': '#dfe6ef', '#253044': '#dfe6ef', '#142138': '#e8eef7',
    '#526174': '#a7b3c2', '#586a80': '#9aa7b6', '#42566c': '#8d99a8', '#56708e': '#93a0b1',
    '#637189': '#93a0b1',
    '#d8e0ea': '#39424f', '#d4dce6': '#39424f', '#dce4ec': '#39424f',
    '#d7e0ea': '#39424f', '#d4e0ed': '#39424f', '#bfd0e2': '#39424f',
    '#d4dfeb': '#39424f', '#d9e3ee': '#39424f', '#e7edf4': '#2a313a',
    '#8ba1bb': '#3f4a58', '#a8bcd0': '#5a6675', '#7e9dbb': '#4a5665',
    '#eef4fb': '#2d3540', '#dfe9f4': '#39424f', '#eaf2ff': '#2b3a4d',
    '#dceaff': '#33475e', '#d4e7f9': '#2b3a4d',
    '#0f6cbd': '#3f8cff', '#1677ff': '#4c9aff', '#0878e8': '#4c9aff',
    '#2463d4': '#2f6fd0', '#176bc0': '#2f6fd0', '#1266af': '#1a5aa8', '#0c508e': '#14457f',
    '#174fad': '#2a5fae', '#143f88': '#1f4a86', '#174a77': '#2c5a8f',
    '#929ba5': '#7c8794', '#6f7882': '#9aa5b2', '#677689': '#0e1217',
}
TO_LIGHT = {}
for light, dark in TO_DARK.items():
    TO_LIGHT.setdefault(dark, light if light.startswith('#') else '#ffffff')

MODE = 'light'


def set_mode(mode):
    global MODE
    MODE = 'dark' if mode == 'dark' else 'light'


def is_dark():
    return MODE == 'dark'


def palette():
    return DARK if MODE == 'dark' else LIGHT


def c(key):
    return palette()[key]


def system_prefers_dark():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            return winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] == 0
    except OSError:
        return False


def resolve(mode):
    """Turn the stored preference into 'light' or 'dark'."""
    if mode == 'system':
        return 'dark' if system_prefers_dark() else 'light'
    return 'dark' if mode == 'dark' else 'light'


def apply_ttk(style):
    p = palette()
    style.configure('.', background=p['bg'], foreground=p['fg'])
    style.configure('TFrame', background=p['bg'])
    style.configure('TLabel', background=p['bg'], foreground=p['fg'])
    style.configure('TCheckbutton', background=p['bg'], foreground=p['fg'])
    style.configure('TButton', background=p['btn'], foreground=p['btn_fg'],
                    bordercolor=p['border'], lightcolor=p['btn'], darkcolor=p['btn'])
    style.map('TButton', background=[('active', p['btn_hover']), ('pressed', p['btn_press'])],
              foreground=[('disabled', p['fg_dim'])])
    style.configure('Primary.TButton', background=p['accent'], foreground='white',
                    bordercolor=p['accent'])
    style.map('Primary.TButton', background=[('active', p['accent_hover']), ('pressed', p['accent_press'])])
    style.configure('TEntry', fieldbackground=p['entry'], foreground=p['fg'],
                    background=p['entry'], bordercolor=p['border'], insertcolor=p['fg'])
    style.map('TEntry', fieldbackground=[('readonly', p['entry'])], foreground=[('readonly', p['fg'])])
    style.configure('TCombobox', fieldbackground=p['entry'], background=p['btn'],
                    foreground=p['fg'], arrowcolor=p['fg'], bordercolor=p['border'])
    style.map('TCombobox', fieldbackground=[('readonly', p['entry'])],
              foreground=[('readonly', p['fg'])], selectbackground=[('readonly', p['entry'])],
              selectforeground=[('readonly', p['fg'])])
    style.configure('Title.TLabel', font=('Microsoft YaHei UI', 15, 'bold'), foreground=p['fg'])
    style.configure('Hint.TLabel', foreground=p['fg_dim'], background=p['bg'])
    style.configure('Status.TLabel', foreground=p['fg_dim'], background=p['bar'], padding=(14, 5))
    style.configure('Document.TNotebook', background=p['bg'], borderwidth=0, tabmargins=(2, 2, 2, 0))
    style.configure('Document.TNotebook.Tab', padding=(14, 7), background=p['btn'],
                    foreground=p['fg_dim'], bordercolor=p['border'], font=('Microsoft YaHei UI', 9))
    style.map('Document.TNotebook.Tab',
              background=[('selected', p['sel']), ('active', p['btn_hover'])],
              foreground=[('selected', '#ffffff'), ('active', p['fg'])],
              bordercolor=[('selected', p['sel'])],
              font=[('selected', ('Microsoft YaHei UI', 9, 'bold'))])
    style.configure('TScrollbar', background=p['btn'], troughcolor=p['scroll_bg'],
                    bordercolor=p['border'], arrowcolor=p['fg'])
    style.configure('TSeparator', background=p['border'])
    style.configure('Vertical.TScrollbar', background=p['btn'], troughcolor=p['scroll_bg'])


def menu(parent):
    p = palette()
    return tk.Menu(parent, tearoff=False, background=p['menu_bg'], foreground=p['menu_fg'],
                   activebackground=p['menu_active'], activeforeground=p['fg'],
                   borderwidth=0, relief='flat')


def _swap(widget, mapping, options):
    for option in options:
        try:
            value = widget.cget(option)
        except tk.TclError:
            continue
        if not isinstance(value, str) or not value:
            continue
        new = mapping.get(value.lower())
        if new is None:
            continue
        try:
            widget.configure(**{option: new})
        except tk.TclError:
            pass


def restyle_tree(widget, mapping=None):
    """Recolour tk widgets in place; ttk widgets follow apply_ttk instead."""
    if mapping is None:
        mapping = TO_DARK if is_dark() else TO_LIGHT
    options = ('background', 'foreground', 'highlightbackground', 'highlightcolor',
               'selectbackground', 'selectforeground', 'troughcolor', 'activebackground',
               'activeforeground', 'insertbackground', 'fieldbackground')
    if not isinstance(widget, ttk.Widget):
        _swap(widget, mapping, options)
    if getattr(widget, 'paint', None) and isinstance(widget, tk.Canvas):
        try:
            widget.configure(background=c('bg'))
            widget.paint()
        except tk.TclError:
            pass
    for child in widget.winfo_children():
        restyle_tree(child, mapping)
