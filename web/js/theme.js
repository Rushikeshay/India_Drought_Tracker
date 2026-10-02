// Shared light/dark theme: applied in <head> before first paint so every page opens in
// the mode the viewer chose last (stored per browser; falls back to the OS setting).
(function () {
  const KEY = "theme";
  const get = () => { try { return localStorage.getItem(KEY); } catch (e) { return null; } };
  const set = (v) => { try { localStorage.setItem(KEY, v); } catch (e) { /* storage blocked */ } };
  const saved = get();
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;

  window.toggleTheme = function () {
    const cur = document.documentElement.dataset.theme ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    set(next);
  };
  document.addEventListener("DOMContentLoaded", () => {
    const b = document.getElementById("theme");
    if (b) b.addEventListener("click", window.toggleTheme);
  });
})();
