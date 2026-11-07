"""QQ-inspired native login card; credentials never pass through the web server."""
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from urllib.parse import urlsplit

from login_bridge import LoginError, login, validate_credentials

BASE = Path(__file__).resolve().parent
BLUE = '#1499f7'
INK = '#283649'
MUTED = '#96a2b2'


class LoginWindow:
    def __init__(self, root, cli, domain):
        self.root, self.cli, self.domain = root, cli, domain
        self.events = queue.Queue()
        self.cancelled = threading.Event()
        self.worker = None
        self.busy = False
        self.email = tk.StringVar()
        self.password = tk.StringVar()
        self.revealed = False
        root.title('Pagelet · 账号登录')
        root.configure(bg='white')
        root.resizable(False, False)
        width, height = 420, 540
        x = (root.winfo_screenwidth() - width) // 2
        y = max(20, (root.winfo_screenheight() - height) // 2 - 30)
        root.geometry(f'{width}x{height}+{x}+{y}')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<Return>', lambda event: self.submit())
        root.bind('<Escape>', lambda event: self.close())

        header = tk.Canvas(root, width=width, height=205, bd=0, highlightthickness=0, bg='white')
        header.pack(fill='x')
        for row in range(150):
            ratio = row / 149
            first, last = (31, 150, 250), (71, 190, 249)
            color = '#%02x%02x%02x' % tuple(round(a+(b-a)*ratio) for a, b in zip(first, last))
            header.create_line(0, row, width, row, fill=color)
        header.create_oval(-70, -110, 150, 110, outline='#65b9fc', width=1)
        header.create_oval(300, 65, 520, 285, outline='#7bd1fd', width=1)
        header.create_text(210, 57, text='你好，欢迎回来', fill='white', font=('Microsoft YaHei UI', 19, 'bold'))
        header.create_text(210, 91, text='登录你的 Z-Library 账号', fill='#e2f5ff', font=('Microsoft YaHei UI', 10))
        header.create_oval(164, 113, 256, 205, fill='white', outline='white')
        header.create_oval(170, 119, 250, 199, fill='#eff8ff', outline='#e1f2ff')
        header.create_polygon(188, 143, 207, 146, 210, 150, 213, 146, 232, 143, 232, 174, 213, 177, 210, 181, 207, 177, 188, 174, fill='#d4ebfd', outline=BLUE, width=2)
        header.create_line(210, 150, 210, 177, fill=BLUE, width=2)
        for offset in (0, 7):
            header.create_line(193, 153+offset, 203, 155+offset, fill='#79b9e9', width=2)
            header.create_line(217, 155+offset, 227, 153+offset, fill='#79b9e9', width=2)

        body = tk.Frame(root, bg='white', padx=38)
        body.pack(fill='both', expand=True)
        tk.Label(body, text='账号邮箱', anchor='w', bg='white', fg='#738197', font=('Microsoft YaHei UI', 10)).pack(fill='x', pady=(8, 7))
        self.email_entry = self.field(body, self.email, '@')
        tk.Label(body, text='密码', anchor='w', bg='white', fg='#738197', font=('Microsoft YaHei UI', 10)).pack(fill='x', pady=(18, 7))
        self.password_entry = self.field(body, self.password, '•', secret=True)
        self.message = tk.Label(body, text='', anchor='w', justify='left', wraplength=342,
                                bg='white', fg='#db6d65', font=('Microsoft YaHei UI', 9))
        self.message.pack(fill='x', pady=(10, 6))
        self.login_button = tk.Button(body, text='登  录', command=self.submit, bg=BLUE, fg='white',
                                      activebackground='#0789e7', activeforeground='white', bd=0,
                                      relief='flat', cursor='hand2', font=('Microsoft YaHei UI', 12),
                                      pady=10, disabledforeground='#d7edff', takefocus=True)
        self.login_button.pack(fill='x', pady=(1, 10))
        tk.Label(body, text='仅保存登录状态，不保存密码', bg='white', fg=MUTED,
                 font=('Microsoft YaHei UI', 9)).pack()
        tk.Label(body, text=f'当前连接：{urlsplit(domain).hostname or domain}', bg='white', fg='#b0b8c5',
                 font=('Microsoft YaHei UI', 8)).pack(pady=(12, 0))
        root.after(120, self.email_entry.focus_set)
        root.after_idle(self.fit_height)
        root.after(100, self.poll)

    def fit_height(self):
        self.root.update_idletasks()
        height = max(540, self.root.winfo_reqheight() + 12)
        height = min(height, self.root.winfo_screenheight() - 100)
        self.root.geometry(f'420x{height}')

    def field(self, parent, variable, icon, secret=False):
        border = tk.Frame(parent, bg='#e2e8ef', padx=1, pady=1)
        border.pack(fill='x')
        inside = tk.Frame(border, bg='#fafbfd', padx=11, pady=10)
        inside.pack(fill='both', expand=True)
        tk.Label(inside, text=icon, bg='#fafbfd', fg='#a3b0c0', width=2, font=('Segoe UI', 13)).pack(side='left', padx=(0, 6))
        entry = tk.Entry(inside, textvariable=variable, show='●' if secret else '', relief='flat', bd=0,
                         bg='#fafbfd', fg=INK, insertbackground=BLUE, selectbackground='#d9edff',
                         font=('Microsoft YaHei UI', 11), width=22)
        entry.pack(side='left', fill='x', expand=True)
        if secret:
            self.reveal_button = tk.Button(inside, text='显示', command=self.toggle_password, bd=0,
                                           bg='#fafbfd', activebackground='#fafbfd', fg='#8e9eb2',
                                           cursor='hand2', font=('Microsoft YaHei UI', 9), padx=2)
            self.reveal_button.pack(side='right')
        entry.bind('<FocusIn>', lambda event: border.configure(bg='#80c7fa'))
        entry.bind('<FocusOut>', lambda event: border.configure(bg='#e2e8ef'))
        return entry

    def toggle_password(self):
        if self.busy:
            return
        self.revealed = not self.revealed
        self.password_entry.configure(show='' if self.revealed else '●')
        self.reveal_button.configure(text='隐藏' if self.revealed else '显示')

    def submit(self):
        if self.busy:
            return
        email, password = self.email.get().strip(), self.password.get()
        try:
            validate_credentials(email, password)
        except LoginError as error:
            self.message.configure(text=str(error), fg='#db6d65')
            self.root.after_idle(self.fit_height)
            (self.email_entry if not email or '@' not in email else self.password_entry).focus_set()
            return
        self.busy = True
        self.cancelled.clear()
        self.email_entry.configure(state='disabled')
        self.password_entry.configure(state='disabled')
        self.reveal_button.configure(state='disabled')
        self.login_button.configure(text='正在登录…', state='disabled')
        self.message.configure(text='正在连接书库，请稍候…', fg='#7d94ab')
        self.root.after_idle(self.fit_height)
        self.password.set('')
        self.password_entry.configure(show='●')
        self.revealed = False
        self.reveal_button.configure(text='显示')
        self.worker = threading.Thread(target=self.authenticate, args=(email, password), daemon=True)
        self.worker.start()

    def authenticate(self, email, password):
        try:
            login([self.cli], self.domain, email, password, self.cancelled)
            self.events.put(('success', '登录成功，正在返回书库…'))
        except LoginError as error:
            self.events.put(('error', str(error)))
        except Exception:
            self.events.put(('error', '登录组件出现异常，请关闭窗口后重试。'))
        finally:
            password = ''

    def poll(self):
        try:
            kind, message = self.events.get_nowait()
            if kind == 'success':
                self.message.configure(text=message, fg='#34a779')
                self.login_button.configure(text='登录成功')
                self.root.after(1000, self.root.destroy)
                return
            self.busy = False
            self.message.configure(text=message, fg='#db6d65')
            self.root.after_idle(self.fit_height)
            self.email_entry.configure(state='normal')
            self.password_entry.configure(state='normal')
            self.reveal_button.configure(state='normal')
            self.login_button.configure(text='登  录', state='normal')
            self.password_entry.focus_set()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def close(self):
        self.cancelled.set()
        self.password.set('')
        if self.worker and self.worker.is_alive():
            self.root.withdraw()
            self.root.after(50, self.wait_closed)
        else:
            self.root.destroy()

    def wait_closed(self):
        if self.worker and self.worker.is_alive():
            self.root.after(50, self.wait_closed)
        else:
            self.root.destroy()


def main():
    if len(sys.argv) != 3:
        return 2
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Shiye.BookLogin')
    root = tk.Tk()
    LoginWindow(root, sys.argv[1], sys.argv[2])
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
