(function () {
  "use strict";

  var root = document.getElementById("rota-app");
  if (!root) return;

  var urls = {
    hoje: root.dataset.hojeUrl,
    ufs: root.dataset.ufsUrl,
    cidades: root.dataset.cidadesUrl,
    bairros: root.dataset.bairrosUrl,
    dfv: root.dataset.dfvUrl,
    validar: root.dataset.validarUrl,
    checkin: root.dataset.checkinUrl,
  };

  var el = {
    skeleton: document.getElementById("rota-skeleton"),
    form: document.getElementById("rota-form"),
    blocoSemana: document.getElementById("bloco-semana"),
    blocoLocal: document.getElementById("bloco-local"),
    metaHint: document.getElementById("meta-semana-hint"),
    alertaSemana: document.getElementById("alerta-semana"),
    uf: document.getElementById("rota_uf"),
    cidade: document.getElementById("rota_cidade"),
    bairro: document.getElementById("rota_bairro"),
    bairrosList: document.getElementById("rota_bairros_list"),
    bairroFonte: document.getElementById("bairro-fonte"),
    qtd: document.getElementById("qtd_vendedores"),
    vendas: document.getElementById("vendas_planejadas_semana"),
    formError: document.getElementById("rota-form-error"),
    statusSalvo: document.getElementById("rota-status-salvo"),
    btnSalvar: document.getElementById("btn-salvar-rota"),
    spinSalvar: document.getElementById("spin-salvar"),
    spinUf: document.getElementById("spin-uf"),
    spinCidade: document.getElementById("spin-cidade"),
    spinBairro: document.getElementById("spin-bairro"),
    dfvEmpty: document.getElementById("dfv-empty"),
    dfvLoading: document.getElementById("dfv-loading"),
    dfvErro: document.getElementById("dfv-erro"),
    dfvConteudo: document.getElementById("dfv-conteudo"),
    dfvLocal: document.getElementById("dfv-local-label"),
    kpiHp: document.getElementById("kpi-hp-livre"),
    kpiHps: document.getElementById("kpi-hps"),
    kpiPct: document.getElementById("kpi-pct-hc"),
    kpiViaveis: document.getElementById("kpi-viaveis"),
    dfvFaixa: document.getElementById("dfv-faixa"),
    dfvClass: document.getElementById("dfv-class"),
    dfvCdos: document.getElementById("dfv-cdos"),
    dfvAlertas: document.getElementById("dfv-alertas"),
    dfvMeta: document.getElementById("dfv-meta-info"),
  };

  var state = {
    ehSegunda: false,
    metaSemana: null,
    dfvResumo: null,
    bairroTimer: null,
    bairroReq: 0,
    cidadeReq: 0,
    bairrosListReq: 0,
  };

  function csrfToken() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function show(node, on) {
    if (!node) return;
    if (on) node.removeAttribute("hidden");
    else node.setAttribute("hidden", "");
  }

  function setSpinner(node, on) {
    show(node, !!on);
  }

  function clearAllSpinners() {
    setSpinner(el.spinUf, false);
    setSpinner(el.spinCidade, false);
    setSpinner(el.spinBairro, false);
    setSpinner(el.spinSalvar, false);
    show(el.dfvLoading, false);
  }

  function fmtNum(n) {
    if (n === null || n === undefined || n === "") return "—";
    return Number(n).toLocaleString("pt-BR");
  }

  async function api(url, options) {
    var opts = options || {};
    var headers = Object.assign({ Accept: "application/json" }, opts.headers || {});
    if (opts.method && opts.method !== "GET") {
      headers["Content-Type"] = "application/json";
      headers["X-CSRFToken"] = csrfToken();
    }
    var res = await fetch(url, {
      method: opts.method || "GET",
      headers: headers,
      body: opts.body,
      credentials: "same-origin",
    });
    var data = null;
    try {
      data = await res.json();
    } catch (e) {
      data = { ok: false, error: { message: "Resposta inválida do servidor." } };
    }
    return { res: res, data: data };
  }

  function tipoRota() {
    var checked = el.form.querySelector('input[name="tipo_rota"]:checked');
    return checked ? checked.value : "PRESENCIAL";
  }

  function syncTipo() {
    var presencial = tipoRota() === "PRESENCIAL";
    show(el.blocoLocal, presencial);
    if (!presencial) {
      resetDfv();
    }
  }

  function fillSelect(select, items, valueKey, labelKey, selected) {
    select.innerHTML = "";
    var opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = "Selecione";
    select.appendChild(opt0);
    var seen = {};
    (items || []).forEach(function (item) {
      var value = String(item[valueKey] || "").trim();
      if (!value) return;
      var key = value.toUpperCase();
      if (seen[key]) return;
      seen[key] = true;
      var opt = document.createElement("option");
      opt.value = value;
      opt.textContent = item[labelKey] || value;
      if (selected && String(selected).trim().toUpperCase() === key) {
        opt.selected = true;
      }
      select.appendChild(opt);
    });
  }

  function resetBairroField(message) {
    el.bairro.value = "";
    el.bairrosList.innerHTML = "";
    el.bairro.disabled = true;
    el.bairro.placeholder = "Selecione a cidade";
    el.bairroFonte.textContent = message || "";
    resetDfv();
  }

  function resetDfv() {
    state.dfvResumo = null;
    state.bairroReq += 1;
    show(el.dfvEmpty, true);
    show(el.dfvLoading, false);
    show(el.dfvErro, false);
    show(el.dfvConteudo, false);
    el.dfvLocal.textContent = "Selecione o bairro";
  }

  function renderDfv(resumo) {
    state.dfvResumo = resumo;
    var ind = resumo.indicadores || {};
    var cred = resumo.credito || {};
    var perfil = resumo.perfil || {};
    var local = resumo.local || {};
    el.dfvLocal.textContent =
      (local.bairro || "—") + " · " + (local.cidade || "") + "/" + (local.uf || "");
    el.kpiHp.textContent = fmtNum(ind.hp_livre);
    el.kpiHps.textContent = fmtNum(ind.hps);
    el.kpiPct.textContent =
      ind.pct_hc === null || ind.pct_hc === undefined ? "—" : fmtNum(ind.pct_hc) + "%";
    el.kpiViaveis.textContent =
      fmtNum(ind.fachadas_viaveis) + " / " + fmtNum(ind.fachadas_total);
    el.dfvFaixa.textContent = cred.faixa_predominante || "—";
    el.dfvClass.textContent = perfil.classificacao_predominante || "—";
    el.dfvCdos.textContent = fmtNum(perfil.cdos_distintos);

    el.dfvAlertas.innerHTML = "";
    (resumo.alertas || []).forEach(function (a) {
      var li = document.createElement("li");
      li.className = "rota-alerta-item " + (a.severidade || "info");
      li.innerHTML =
        "<strong>" +
        (a.titulo || a.codigo) +
        "</strong><span>" +
        (a.detalhe || "") +
        "</span>";
      el.dfvAlertas.appendChild(li);
    });

    var meta = resumo.meta || {};
    el.dfvMeta.textContent = meta.incompleto
      ? "Resumo parcial (volume alto no bairro)."
      : "Fonte: " + (meta.fonte || "DFV");

    show(el.dfvEmpty, false);
    show(el.dfvLoading, false);
    show(el.dfvErro, false);
    show(el.dfvConteudo, true);
  }

  async function loadUfs(selectedUf) {
    setSpinner(el.spinUf, true);
    try {
      var out = await api(urls.ufs);
      if (!out.data.ok) return;
      fillSelect(el.uf, out.data.data.items, "uf", "uf", selectedUf);
    } finally {
      setSpinner(el.spinUf, false);
    }
  }

  async function loadCidades(uf, selectedCidade) {
    var reqId = ++state.cidadeReq;
    el.cidade.disabled = !uf;
    resetBairroField(uf ? "Selecione a cidade para carregar os bairros." : "");
    if (!uf) {
      fillSelect(el.cidade, [], "cidade", "cidade");
      return;
    }
    setSpinner(el.spinCidade, true);
    try {
      var out = await api(urls.cidades + "?uf=" + encodeURIComponent(uf));
      if (reqId !== state.cidadeReq) return;
      if (!out.data.ok) return;
      fillSelect(el.cidade, out.data.data.items, "cidade", "cidade", selectedCidade);
      el.cidade.disabled = false;
    } finally {
      if (reqId === state.cidadeReq) setSpinner(el.spinCidade, false);
    }
  }

  /** Só chama após seleção de cidade (não no carregamento inicial de UF). */
  async function loadBairros(uf, cidade, preserveBairro) {
    var reqId = ++state.bairrosListReq;
    var keep = (preserveBairro || "").trim();
    el.bairrosList.innerHTML = "";
    el.bairroFonte.textContent = "";
    if (!(uf && cidade)) {
      resetBairroField();
      return;
    }
    el.bairro.disabled = false;
    el.bairro.placeholder = "Carregando bairros…";
    if (!keep) el.bairro.value = "";
    setSpinner(el.spinBairro, true);
    try {
      var out = await api(
        urls.bairros +
          "?uf=" +
          encodeURIComponent(uf) +
          "&cidade=" +
          encodeURIComponent(cidade)
      );
      if (reqId !== state.bairrosListReq) return;
      if (!out.data.ok) {
        el.bairro.placeholder = "Digite o bairro";
        el.bairroFonte.textContent =
          "Não foi possível listar bairros; digite manualmente.";
        if (keep) el.bairro.value = keep;
        return;
      }
      var items = out.data.data.items || [];
      var seen = {};
      items.forEach(function (item) {
        var nome = String(item.bairro || "").trim();
        if (!nome) return;
        var key = nome.toUpperCase();
        if (seen[key]) return;
        seen[key] = true;
        var opt = document.createElement("option");
        opt.value = nome;
        el.bairrosList.appendChild(opt);
      });
      el.bairro.placeholder = "Selecione ou digite o bairro";
      if (keep) el.bairro.value = keep;
      var fonte = out.data.data.fonte || "";
      el.bairroFonte.textContent = items.length
        ? items.length + " bairros carregados após a cidade (" + fonte + ")"
        : "Nenhum bairro na lista — digite manualmente (" + fonte + ")";
    } finally {
      if (reqId === state.bairrosListReq) setSpinner(el.spinBairro, false);
    }
  }

  async function loadDfv(uf, cidade, bairro) {
    if (!(uf && cidade && bairro) || tipoRota() !== "PRESENCIAL") {
      resetDfv();
      return;
    }
    var reqId = ++state.bairroReq;
    show(el.dfvEmpty, false);
    show(el.dfvConteudo, false);
    show(el.dfvErro, false);
    show(el.dfvLoading, true);
    el.dfvLocal.textContent = bairro + " · " + cidade + "/" + uf;

    try {
      var out = await api(
        urls.dfv +
          "?uf=" +
          encodeURIComponent(uf) +
          "&cidade=" +
          encodeURIComponent(cidade) +
          "&bairro=" +
          encodeURIComponent(bairro)
      );
      if (reqId !== state.bairroReq) return;
      if (!out.data.ok) {
        show(el.dfvErro, true);
        el.dfvErro.textContent =
          (out.data.error && out.data.error.message) || "Falha ao consultar DFV.";
        return;
      }
      renderDfv(out.data.data);
    } catch (e) {
      if (reqId !== state.bairroReq) return;
      show(el.dfvErro, true);
      el.dfvErro.textContent = "Falha de rede ao consultar DFV.";
    } finally {
      if (reqId === state.bairroReq) show(el.dfvLoading, false);
    }
  }

  function scheduleDfv() {
    clearTimeout(state.bairroTimer);
    var bairro = (el.bairro.value || "").trim();
    if (!bairro) {
      resetDfv();
      return;
    }
    state.bairroTimer = setTimeout(function () {
      loadDfv(el.uf.value, el.cidade.value, bairro);
    }, 400);
  }

  async function validarSemana() {
    if (!state.ehSegunda) return;
    var raw = el.vendas.value;
    if (raw === "" || raw === null) {
      show(el.alertaSemana, false);
      return;
    }
    var out = await api(urls.validar, {
      method: "POST",
      body: JSON.stringify({ vendas_planejadas: Number(raw) }),
    });
    if (!out.data.ok) return;
    var d = out.data.data;
    el.alertaSemana.className = "rota-alerta " + (d.status_alerta || "ok");
    el.alertaSemana.textContent = d.mensagem || "";
    show(el.alertaSemana, true);
  }

  function applyCheckin(checkin) {
    if (!checkin) return;
    var radio = el.form.querySelector(
      'input[name="tipo_rota"][value="' + checkin.tipo_rota + '"]'
    );
    if (radio) radio.checked = true;
    el.qtd.value = checkin.qtd_vendedores;
    syncTipo();
    el.statusSalvo.textContent =
      "Check-in de hoje já registrado — você pode atualizar.";
    show(el.statusSalvo, true);
    el.btnSalvar.querySelector(".btn-label").textContent = "Atualizar rota";
  }

  async function init() {
    try {
      var out = await api(urls.hoje);
      show(el.skeleton, false);
      show(el.form, true);
      if (!out.data.ok) {
        show(el.formError, true);
        el.formError.textContent =
          (out.data.error && out.data.error.message) || "Falha ao carregar.";
        return;
      }
      var data = out.data.data;
      state.ehSegunda = !!data.eh_segunda;
      state.metaSemana = data.meta_semana || {};
      show(el.blocoSemana, state.ehSegunda);
      if (state.ehSegunda) {
        el.metaHint.textContent =
          "Meta semanal de referência: " +
          fmtNum(state.metaSemana.valor) +
          " (meta mensal VL " +
          fmtNum(state.metaSemana.meta_mensal_vl) +
          " ÷ 4).";
        if (data.planejamento_semana) {
          el.vendas.value = data.planejamento_semana.vendas_planejadas;
          el.alertaSemana.className =
            "rota-alerta " + (data.planejamento_semana.status_alerta || "ok");
          el.alertaSemana.textContent = data.planejamento_semana.mensagem || "";
          show(el.alertaSemana, true);
        }
      }

      var loc = (data.checkin && data.checkin.local) || data.defaults || {};
      var uf = loc.uf || "";
      var cidade = loc.cidade || "";
      var bairro = loc.bairro || "";

      await loadUfs(uf);
      if (uf) {
        await loadCidades(uf, cidade);
        // Bairros só depois da cidade definida (check-in ou default com cidade)
        if (cidade) {
          await loadBairros(uf, cidade, bairro);
          if (bairro && (!data.checkin || data.checkin.tipo_rota === "PRESENCIAL")) {
            scheduleDfv();
          }
        } else {
          resetBairroField("Selecione a cidade para carregar os bairros.");
        }
      }

      if (data.checkin) applyCheckin(data.checkin);
      syncTipo();
    } finally {
      clearAllSpinners();
    }
  }

  el.form.addEventListener("change", function (ev) {
    if (ev.target && ev.target.name === "tipo_rota") syncTipo();
  });

  el.uf.addEventListener("change", function () {
    // Trocar UF: limpa cidade/bairro; bairros só após nova cidade
    loadCidades(el.uf.value, "");
  });

  el.cidade.addEventListener("change", function () {
    var cidade = el.cidade.value;
    if (!cidade) {
      resetBairroField("Selecione a cidade para carregar os bairros.");
      return;
    }
    loadBairros(el.uf.value, cidade, "");
  });

  el.bairro.addEventListener("input", scheduleDfv);
  el.bairro.addEventListener("change", scheduleDfv);

  if (el.vendas) {
    el.vendas.addEventListener("change", validarSemana);
    el.vendas.addEventListener("blur", validarSemana);
  }

  el.form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    show(el.formError, false);
    setSpinner(el.spinSalvar, true);
    el.btnSalvar.disabled = true;

    var payload = {
      tipo_rota: tipoRota(),
      qtd_vendedores: Number(el.qtd.value),
      uf: el.uf.value || "",
      cidade: el.cidade.value || "",
      bairro: (el.bairro.value || "").trim(),
    };
    if (state.ehSegunda) {
      payload.vendas_planejadas_semana = Number(el.vendas.value);
    }

    try {
      var out = await api(urls.checkin, {
        method: "POST",
        body: JSON.stringify(payload),
      });

      if (!out.data.ok) {
        show(el.formError, true);
        var err = out.data.error || {};
        var fields = err.fields || {};
        var parts = Object.keys(fields).map(function (k) {
          return fields[k];
        });
        el.formError.textContent =
          parts.join(" ") || err.message || "Não foi possível salvar.";
        return;
      }

      applyCheckin(out.data.data);
      el.statusSalvo.textContent = "Rota salva com sucesso.";
      show(el.statusSalvo, true);
    } finally {
      setSpinner(el.spinSalvar, false);
      el.btnSalvar.disabled = false;
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
