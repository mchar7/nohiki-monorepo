(() => {
  const stored = localStorage.getItem('vite-ui-theme');
  const isDark =
    stored === 'dark' ||
    (stored !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches);
  if (isDark) document.documentElement.classList.add('dark');
})();
