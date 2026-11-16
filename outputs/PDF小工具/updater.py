"""Check for newer releases published on GitHub.

Two transports are used:
  1. the REST API (fast, includes release notes and asset sizes);
  2. a fallback that only needs github.com — some networks block or rate-limit
     api.github.com, and then the update check used to fail completely.
"""
import json
import re
import ssl
import urllib.error
import urllib.request

APP_VERSION = '1.1.5'
DEFAULT_REPO = 'XIOAFENG04/pdf-label-editor'
API = 'https://api.github.com/repos/{repo}/releases/latest'
LATEST = 'https://github.com/{repo}/releases/latest'
ASSETS = 'https://github.com/{repo}/releases/expanded_assets/{tag}'
HEADERS = {'User-Agent': 'PDFLabelEditor/' + APP_VERSION}


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


def _request(url, accept=None, timeout=10):
    headers = dict(HEADERS)
    if accept:
        headers['Accept'] = accept
    request = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context())


def _from_api(repo, timeout=10):
    with _request(API.format(repo=repo), 'application/vnd.github+json', timeout) as response:
        data = json.loads(response.read().decode('utf-8'))
    assets = [{'name': item.get('name') or '', 'size': item.get('size') or 0,
               'url': item.get('browser_download_url') or ''}
              for item in (data.get('assets') or [])]
    return {
        'version': str(data.get('tag_name') or data.get('name') or '').lstrip('vV'),
        'name': data.get('name') or '',
        'notes': data.get('body') or '',
        'page': data.get('html_url') or '',
        'published': data.get('published_at') or '',
        'assets': assets,
    }


def _from_web(repo, timeout=10):
    """Fallback: follow github.com/OWNER/REPO/releases/latest and read the tag."""
    with _request(LATEST.format(repo=repo), timeout=timeout) as response:
        final = response.geturl()
    match = re.search(r'/releases/tag/([^/?#]+)', final or '')
    if not match:
        raise RuntimeError('GitHub 返回的页面里没有版本号，可能网络被劫持或需要登录。')
    tag = match.group(1)
    version = tag.lstrip('vV')
    page = f'https://github.com/{repo}/releases/tag/{tag}'
    assets = []
    try:
        with _request(ASSETS.format(repo=repo, tag=tag), timeout=timeout) as response:
            html = response.read().decode('utf-8', 'replace')
        for href, name in re.findall(r'href="(/[^"]*?/releases/download/[^"]+)"[^>]*>\s*([^<]+)<', html):
            clean = name.strip()
            if clean:
                assets.append({'name': clean, 'size': 0, 'url': 'https://github.com' + href})
    except Exception:
        pass
    if not assets:
        # Convention used by this project, so the download still works offline of the API.
        name = f'PDFLabelEditor-Setup-{version}.exe'
        assets.append({'name': name, 'size': 0,
                       'url': f'https://github.com/{repo}/releases/download/{tag}/{name}'})
    return {'version': version, 'name': f'PDF 标签编辑器 {version}', 'notes': '',
            'page': page, 'published': '', 'assets': assets}


def fetch_latest(repo, timeout=10):
    """Latest release information; falls back to the web page when the API is blocked."""
    try:
        return _from_api(repo, timeout)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError) as first:
        try:
            release = _from_web(repo, timeout)
            release['notes'] = release.get('notes') or ''
            return release
        except Exception:
            raise first


def check(repo, current=APP_VERSION):
    """Return (has_update, release). Raises RuntimeError with a friendly message."""
    parsed = parse_repo(repo)
    if not parsed:
        raise RuntimeError('还没有配置更新仓库。\n\n请在 设置 → 检查更新 里填写 GitHub 用户名/仓库名。')
    try:
        release = fetch_latest(parsed)
    except urllib.error.HTTPError as error:
        if error.code == 403:
            raise RuntimeError('GitHub 拒绝了这次访问（HTTP 403）。\n\n'
                               '通常是同一网络下检查次数太多被临时限流，等几分钟再试；'
                               '也可能是公司网络/代理拦截了 GitHub。') from error
        if error.code == 404:
            raise RuntimeError(f'仓库 {parsed} 还没有发布版本（Releases 为空）。') from error
        raise RuntimeError(f'访问 GitHub 失败（HTTP {error.code}）。') from error
    except urllib.error.URLError as error:
        raise RuntimeError('无法连接 GitHub。\n\n请检查网络，或公司网络是否拦截了 '
                           'api.github.com / github.com。') from error
    except Exception as error:
        raise RuntimeError(f'检查更新失败：{error}') from error
    if not release['version']:
        raise RuntimeError('最新版本没有可用的版本号。')
    return is_newer(release['version'], current), release


def installer_asset(release):
    """Pick the Windows installer among the release assets."""
    for asset in release.get('assets') or []:
        name = (asset.get('name') or '').lower()
        if name.endswith('.exe'):
            return asset
    return None


if __name__ == '__main__':
    import sys
    repo = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REPO
    newer, info = check(repo)
    print('newer' if newer else 'up to date', info['version'], info.get('page'))
