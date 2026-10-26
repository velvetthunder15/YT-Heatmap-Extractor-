/* Theme: light or dark. Runs in <head> so the page never flashes the wrong theme. */
(() => {
  const KEY = "hmdash.theme";
  const root = document.documentElement;
  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch (_) { /* private mode */ }
  const prefers = () => (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  const apply = (t) => {
    root.dataset.theme = t;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = t === "light" ? "#f7f6f3" : "#08080c";
    document.dispatchEvent(new CustomEvent("themechange", { detail: t }));
  };
  apply(saved || prefers());
  matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => { if (!saved) apply(prefers()); });
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-theme-toggle]").forEach((b) => {
      const label = () => b.setAttribute("aria-label", root.dataset.theme === "light" ? "Switch to dark theme" : "Switch to light theme");
      label();
      b.addEventListener("click", () => {
        saved = root.dataset.theme === "light" ? "dark" : "light";
        try { localStorage.setItem(KEY, saved); } catch (_) { /* ignore */ }
        apply(saved); label(); b.title = b.getAttribute("aria-label");
      });
      b.title = b.getAttribute("aria-label");
    });
  });
})();
