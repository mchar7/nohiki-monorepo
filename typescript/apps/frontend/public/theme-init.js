(() => {
  const stored = localStorage.getItem('vite-ui-theme');
  const isDark =
    stored === 'dark' || (stored !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches);
  if (isDark) document.documentElement.classList.add('dark');
  const color = localStorage.getItem('nohiki-theme-color');
  // System preference resolves to the default emerald CSS, so only manual accents need a class.
  if (
    localStorage.getItem('nohiki-theme-system') !== 'true' &&
    color !== null &&
    /^[a-z]+(?:-[a-z]+)*$/u.test(color)
  ) {
    document.documentElement.classList.add(`theme-${color}`);
  }
})();
