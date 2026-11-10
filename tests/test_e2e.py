import base64
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def handle_request(self):
        server = self.server
        url = urlsplit(self.path)
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length)
        body = json.loads(raw) if raw and self.headers.get('Content-Type') == 'application/json' else {}
        server.requests.append((self.command, url.path, body))
        if getattr(server, 'failure', None) and url.path == '/boat-profiles':
            failure = server.failure
            server.failure = None
            if failure == 'timeout':
                time.sleep(1)
                return
            if failure == 'truncated':
                self.send_response(200)
                self.send_header('Content-Length', '100')
                self.end_headers()
                self.wfile.write(b'{}')
                return
            if failure == 'malformed':
                self.send_response(200); self.end_headers(); self.wfile.write(b'{'); return
            if failure == 'oversize':
                self.send_response(200); self.end_headers(); self.wfile.write(b' ' * (8 * 1024 * 1024 + 1)); return
            if failure == 'shape':
                return self.respond(200, {'boatProfiles': 'bad'})
            return self.respond(failure, {})
        if url.path in ('/', '/assets/index-test.js'):
            if self.headers.get('Authorization') or self.headers.get('id-token'):
                return self.respond(403, {})
            if url.path == '/':
                data = server.config_html.encode()
            else:
                data = server.config_js.encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if url.path.startswith('/v1/accounts:signInWithPassword'):
            if parse_qs(url.query).get('key') != ['synthetic-public-config']:
                return self.respond(400, {})
            if body.get('password') != 'correct':
                return self.respond(400, {'error': {'code': 400, 'message': 'EMAIL_NOT_FOUND'}})
            return self.respond(200, {'idToken': 'id-token', 'refreshToken': 'refresh', 'expiresIn': '3600', 'localId': 'user1'})
        if url.path == '/v1/token':
            time.sleep(getattr(server, 'refresh_delay', 0))
            if server.revoked:
                return self.respond(400, {})
            return self.respond(200, {'id_token': 'id-token', 'refresh_token': 'refresh', 'expires_in': '3600', 'user_id': 'user1'})
        if url.path.startswith('/v1/projects/nautical-app-se/databases/(default)/documents/users/user1/tracks2026'):
            if self.headers.get('Authorization') != 'Bearer id-token':
                return self.respond(403, {})
            if server.trip_denied:
                return self.respond(403, {})
            token = parse_qs(url.query).get('pageToken', [None])[0]
            doc = {'name': url.path + ('/t2' if token else '/t1'), 'fields': {'startTimeInMillis': {'integerValue': '1735776000000'}, 'name': {'stringValue': 'Trip'}}}
            if url.path.endswith('/t1'):
                doc['name'] = url.path
                return self.respond(200, doc)
            if server.trip_pages:
                return self.respond(200, {'documents': [doc], 'nextPageToken': 'next'} if (not token or server.trip_pages == 'repeat') else {'documents': [doc]})
            return self.respond(200, {'documents': [doc]})
        if url.path == '/cdn/a1':
            if self.headers.get('Authorization') or self.headers.get('id-token'):
                return self.respond(403, {})
            data = b'unrelated' if server.cdn_mode == 'mismatch' else server.asset_bytes
            if server.cdn_mode == 'oversize':
                self.send_response(200)
                self.send_header('Content-Length', str(11 * 1024 * 1024))
                self.end_headers()
                return
            if server.cdn_mode == 'truncated':
                self.send_response(200)
                self.send_header('Content-Length', '1000')
                self.end_headers()
                self.wfile.write(b'partial')
                return
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.headers.get('id-token') != 'id-token' or self.headers.get('target') != 'SE' or self.headers.get('Authorization') != 'Basic ' + base64.b64encode(b'bpClient:synthetic-public-client').decode():
            return self.respond(403, {})
        boat = server.boat
        if url.path == '/insurances/companies/list':
            return self.respond(200, [{'id': 'co1', 'name': 'Synthetic'}])
        if url.path == '/boat-profiles/b1/navigation-settings' and self.command == 'POST':
            boat['navigationSettings'] = dict(body)
            if 'speedInMs' in boat['navigationSettings']:
                boat['navigationSettings']['speedInMs'] = round(boat['navigationSettings']['speedInMs'], 2)
            if server.settings_mismatch:
                boat['navigationSettings']['safeDepthInMeters'] = 999
            return self.respond(200, body)
        if url.path == '/boat-profiles/b1/boat-insurance' and self.command == 'POST':
            body['id'] = 'ins1'
            boat['insurance'] = body
            return self.respond(200, body)
        if url.path == '/boat-profiles/b1/boat-insurance/insurance/ins1' and self.command == 'DELETE':
            boat.pop('insurance', None)
            return self.respond(200, {})
        if url.path == '/checklists/c1/item' and self.command == 'POST':
            item = {'id': 'i2', 'type': 0, 'name': parse_qs(url.query)['text'][0], 'checked': False}
            boat['checklists'][0]['items'].append(item)
            return self.respond(200, item)
        if url.path == '/checklists/item/i2' and self.command == 'DELETE':
            boat['checklists'][0]['items'] = [x for x in boat['checklists'][0]['items'] if x['id'] != 'i2']
            return self.respond(200, {})
        if url.path == '/web/assets/add' and self.command == 'POST':
            query = parse_qs(url.query)
            if query.get('entityId') != ['e1'] or query.get('entityType') != ['BOAT_PROFILE_EVENT_ASSET'] or self.headers.get('Content-Type') != 'application/octet-stream':
                return self.respond(400, {})
            if server.asset_reject:
                return self.respond(400, {})
            server.asset_bytes = raw
            asset = {'id': 'a1', 'originalUrl': f'http://127.0.0.1:{server.server_port}/cdn/a1', 'type': 'IMAGE'}
            server.events[0].setdefault('assets', []).append(asset)
            if server.asset_status_error:
                return self.respond(200, {'status': 'ERROR'})
            if server.asset_drop:
                self.close_connection = True
                self.connection.shutdown(2)
                self.connection.close()
                return
            return self.respond(200, {'status': 'OK'})
        if url.path == '/web/assets/delete/a1' and self.command == 'DELETE':
            server.events[0]['assets'] = []
            return self.respond(200, {'status': 'OK'})
        if url.path == '/boat-profiles/b1/boat-events/event/e1' and self.command == 'DELETE':
            server.events = []
            return self.respond(200, {})
        if url.path == '/boat-profiles' and self.command == 'GET':
            return self.respond(200, {'boatProfiles': [boat] + server.extra_boats, 'user': {}})
        if url.path == '/boat-profiles/b1/base-data' and self.command == 'POST':
            boat['baseData'] = body
            return self.respond(200, body)
        if url.path == '/boat-profiles/b1/home-harbor' and self.command == 'POST':
            boat['homeHarbor'] = {'coordinate': body}
            return self.respond(200, boat['homeHarbor'])
        if url.path == '/boat-profiles/b1/engine' and self.command == 'POST':
            boat['engine'] = body
            return self.respond(200, body)
        if url.path == '/checklists/item/i1' and self.command == 'PUT':
            boat['checklists'][0]['items'][0]['checked'] = parse_qs(url.query)['checked'][0] == 'true'
            return self.respond(200, {})
        if url.path == '/boat-profiles/b1/boat-events/all':
            return self.respond(200, server.events)
        if url.path == '/boat-profiles/b1/boat-events' and self.command == 'POST':
            body['id'] = 'e1'
            existing = next((i for i, e in enumerate(server.events) if e['id'] == body['id']), None)
            if existing is None:
                server.events.append(body)
            else:
                server.events[existing] = body
            if server.drop_write:
                self.close_connection = True
                self.connection.shutdown(2)
                self.connection.close()
                return
            if server.bad_readback:
                server.events[-1]['title'] = 'Unexpected'
            return self.respond(200, body)
        if url.path == '/boat-profiles/b1/notes/all':
            return self.respond(200, server.notes)
        if url.path == '/boat-profiles/b1/notes/note' and self.command == 'POST':
            if body.get('id'):
                server.notes = [body if n['id'] == body['id'] else n for n in server.notes]
            else:
                body['id'] = 'n1'
                server.notes.append(body)
            return self.respond(200, server.notes)
        if url.path == '/boat-profiles/b1/notes/note/n1' and self.command == 'DELETE':
            server.notes = []
            return self.respond(200, [])
        self.respond(404, {})

    do_GET = do_POST = do_PUT = do_DELETE = handle_request


