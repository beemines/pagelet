"""Visual QA instance, with no service requests or saved credentials."""
import ctypes
from pathlib import Path
import sys
import tkinter as tk
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from login_gui import LoginWindow

ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Shiye.BookLogin.Preview')
root=tk.Tk()
window=LoginWindow(root, 'not-used-in-preview.exe', 'https://example.com')
root.title('Pagelet · 登录预览')
root.mainloop()
