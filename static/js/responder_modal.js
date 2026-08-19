(function () {
  const root = function () {
    return document.getElementById("modal-root");
  };

  function csrfToken() {
    const el = document.querySelector("[name=csrfmiddlewaretoken]");
    if (el && el.value) return el.value;
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function formatElapsed(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    if (h > 0) return h + ":" + pad(m) + ":" + pad(s);
    return pad(m) + ":" + pad(s);
  }

  let timerId = null;

  function stopTimer() {
    if (timerId) {
      clearInterval(timerId);
      timerId = null;
    }
  }

  function startTimer(overlay) {
    stopTimer();
    if (!overlay) return;
    const el = overlay.querySelector("[data-timer-tratamento]");
    if (!el) return;
    if (overlay.getAttribute("data-tempo-ok") === "1") return;
    const iso = overlay.getAttribute("data-iniciado");
    const started = iso ? Date.parse(iso) : Date.now();
    if (Number.isNaN(started)) return;
    const tick = function () {
      el.textContent = formatElapsed(Date.now() - started);
    };
    tick();
    timerId = setInterval(tick, 1000);
  }

  function closeModal() {
    stopTimer();
    const box = root();
    if (box) box.innerHTML = "";
    document.body.classList.remove("modal-open");
  }

  function activateTab(overlay, tabId) {
    overlay.querySelectorAll(".tab").forEach(function (btn) {
      const on = btn.getAttribute("data-tab") === tabId;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
    overlay.querySelectorAll(".tab-panel").forEach(function (panel) {
      panel.classList.toggle("is-active", panel.getAttribute("data-panel") === tabId);
    });
  }

  function firstErrorTab(overlay) {
    const marked = overlay.querySelector(".tab.has-error");
    if (marked) {
      activateTab(overlay, marked.getAttribute("data-tab"));
      return;
    }
    const err = overlay.querySelector(".tab-panel .help[style*='danger'], .tab-panel .errorlist");
    if (!err) return;
    const panel = err.closest(".tab-panel");
    if (panel) activateTab(overlay, panel.getAttribute("data-panel"));
  }

  function bindModal(overlay) {
    if (!overlay) return;
    document.body.classList.add("modal-open");
    startTimer(overlay);
    firstErrorTab(overlay);
    overlay.addEventListener("click", function (ev) {
      if (ev.target === overlay) closeModal();
    });
  }

  async function abrirResponder(protocolo, nextUrl) {
    const box = root();
    if (!box) return;
    const fd = new FormData();
    fd.append("csrfmiddlewaretoken", csrfToken());
    fd.append("action", "abrir");
    if (nextUrl) fd.append("next", nextUrl);
    try {
      const res = await fetch("/tickets/" + encodeURIComponent(protocolo) + "/responder/", {
        method: "POST",
        body: fd,
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const html = await res.text();
      box.innerHTML = html;
      bindModal(box.querySelector("#modal-responder"));
    } catch (e) {
      window.location.href = "/tickets/" + encodeURIComponent(protocolo) + "/?responder=1";
    }
  }

  document.addEventListener("click", function (ev) {
    const abrir = ev.target.closest("[data-abrir-resposta]");
    if (abrir) {
      ev.preventDefault();
      abrirResponder(
        abrir.getAttribute("data-abrir-resposta"),
        abrir.getAttribute("data-next") || ""
      );
      return;
    }
    if (ev.target.closest("[data-fechar-modal]")) {
      ev.preventDefault();
      closeModal();
    }
    const tab = ev.target.closest(".tab[data-tab]");
    if (tab) {
      ev.preventDefault();
      const overlay = tab.closest("#modal-responder");
      if (overlay) activateTab(overlay, tab.getAttribute("data-tab"));
    }
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") closeModal();
  });

  function showModalNotice(overlay, text, ok) {
    if (!overlay) return;
    let box = overlay.querySelector("[data-modal-notice]");
    if (!box) {
      box = document.createElement("div");
      box.setAttribute("data-modal-notice", "1");
      const tabs = overlay.querySelector(".tabs");
      if (tabs && tabs.parentNode) {
        tabs.parentNode.insertBefore(box, tabs.nextSibling);
      } else {
        const modal = overlay.querySelector(".modal-responder") || overlay;
        modal.insertBefore(box, modal.firstChild);
      }
    }
    box.className = ok ? "modal-ok" : "modal-erro";
    box.setAttribute("role", "alert");
    box.textContent = text;
  }

  document.addEventListener("submit", async function (ev) {
    const form = ev.target.closest("#form-responder");
    if (!form) return;
    ev.preventDefault();
    const overlay = form.closest("#modal-responder");
    const btn = form.querySelector('button[type="submit"]');
    const label = btn ? btn.textContent : "";
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Salvando…";
    }
    showModalNotice(overlay, "Salvando resposta…", true);
    try {
      const res = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest", "Accept": "application/json" },
      });
      const ct = res.headers.get("content-type") || "";
      if (ct.indexOf("application/json") !== -1) {
        const data = await res.json();
        if (data.ok && data.redirect) {
          showModalNotice(overlay, data.message || "Resposta salva. Atualizando…", true);
          window.location.href = data.redirect;
          return;
        }
        showModalNotice(overlay, data.error || "Não foi possível salvar.", false);
        return;
      }
      const html = await res.text();
      const box = root();
      if (box) {
        box.innerHTML = html;
        bindModal(box.querySelector("#modal-responder"));
      }
    } catch (e) {
      showModalNotice(overlay, "Falha de rede ao salvar. Tente de novo.", false);
    } finally {
      if (btn && document.body.contains(btn)) {
        btn.disabled = false;
        btn.textContent = label || "Salvar resposta";
      }
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    const existing = document.querySelector("#modal-root #modal-responder");
    if (existing) bindModal(existing);
  });
})();
