"""Discover the public Firebase configuration from Skippo's published web app."""
import functools
import http.client
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser

from . import core
from .core import Error

PUBLIC_BASE = 'https://my-boat.skippo.io'
HTML_LIMIT = 1024 * 1024
SCRIPT_LIMIT = 8 * 1024 * 1024
SCRIPT_PATH = re.compile(r'/assets/index-(?!legacy-)[A-Za-z0-9_-]+\.js\Z')


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == 'script' and fields.get('type') == 'module':
            src = fields.get('src', '')
            if SCRIPT_PATH.fullmatch(src):
                self.paths.append(src)


def fetch(path, limit):
    req = urllib.request.Request(PUBLIC_BASE + path, method='GET')
    try:
        with urllib.request.build_opener(core.NoRedirect).open(req, timeout=core.REQUEST_TIMEOUT) as response:
            body = response.read(limit + 1)
            if len(body) > limit:
                raise Error('Public configuration response is too large.', 5, 'service')
        return body.decode('utf-8')
    except urllib.error.HTTPError as e:
        raise core.http_error(e, service='Public configuration') from None
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException, UnicodeDecodeError):
        raise Error('Could not fetch Skippo public configuration.', 5, 'network') from None


@functools.lru_cache(maxsize=1)
def config():
    page = fetch('/', HTML_LIMIT)
    parser = Scripts()
    parser.feed(page)
    if len(parser.paths) != 1:
        raise Error('Could not identify Skippo public configuration script.', 5, 'service')
    script = fetch(parser.paths[0], SCRIPT_LIMIT)
    matches = []
    for obj in re.findall(r'\{[^{}]{0,4096}\}', script):
        if not re.search(r'\bauthDomain\s*:\s*[`\'"]nautical-app-se\.firebaseapp\.com[`\'"]', obj):
            continue
        found = re.search(r'\bapiKey\s*:\s*([`\'"])([^`\'"\s]{1,256})\1', obj)
        if found:
            matches.append(found.group(2))
    if len(matches) != 1:
        raise Error('Could not identify Skippo public Firebase configuration.', 5, 'service')
    clients = re.findall(r'btoa\(\s*([`\'"])(bpClient:[^`\'"\s]{1,256})\1\s*\)', script)
    if len(clients) != 1:
        raise Error('Could not identify Skippo public client configuration.', 5, 'service')
    return matches[0], clients[0][1]


def api_key():
    return config()[0]


def client():
    return config()[1]
