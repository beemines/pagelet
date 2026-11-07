from pathlib import Path
import unittest

try:
    from app_paths import resolve_layout
except ImportError:
    resolve_layout=None


class PortablePathsTests(unittest.TestCase):
    def test_frozen_data_and_cli_stay_outside_internal_resources(self):
        self.assertIsNotNone(resolve_layout)
        app=Path('C:/Apps/Pagelet')
        result=resolve_layout(True,app/'Pagelet.exe',app/'_internal')
        self.assertEqual(result['data'],app/'data')
        self.assertEqual(result['downloads'],app/'Downloads')
        self.assertEqual(result['cli'],app/'bin/zlib.exe')
        self.assertEqual(result['resources'],app/'_internal')

    def test_source_mode_preserves_existing_folder_layout(self):
        self.assertIsNotNone(resolve_layout)
        root=Path('C:/Project/book-web')
        result=resolve_layout(False,Path('C:/Python/python.exe'),root)
        self.assertEqual(result['data'],root/'data')
        self.assertEqual(result['cli'],root.parent/'zlib-windows-v0.0.12/zlib.exe')
