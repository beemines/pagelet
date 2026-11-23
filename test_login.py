"""Native login adapter tests use synthetic console processes, never a live account."""
from pathlib import Path
import sys
import threading
import unittest

try:
    from login_bridge import LoginError, _failure, login, validate_credentials
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

    def test_only_distinguishes_account_and_password_when_upstream_does(self):
        self.assertIn('密码不正确', _failure('Error: Incorrect password'))
        self.assertIn('没有找到这个账号', _failure('Error: Account not found'))
        self.assertIn('邮箱或密码', _failure('Error: Incorrect email or password'))
        self.assertNotIn('密码不正确', _failure('Error: dial tcp: i/o timeout'))

    def test_domain_precheck_failure_is_not_an_account_or_domain_format_error(self):
        report = ('Email: probe@example.invalid\n'
                  'Error: https://z-lib.gd is not usable for EAPI (network_error): '
                  'set ZLIB_DOMAIN to a domain reported healthy by zlib doctor')
        self.assertEqual(_failure(report), '连不上书库，尚未验证账号或密码。请在「连接设置」检测域名或检查代理。')

    def test_domain_precheck_distinguishes_website_verification_from_network_failure(self):
        self.assertIn('网页验证', _failure('Error: https://z-lib.gd is not usable for EAPI (challenged): use zlib doctor'))
        self.assertIn('尚未验证账号或密码', _failure('Error: https://z-lib.gd is not usable for EAPI (http_error)'))

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
