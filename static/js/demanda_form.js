(function () {
  function initDemandaForm(form) {
    if (!form || form.dataset.demandaBound) return;
    form.dataset.demandaBound = "1";

    const schemaEl = document.getElementById("demanda-schema");
    if (!schemaEl) return;
    let schema = {};
    try {
      schema = JSON.parse(schemaEl.textContent);
    } catch (e) {
      return;
    }

    const tipoSelect = form.querySelector('[name="tipo"]');
    const hint = form.querySelector("[data-tipo-hint]");
    const rows = Array.from(form.querySelectorAll("[data-field]"));

    function apply() {
      const tipo = tipoSelect ? tipoSelect.value : "";
      const cfg = schema[tipo];
      const allowed = new Set(cfg ? cfg.campos : []);
      const required = new Set(cfg ? cfg.obrigatorios : []);
      const labels = (cfg && cfg.labels) || {};

      if (hint) {
        hint.textContent = cfg
          ? cfg.titulo
          : "Selecione o tipo da demanda para ver só os campos necessários.";
      }

      rows.forEach(function (row) {
        const name = row.getAttribute("data-field");
        if (name === "tipo" || name === "parceiro") {
          row.hidden = false;
          return;
        }
        const show = !!tipo && allowed.has(name);
        row.hidden = !show;
        const label = row.querySelector("label");
        if (label && show) {
          if (!label.getAttribute("data-base-label")) {
            label.setAttribute("data-base-label", label.textContent.replace(/\s*\*$/, "").trim());
          }
          const base = labels[name] || label.getAttribute("data-base-label");
          label.textContent = required.has(name) ? base + " *" : base;
        }
      });
    }

    if (tipoSelect) {
      tipoSelect.addEventListener("change", apply);
    }
    apply();
  }

  function boot() {
    document.querySelectorAll("form[data-demanda-form]").forEach(initDemandaForm);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
