/* Heatmapify docs page: highlight the section you're reading in the table of contents. */
// highlight the section you're reading in the table of contents
(() => {
  const links = [...document.querySelectorAll("#toc a")];
  const map = new Map(links.map((a) => [a.getAttribute("href").slice(1), a]));
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) { links.forEach((a) => a.classList.remove("on")); const a = map.get(e.target.id); if (a) a.classList.add("on"); }
    });
  }, { rootMargin: "-30% 0px -60% 0px" });
  document.querySelectorAll(".doc-sec").forEach((s) => io.observe(s));
})();
