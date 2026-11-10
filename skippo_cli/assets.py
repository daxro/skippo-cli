"""Image attachments belonging to digital boat binder events."""
import http.client
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import core
from .core import Error

ASSET_BASE = 'https://nautical-assets.skippo.io'
CDN_BASE = 'https://nautical-assets-cdn.skippo.io'
MAX_FILE = 10 * 1024 * 1024


def configure(subs):
    sub = subs.add_parser('attachments', help='Images and scanned documents on binder events').add_subparsers(dest='action', required=True)
    for action in ('list', 'upload', 'download', 'delete'):
        a = sub.add_parser(action)
        a.add_argument('event', help='Boat event ID')
        a.add_argument('--boat')
        if action in ('download', 'delete'):
            a.add_argument('id', help='Attachment ID')
        if action == 'upload':
            a.add_argument('file', help='JPEG, PNG, GIF, WebP, or PDF file (maximum 10 MiB)')
        if action == 'download':
            a.add_argument('--output', required=True, help='New file path; existing files are not overwritten')
        if action in ('upload', 'delete'):
            a.add_argument('--dry-run', action='store_true')
        if action == 'delete':
            a.add_argument('--yes', action='store_true')


def safe_url(url):
    try:
        u = urllib.parse.urlsplit(url)
        expected = urllib.parse.urlsplit(CDN_BASE)
        decoded = urllib.parse.unquote(u.path)
        if (u.scheme != expected.scheme or u.netloc != expected.netloc or not u.path.startswith('/')
                or u.username or u.password or u.fragment or '\\' in decoded
                or any(part in ('.', '..') for part in decoded.split('/'))):
            raise ValueError
        return url
    except (TypeError, ValueError):
        raise Error('Attachment URL is not an approved CDN URL.', 5, 'service') from None


def fetch(url):
    request = urllib.request.Request(safe_url(url), method='GET')
    try:
        with urllib.request.build_opener(core.NoRedirect).open(request, timeout=core.REQUEST_TIMEOUT) as response:
            length = response.headers.get('Content-Length')
            if length and (not length.isdigit() or int(length) > MAX_FILE):
                raise Error('Attachment exceeds the download size limit.', 5, 'service')
            data = response.read(MAX_FILE + 1)
            if len(data) > MAX_FILE or (length and len(data) != int(length)):
                raise Error('Attachment download was incomplete or too large.', 5, 'service')
            return data
    except urllib.error.HTTPError as e:
        raise core.http_error(e, service='Attachment download') from None
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        raise Error('Attachment download failed.', 5, 'network') from None


