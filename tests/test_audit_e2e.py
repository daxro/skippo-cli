"""Adversarial end-to-end regressions using the local synthetic service."""
import json
import subprocess
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AuditE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import locally to avoid exposing the other TestCase to discovery twice.
        from test_e2e import E2E, Handler
        cls.fixture_class = E2E

        class AuditHandler(Handler):
            def respond(self, code, obj):
                auth_path = {'login': '/v1/accounts:signInWithPassword',
                             'refresh': '/v1/token'}.get(self.server.auth_endpoint)
                if (code == 200 and self.server.auth_reply is not None
                        and auth_path and self.path.startswith(auth_path)):
                    obj = self.server.auth_reply
                if (self.command == 'POST' and self.path == '/boat-profiles/b1/engine'
                        and code == 200 and self.server.return_plural):
                    self.server.boat['engines'] = [self.server.boat.pop('engine')]
                if (self.command == 'POST' and self.path == '/boat-profiles/b1/engine'
                        and code == 200 and self.server.retain_engine_data):
                    self.server.boat['engine']['data'] = {'horsePower': 50}
                return super().respond(code, obj)

            def handle_request(self):
                if self.path.startswith('/v1/projects/') and self.server.retry_denied:
                    self.server.trip_requests += 1
                    return self.respond(401 if self.server.trip_requests == 1 else 403, {})
                return super().handle_request()

            do_GET = do_POST = do_PUT = do_DELETE = handle_request

        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), AuditHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        E2E.server = cls.server

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.fixture = self.fixture_class()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.server.return_plural = False
        self.server.retain_engine_data = False
        self.server.retry_denied = False
        self.server.trip_requests = 0
        self.server.auth_reply = None
        self.server.auth_endpoint = None

    def run_cli(self, *args, input=None, env=None):
        return subprocess.run([sys.executable, str(ROOT / 'tests/launcher.py'), '--json', *args],
                              input=input, capture_output=True, text=True,
                              env=env or self.fixture.env, cwd=self.fixture.tmp.name, check=False)

    def login(self):
        result = self.run_cli('auth', 'login', '--email', 'synthetic@example.test',
                              '--password-stdin', input='correct\n')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_engine_none_with_existing_data(self):
        self.login()
        self.server.boat['engine'] = {'type': 0, 'data': {'horsePower': 50}}
        result = self.run_cli('engines', 'update', '--type', 'none')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.server.boat['engine'], {'type': 4, 'data': None})
        self.assertEqual(json.loads(result.stdout)['type'], 4)

    def test_engine_verification_with_plural_profile(self):
        self.login()
        self.server.return_plural = True
        self.server.boat['engines'] = [{'type': 0, 'data': {'horsePower': 50}}]
        result = self.run_cli('engines', 'update', '--horsepower', '60')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.server.boat['engines'][0]['data']['horsePower'], 60)
        self.assertEqual(json.loads(result.stdout)['data']['horsePower'], 60)

    def test_engine_none_can_retain_previous_data(self):
        self.login()
        self.server.retain_engine_data = True
        self.server.boat['engine'] = {'type': 0, 'data': {'horsePower': 50}}
        result = self.run_cli('engines', 'update', '--type', 'none')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['type'], 4)
        self.assertEqual(self.server.boat['engine']['data']['horsePower'], 50)

    def test_non_utf8_password_file_is_input_error(self):
        password = Path(self.fixture.tmp.name) / 'bad-password'
        password.write_bytes(b'\xff')
        result = self.run_cli('auth', 'login', '--email', 'synthetic@example.test',
                              '--password-file', str(password))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stderr)['error']['type'], 'input')
        self.assertEqual(result.stdout, '')

    def test_trip_denial_after_refresh_is_permission_denied(self):
        self.login()
        self.server.retry_denied = True
        result = self.run_cli('trips', 'list')
        self.assertEqual(self.server.trip_requests, 2)
        self.assertEqual(result.returncode, 5, result.stderr)
        self.assertEqual(json.loads(result.stderr)['error']['type'], 'permission_denied')
        self.assertEqual(result.stdout, '')

    def test_logout_config_path_error_is_config_error(self):
        env = dict(self.fixture.env, XDG_CONFIG_HOME='/dev/null')
        result = self.run_cli('auth', 'logout', env=env)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stderr)['error']['type'], 'config')
        self.assertEqual(result.stdout, '')

    def test_invalid_login_response_preserves_existing_session(self):
        self.login()
        session = Path(self.fixture.tmp.name) / 'skippo-cli' / 'session.json'
        before = session.read_bytes()
        valid = {'idToken': 'new-id', 'refreshToken': 'new-refresh',
                 'expiresIn': '3600', 'localId': 'user1'}
        self.server.auth_endpoint = 'login'
        for key, value in [('idToken', ''), ('idToken', 42), ('refreshToken', ''),
                           ('refreshToken', ['bad']), ('expiresIn', '0'),
                           ('expiresIn', '-1'), ('expiresIn', 'invalid')]:
            with self.subTest(field=key, value=value):
                session.write_bytes(before)
                self.server.auth_reply = dict(valid, **{key: value})
                result = self.run_cli('auth', 'login', '--email', 'synthetic@example.test',
                                      '--password-stdin', input='correct\n')
                self.assertEqual(result.returncode, 5, result.stderr)
                self.assertEqual(json.loads(result.stderr)['error']['type'], 'service')
                self.assertEqual(result.stdout, '')
                self.assertEqual(session.read_bytes(), before)

    def test_invalid_refresh_response_preserves_existing_session(self):
        self.login()
        session = Path(self.fixture.tmp.name) / 'skippo-cli' / 'session.json'
        old = json.loads(session.read_text())
        old['expires_at'] = 0
        session.write_text(json.dumps(old))
        before = session.read_bytes()
        valid = {'id_token': 'new-id', 'refresh_token': 'new-refresh',
                 'expires_in': '3600', 'user_id': 'user1'}
        self.server.auth_endpoint = 'refresh'
        for key, value in [('id_token', ''), ('id_token', 42), ('refresh_token', ''),
                           ('refresh_token', ['bad']), ('expires_in', '0'),
                           ('expires_in', '-1'), ('expires_in', 'invalid')]:
            with self.subTest(field=key, value=value):
                session.write_bytes(before)
                self.server.auth_reply = dict(valid, **{key: value})
                result = self.run_cli('boats', 'list')
                self.assertEqual(result.returncode, 5, result.stderr)
                self.assertEqual(json.loads(result.stderr)['error']['type'], 'service')
                self.assertEqual(result.stdout, '')
                self.assertEqual(session.read_bytes(), before)

    def test_login_allows_missing_uid(self):
        self.server.auth_endpoint = 'login'
        self.server.auth_reply = {'idToken': 'id-token', 'refreshToken': 'refresh',
                                  'expiresIn': '3600'}
        result = self.run_cli('auth', 'login', '--email', 'synthetic@example.test',
                              '--password-stdin', input='correct\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['authenticated'])
        session = Path(self.fixture.tmp.name) / 'skippo-cli' / 'session.json'
        self.assertFalse(json.loads(session.read_text()).get('uid'))

    def test_legacy_session_without_uid_can_refresh(self):
        self.login()
        session = Path(self.fixture.tmp.name) / 'skippo-cli' / 'session.json'
        old = json.loads(session.read_text())
        old.pop('uid')
        old['expires_at'] = 0
        session.write_text(json.dumps(old))
        self.server.auth_endpoint = 'refresh'
        self.server.auth_reply = {'id_token': 'id-token', 'refresh_token': 'refresh',
                                  'expires_in': '3600'}
        result = self.run_cli('boats', 'list')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)[0]['id'], 'b1')
        self.assertFalse(json.loads(session.read_text()).get('uid'))

    def test_type_none_rejects_contradictory_data_without_write(self):
        self.login()
        self.server.boat['engine'] = {'type': 0, 'data': {'horsePower': 50}}
        before = len(self.server.requests)
        result = self.run_cli('engines', 'update', '--type', 'none', '--horsepower', '60')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(any(method != 'GET' for method, _, _ in self.server.requests[before:]))
        self.assertEqual(self.server.boat['engine']['data']['horsePower'], 50)

    def test_multiple_engines_are_not_overwritten_via_legacy_field(self):
        self.login()
        first = {'type': 0, 'data': {'horsePower': 50}}
        self.server.boat.update(engine=first, engines=[first, {'type': 1, 'data': {'horsePower': 20}}])
        before = len(self.server.requests)
        result = self.run_cli('engines', 'update', '--horsepower', '60')
        self.assertEqual(result.returncode, 5, result.stderr)
        self.assertEqual(json.loads(result.stderr)['error']['type'], 'unsupported_schema')
        self.assertFalse(any(method != 'GET' for method, _, _ in self.server.requests[before:]))

    def test_lock_and_save_failures_are_configuration_errors(self):
        directory = Path(self.fixture.tmp.name) / 'skippo-cli'
        directory.mkdir()
        lock = directory / 'lock'
        lock.mkdir()
        result = self.run_cli('auth', 'logout')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stderr)['error']['type'], 'config')
        lock.rmdir()
        # A directory at the session file path makes atomic replacement fail,
        # even when these tests run with elevated filesystem permissions.
        (directory / 'session.json').mkdir()
        result = self.run_cli('auth', 'login', '--email', 'synthetic@example.test',
                              '--password-stdin', input='correct\n')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stderr)['error']['type'], 'config')
        self.assertFalse(list(directory.glob('.tmp-*')))

    def test_invalid_local_config_and_expiry_are_configuration_errors(self):
        self.login()
        directory = Path(self.fixture.tmp.name) / 'skippo-cli'
        (directory / 'config.json').write_text('[]')
        result = self.run_cli('config', 'get')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stderr)['error']['type'], 'config')
        session = directory / 'session.json'
        data = json.loads(session.read_text())
        data['expires_at'] = 'invalid'
        session.write_text(json.dumps(data))
        result = self.run_cli('boats', 'list')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stderr)['error']['type'], 'config')

    def test_fuel_update_does_not_claim_success_if_attachments_disappear(self):
        self.login()
        self.server.events = [{'id': 'e1', 'category': 4, 'title': 'Diesel',
                               'description': '20', 'dateEpochMs': 1735776000000,
                               'assets': [{'id': 'a1', 'type': 'IMAGE'}]}]
        before = len(self.server.requests)
        # This simulator replaces the record and drops read-only attachment
        # metadata. That is fault injection, not proof of Skippo's behavior.
        result = self.run_cli('fuel', 'update', 'e1', '--liters', '25')
        self.assertEqual(result.returncode, 5, result.stderr)
        self.assertEqual(json.loads(result.stderr)['error']['type'], 'written_not_verified')
        posts = [body for method, path, body in self.server.requests[before:]
                 if method == 'POST' and path.endswith('/boat-events')]
        self.assertEqual(len(posts), 1)
        # Do not send signed URLs or invent writable relationship fields.
        self.assertNotIn('assets', posts[0])
