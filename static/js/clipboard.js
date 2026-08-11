(function () {
  function fallbackCopy(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, ta.value.length);
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (e) {
      ok = false;
    }
    document.body.removeChild(ta);
    return ok;
  }

    window.copyText = function (text, btn) {
    const value = (text || "").toString();
    const done = function (ok) {
      if (!btn) return;
      if (btn.querySelector("svg")) {
        const prevTitle = btn.getAttribute("title") || "";
        btn.setAttribute("title", ok ? "Copiado!" : "Falhou — tente de novo");
        btn.classList.toggle("is-copied", !!ok);
        setTimeout(function () {
          btn.setAttribute("title", prevTitle || "Copiar máscara");
          btn.classList.remove("is-copied");
        }, 1800);
        return;
      }
      const prev = btn.getAttribute("data-label") || btn.textContent;
      if (!btn.getAttribute("data-label")) btn.setAttribute("data-label", prev);
      btn.textContent = ok ? "Copiado!" : "Falhou — selecione e Ctrl+C";
      btn.disabled = true;
      setTimeout(function () {
        btn.textContent = btn.getAttribute("data-label");
        btn.disabled = false;
      }, 1800);
    };

    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(value).then(
        function () { done(true); },
        function () { done(fallbackCopy(value)); }
      );
    } else {
      done(fallbackCopy(value));
    }
  };

  document.addEventListener("click", function (ev) {
    const btn = ev.target.closest("[data-copy-target], [data-copy-text]");
    if (!btn) return;
    ev.preventDefault();
    let text = btn.getAttribute("data-copy-text") || "";
    const targetId = btn.getAttribute("data-copy-target");
    if (targetId) {
      const el = document.getElementById(targetId);
      if (el) text = el.value != null ? el.value : el.textContent;
    }
    window.copyText(text, btn);
  });
})();
