(function () {
  function onlyDigits(v) {
    return String(v || "").replace(/\D/g, "");
  }

  function formatCep(v) {
    const d = onlyDigits(v).slice(0, 8);
    if (d.length <= 5) return d;
    return d.slice(0, 5) + "-" + d.slice(5);
  }

  function setVal(form, name, value) {
    const el = form.querySelector('[name="' + name + '"]');
    if (el) el.value = value || "";
  }

  function getVal(form, name) {
    const el = form.querySelector('[name="' + name + '"]');
    return el ? el.value.trim() : "";
  }

  function composeEndereco(form) {
    const logradouro = getVal(form, "logradouro");
    const numero = getVal(form, "numero_fachada");
    const complemento = getVal(form, "complemento");
    const bairro = getVal(form, "bairro");
    const cidade = getVal(form, "cidade");
    const uf = getVal(form, "uf");
    const cep = getVal(form, "cep");
    const parts = [];
    if (logradouro) parts.push(logradouro);
    if (numero) parts.push(numero);
    if (complemento) parts.push(complemento);
    let loc = "";
    if (bairro) loc = bairro;
    if (cidade) loc = loc ? loc + ", " + cidade : cidade;
    if (uf) loc = loc ? loc + " - " + uf.toUpperCase() : uf.toUpperCase();
    if (loc) parts.push(loc);
    if (cep) parts.push(cep);
    setVal(form, "endereco_completo", parts.join(", "));
  }

  async function lookupCep(form, cepInput) {
    const cep = onlyDigits(cepInput.value);
    let status = form.querySelector(".cep-status");
    if (!status) {
      status = document.createElement("div");
      status.className = "cep-status";
      cepInput.parentNode.appendChild(status);
    }
    if (cep.length !== 8) {
      status.className = "cep-status err";
      status.textContent = "CEP deve ter 8 dígitos.";
      return;
    }
    status.className = "cep-status";
    status.textContent = "Consultando ViaCEP...";
    try {
      const res = await fetch("https://viacep.com.br/ws/" + cep + "/json/");
      const data = await res.json();
      if (data.erro) {
        status.className = "cep-status err";
        status.textContent = "CEP não encontrado.";
        return;
      }
      setVal(form, "logradouro", data.logradouro || "");
      setVal(form, "bairro", data.bairro || "");
      setVal(form, "cidade", data.localidade || "");
      setVal(form, "uf", (data.uf || "").toUpperCase());
      composeEndereco(form);
      status.className = "cep-status ok";
      status.textContent = "Endereço preenchido via ViaCEP.";
      const num = form.querySelector('[name="numero_fachada"]');
      if (num) num.focus();
    } catch (e) {
      status.className = "cep-status err";
      status.textContent = "Falha ao consultar ViaCEP.";
    }
  }

  function bindForm(form) {
    const cep = form.querySelector('[name="cep"]');
    if (!cep || cep.dataset.viacepBound) return;
    cep.dataset.viacepBound = "1";
    cep.addEventListener("input", function () {
      const pos = cep.selectionStart;
      const before = cep.value.length;
      cep.value = formatCep(cep.value);
      const after = cep.value.length;
      if (typeof pos === "number") {
        try {
          cep.setSelectionRange(pos + (after - before), pos + (after - before));
        } catch (e) {}
      }
    });
    cep.addEventListener("blur", function () {
      if (onlyDigits(cep.value).length === 8) lookupCep(form, cep);
    });
    ["logradouro", "numero_fachada", "complemento", "bairro", "cidade", "uf", "cep"].forEach(
      function (name) {
        const el = form.querySelector('[name="' + name + '"]');
        if (el) el.addEventListener("change", function () {
          composeEndereco(form);
        });
        if (el) el.addEventListener("blur", function () {
          composeEndereco(form);
        });
      }
    );
  }

  function init() {
    document.querySelectorAll("form").forEach(bindForm);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
