(function () {
  "use strict";

  var toggle = document.getElementById("nav-toggle");
  var nav = document.getElementById("site-nav");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = document.body.classList.toggle("nav-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    nav.addEventListener("click", function (ev) {
      if (ev.target.closest("a")) {
        document.body.classList.remove("nav-open");
        toggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  var gestaoBtn = document.getElementById("gestao-toggle");
  var gestaoBar = document.getElementById("gestao-bar");
  if (!gestaoBtn || !gestaoBar) return;

  var key = "nio-gestao-nav";
  var onFila = document.body.classList.contains("page-fila");
  var saved = null;
  try {
    saved = localStorage.getItem(key);
  } catch (e) {
    saved = null;
  }
  var open = saved === "1" || (saved !== "0" && !onFila);
  function apply(isOpen) {
    gestaoBar.classList.add("ready");
    gestaoBar.classList.toggle("is-collapsed", !isOpen);
    gestaoBtn.setAttribute("aria-expanded", isOpen ? "true" : "false");
    gestaoBtn.textContent = isOpen ? "Ocultar gestão" : "Gestão";
  }
  apply(open);
  gestaoBtn.addEventListener("click", function () {
    var next = gestaoBar.classList.contains("is-collapsed");
    apply(next);
    try {
      localStorage.setItem(key, next ? "1" : "0");
    } catch (e) {
      /* ignore */
    }
  });
})();
