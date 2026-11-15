"""Installer for PDF 标签编辑器.

A single-file windowed executable that carries the application payload, asks
where to install, copies the files, optionally creates desktop / Start-menu
shortcuts and registers an uninstaller in HKCU.

Silent mode (used by the automated install test):

    PDF标签编辑器安装程序.exe --silent --dir "C:\\path" [--no-desktop] [--no-startmenu]

Uninstall mode (the copy placed next to the program):

    uninstall.exe --uninstall --dir "C:\\path"
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import tkinter as tk
import winreg
import pdf_association
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_NAME = 'PDF 标签编辑器'
APP_EXE = 'PDF标签编辑器.exe'
VERSION = '1.1.2'
PUBLISHER = 'PDF 标签编辑器'
UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFLabelEditor'
CREATION_FLAGS = 0x08000000 if sys.platform == 'win32' else 0

BATCH_TEMPLATE = '@echo off\nchcp 936 >nul\ntitle 卸载 PDF 标签编辑器\necho.\necho   即将卸载程序，PDF 和素材库将保留。\necho   安装位置：%~dp0\necho.\nchoice /c YN /m "确定卸载"\nif errorlevel 2 exit /b 0\nreg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PDFLabelEditor" /f >nul 2>nul\ndel "%~dp0PDF标签编辑器.exe" >nul 2>nul\ndel "%~dp0app.ico" "%~dp0pdf_doc.ico" "%~dp0installed.json" >nul 2>nul\ndel "%~f0" >nul 2>nul\nexit /b 0\n'


def payload_dir():
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return base / 'payload'


def default_dir():
    base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or str(Path.home())
    return str(Path(base) / 'Programs' / APP_NAME)


def powershell(script):
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', script],
                   creationflags=CREATION_FLAGS, capture_output=True)


def make_shortcut(link, target, workdir, icon):
    link = str(link)
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
              "$s.TargetPath='%s';$s.WorkingDirectory='%s';$s.IconLocation='%s,0';$s.Save()"
              % (link, target, workdir, icon))
    powershell(script)


def desktop_link():
    for name in ('Desktop', '桌面'):
        path = Path.home() / name
        if path.is_dir():
            return path / f'{APP_NAME}.lnk'
    return Path.home() / 'Desktop' / f'{APP_NAME}.lnk'


def start_menu_link():
    base = os.environ.get('APPDATA') or str(Path.home())
    folder = Path(base) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs'
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f'{APP_NAME}.lnk'


def register_uninstall(target):
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    with key:
        entries = {
            'DisplayName': APP_NAME,
            'DisplayVersion': VERSION,
            'Publisher': PUBLISHER,
            'InstallLocation': str(target),
            'DisplayIcon': str(target / APP_EXE),
            'UninstallString': f'"{target / "uninstall.cmd"}"',
            'NoModify': 1,
            'NoRepair': 1,
        }
        for name, value in entries.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ if isinstance(value, str) else winreg.REG_DWORD, value)


def remove_uninstall_key():
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass


def write_uninstaller(target):
    """A tiny .cmd uninstaller instead of shipping another 100 MB executable."""
    target = Path(target)
    script = BATCH_TEMPLATE.replace('{install}', str(target))
    path = target / 'uninstall.cmd'
    try:
        path.write_text(script, encoding='mbcs')
    except LookupError:
        path.write_text(script, encoding='utf-8')


def copy_payload(target, progress=None):
    source = payload_dir()
    if not source.is_dir():
        raise RuntimeError('安装包缺少应用文件（payload）。')
    target.mkdir(parents=True, exist_ok=True)
    files = [path for path in source.rglob('*') if path.is_file()]
    total = sum(path.stat().st_size for path in files) or 1
    done = 0
    for path in files:
        relative = path.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        done += path.stat().st_size
        if progress:
            progress(done / total)
    write_uninstaller(target)


def install(target, desktop=True, start_menu=True, progress=None, set_default_pdf=False):
    target = Path(target)
    copy_payload(target, progress)
    icon = target / 'app.ico'
    if desktop:
        try: make_shortcut(desktop_link(), target / APP_EXE, target, icon)
        except Exception: pass
    if start_menu:
        try: make_shortcut(start_menu_link(), target / APP_EXE, target, icon)
        except Exception: pass
    register_uninstall(target)
    if set_default_pdf:
        try:
            pdf_association.register(target / APP_EXE, icon if icon.exists() else None)
        except Exception:
            pass
    (target / 'installed.json').write_text(json.dumps({'version': VERSION, 'dir': str(target)}, ensure_ascii=False),
                                            encoding='utf-8')


def uninstall(target, silent=False):
    target = Path(target)
    if not silent:
        if not messagebox.askyesno('卸载 ' + APP_NAME, f'确定从下面位置卸载 {APP_NAME}？\n\n{target}'):
            return
    for link in (desktop_link(), start_menu_link()):
        try: link.unlink()
        except OSError: pass
    remove_uninstall_key()
    for name in (APP_EXE, 'app.ico', 'pdf_doc.ico', 'installed.json', 'uninstall.cmd'):
        try: (target / name).unlink()
        except OSError: pass
    if not silent:
        messagebox.showinfo('卸载完成', f'{APP_NAME} 已卸载。')


class Installer(tk.Tk):
    def __init__(self, silent=False, target=None, desktop=True, start_menu=True, default_app=False):
        super().__init__()
        self.title(f'{APP_NAME} 安装程序')
        self.resizable(False, False)
        self.configure(background='#f5f7fa')
        self.silent = silent
        self.target = tk.StringVar(value=target or default_dir())
        self.desktop = tk.BooleanVar(value=desktop)
        self.start_menu = tk.BooleanVar(value=start_menu)
        self.launch_after = tk.BooleanVar(value=True)
        self.default_app = tk.BooleanVar(value=default_app)
        style = ttk.Style(self); style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 9), background='#f5f7fa', foreground='#253044')
        style.configure('TFrame', background='#f5f7fa')
        style.configure('TLabel', background='#f5f7fa')
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 15, 'bold'))
        style.configure('Hint.TLabel', foreground='#637189')
        style.configure('Primary.TButton', background='#2463d4', foreground='white')
        style.map('Primary.TButton', background=[('active', '#174fad')])
        self.build()
        self.protocol('WM_DELETE_WINDOW', self.destroy)
        if silent:
            self.withdraw()
            try:
                install(self.target.get(), bool(self.desktop.get()), bool(self.start_menu.get()),
                        set_default_pdf=bool(self.default_app.get()))
                self.destroy()
            except Exception as exc:
                print(exc, file=sys.stderr)
                self.destroy()
                sys.exit(1)

    def build(self):
        body = ttk.Frame(self, padding=22)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=f'{APP_NAME} {VERSION}', style='Title.TLabel').pack(anchor='w')
        ttk.Label(body, text='选择安装位置，安装程序会复制程序文件，并可创建桌面和开始菜单快捷方式。',
                  style='Hint.TLabel').pack(anchor='w', pady=(4, 14))
        row = ttk.Frame(body); row.pack(fill='x')
        ttk.Label(row, text='安装位置').pack(side='left')
        entry = ttk.Entry(row, textvariable=self.target, width=52)
        entry.pack(side='left', fill='x', expand=True, padx=(10, 6))
        def browse():
            chosen = filedialog.askdirectory(title='选择安装位置', parent=self)
            if chosen: self.target.set(chosen)
        ttk.Button(row, text='浏览…', command=browse).pack(side='left')
        options = ttk.Frame(body); options.pack(fill='x', pady=(12, 0))
        ttk.Checkbutton(options, text='创建桌面快捷方式', variable=self.desktop).pack(anchor='w')
        ttk.Checkbutton(options, text='创建开始菜单快捷方式', variable=self.start_menu).pack(anchor='w', pady=(4, 0))
        ttk.Checkbutton(options, text='安装完成后启动程序', variable=self.launch_after).pack(anchor='w', pady=(4, 0))
        ttk.Checkbutton(options, text='设为默认 PDF 应用（安装后打开 Windows 默认应用设置确认）',
                        variable=self.default_app).pack(anchor='w', pady=(4, 0))
        self.progress = ttk.Progressbar(body, maximum=100)
        self.progress.pack(fill='x', pady=(16, 4))
        self.status = ttk.Label(body, text='准备就绪。', style='Hint.TLabel')
        self.status.pack(anchor='w')
        buttons = ttk.Frame(body); buttons.pack(fill='x', pady=(16, 0))
        self.install_button = ttk.Button(buttons, text='安装', style='Primary.TButton', command=self.run_install)
        self.install_button.pack(side='right')
        ttk.Button(buttons, text='取消', command=self.destroy).pack(side='right', padx=(0, 8))

    def run_install(self):
        target = self.target.get().strip()
        if not target:
            messagebox.showerror('安装', '请选择安装位置。', parent=self); return
        if Path(target, APP_EXE).exists():
            if not messagebox.askyesno('安装', '该位置已有同名程序，是否覆盖安装？', parent=self):
                return
        self.install_button.config(state='disabled')
        def progress(value):
            self.progress['value'] = value * 100
            self.status.config(text=f'正在复制文件… {value*100:.0f}%')
            self.update_idletasks()
        try:
            install(target, bool(self.desktop.get()), bool(self.start_menu.get()), progress,
                    set_default_pdf=bool(self.default_app.get()))
        except Exception as exc:
            messagebox.showerror('安装失败', str(exc), parent=self)
            self.install_button.config(state='normal')
            return
        self.progress['value'] = 100
        self.status.config(text='安装完成。')
        if self.launch_after.get():
            try: subprocess.Popen([str(Path(target) / APP_EXE)], creationflags=CREATION_FLAGS, cwd=target)
            except OSError: pass
        messagebox.showinfo('安装完成', f'{APP_NAME} 已安装到：\n{target}', parent=self)
        if self.default_app.get():
            pdf_association.open_default_apps()
        self.destroy()


def main():
    args = sys.argv[1:]
    def value(flag, fallback=None):
        if flag in args:
            index = args.index(flag)
            if index + 1 < len(args): return args[index + 1]
        return fallback
    silent = '--silent' in args
    if '--uninstall' in args:
        uninstall(value('--dir', default_dir()) or default_dir(), silent)
        return
    Installer(silent=silent, target=value('--dir'), desktop='--no-desktop' not in args,
              start_menu='--no-startmenu' not in args,
              default_app='--default-pdf' in args).mainloop()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:  # keep windowed failures readable
        ctypes.windll.user32.MessageBoxW(0, str(error), APP_NAME + ' 安装程序', 0x10)
        sys.exit(1)
