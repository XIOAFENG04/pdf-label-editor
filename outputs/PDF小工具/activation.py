"""Local first-run activation for the packaged application."""
import hashlib
import hmac
import sys
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
import settings

KEY_HASH = 'cfb8f86f83f723a20ecb167eee52053997e088f4b20196ecd6940ccc6243d409'
MARKER_PREFIX = 'activated-v2:'


def activation_marker():
    """Keep activation for updates in the same install, not unrelated copies."""
    executable_dir = Path(sys.executable).resolve().parent
    identity = hashlib.sha256(str(executable_dir).casefold().encode('utf-8')).hexdigest()[:16]
    return MARKER_PREFIX + identity


def valid_key(key):
    return hmac.compare_digest(hashlib.sha256(key.strip().encode('utf-8')).hexdigest(), KEY_HASH)


def prompt_key(root):
    dialog = tk.Toplevel(root)
    dialog.withdraw()
    dialog.title('激活 PDF 标签编辑器')
    dialog.resizable(False, False)
    dialog.configure(bg='#f4f7fb')
    try:
        base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
        dialog.iconbitmap(str(base / 'app.ico'))
    except tk.TclError:
        pass
    panel = tk.Frame(dialog, bg='white', padx=28, pady=24)
    panel.pack(fill='both', expand=True, padx=12, pady=12)
    tk.Label(panel, text='激活软件', bg='white', fg='#172b4d',
             font=('Microsoft YaHei UI', 17, 'bold'), anchor='w').pack(fill='x')
    tk.Label(panel, text='请输入你的软件密钥，激活后即可使用。', bg='white',
             fg='#65758b', font=('Microsoft YaHei UI', 10), anchor='w').pack(fill='x', pady=(7, 20))
    tk.Label(panel, text='没有密钥？请联系：730004921@qq.com', bg='white', fg='#1769c2',
             font=('Microsoft YaHei UI', 9), anchor='w').pack(fill='x', pady=(0, 12))
    tk.Label(panel, text='软件密钥', bg='white', fg='#253858',
             font=('Microsoft YaHei UI', 10, 'bold'), anchor='w').pack(fill='x', pady=(0, 6))
    key = tk.StringVar()
    entry = tk.Entry(panel, textvariable=key, show='●', font=('Microsoft YaHei UI', 12),
                     relief='solid', bd=1, width=32)
    entry.pack(fill='x', ipady=7)
    visible = tk.BooleanVar(value=False)
    tk.Checkbutton(panel, text='显示密钥', variable=visible, bg='white', activebackground='white',
                   fg='#52647a', font=('Microsoft YaHei UI', 9),
                   command=lambda: entry.config(show='' if visible.get() else '●')).pack(anchor='w', pady=(5, 16))
    buttons = tk.Frame(panel, bg='white')
    buttons.pack(fill='x')
    result = [None]
    def submit(event=None):
        result[0] = key.get()
        dialog.destroy()
    tk.Button(buttons, text='退出', command=dialog.destroy, bg='#edf1f6', fg='#34445a',
              relief='flat', padx=22, pady=7, font=('Microsoft YaHei UI', 10)).pack(side='right')
    tk.Button(buttons, text='激活并进入', command=submit, bg='#1769c2', fg='white',
              activebackground='#1256a2', activeforeground='white', relief='flat', padx=20, pady=7,
              font=('Microsoft YaHei UI', 10, 'bold')).pack(side='right', padx=(0, 10))
    dialog.bind('<Return>', submit)
    dialog.bind('<Escape>', lambda event: dialog.destroy())
    dialog.update_idletasks()
    x = max(0, (dialog.winfo_screenwidth() - dialog.winfo_reqwidth()) // 2)
    y = max(0, (dialog.winfo_screenheight() - dialog.winfo_reqheight()) // 2)
    dialog.geometry(f'+{x}+{y}')
    dialog.deiconify()
    dialog.lift()
    dialog.grab_set()
    entry.focus_set()
    root.wait_window(dialog)
    return result[0]


def activate(root):
    prefs = settings.load()
    marker = activation_marker()
    if prefs.get('activation') == marker:
        return True
    key = prompt_key(root)
    if key is None:
        return False
    if not valid_key(key):
        messagebox.showerror('激活失败', '密钥不正确，软件将退出。', parent=root)
        return False
    prefs['activation'] = marker
    if not settings.save(prefs):
        messagebox.showerror('激活失败', '无法保存激活状态，请检查用户设置目录的写入权限。', parent=root)
        return False
    return True
