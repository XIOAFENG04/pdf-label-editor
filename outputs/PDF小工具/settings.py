"""User preferences stored in %APPDATA%\\PDF标签编辑器\\settings.json.

Defaults are conservative: files open as tabs in one window, a page opens at
actual size (100%), and the theme follows Windows.
"""
import json
import os
from pathlib import Path

APP = 'PDF标签编辑器'
DEFAULTS = {
    'open_mode': 'same_window',   # same_window | new_window
    'default_zoom': 'percent',    # percent | actual | fit | fit_width | last
    'default_percent': 320,       # used by the percent mode
    'theme': 'system',            # system | light | dark
    'update_repo': 'XIOAFENG04/pdf-label-editor',   # GitHub 用户名/仓库名，用于检查更新
    'last_scale': 1.0,
    'geometry': '',             # window size/position, restored on start
    'thumb_width': 210,
    'assets_width': 225,
}


def path():
    override = os.environ.get('PDFTOOL_SETTINGS')
    if override:
        return Path(override)
    base = os.environ.get('APPDATA') or str(Path.home())
    return Path(base) / APP / 'settings.json'


def load():
    data = dict(DEFAULTS)
    stored = {}
    try:
        stored = json.loads(path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        stored = {}
    if isinstance(stored, dict):
        # Files written before the 320% default existed keep the old 'fit' choice
        # and would ignore the new default, so migrate them once. Explicit
        # PDFTOOL_SETTINGS files (tests) are left exactly as written.
        if stored and 'settings_version' not in stored and not os.environ.get('PDFTOOL_SETTINGS'):
            stored['default_zoom'] = 'percent'
            stored['default_percent'] = 320
        data.update(stored)
    data['settings_version'] = 2
    return data


def save(data):
    target = path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
        return True
    except OSError:
        return False
