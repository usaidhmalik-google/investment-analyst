// Apply the persisted (or system) colour theme before first paint to avoid a
// flash. Kept as an external file so the CSP can use script-src 'self'.
(function () {
  try {
    var t = localStorage.getItem('ia-theme');
    var dark = t ? t === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (dark) document.documentElement.classList.add('dark');
  } catch (e) {
    document.documentElement.classList.add('dark');
  }
})();
