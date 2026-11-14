"""Check for newer releases published on GitHub.

The repository is configurable through settings.json (`update_repo`), so the app
does not hard-code an account. The GitHub Releases API needs no token for public
repositories.
"""
import json
import re
import ssl
import urllib.error
import urllib.request

APP_VERSION = '1.0.1'
DEFAULT_REPO = 'XIOAFENG04/pdf-label-editor'
API = 'https://api.github.com/repos/{repo}/releases/latest'


def version_tuple(text):
    parts = re.findall(r'\d+', str(text or '0'))
    values = [int(part) for part in parts[:4]]
    while len(values) < 4:
        values.append(0)
    return tuple(values)


def is_newer(candidate, current=APP_VERSION):
    return version_tuple(candidate) > version_tuple(current)


def parse_repo(value):
    text = str(value or '').strip()
    if text.startswith('https://github.com/'):
        text = text[len('https://github.com/'):]
    elif text.startswith('github.com/'):
        text = text[len('github.com/'):]
    text = text.strip('/')
    if text.endswith('.git'):
        text = text[:-4]
    parts = [part for part in text.split('/') if part]
    if len(parts) != 2:
        return ''
    return f'{parts[0]}/{parts[1]}'


def fetch_latest(repo, timeout=8):
    """Return the latest release information, raising a readable error on failure."""
    address = API.format(repo=repo)
    request = urllib.request.Request(address, headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'PDFLabelEditor/' + APP_VERSION,
    })
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        data = json.loads(response.read().decode('utf-8'))
    assets = []
    for asset in data.get('assets') or []:
        assets.append({
            'name': asset.get('name') or '',
            'size': asset.get('size') or 0,
            'url': asset.get('browser_download_url') or '',
        })
    return {
        'version': str(data.get('tag_name') or data.get('name') or '').lstrip('vV'),
        'name': data.get('name') or '',
        'notes': data.get('body') or '',
        'page': data.get('html_url') or '',
        'published': data.get('published_at') or '',
        'assets': assets,
    }


def check(repo, current=APP_VERSION):
    """Return (has_update, release). Raises RuntimeError with a friendly message."""
    parsed = parse_repo(repo)
    if not parsed:
        raise RuntimeError('还没有配置更新仓库。\n\n请在 设置 → 检查更新 里填写 GitHub 用户名/仓库名。')
    try:
        release = fetch_latest(parsed)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise RuntimeError(f'仓库 {parsed} 还没有发布版本（Releases 为空）。') from error
        raise RuntimeError(f'访问 GitHub 失败（HTTP {error.code}）。') from error
    except urllib.error.URLError as error:
        raise RuntimeError('无法连接 GitHub，请检查网络。') from error
    except Exception as error:  # timeout, ssl, json
        raise RuntimeError(f'检查更新失败：{error}') from error
    if not release['version']:
        raise RuntimeError('最新版本没有可用的版本号。')
    return is_newer(release['version'], current), release


def installer_asset(release):
    """Pick the Windows installer among the release assets."""
    for asset in release.get('assets') or []:
        name = asset['name'].lower()
        if name.endswith('.exe'):
            return asset
    return None


if __name__ == '__main__':
    import sys
    repo = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REPO
    newer, info = check(repo)
    print('newer' if newer else 'up to date', info['version'])
