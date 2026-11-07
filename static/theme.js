/* Apply the last choice before styles paint; a blocked storage area is harmless. */
(() => {
  const root = document.documentElement;
  function apply(theme) {
    root.dataset.theme = theme;
    root.classList.toggle('dark', theme === 'dark');
    document.querySelector('meta[name="color-scheme"]')?.setAttribute('content', theme);
    const button = document.getElementById('theme-toggle');
    if (button) {
      const label = theme === 'dark' ? '切换到浅色模式' : '切换到深色模式';
      button.setAttribute('aria-label', label); button.title = label;
      button.setAttribute('aria-pressed', String(theme === 'dark'));
    }
  }
  let theme = 'light';
  try { if (localStorage.getItem('shiye-theme') === 'dark') theme = 'dark'; } catch {}
  apply(theme);
  document.addEventListener('DOMContentLoaded', () => {
    apply(root.dataset.theme);
    document.getElementById('theme-toggle')?.addEventListener('click', () => {
      const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
      apply(next);
      try { localStorage.setItem('shiye-theme', next); } catch {}
    });
  });
})();
