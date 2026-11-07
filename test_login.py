"""Native login adapter tests use synthetic console processes, never a live account."""
from pathlib import Path
import sys
import threading
import unittest

try:
    from login_bridge import LoginError, login, validate_credentials
except ImportError:
    LoginError = login = validate_credentials = None


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(login, 'Graphical login adapter is not implemented')
        self.fixture = [sys.executable, str(Path(__file__).parent / 'tests/fixture_login.py')]

    def test_password_with_unicode_and_shell_symbols_is_delivered_as_terminal_input(self):
        result = login(self.fixture, 'https://example.com', 'reader@example.com', 'p&ass中文', threading.Event(), timeout=5)
        self.assertTrue(result)

    def test_success_exit_without_authentication_is_not_accepted(self):
        with self.assertRaises(LoginError):
            login(self.fixture, 'https://example.com', 'cancel@example.com', 'p&ass中文', threading.Event(), timeout=5)

    def test_rejection_is_actionable_and_does_not_expose_password(self):
        with self.assertRaises(LoginError) as error:
            login(self.fixture, 'https://example.com', 'wrong@example.com', 'p&ass中文', threading.Event(), timeout=5)
        self.assertIn('邮箱或密码', str(error.exception))
        self.assertNotIn('p&ass中文', str(error.exception))

    def test_cancel_and_timeout_stop_waiting(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(LoginError):
            login(self.fixture, 'https://example.com', 'reader@example.com', 'p&ass中文', cancelled, timeout=5)
        with self.assertRaises(LoginError) as error:
            login(self.fixture, 'https://example.com', 'hang@example.com', 'p&ass中文', threading.Event(), timeout=.5)
        self.assertIn('超时', str(error.exception))

    def test_empty_fields_and_control_characters_are_rejected(self):
        for email, password in [('', 'x'), ('reader@example.com', ''), ('reader@example.com', 'x\x1b[201~'), ('a\nb@example.com','x')]:
            with self.subTest(email=email), self.assertRaises(LoginError):
                validate_credentials(email, password)
