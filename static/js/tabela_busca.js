(function () {
  function normalize(text) {
    return (text || "")
      .toString()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .trim();
  }

  function initTabelaBusca(root) {
    if (!root) return;
    const input = root.querySelector("[data-tabela-busca]");
    const rows = Array.from(document.querySelectorAll(root.getAttribute("data-rows") || "[data-busca]"));
    const countEl = root.querySelector("[data-busca-count]");
    const emptySel = root.getAttribute("data-empty");
    const emptyEl = emptySel ? document.querySelector(emptySel) : null;
    if (!input || !rows.length) return;

    rows.forEach(function (row, idx) {
      if (!row.getAttribute("data-id")) {
        row.setAttribute("data-id", "row-" + idx);
      }
    });
    const totalUniq = new Set(rows.map(function (row) { return row.getAttribute("data-id"); })).size;

    function apply() {
      const q = normalize(input.value);
      let visiveis = 0;
      const vistos = new Set();
      rows.forEach(function (row) {
        const hay = normalize(row.getAttribute("data-busca") || row.textContent);
        const show = !q || hay.indexOf(q) !== -1;
        row.hidden = !show;
        if (!show) return;
        const id = row.getAttribute("data-id");
        if (!vistos.has(id)) {
          vistos.add(id);
          visiveis += 1;
        }
      });
      if (countEl) {
        countEl.textContent = q
          ? visiveis + " de " + totalUniq
          : totalUniq + " registro" + (totalUniq === 1 ? "" : "s");
      }
      if (emptyEl) emptyEl.hidden = visiveis > 0;
    }

    input.addEventListener("input", apply);
    apply();
  }

  document.querySelectorAll("[data-busca-box]").forEach(initTabelaBusca);
})();