def asset_request(path, method, data=None):
    # This function never accepts an arbitrary host or caller-provided headers.
    parsed = urllib.parse.urlsplit(path)
    if method == 'POST':
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        expected = {'entityId', 'type', 'entityType', 'lat', 'lon', 'name'}
        if (parsed.path != '/web/assets/add' or set(query) != expected
                or any(len(v) != 1 for v in query.values())
                or query['type'] != ['IMAGE'] or query['entityType'] != ['BOAT_PROFILE_EVENT_ASSET']
                or query['lat'] != ['0'] or query['lon'] != ['0']
                or not query['entityId'][0] or not query['name'][0]):
            raise Error('Invalid asset operation.', 2, 'config')
    elif method == 'DELETE':
        if not re.fullmatch(r'/web/assets/delete/[^/]+', parsed.path) or parsed.query:
            raise Error('Invalid asset operation.', 2, 'config')
    else:
        raise Error('Invalid asset operation.', 2, 'config')
    s = core.session()
    headers = {'id-token': s['id_token'], 'target': 'SE', 'Authorization': core.client_header(),
               'Content-Type': 'application/octet-stream' if data is not None else 'application/json'}
    req = urllib.request.Request(ASSET_BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.build_opener(core.NoRedirect).open(req, timeout=core.REQUEST_TIMEOUT) as res:
            raw = res.read(core.MAX_RESPONSE + 1)
        if len(raw) > core.MAX_RESPONSE:
            raise Error('Asset service response exceeded size limit.', 5, 'service')
        result = json.loads(raw) if raw else None
        if isinstance(result, dict) and (result.get('error') or ('status' in result and result['status'] != 'OK')):
            raise Error('Asset service did not confirm the write.', 5, 'service')
        return result
    except urllib.error.HTTPError as e:
        raise core.http_error(e, service='Asset service') from None
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        raise Error('Asset service connection failed.', 5, 'network') from None
    except (ValueError, UnicodeDecodeError):
        raise Error('Invalid asset service response.', 5, 'service') from None


def image_bytes(path):
    try:
        with open(path, 'rb') as source:
            data = source.read(MAX_FILE + 1)
    except OSError:
        raise Error('Cannot read attachment file.', 2, 'input') from None
    valid = (data.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff', b'GIF87a', b'GIF89a', b'%PDF-')) or data.startswith(b'RIFF') and data[8:12] == b'WEBP')
    if len(data) > MAX_FILE or not valid:
        raise Error('Use a JPEG, PNG, GIF, WebP, or PDF file up to 10 MiB.', 2, 'input')
    return data


def clean(asset):
    return {k: v for k, v in asset.items() if k not in ('originalUrl', 'scaledUrl')}


def execute(a, b, helpers):
    find, pathid, collection, confirm = helpers
    bid, eid = pathid(b['id']), pathid(a.event)
    event = find(collection(b, 'boat-events'), a.event, 'Event')
    items = event.get('assets') or []
    if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
        raise Error('Invalid attachment list.', 5, 'service')
    if a.action == 'list':
        return [clean(x) for x in items]
    if a.action == 'download':
        item = find(items, a.id, 'Attachment')
        target = Path(a.output)
        if target.exists() or target.is_symlink():
            raise Error('Output already exists.', 2, 'input')
        data = fetch(item.get('originalUrl'))
        temp = None
        try:
            fd, temp = tempfile.mkstemp(prefix='.skippo-', dir=target.parent)
            with os.fdopen(fd, 'wb') as out:
                out.write(data)
            os.link(temp, target)
        except FileExistsError:
            raise Error('Output already exists.', 2, 'input') from None
        except OSError:
            raise Error('Could not save attachment.', 2, 'input') from None
        finally:
            if temp and os.path.exists(temp):
                os.unlink(temp)
        return {'saved': str(target), 'bytes': len(data)}
    if a.action == 'delete':
        item = find(items, a.id, 'Attachment')
        confirm(a, 'attachment')
        if a.dry_run:
            return {'dry_run': True, 'operation': 'delete', 'id': a.id}
        path = '/web/assets/delete/' + pathid(item['id'])
    else:
        data = image_bytes(a.file)
        name = Path(a.file).name
        if not name or len(name.encode()) > 255 or any(ord(c) < 32 for c in name):
            raise Error('Invalid file name.', 2, 'input')
        if a.dry_run:
            return {'dry_run': True, 'operation': 'upload', 'name': name, 'bytes': len(data)}
        query = urllib.parse.urlencode({'entityId': a.event, 'type': 'IMAGE', 'entityType': 'BOAT_PROFILE_EVENT_ASSET', 'lat': '0', 'lon': '0', 'name': name})
        path = '/web/assets/add?' + query
    reconcile = f'skippo attachments list {eid} --boat {bid}'
    try:
        result = asset_request(path, 'DELETE' if a.action == 'delete' else 'POST', None if a.action == 'delete' else data)
    except Error as exc:
        if exc.code == 5:
            unknown = Error('Write outcome unknown; inspect with: ' + reconcile, 5, 'outcome_unknown')
            unknown.status, unknown.reason = exc.status, exc.reason
            raise unknown from None
        raise
    try:
        updated = find(collection(b, 'boat-events'), a.event, 'Event').get('assets')
        if updated is None:
            updated = []
        if not isinstance(updated, list) or any(not isinstance(x, dict) for x in updated):
            raise ValueError
        if a.action == 'delete':
            if any(str(x.get('id')) == a.id for x in updated):
                raise ValueError
            return {'deleted': a.id}
        old = {str(x.get('id')) for x in items}
        new = [x for x in updated if str(x.get('id')) not in old]
        if len(new) != 1:
            raise ValueError
        returned_id = result.get('id') if isinstance(result, dict) else None
        if returned_id and str(new[0].get('id')) != str(returned_id):
            raise ValueError
        if fetch(new[0].get('originalUrl')) != data:
            raise ValueError
        return clean(new[0])
    except (Error, ValueError, TypeError, KeyError):
        raise Error('Write completed but could not be verified; inspect with: ' + reconcile, 5, 'written_not_verified') from None
