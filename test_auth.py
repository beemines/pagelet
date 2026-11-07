import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import server


class WebAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent / 'tests')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = server.App(self.root / 'data', cli=[sys.executable, str(Path(__file__).parent / 'tests/fixture_login.py')], downloads_dir=self.root / 'books')
        self.app.update_settings({'domain':'https://example.com'})
        self.addCleanup(self.app.executor.shutdown, wait=True)
        self.addCleanup(self.close_auth)

    def close_auth(self):
        self.app.cancel_auth()
        if self.app.auth_thread:
            self.app.auth_thread.join(timeout=3)

    def wait_done(self):
        for _ in range(150):
            state = self.app.auth_state()
            if state['status'] not in ('running', 'cancelling'):
                return state
            time.sleep(.025)
        self.fail('Authentication did not finish')

    def test_success_has_no_credentials_in_state_or_files(self):
        result = self.app.start_auth({'email':'reader@example.com','password':'p&ass中文'})
        self.assertNotIn('password', result)
        state = self.wait_done()
        self.assertEqual(state['status'], 'success')
        for value in (json.dumps(self.app.state(),ensure_ascii=False),json.dumps(state,ensure_ascii=False)):
            self.assertNotIn('p&ass中文', value)
            self.assertNotIn('reader@example.com', value)
        for file in (self.root/'data').glob('*.json'):
            self.assertNotIn('p&ass中文', file.read_text(encoding='utf-8'))

    def test_failure_is_visible_and_redacted(self):
        self.app.start_auth({'email':'wrong@example.com','password':'p&ass中文'})
        result = self.wait_done()
        self.assertEqual(result['status'], 'failed')
        self.assertIn('邮箱或密码', result['error'])
        self.assertNotIn('p&ass中文', result['error'])

    def test_running_login_is_deduplicated_and_cancellable(self):
        self.app.start_auth({'email':'hang@example.com','password':'p&ass中文'})
        with self.assertRaises(server.AppError):
            self.app.start_auth({'email':'reader@example.com','password':'p&ass中文'})
        self.app.cancel_auth()
        self.assertEqual(self.wait_done()['status'], 'cancelled')

    def test_invalid_payload_never_starts_authentication(self):
        with self.assertRaises(server.AppError):
            self.app.start_auth({'email':'not-an-email','password':''})
        self.assertEqual(self.app.auth_state()['status'], 'idle')

    def test_cancelled_request_cannot_start_late(self):
        attempt = 'delayed-start-001'
        self.app.cancel_auth({'attempt_id':attempt})
        with self.assertRaises(server.AppError) as error:
            self.app.start_auth({'email':'reader@example.com','password':'p&ass中文','attempt_id':attempt})
        self.assertEqual(error.exception.code, 'auth_cancelled')
        self.assertIsNone(self.app.auth_thread)

    def test_cancelling_other_attempt_does_not_stop_current_login(self):
        self.app.start_auth({'email':'hang@example.com','password':'p&ass中文','attempt_id':'current'})
        self.app.cancel_auth({'attempt_id':'another'})
        self.assertEqual(self.app.auth_state()['status'], 'running')
        self.app.cancel_auth({'attempt_id':'current'})
        self.assertEqual(self.wait_done()['status'], 'cancelled')
