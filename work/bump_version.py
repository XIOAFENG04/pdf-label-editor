"""Bump the application version in every place it is stored."""
import io
import re
import sys

VERSION = sys.argv[1] if len(sys.argv) > 1 else '1.1.22'
UPDATER = r'outputs\PDF小工具\updater.py'
VERSION_INFO = r'work\assets\version_info.txt'
INSTALLER_INFO = r'work\assets\version_info_installer.txt'

text = io.open(UPDATER, encoding='utf-8').read()
text = re.sub(r"APP_VERSION = '[^']*'", "APP_VERSION = '%s'" % VERSION, text, count=1)
io.open(UPDATER, 'w', encoding='utf-8', newline='').write(text)
print('APP_VERSION ->', VERSION)

parts = VERSION.split('.') + ['0']
for path in (VERSION_INFO, INSTALLER_INFO):
    text = io.open(path, encoding='utf-8').read()
    text = re.sub(r"filevers=\([^)]*\)", "filevers=(%s)" % ', '.join(parts), text)
    text = re.sub(r"prodvers=\([^)]*\)", "prodvers=(%s)" % ', '.join(parts), text)
    text = re.sub(r"StringStruct\('FileVersion', '[^']*'\)", "StringStruct('FileVersion', '%s.0')" % VERSION, text)
    text = re.sub(r"StringStruct\('ProductVersion', '[^']*'\)", "StringStruct('ProductVersion', '%s.0')" % VERSION, text)
    io.open(path, 'w', encoding='utf-8', newline='').write(text)
    print('bumped', path)
