"""Register the editor as a PDF handler and open the Windows default-apps page.

Windows 10/11 require the user to confirm a new default handler, so the
registration makes the app appear in "打开方式 / 默认应用" and then opens that
page; the user picks the app once.
"""
import os
import subprocess
import sys
import winreg

APP_NAME = 'PDF 标签编辑器'
PROGID = 'PDFLabelEditor.pdf'
CAPABILITIES = r'Software\PDFLabelEditor\Capabilities'


def _set(key, name, value):
    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def register(exe_path, icon_path=None):
    """Add the app to the OpenWith list and default-apps capabilities (per user)."""
    exe = str(exe_path)
    icon = str(icon_path or exe_path)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf'Software\Classes\{PROGID}') as key:
        _set(key, '', 'PDF 标签编辑器 文档')
        _set(key, 'FriendlyTypeName', 'PDF 标签编辑器 文档')
        _set(key, 'DefaultIcon', f'{icon},0')
        with winreg.CreateKey(key, r'shell\open\command') as command:
            _set(command, '', f'"{exe}" "%1"')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Classes\.pdf\OpenWithProgids') as key:
        winreg.SetValueEx(key, PROGID, 0, winreg.REG_NONE, b'')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CAPABILITIES) as key:
        _set(key, 'ApplicationName', APP_NAME)
        _set(key, 'ApplicationDescription', '查看、编辑、打印 PDF 标签')
        _set(key, 'ApplicationIcon', f'{icon},0')
        with winreg.CreateKey(key, 'FileAssociations') as associations:
            _set(associations, '.pdf', PROGID)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\RegisteredApplications') as key:
        _set(key, APP_NAME, CAPABILITIES)


def open_default_apps():
    """Open the Windows page where the user confirms the default PDF app."""
    try:
        os.startfile('ms-settings:defaultapps')
        return True
    except OSError:
        try:
            subprocess.Popen(['control', '/name', 'Microsoft.DefaultPrograms', '/page', 'pageDefaultProgram'],
                             creationflags=0x08000000, close_fds=True)
            return True
        except OSError:
            return False


def configure(exe_path, icon_path=None, open_page=True):
    register(exe_path, icon_path)
    return open_default_apps() if open_page else True


if __name__ == '__main__':
    exe = sys.argv[1] if len(sys.argv) > 1 else sys.executable
    icon = sys.argv[2] if len(sys.argv) > 2 else None
    configure(exe, icon)
    print('registered', exe)
