from pathlib import Path
import sys
import unittest

try:
    import book_catalog as catalog
except ImportError:
    catalog = None


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(catalog,'Book catalog adapter is not implemented')
        self.cli = [sys.executable,str(Path(__file__).parent/'tests/fixture_mcp.py')]

    def test_read_only_mcp_fetches_description_and_metadata(self):
        result=catalog.fetch_details(self.cli,{},'42:abc')
        self.assertEqual(result['name'],'测试图书')
        self.assertEqual(result['isbn'],'9780000000000')
        self.assertEqual(result['description'],'简介第一段。\n\n第二段 & 目录')
        self.assertNotIn('evil',result['description'])

    def test_bad_reference_is_rejected_before_starting_cli(self):
        with self.assertRaises(catalog.CatalogError):
            catalog.fetch_details(['not-an-executable'],{},'--help')

    def test_mcp_error_and_timeout_are_actionable(self):
        with self.assertRaises(catalog.CatalogError) as error:
            catalog.fetch_details(self.cli,{},'98:error')
        self.assertIn('登录',str(error.exception))
        with self.assertRaises(catalog.CatalogError) as error:
            catalog.fetch_details(self.cli,{},'99:timeout',timeout=.2)
        self.assertIn('超时',str(error.exception))

    def test_only_known_https_cover_hosts_are_accepted(self):
        good='https://s3proxy-alp2-covers.cdn-zlib.sk/covers/books/test.jpg'
        self.assertEqual(catalog.safe_cover(good),good)
        for url in ['http://s3proxy-alp2-covers.cdn-zlib.sk/x','https://127.0.0.1/x','https://cdn-zlib.sk.evil.invalid/x','https://user:secret@cdn-zlib.sk/x','javascript:alert(1)']:
            self.assertEqual(catalog.safe_cover(url),'')

    def test_source_link_uses_configured_book_origin(self):
        self.assertEqual(catalog.safe_source('https://evil.invalid/book/42/abc','https://z-lib.gd'),'https://z-lib.gd/book/42/abc')
        self.assertEqual(catalog.safe_source('https://evil.invalid/account','https://z-lib.gd'),'')
