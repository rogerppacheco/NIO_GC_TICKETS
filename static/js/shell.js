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

  var groups = document.querySelectorAll("[data-acc]");
  groups.forEach(function (item) {
    item.addEventListener("toggle", function () {
      if (!item.open) return;
      groups.forEach(function (other) {
        if (other !== item) other.open = false;
      });
    });
  });

  var sideBtn = document.getElementById("sidebar-toggle");
  if (!sideBtn) return;
  var key = "nio-sidebar";
  var onFila = document.body.classList.contains("page-fila");
  var saved = null;
  try {
    saved = localStorage.getItem(key);
  } catch (e) {
    saved = null;
  }
  var open = saved === "1" || (saved !== "0" && !onFila);
  function apply(isOpen) {
    document.body.classList.add("sidebar-ready");
    document.body.classList.toggle("sidebar-collapsed", !isOpen);
    sideBtn.setAttribute("aria-expanded", isOpen ? "true" : "false");
    sideBtn.textContent = isOpen ? "Ocultar menu" : "Menu";
  }
  apply(open);
  sideBtn.addEventListener("click", function () {
    var next = document.body.classList.contains("sidebar-collapsed");
    apply(next);
    try {
      localStorage.setItem(key, next ? "1" : "0");
    } catch (e) {
      /* ignore */
    }
  });
})();
