from pathlib import Path
import sys
import tempfile
import time
import threading
import unittest

try:
    from download_progress import run_download
except ImportError:
    run_download = None


class DownloadProgressTests(unittest.TestCase):
    def test_cancel_stops_a_waiting_subprocess_promptly(self):
        from download_progress import DownloadCancelled
        cancelled=threading.Event()
        timer=threading.Timer(.15,cancelled.set);timer.start()
        self.addCleanup(timer.cancel)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tests') as folder:
            started=time.monotonic()
            with self.assertRaises(DownloadCancelled):
                run_download([sys.executable,str(Path(__file__).parent/'tests/fixture_cli.py')],
                    '45:hang',folder,{'PYTHONUTF8':'1'},lambda sample:None,timeout=5,cancelled=cancelled)
            self.assertLess(time.monotonic()-started,2)
    def test_reports_cli_progress_before_exit_and_keeps_result_json(self):
        self.assertIsNotNone(run_download)
        samples=[]
        cli=[sys.executable,str(Path(__file__).parent/'tests/fixture_cli.py')]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent/"tests") as folder:
            result=run_download(cli,'42:abc',folder,{'PYTHONUTF8':'1'},lambda sample:samples.append({**sample,'file_exists':Path(folder,'fixture.epub').exists()}),timeout=3)
            self.assertTrue(Path(result['path']).is_file())
        self.assertTrue(any(s.get('percent')==40 and not s['file_exists'] for s in samples))
        self.assertTrue(any(s.get('phase')=='transferring' for s in samples))
        self.assertTrue(any(s.get('percent')==100 and s.get('phase')=='finalizing' for s in samples))

    def test_unknown_size_does_not_invent_a_percentage(self):
        self.assertIsNotNone(run_download)
        samples=[]
        cli=[sys.executable,str(Path(__file__).parent/'tests/fixture_cli.py')]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent/"tests") as folder:
            run_download(cli,'44:unknown',folder,{'PYTHONUTF8':'1'},samples.append,timeout=3)
        sample=next(s for s in samples if s.get('transferred_bytes'))
        self.assertIsNone(sample.get('percent'))
        self.assertEqual(sample['transferred_bytes'],5*1024*1024)

    def test_timeout_and_errors_do_not_echo_signed_links(self):
        self.assertIsNotNone(run_download)
        cli=[sys.executable,str(Path(__file__).parent/'tests/fixture_cli.py')]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent/"tests") as folder:
            with self.assertRaises(Exception) as error:
                run_download(cli,'99:bad',folder,{'PYTHONUTF8':'1'},lambda sample:None,timeout=3)
            self.assertNotIn('signed-secret',str(error.exception))
            with self.assertRaises(Exception) as error:
                run_download(cli,'45:hang',folder,{'PYTHONUTF8':'1'},lambda sample:None,timeout=.2)
            self.assertIn('超时',str(error.exception))