class E2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server.boat = {'id': 'b1', 'baseData': {'name': 'Example', 'year': 2000, 'type': 1}, 'checklists': [{'id': 'c1', 'items': [{'id': 'i1', 'checked': False}]}]}
        self.server.events, self.server.notes, self.server.requests = [], [], []
        self.server.failure = None
        self.server.drop_write = self.server.bad_readback = False
        self.server.refresh_delay = 0
        self.server.extra_boats = []
        self.server.trip_denied = False
        self.server.trip_pages = None
        self.server.revoked = False
        self.server.config_html = '<script type="module" src="/assets/index-test.js"></script>'
        self.server.config_js = '{apiKey:`synthetic-dk`,authDomain:`nautical-app-dk.firebaseapp.com`};{apiKey:`synthetic-public-config`,authDomain:`nautical-app-se.firebaseapp.com`};btoa(`bpClient:synthetic-public-client`)'
        self.server.asset_bytes = b''
        self.server.cdn_mode = None
        self.server.asset_drop = self.server.asset_reject = self.server.asset_status_error = self.server.settings_mismatch = False
        self.env = dict(os.environ, TEST_SERVER=f'http://127.0.0.1:{self.server.server_port}', XDG_CONFIG_HOME=self.tmp.name)
        self.env.pop('PYTHONPATH', None)

    def cli(self, *args, input=None, code=0):
        proc = subprocess.run([sys.executable, str(ROOT / 'tests/launcher.py'), '--json', *args], input=input, capture_output=True, text=True, env=self.env, cwd=self.tmp.name, check=False)
        self.assertEqual(proc.returncode, code, proc.stderr)
        if code == 0:
            self.assertEqual(proc.stderr, '')
            return json.loads(proc.stdout)
        self.assertEqual(proc.stdout, '')
        return json.loads(proc.stderr)

    def login(self):
        self.cli('auth', 'login', '--email', 'synthetic@example.test', '--password-stdin', input='correct\n')

    def test_login_provider_reason_in_human_output(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tests/launcher.py'),
                                 'auth', 'login', '--email', 'synthetic@example.test',
                                 '--password-stdin'], input='wrong\n', capture_output=True,
                                text=True, env=self.env, cwd=self.tmp.name, check=False)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout, '')
        self.assertIn('HTTP 400', result.stderr)
        self.assertIn('EMAIL_NOT_FOUND', result.stderr)

    def test_login_provider_reason_is_reported(self):
        error = self.cli('auth', 'login', '--email', 'synthetic@example.test',
                         '--password-stdin', input='wrong\n', code=3)
        self.assertEqual(error['error']['http_status'], 400)
        self.assertEqual(error['error']['reason'], 'EMAIL_NOT_FOUND')
        self.assertIn('EMAIL_NOT_FOUND', error['error']['message'])

    def test_full_flow(self):
        self.login()
        self.assertEqual(self.cli('boats', 'list')[0]['id'], 'b1')
        self.cli('config', 'set', 'boat', 'b1')
        self.assertEqual(self.cli('boats', 'show')['id'], 'b1')
        before = len(self.server.requests)
        self.cli('boats', 'update', '--name', 'Updated', '--dry-run')
        self.assertFalse(any(method != 'GET' for method, _, _ in self.server.requests[before:]))
        self.cli('boats', 'update', '--name', 'Updated')
        self.assertEqual(self.server.boat['baseData'], {'name': 'Updated', 'year': 2000, 'type': 1})
        self.cli('boats', 'harbor', '--latitude', '59', '--longitude', '18')
        self.assertEqual(self.server.boat['homeHarbor']['coordinate'], {'lat': 59, 'lon': 18})
        self.cli('engines', 'add', '--type', 'petrol', '--horsepower', '40')
        engine_request = next(body for method, path, body in self.server.requests if path.endswith('/engine') and method == 'POST')
        self.assertEqual(engine_request, {'type': 1, 'data': {'horsePower': 40}})
        self.cli('engines', 'update', '--year', '2020')
        self.assertEqual(self.cli('engines', 'list')[0]['data']['horsePower'], 40)
        self.cli('checklists', 'check', 'c1', 'i1')
        self.assertTrue(self.cli('checklists', 'show', 'c1')['items'][0]['checked'])
        self.cli('checklists', 'uncheck', 'c1', 'i1')
        event = self.cli('events', 'add', '--title', 'Service', '--date', '2025-01-02', '--category', 'service')
        self.assertEqual(self.cli('events', 'show', event['id'])['title'], 'Service')
        event_request = next(body for method, path, body in self.server.requests if path.endswith('/boat-events') and method == 'POST')
        self.assertEqual(event_request['category'], 3)
        self.assertEqual(event_request['dateEpochMs'], 1735776000000)
        self.assertEqual(len(self.cli('events', 'list', '--since', '2025-01-02')), 1)
        note = self.cli('notes', 'add', '--title', 'Test', '--content', 'One')
        self.cli('notes', 'update', note['id'], '--content', 'Two')
        self.assertEqual(self.cli('notes', 'show', note['id'])['content'], 'Two')
        self.cli('notes', 'delete', note['id'], '--yes', '--no-input')
        self.assertEqual(self.cli('notes', 'list'), [])
        self.assertEqual(self.cli('trips', 'list', '--since', '2025-01-02')[0]['name'], 'Trip')
        self.assertEqual(self.cli('trips', 'show', 't1')['id'], 't1')
        self.cli('auth', 'logout')
        self.cli('boats', 'list', code=3)

    def test_failures_and_persistent_login(self):
        self.login()
        self.cli('auth', 'login', '--email', 'synthetic@example.test', '--password-stdin', input='wrong\n', code=3)
        self.cli('auth', 'status')
        self.cli('events', 'list', '--since', 'bad', code=2)
        self.cli('notes', 'show', 'missing', code=4)
        self.cli('notes', 'add', '--title', 'A')
        self.cli('notes', 'delete', 'n1', '--no-input', code=2)
        self.assertEqual(len(self.server.notes), 1)

    def test_service_errors_and_security(self):
        self.login()
        for status in (429, 500, 'malformed', 'oversize', 'shape', 'timeout', 'truncated'):
            self.server.failure = status
            self.cli('boats', 'list', code=5)
        self.cli('boats', 'show', 'foreign', code=4)
        self.cli('checklists', 'check', 'c1', 'foreign', code=4)
        self.cli('engines', 'add', '--type', 'petrol', '--horsepower', 'nan', code=2)
        self.cli('boats', 'harbor', '--latitude', '91', '--longitude', '18', code=2)
        config_dir = Path(self.tmp.name) / 'skippo-cli'
        if os.name == 'posix':
            self.assertEqual((config_dir.stat().st_mode & 0o777), 0o700)
            self.assertEqual(((config_dir / 'session.json').stat().st_mode & 0o777), 0o600)

    def test_expired_token_refresh(self):
        self.login()
        session_file = Path(self.tmp.name) / 'skippo-cli' / 'session.json'
        session = json.loads(session_file.read_text())
        session['expires_at'] = 0
        session_file.write_text(json.dumps(session))
        self.cli('boats', 'list')
        self.assertEqual(sum(path == '/v1/token' for _, path, _ in self.server.requests), 1)

    def test_uncertain_write_never_retried(self):
        self.login()
        self.server.drop_write = True
        error = self.cli('events', 'add', '--title', 'Service', '--date', '2025-01-02', '--category', 'service', code=5)
        self.assertEqual(error['error']['type'], 'outcome_unknown')
        self.assertEqual(len(self.server.events), 1)
        self.assertEqual(sum(method == 'POST' and path.endswith('/boat-events') for method, path, _ in self.server.requests), 1)

    def test_concurrent_refresh_and_logout(self):
        self.login()
        session_file = Path(self.tmp.name) / 'skippo-cli' / 'session.json'
        session = json.loads(session_file.read_text())
        session['expires_at'] = 0
        session_file.write_text(json.dumps(session))
        self.server.refresh_delay = 0.2
        def start(*args):
            return subprocess.Popen([sys.executable, str(ROOT / 'tests/launcher.py'), '--json', *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
        processes = [start('boats', 'list') for _ in range(3)]
        for proc in processes:
            out, err = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 0, err)
            json.loads(out)
        self.assertEqual(sum(path == '/v1/token' for _, path, _ in self.server.requests), 1)
        session = json.loads(session_file.read_text())
        session['expires_at'] = 0
        session_file.write_text(json.dumps(session))
        refresh = start('boats', 'list')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and sum(path == '/v1/token' for _, path, _ in self.server.requests) < 2:
            time.sleep(.01)
        logout = start('auth', 'logout')
        refresh.communicate(timeout=5)
        logout.communicate(timeout=5)
        self.assertFalse(session_file.exists())


    def test_extended_boat_features(self):
        self.login()
        self.cli('settings', 'update', '--safe-depth', '2.5', '--average-speed', '10', '--consumption', '1.2')
        settings = self.cli('settings', 'show')
        self.assertEqual(settings['speedInMs'], 5.14)
        self.cli('settings', 'update', '--safe-height', '8')
        self.assertEqual(self.cli('settings', 'show')['safeDepthInMeters'], 2.5)
        self.cli('insurance', 'update', '--company-id', 'co1', '--policy-number', 'SYNTHETIC', '--reminder')
        self.cli('insurance', 'update', '--expiration-date', '2026-11-10')
        self.assertEqual(self.cli('insurance', 'show')['insuranceNumber'], 'SYNTHETIC')
        self.cli('insurance', 'delete', '--yes')
        self.cli('checklists', 'add-item', 'c1', '--text', 'Line & knot')
        self.assertEqual(self.server.boat['checklists'][0]['items'][-1]['name'], 'Line & knot')
        self.cli('checklists', 'delete-item', 'c1', 'i2', '--yes')
        fuel = self.cli('fuel', 'add', '--type', 'diesel', '--date', '2025-01-02', '--liters', '123.4567891', '--cost', '200', '--source', 'Station')
        self.assertEqual(fuel['description'], '123.4567891')
        self.assertEqual(fuel['cost'], {'amount': 200, 'currency': 'SEK'})
        self.cli('fuel', 'update', 'e1', '--liters', '20', '--price-per-liter', '2.5')
        self.assertEqual(self.cli('fuel', 'show', 'e1')['cost']['amount'], 50)
        self.assertEqual(self.cli('fuel', 'show', 'e1')['costSource'], 'Station')
        self.cli('fuel', 'delete', 'e1', '--yes')

    def test_attachments_upload_download_delete(self):
        self.login()
        self.cli('events', 'add', '--title', 'Service', '--date', '2025-01-02', '--category', 'service')
        data = b'\x89PNG\r\n\x1a\nsynthetic-image'
        path = Path(self.tmp.name) / 'scan.png'
        path.write_bytes(data)
        before = len(self.server.requests)
        self.cli('attachments', 'upload', 'e1', str(path), '--dry-run')
        self.assertFalse(any(method != 'GET' for method, _, _ in self.server.requests[before:]))
        self.cli('attachments', 'upload', 'e1', str(path))
        self.assertEqual(self.server.asset_bytes, data)
        item = self.cli('attachments', 'list', 'e1')[0]
        self.assertNotIn('originalUrl', item)
        output = Path(self.tmp.name) / 'download.png'
        self.cli('attachments', 'download', 'e1', 'a1', '--output', str(output))
        self.assertEqual(output.read_bytes(), data)
        self.cli('attachments', 'download', 'e1', 'a1', '--output', str(output), code=2)
        self.server.events[0]['assets'][0]['originalUrl'] = 'https://evil.example/a'
        self.cli('attachments', 'download', 'e1', 'a1', '--output', str(output) + '2', code=5)
        self.cli('attachments', 'delete', 'e1', 'a1', '--yes')
        self.assertEqual(self.cli('attachments', 'list', 'e1'), [])


    def test_new_write_failures_and_dry_runs(self):
        self.login()
        before = len(self.server.requests)
        self.cli('settings', 'update', '--safe-depth', '2', '--dry-run')
        self.cli('insurance', 'update', '--company-id', '-', '--policy-number', 'X', '--dry-run')
        self.cli('fuel', 'add', '--type', 'diesel', '--date', '2025-01-02', '--dry-run')
        for value in ('abc', 'NaN', 'sNaN', 'Infinity', '-1'):
            self.cli('fuel', 'add', '--type', 'diesel', '--date', '2025-01-02', '--liters', value, code=2)
        self.cli('checklists', 'add-item', 'foreign', '--text', 'X', code=4)
        self.assertFalse(any(method != 'GET' for method, _, _ in self.server.requests[before:]))
        self.server.settings_mismatch = True
        error = self.cli('settings', 'update', '--safe-depth', '2', code=5)
        self.assertEqual(error['error']['type'], 'written_not_verified')

    def test_attachment_failures_and_pdf(self):
        self.login()
        self.cli('events', 'add', '--title', 'Service', '--date', '2025-01-02', '--category', 'service')
        pdf = b'%PDF-1.4\nsynthetic\n%%EOF\n'
        path = Path(self.tmp.name) / 'document.pdf'
        path.write_bytes(pdf)
        before = len(self.server.requests)
        self.cli('attachments', 'upload', 'foreign', str(path), code=4)
        self.cli('attachments', 'delete', 'e1', 'foreign', '--yes', code=4)
        path.write_bytes(b'invalid')
        self.cli('attachments', 'upload', 'e1', str(path), code=2)
        path.write_bytes(b'%PDF-' + b'x' * (10 * 1024 * 1024))
        self.cli('attachments', 'upload', 'e1', str(path), code=2)
        self.assertFalse(any(method != 'GET' for method, _, _ in self.server.requests[before:]))
        path.write_bytes(pdf)
        self.server.asset_reject = True
        self.cli('attachments', 'upload', 'e1', str(path), code=5)
        self.assertFalse(self.server.events[0].get('assets'))
        self.server.asset_reject = False
        self.server.asset_status_error = True
        result = self.cli('attachments', 'upload', 'e1', str(path), code=5)
        self.assertEqual(result['error']['type'], 'outcome_unknown')
        self.server.events[0]['assets'] = []
        self.server.asset_status_error = False
        self.server.cdn_mode = 'mismatch'
        result = self.cli('attachments', 'upload', 'e1', str(path), code=5)
        self.assertEqual(result['error']['type'], 'written_not_verified')
        self.server.events[0]['assets'] = []
        self.server.cdn_mode = None
        self.cli('attachments', 'upload', 'e1', str(path))
        output = Path(self.tmp.name) / 'saved.pdf'
        self.cli('attachments', 'download', 'e1', 'a1', '--output', str(output))
        self.assertEqual(output.read_bytes(), pdf)
        self.cli('attachments', 'delete', 'e1', 'a1', '--no-input', code=2)
        for mode in ('oversize', 'truncated'):
            self.server.cdn_mode = mode
            target = Path(self.tmp.name) / (mode + '.pdf')
            self.cli('attachments', 'download', 'e1', 'a1', '--output', str(target), code=5)
            self.assertFalse(target.exists())
            self.assertFalse(list(Path(self.tmp.name).glob('.skippo-*')))
        self.server.cdn_mode = None
        self.cli('attachments', 'delete', 'e1', 'a1', '--yes')
        self.server.asset_drop = True
        before = len(self.server.requests)
        error = self.cli('attachments', 'upload', 'e1', str(path), code=5)
        self.assertEqual(error['error']['type'], 'outcome_unknown')
        self.assertEqual(sum(method == 'POST' and endpoint == '/web/assets/add' for method, endpoint, _ in self.server.requests[before:]), 1)


    def test_public_config_selection_and_invalid_documents(self):
        self.login()
        self.assertEqual(sum(path == '/assets/index-test.js' for _, path, _ in self.server.requests), 1)
        for html, script in (
            ('<script type="module" src="https://evil.test/assets/index-test.js"></script>', self.server.config_js),
            ('<script type="module" src="/assets/index-legacy-test.js"></script>', ''),
            ('<script type="module" src="/assets/index-test.js"></script>', '{authDomain:`nautical-app-se.firebaseapp.com`}'),
            ('<script type="module" src="/assets/index-test.js"></script>', '{apiKey:`synthetic-a`,authDomain:`nautical-app-dk.firebaseapp.com`}'),
        ):
            self.server.config_html, self.server.config_js = html, script
            self.cli('auth', 'login', '--email', 'synthetic@example.test', '--password-stdin', input='correct\n', code=5)
        self.assertTrue((Path(self.tmp.name) / 'skippo-cli' / 'session.json').exists())


    def test_written_but_not_verified(self):
        self.login()
        self.server.bad_readback = True
        result = self.cli('events', 'add', '--title', 'Service', '--date', '2025-01-02', '--category', 'service', code=5)
        self.assertEqual(result['error']['type'], 'written_not_verified')
        self.assertEqual(len(self.server.events), 1)

    def test_trips_pagination_and_denial(self):
        self.login()
        self.server.trip_pages = 'pages'
        self.assertEqual(len(self.cli('trips', 'list')), 2)
        self.server.trip_pages = 'repeat'
        self.cli('trips', 'list', code=5)
        self.server.trip_denied = True
        error = self.cli('trips', 'list', code=5)
        self.assertEqual(error['error']['type'], 'permission_denied')

    def test_selection_and_revoked_refresh(self):
        self.login()
        self.server.extra_boats = [{'id': 'b2', 'baseData': {'name': 'Example'}}]
        self.cli('boats', 'show', code=2)
        self.cli('config', 'set', 'boat', 'b1')
        self.server.boat['id'] = 'other'
        self.cli('boats', 'show', code=4)
        session_file = Path(self.tmp.name) / 'skippo-cli' / 'session.json'
        session = json.loads(session_file.read_text())
        session['expires_at'] = 0
        session_file.write_text(json.dumps(session))
        self.server.revoked = True
        self.cli('boats', 'list', code=3)

    def test_help_version_and_missing_subcommands_offline(self):
        for args in (('--help',), ('--version',)):
            proc = subprocess.run([sys.executable, str(ROOT / 'tests/launcher.py'), *args], env=self.env, cwd=self.tmp.name, capture_output=True, text=True, check=False)
            self.assertEqual(proc.returncode, 0)
            self.assertTrue(proc.stdout)
        self.cli('boats', code=2)
        self.cli('bogus', code=2)
        self.assertFalse(self.server.requests)


    @unittest.skipUnless(os.name == 'posix', 'PTY requires POSIX')
    def test_confirmation_denied_in_terminal(self):
        import pty
        self.login()
        self.cli('notes', 'add', '--title', 'A')
        master, slave = pty.openpty()
        try:
            proc = subprocess.Popen([sys.executable, str(ROOT / 'tests/launcher.py'), '--json', 'notes', 'delete', 'n1'], stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, cwd=self.tmp.name)
            os.close(slave)
            slave = None
            os.write(master, b'n\n')
            out, err = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 2, err)
            self.assertFalse(out)
            self.assertEqual(len(self.server.notes), 1)
        finally:
            os.close(master)
            if slave is not None:
                os.close(slave)

    @unittest.skipUnless(os.name == 'posix', 'Signals require POSIX')
    def test_interrupt_and_broken_pipe(self):
        self.login()
        session_file = Path(self.tmp.name) / 'skippo-cli' / 'session.json'
        session = json.loads(session_file.read_text())
        session['expires_at'] = 0
        session_file.write_text(json.dumps(session))
        self.server.refresh_delay = 1
        proc = subprocess.Popen([sys.executable, str(ROOT / 'tests/launcher.py'), '--json', 'boats', 'list'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, cwd=self.tmp.name)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not any(path == '/v1/token' for _, path, _ in self.server.requests):
            time.sleep(.01)
        proc.send_signal(signal.SIGINT)
        out, err = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 130, err)
        self.assertFalse(out)
        self.assertEqual(json.loads(err)['error']['type'], 'interrupted')
        proc = subprocess.Popen([sys.executable, str(ROOT / 'tests/launcher.py'), '--help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, cwd=self.tmp.name)
        proc.stdout.close()
        err = proc.stderr.read()
        proc.stderr.close()
        self.assertEqual(proc.wait(timeout=5), 0, err)
        self.assertNotIn(b'Traceback', err)


    def test_plural_engines_are_not_blindly_written(self):
        self.login()
        self.server.boat['engines'] = []
        self.assertEqual(self.cli('engines', 'list'), [])
        self.cli('engines', 'add', '--type', 'petrol', '--number-of-engines', '2', code=2)
        self.assertFalse(any(path.endswith('/engine') and method == 'POST' for method, path, _ in self.server.requests))


if __name__ == '__main__':
    unittest.main()
