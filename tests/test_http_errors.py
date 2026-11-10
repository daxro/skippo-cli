import io
import json
import unittest
from urllib.error import HTTPError

from skippo_cli.core import http_error


class HttpErrorTests(unittest.TestCase):
    def error(self, body):
        return HTTPError('https://example.invalid', 400, 'error', {}, io.BytesIO(body))

    def test_firebase_reason_and_private_suffix(self):
        err = http_error(self.error(json.dumps({'error': {'message': 'EMAIL_NOT_FOUND : private@example.test'}}).encode()), authentication=True)
        self.assertEqual((err.code, err.status, err.reason), (3, 400, 'EMAIL_NOT_FOUND'))
        self.assertNotIn('private@example.test', str(err))

    def test_untrusted_or_invalid_bodies_are_not_exposed(self):
        for body in (b'{', b'not json', b'x' * 65537,
                     b'{"error":{"message":"private@example.test"}}',
                     b'{"error":{"message":"EMAIL_NOT_FOUND_SECRET"}}'):
            with self.subTest(body_length=len(body)):
                err = http_error(self.error(body), authentication=True)
                self.assertEqual(err.status, 400)
                self.assertIsNone(err.reason)
                self.assertNotIn('private@example.test', str(err))

    def test_firestore_status_code(self):
        err = http_error(self.error(b'{"error":{"status":"PERMISSION_DENIED","message":"Missing permissions"}}'))
        self.assertEqual(err.reason, 'PERMISSION_DENIED')
