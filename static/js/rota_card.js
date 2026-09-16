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
    agendas: root.dataset.agendasUrl,
  };

  var visaoEquipe = root.dataset.visaoEquipe === "1";

  var el = {
    week: document.getElementById("rota-week"),
    skeleton: document.getElementById("rota-skeleton"),
    form: document.getElementById("rota-form"),
    title: document.getElementById("rota-checkin-title"),
    pdvHint: document.getElementById("rota-pdv-hint"),
    blocoSemana: document.getElementById("bloco-semana"),
    blocoLocal: document.getElementById("bloco-local"),
    metaHint: document.getElementById("meta-semana-hint"),
    alertaSemana: document.getElementById("alerta-semana"),
    alertaTitulo: document.getElementById("alerta-semana-titulo"),
    alertaMsg: document.getElementById("alerta-semana-msg"),
    fieldUf: document.getElementById("field-uf"),
    fieldCidade: document.getElementById("field-cidade"),
    fieldBairro: document.getElementById("field-bairro"),
    uf: document.getElementById("rota_uf"),
    cidade: document.getElementById("rota_cidade"),
    bairro: document.getElementById("rota_bairro"),
    bairroFonte: document.getElementById("bairro-fonte"),
    qtdEquipes: document.getElementById("qtd_equipes"),
    equipes: document.getElementById("rota-equipes"),
    vbDia: document.getElementById("planejamento_vb_dia"),
    vendas: document.getElementById("vendas_planejadas_semana"),
    blocoContratacao: document.getElementById("bloco-contratacao"),
    blocoDesligamento: document.getElementById("bloco-desligamento"),
    qtdContratacoes: document.getElementById("qtd_contratacoes"),
    qtdDesligamentos: document.getElementById("qtd_desligamentos"),
    resumo: document.getElementById("rota-resumo"),
    resumoEquipes: document.getElementById("rota-resumo-equipes"),
    resumoPessoas: document.getElementById("rota-resumo-pessoas"),
    resumoVb: document.getElementById("rota-resumo-vb"),
    resumoRh: document.getElementById("rota-resumo-rh"),
    formError: document.getElementById("rota-form-error"),
    statusSalvo: document.getElementById("rota-status-salvo"),
    btnSalvar: document.getElementById("btn-salvar-rota"),
    spinSalvar: document.getElementById("spin-salvar"),
    spinUf: document.getElementById("spin-uf"),
    spinCidade: document.getElementById("spin-cidade"),
    spinBairro: document.getElementById("spin-bairro"),
    agendasQ: document.getElementById("rota-agendas-q"),
    agendasBody: document.getElementById("rota-agendas-body"),
    resultadoDia: document.getElementById("rota-resultado-dia"),
    kpiVbDia: document.getElementById("kpi-vb-dia"),
    kpiVbSemana: document.getElementById("kpi-vb-semana"),
    kpiEqDia: document.getElementById("kpi-eq-dia"),
    kpiPeDia: document.getElementById("kpi-pe-dia"),
    kpiPdvDia: document.getElementById("kpi-pdv-dia"),
    especs: document.getElementById("rota-especs"),
    resultadoBody: document.getElementById("rota-resultado-body"),
    dfvEmpty: document.getElementById("dfv-empty"),
    dfvLoading: document.getElementById("dfv-loading"),
    dfvErro: document.getElementById("dfv-erro"),
    dfvErroMsg: document.getElementById("dfv-erro-msg"),
    dfvConteudo: document.getElementById("dfv-conteudo"),
    dfvLocal: document.getElementById("dfv-local-label"),
    kpiHp: document.getElementById("kpi-hp-livre"),
    kpiOcupacao: document.getElementById("kpi-ocupacao"),
    kpiHps: document.getElementById("kpi-hps"),
    kpiPct: document.getElementById("kpi-pct-hc"),
    kpiViaveis: document.getElementById("kpi-viaveis"),
    dfvFaixa: document.getElementById("dfv-faixa"),
    dfvClass: document.getElementById("dfv-class"),
    dfvClasseSocial: document.getElementById("dfv-classe-social"),
    dfvCdos: document.getElementById("dfv-cdos"),
    dfvAlertas: document.getElementById("dfv-alertas"),
    dfvMeta: document.getElementById("dfv-meta-info"),
  };

  var state = {
    pdvId: root.dataset.pdvId || "",
    dia: "",
    hoje: "",
    ehSegunda: false,
    semana: { dias: [] },
    metaSemana: null,
    dfvResumo: null,
    bairroTimer: null,
    bairroReq: 0,
    cidadeReq: 0,
    bairrosListReq: 0,
    agendasTimer: null,
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

  function setFieldBusy(field, on) {
    if (!field) return;
    field.classList.toggle("is-busy", !!on);
  }

  function fmtNum(n) {
    if (n === null || n === undefined || n === "") return "—";
    return Number(n).toLocaleString("pt-BR");
  }

  function withPdv(url, extra) {
    var parts = [];
    if (state.pdvId) parts.push("pdv=" + encodeURIComponent(state.pdvId));
    Object.keys(extra || {}).forEach(function (k) {
      if (extra[k] !== undefined && extra[k] !== "") {
        parts.push(encodeURIComponent(k) + "=" + encodeURIComponent(extra[k]));
      }
    });
    if (!parts.length) return url;
    return url + (url.indexOf("?") >= 0 ? "&" : "?") + parts.join("&");
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

  function radioVal(name, fallback) {
    var checked = el.form.querySelector('input[name="' + name + '"]:checked');
    return checked ? checked.value : fallback;
  }

  function setRadio(name, value) {
    var node = el.form.querySelector('input[name="' + name + '"][value="' + value + '"]');
    if (node) node.checked = true;
  }

  function precisaLocal() {
    return lerEquipes().some(function (eq) {
      return eq.atuacao !== "DIGITAL";
    });
  }

  function lerEquipes() {
    var rows = el.equipes.querySelectorAll(".rota-equipe");
    var saida = [];
    rows.forEach(function (row, idx) {
      var atuacao = row.querySelector('input[type="radio"]:checked');
      var pessoas = row.querySelector('input[name="pessoas_equipe"]');
      saida.push({
        ordem: idx + 1,
        atuacao: atuacao ? atuacao.value : "PAP",
        pessoas: Number(pessoas && pessoas.value) || 0,
      });
    });
    return saida;
  }

  function totalPessoas() {
    return lerEquipes().reduce(function (acc, eq) {
      return acc + (eq.pessoas > 0 ? eq.pessoas : 0);
    }, 0);
  }

  function qtdContratacoes() {
    return radioVal("houve_contratacao", "nao") === "sim"
      ? Number(el.qtdContratacoes.value) || 0
      : 0;
  }

  function qtdDesligamentos() {
    return radioVal("houve_desligamento", "nao") === "sim"
      ? Number(el.qtdDesligamentos.value) || 0
      : 0;
  }

  function syncResumo() {
    var n = Number(el.qtdEquipes.value) || 0;
    var pessoas = totalPessoas();
    el.resumoEquipes.textContent =
      n + (n === 1 ? " equipe em campo" : " equipes em campo");
    el.resumoPessoas.textContent =
      pessoas + (pessoas === 1 ? " pessoa" : " pessoas");
    if (el.resumoVb) {
      var vb = Number(el.vbDia && el.vbDia.value) || 0;
      el.resumoVb.textContent = vb + " VBs";
    }
    var rh = [];
    var c = qtdContratacoes();
    var d = qtdDesligamentos();
    if (c) rh.push("+" + c + " contratação" + (c === 1 ? "" : "ões"));
    if (d) rh.push(d + " desligamento" + (d === 1 ? "" : "s"));
    el.resumoRh.textContent = rh.join(" · ");
  }

  function syncLocal() {
    var precisa = precisaLocal();
    show(el.blocoLocal, precisa);
    if (!precisa) resetDfv();
  }

  function syncRh() {
    show(el.blocoContratacao, radioVal("houve_contratacao", "nao") === "sim");
    show(el.blocoDesligamento, radioVal("houve_desligamento", "nao") === "sim");
    syncResumo();
  }

  function renderEquipes(preset) {
    var n = Math.max(1, Math.min(12, Number(el.qtdEquipes.value) || 1));
    el.qtdEquipes.value = String(n);
    var atuais = preset && preset.length ? preset : lerEquipes();
    el.equipes.innerHTML = "";
    for (var i = 0; i < n; i++) {
      var base = atuais[i] || { atuacao: "PAP", pessoas: 1 };
      var wrap = document.createElement("div");
      wrap.className = "rota-equipe";
      wrap.innerHTML =
        "<p class=\"rota-equipe-n\">Equipe " +
        (i + 1) +
        "</p>" +
        "<div class=\"rota-segment\" role=\"group\" aria-label=\"Atuação da equipe " +
        (i + 1) +
        "\">" +
        ["PAP", "DIGITAL", "MISTO"]
          .map(function (modo) {
            var checked = (base.atuacao || "PAP") === modo ? " checked" : "";
            var label = modo === "MISTO" ? "Misto" : modo === "DIGITAL" ? "Digital" : "PAP";
            return (
              "<label class=\"rota-seg\"><input type=\"radio\" name=\"atuacao_" +
              i +
              "\" value=\"" +
              modo +
              "\"" +
              checked +
              "><span>" +
              label +
              "</span></label>"
            );
          })
          .join("") +
        "</div>" +
        "<label class=\"rota-equipe-pessoas\">Pessoas <input class=\"rota-input\" type=\"number\" inputmode=\"numeric\" name=\"pessoas_equipe\" min=\"1\" max=\"80\" step=\"1\" value=\"" +
        (base.pessoas > 0 ? base.pessoas : 1) +
        "\"></label>";
      el.equipes.appendChild(wrap);
    }
    syncLocal();
    syncResumo();
  }

  function fillSelect(select, items, valueKey, labelKey, selected, emptyLabel) {
    select.innerHTML = "";
    var opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = emptyLabel || "Selecione";
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
    fillSelect(el.bairro, [], "bairro", "bairro", "", "Selecione a cidade");
    el.bairro.disabled = true;
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
    if (el.kpiOcupacao) {
      el.kpiOcupacao.textContent =
        ind.pct_hc === null || ind.pct_hc === undefined
          ? ""
          : "Ocupação " + fmtNum(ind.pct_hc) + "% dos HPs da área";
    }
    el.kpiHps.textContent = fmtNum(ind.hps);
    el.kpiPct.textContent =
      ind.pct_hc === null || ind.pct_hc === undefined ? "—" : fmtNum(ind.pct_hc) + "%";
    el.kpiViaveis.textContent =
      fmtNum(ind.fachadas_viaveis) + " / " + fmtNum(ind.fachadas_total);
    el.dfvFaixa.textContent = cred.faixa_predominante || "—";
    el.dfvClass.textContent = perfil.classificacao_predominante || "—";
    if (el.dfvClasseSocial) {
      el.dfvClasseSocial.textContent = perfil.classe_social_predominante || "—";
    }
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
    el.dfvConteudo.classList.remove("rota-fade");
    void el.dfvConteudo.offsetWidth;
    el.dfvConteudo.classList.add("rota-fade");
    show(el.dfvConteudo, true);
  }

  async function loadUfs(selectedUf) {
    setFieldBusy(el.fieldUf, true);
    setSpinner(el.spinUf, true);
    el.cidade.disabled = true;
    try {
      var out = await api(withPdv(urls.ufs));
      if (!out.data.ok) return;
      fillSelect(el.uf, out.data.data.items, "uf", "uf", selectedUf);
    } finally {
      setSpinner(el.spinUf, false);
      setFieldBusy(el.fieldUf, false);
    }
  }

  async function loadCidades(uf, selectedCidade) {
    var reqId = ++state.cidadeReq;
    el.cidade.disabled = true;
    el.bairro.disabled = true;
    setFieldBusy(el.fieldCidade, true);
    resetBairroField(uf ? "Selecione a cidade para carregar os bairros." : "");
    if (!uf) {
      fillSelect(el.cidade, [], "cidade", "cidade");
      setFieldBusy(el.fieldCidade, false);
      return;
    }
    setSpinner(el.spinCidade, true);
    try {
      var out = await api(withPdv(urls.cidades, { uf: uf }));
      if (reqId !== state.cidadeReq) return;
      if (!out.data.ok) return;
      fillSelect(el.cidade, out.data.data.items, "cidade", "cidade", selectedCidade);
      el.cidade.disabled = false;
    } finally {
      if (reqId === state.cidadeReq) {
        setSpinner(el.spinCidade, false);
        setFieldBusy(el.fieldCidade, false);
      }
    }
  }

  async function loadBairros(uf, cidade, preserveBairro) {
    var reqId = ++state.bairrosListReq;
    var keep = (preserveBairro || "").trim();
    if (!(uf && cidade)) {
      resetBairroField();
      return;
    }
    el.bairro.disabled = true;
    setFieldBusy(el.fieldBairro, true);
    setSpinner(el.spinBairro, true);
    try {
      var out = await api(withPdv(urls.bairros, { uf: uf, cidade: cidade }));
      if (reqId !== state.bairrosListReq) return;
      if (!out.data.ok) {
        fillSelect(el.bairro, [], "bairro", "bairro", "", "Lista indisponível");
        el.bairroFonte.textContent = "Não foi possível listar os bairros disponíveis.";
        return;
      }
      var items = out.data.data.items || [];
      fillSelect(el.bairro, items, "bairro", "bairro", keep, "Selecione o bairro");
      el.bairro.disabled = items.length === 0;
      var fonte = out.data.data.fonte || "";
      el.bairroFonte.textContent = items.length
        ? items.length + " bairros disponíveis"
        : "Nenhum bairro disponível para esta cidade (" + fonte + ").";
      if (keep && el.bairro.value === keep) scheduleDfv();
    } finally {
      if (reqId === state.bairrosListReq) {
        setSpinner(el.spinBairro, false);
        setFieldBusy(el.fieldBairro, false);
      }
    }
  }

  async function loadDfv(uf, cidade, bairro) {
    if (!(uf && cidade && bairro) || !precisaLocal()) {
      resetDfv();
      return;
    }
    var reqId = ++state.bairroReq;
    show(el.dfvEmpty, false);
    show(el.dfvConteudo, false);
    show(el.dfvErro, false);
    show(el.dfvLoading, true);
    el.dfvLocal.textContent = bairro + " · " + cidade + "/" + uf;
    el.btnSalvar.disabled = true;
    try {
      var out = await api(withPdv(urls.dfv, { uf: uf, cidade: cidade, bairro: bairro }));
      if (reqId !== state.bairroReq) return;
      if (!out.data.ok) {
        show(el.dfvErro, true);
        if (el.dfvErroMsg) {
          el.dfvErroMsg.textContent =
            (out.data.error && out.data.error.message) ||
            "Tente escolher o bairro novamente em instantes.";
        }
        return;
      }
      renderDfv(out.data.data);
    } catch (e) {
      if (reqId !== state.bairroReq) return;
      show(el.dfvErro, true);
      if (el.dfvErroMsg) {
        el.dfvErroMsg.textContent = "A consulta demorou ou falhou. Tente de novo em instantes.";
      }
    } finally {
      if (reqId === state.bairroReq) {
        show(el.dfvLoading, false);
        el.btnSalvar.disabled = false;
      }
    }
  }

  function scheduleDfv() {
    clearTimeout(state.bairroTimer);
    var bairro = (el.bairro.value || "").trim();
    if (!bairro || !precisaLocal()) {
      resetDfv();
      return;
    }
    state.bairroTimer = setTimeout(function () {
      loadDfv(el.uf.value, el.cidade.value, bairro);
    }, 250);
  }

  function renderAlertaSemana(status, mensagem, metaRef) {
    if (!el.alertaSemana) return;
    var st = status || "ok";
    el.alertaSemana.className = "rota-callout " + st;
    var titulo = "Plano alinhado à meta semanal.";
    if (st === "critico" || st === "abaixo") {
      titulo = "Atenção: a meta de referência da semana é " + fmtNum(metaRef) + ".";
    }
    if (el.alertaTitulo) el.alertaTitulo.textContent = titulo;
    if (el.alertaMsg) el.alertaMsg.textContent = mensagem || "";
    show(el.alertaSemana, true);
  }

  async function validarSemana() {
    if (!state.ehSegunda || !state.pdvId) return;
    var raw = el.vendas.value;
    if (raw === "" || raw === null) {
      show(el.alertaSemana, false);
      return;
    }
    var out = await api(urls.validar, {
      method: "POST",
      body: JSON.stringify({ vendas_planejadas: Number(raw), pdv: state.pdvId }),
    });
    if (!out.data.ok) return;
    var d = out.data.data;
    renderAlertaSemana(d.status_alerta, d.mensagem, d.meta_referencia);
  }

  function rotuloDia(iso) {
    if (!iso) return "Rota";
    var p = iso.split("-");
    return "Rota de " + p[2] + "/" + p[1];
  }

  function renderWeek() {
    if (!el.week) return;
    el.week.innerHTML = "";
    (state.semana.dias || []).forEach(function (dia) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "rota-day";
      if (dia.data === state.dia) btn.classList.add("is-on");
      if (dia.eh_hoje) btn.classList.add("is-hoje");
      if (dia.preenchido) btn.classList.add("is-done");
      btn.dataset.data = dia.data;
      btn.innerHTML =
        "<span class=\"rota-day-lab\">" +
        dia.label +
        "</span><span class=\"rota-day-num\">" +
        dia.data.slice(8) +
        "</span>" +
        (dia.preenchido
          ? "<span class=\"rota-day-dot\">" + (dia.qtd_equipes || 1) + "</span>"
          : "");
      btn.addEventListener("click", function () {
        carregarDia(dia.data);
      });
      el.week.appendChild(btn);
    });
  }

  function resetFormulario() {
    el.qtdEquipes.value = "1";
    renderEquipes([{ atuacao: "PAP", pessoas: 1 }]);
    setRadio("houve_contratacao", "nao");
    setRadio("houve_desligamento", "nao");
    el.qtdContratacoes.value = "";
    el.qtdDesligamentos.value = "";
    if (el.vendas) el.vendas.value = "";
    if (el.vbDia) el.vbDia.value = "0";
    show(el.alertaSemana, false);
    show(el.statusSalvo, false);
    show(el.formError, false);
    el.btnSalvar.querySelector(".btn-label").textContent = "Registrar rota";
    syncRh();
  }

  function applyCheckin(checkin) {
    if (!checkin) {
      resetFormulario();
      return;
    }
    var equipes = checkin.equipes && checkin.equipes.length ? checkin.equipes : [];
    el.qtdEquipes.value = String(checkin.qtd_equipes || equipes.length || 1);
    renderEquipes(equipes);
    var c = Number(checkin.qtd_contratacoes) || 0;
    var d = Number(checkin.qtd_desligamentos) || 0;
    setRadio("houve_contratacao", c > 0 ? "sim" : "nao");
    setRadio("houve_desligamento", d > 0 ? "sim" : "nao");
    el.qtdContratacoes.value = c > 0 ? String(c) : "";
    el.qtdDesligamentos.value = d > 0 ? String(d) : "";
    if (el.vbDia) el.vbDia.value = String(Number(checkin.planejamento_vb_dia) || 0);
    syncRh();
    el.statusSalvo.textContent = "Rota deste dia já registrada — você pode atualizar.";
    show(el.statusSalvo, true);
    el.btnSalvar.querySelector(".btn-label").textContent = "Atualizar rota";
  }

  function podeEditar() {
    return !!state.pdvId;
  }

  async function carregarDia(iso, opts) {
    var options = opts || {};
    state.dia = iso;
    renderWeek();
    if (el.title) el.title.textContent = rotuloDia(iso);
    if (!state.pdvId) {
      show(el.form, visaoEquipe);
      if (el.pdvHint) show(el.pdvHint, true);
      show(el.skeleton, false);
      if (visaoEquipe) loadAgendas();
      return;
    }
    if (el.pdvHint) show(el.pdvHint, false);
    show(el.skeleton, true);
    show(el.form, false);
    try {
      var out = await api(withPdv(urls.hoje, { data: iso }));
      show(el.skeleton, false);
      show(el.form, true);
      if (!out.data.ok) {
        show(el.formError, true);
        el.formError.textContent =
          (out.data.error && out.data.error.message) || "Falha ao carregar.";
        return;
      }
      aplicarPayload(out.data.data, { manterLoc: options.manterLoc });
      if (options.scroll && el.form) {
        el.form.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    } finally {
      show(el.skeleton, false);
      if (visaoEquipe) loadAgendas();
    }
  }

  async function aplicarPayload(data, opts) {
    var options = opts || {};
    state.hoje = data.hoje || state.hoje;
    state.ehSegunda = !!data.eh_segunda;
    state.metaSemana = data.meta_semana || {};
    if (data.semana) state.semana = data.semana;
    if (data.pdv && data.pdv.id) state.pdvId = String(data.pdv.id);
    state.dia = data.data || state.dia;
    renderWeek();
    if (el.title) el.title.textContent = rotuloDia(state.dia);

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
        renderAlertaSemana(
          data.planejamento_semana.status_alerta,
          data.planejamento_semana.mensagem,
          data.planejamento_semana.meta_referencia
        );
      } else if (!data.checkin) {
        el.vendas.value = "";
        show(el.alertaSemana, false);
      }
    }

    applyCheckin(data.checkin || null);

    if (!options.manterLoc) {
      var loc = (data.checkin && data.checkin.local) || data.defaults || {};
      var uf = loc.uf || "";
      var cidade = loc.cidade || "";
      var bairro = loc.bairro || "";
      await loadUfs(uf);
      if (uf) {
        await loadCidades(uf, cidade);
        if (cidade) {
          await loadBairros(uf, cidade, bairro);
        } else {
          resetBairroField("Selecione a cidade para carregar os bairros.");
        }
      } else {
        resetBairroField();
      }
    }
    syncLocal();
  }

  function renderResultado(payload) {
    var totais = (payload && payload.totais) || {};
    var dia = totais.dia || {};
    var semana = totais.semana || {};
    if (el.resultadoDia && payload && payload.data) {
      var p = String(payload.data).split("-");
      el.resultadoDia.textContent = p.length === 3 ? p[2] + "/" + p[1] : payload.data;
    }
    if (el.kpiVbDia) el.kpiVbDia.textContent = fmtNum(dia.vb || 0);
    if (el.kpiVbSemana) el.kpiVbSemana.textContent = fmtNum(semana.vb || 0);
    if (el.kpiEqDia) el.kpiEqDia.textContent = fmtNum(dia.equipes || 0);
    if (el.kpiPeDia) el.kpiPeDia.textContent = fmtNum(dia.pessoas || 0);
    if (el.kpiPdvDia) el.kpiPdvDia.textContent = fmtNum(dia.pdvs || 0);

    if (el.especs) {
      var grupos = (payload && payload.especialistas) || [];
      if (!grupos.length) {
        el.especs.innerHTML = "";
      } else {
        el.especs.innerHTML = grupos
          .map(function (g) {
            var d = g.dia || {};
            var s = g.semana || {};
            return (
              "<article class=\"rota-espec-card\">" +
              "<p class=\"rota-kicker\">Especialista</p>" +
              "<h3>" +
              (g.nome || "Sem especialista") +
              "</h3>" +
              "<p><strong>" +
              fmtNum(d.vb || 0) +
              " VBs</strong> no dia · " +
              fmtNum(s.vb || 0) +
              " na semana</p>" +
              "<p class=\"help\">" +
              fmtNum(d.equipes || 0) +
              " equipes · " +
              fmtNum(d.pessoas || 0) +
              " pessoas · " +
              fmtNum(d.pdvs || 0) +
              " PDVs no dia</p>" +
              "</article>"
            );
          })
          .join("");
      }
    }

    if (!el.resultadoBody) return;
    var linhas = (payload && payload.items) || [];
    if (!linhas.length) {
      el.resultadoBody.innerHTML =
        "<tr><td colspan=\"6\" class=\"help\">Nenhum PDV nesta busca.</td></tr>";
      return;
    }
    el.resultadoBody.innerHTML = "";
    linhas.forEach(function (pdv) {
      var tr = document.createElement("tr");
      if (String(pdv.id) === String(state.pdvId)) tr.className = "is-on";
      var diaP = pdv.dia || {};
      var semP = pdv.semana || {};
      tr.innerHTML =
        "<td><button type=\"button\" class=\"rota-agendas-pdv\" data-pdv=\"" +
        pdv.id +
        "\">" +
        pdv.codigo_pdv +
        " · " +
        pdv.nome +
        "</button></td>" +
        "<td>" +
        (pdv.especialista || "—") +
        "</td>" +
        "<td>" +
        (diaP.preenchido ? fmtNum(diaP.vb || 0) : "—") +
        "</td>" +
        "<td>" +
        (diaP.preenchido ? fmtNum(diaP.equipes || 0) : "—") +
        "</td>" +
        "<td>" +
        (diaP.preenchido ? fmtNum(diaP.pessoas || 0) : "—") +
        "</td>" +
        "<td>" +
        fmtNum(semP.vb || 0) +
        "</td>";
      el.resultadoBody.appendChild(tr);
    });
  }

  function renderAgendas(payload) {
    if (!el.agendasBody) return;
    var items = (payload && payload.items) || [];
    if (!items.length) {
      el.agendasBody.innerHTML =
        "<tr><td colspan=\"8\" class=\"help\">Nenhum PDV nesta busca.</td></tr>";
      return;
    }
    el.agendasBody.innerHTML = "";
    items.forEach(function (pdv) {
      var tr = document.createElement("tr");
      if (String(pdv.id) === String(state.pdvId)) tr.className = "is-on";
      var nome =
        "<button type=\"button\" class=\"rota-agendas-pdv\" data-pdv=\"" +
        pdv.id +
        "\">" +
        pdv.codigo_pdv +
        " · " +
        pdv.nome +
        "</button>";
      var cells = (state.semana.dias || []).map(function (slot) {
        var info = (pdv.dias || {})[slot.data];
        if (!info) {
          return (
            "<td><button type=\"button\" class=\"rota-ag-dot is-empty\" data-pdv=\"" +
            pdv.id +
            "\" data-dia=\"" +
            slot.data +
            "\" aria-label=\"Abrir " +
            slot.label +
            "\"></button></td>"
          );
        }
        return (
          "<td><button type=\"button\" class=\"rota-ag-dot is-done\" data-pdv=\"" +
          pdv.id +
          "\" data-dia=\"" +
          slot.data +
          "\" title=\"" +
          (info.qtd_equipes || 1) +
          " equipes · " +
          fmtNum(info.planejamento_vb_dia || 0) +
          " VBs\">" +
          (info.qtd_equipes || 1) +
          "</button></td>"
        );
      });
      tr.innerHTML = "<td>" + nome + "</td>" + cells.join("");
      el.agendasBody.appendChild(tr);
    });
  }

  async function loadAgendas() {
    if (!visaoEquipe || !urls.agendas) return;
    var q = el.agendasQ ? el.agendasQ.value : "";
    var params = [];
    if (state.dia) params.push("data=" + encodeURIComponent(state.dia));
    if (q) params.push("q=" + encodeURIComponent(q));
    var out = await api(urls.agendas + (params.length ? "?" + params.join("&") : ""));
    if (out.data.ok) {
      renderAgendas(out.data.data);
      renderResultado(out.data.data);
    }
  }

  async function selecionarPdv(id, dia) {
    state.pdvId = String(id || "");
    await carregarDia(dia || state.dia || state.hoje, { scroll: true });
  }

  async function init() {
    try {
      var out = await api(withPdv(urls.hoje));
      if (!out.data.ok) {
        show(el.skeleton, false);
        show(el.form, true);
        show(el.formError, true);
        el.formError.textContent =
          (out.data.error && out.data.error.message) || "Falha ao carregar.";
        return;
      }
      var data = out.data.data;
      state.hoje = data.hoje || data.data;
      state.dia = data.data;
      if (data.pdv && data.pdv.id) state.pdvId = String(data.pdv.id);
      if (data.semana) state.semana = data.semana;
      renderWeek();
      show(el.skeleton, false);
      if (state.pdvId) {
        show(el.form, true);
        await aplicarPayload(data);
      } else {
        show(el.form, visaoEquipe);
        if (el.pdvHint) show(el.pdvHint, true);
      }
      await loadAgendas();
    } finally {
      show(el.skeleton, false);
    }
  }

  el.form.addEventListener("change", function (ev) {
    var t = ev.target;
    if (!t) return;
    if (t.name === "houve_contratacao" || t.name === "houve_desligamento") syncRh();
    if (t.name && t.name.indexOf("atuacao_") === 0) {
      syncLocal();
      scheduleDfv();
    }
    if (t.name === "pessoas_equipe") syncResumo();
  });
  el.form.addEventListener("input", function (ev) {
    var t = ev.target;
    if (!t) return;
    if (t.name === "pessoas_equipe" || t.id === "qtd_contratacoes" || t.id === "qtd_desligamentos" || t.id === "planejamento_vb_dia") {
      syncResumo();
    }
  });

  el.qtdEquipes.addEventListener("change", function () {
    renderEquipes();
  });

  el.uf.addEventListener("change", function () {
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

  el.bairro.addEventListener("change", scheduleDfv);

  if (el.vendas) {
    el.vendas.addEventListener("change", validarSemana);
    el.vendas.addEventListener("blur", validarSemana);
  }

  if (el.agendasQ) {
    el.agendasQ.addEventListener("input", function () {
      clearTimeout(state.agendasTimer);
      state.agendasTimer = setTimeout(loadAgendas, 280);
    });
  }

  if (el.agendasBody) {
    el.agendasBody.addEventListener("click", function (ev) {
      var btn = ev.target.closest("[data-pdv]");
      if (!btn) return;
      selecionarPdv(btn.getAttribute("data-pdv"), btn.getAttribute("data-dia") || undefined);
    });
  }
  if (el.resultadoBody) {
    el.resultadoBody.addEventListener("click", function (ev) {
      var btn = ev.target.closest("[data-pdv]");
      if (!btn) return;
      selecionarPdv(btn.getAttribute("data-pdv"));
    });
  }

  el.form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    show(el.formError, false);
    if (!podeEditar()) {
      show(el.formError, true);
      el.formError.textContent = "Selecione o PDV na agenda.";
      return;
    }
    setSpinner(el.spinSalvar, true);
    el.btnSalvar.disabled = true;

    var equipes = lerEquipes();
    var payload = {
      data: state.dia,
      pdv: state.pdvId,
      equipes: equipes,
      qtd_vendedores: totalPessoas(),
      qtd_contratacoes: qtdContratacoes(),
      qtd_desligamentos: qtdDesligamentos(),
      planejamento_vb_dia: Number(el.vbDia && el.vbDia.value) || 0,
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

      var salvo = out.data.data;
      if (salvo.semana) {
        state.semana = salvo.semana;
        renderWeek();
      }
      applyCheckin(salvo);
      var n = salvo.qtd_equipes || equipes.length;
      el.statusSalvo.textContent =
        "Rota salva · " +
        n +
        (n === 1 ? " equipe" : " equipes") +
        " em campo · " +
        (salvo.total_campo || totalPessoas()) +
        " pessoas · " +
        (salvo.planejamento_vb_dia || 0) +
        " VBs.";
      show(el.statusSalvo, true);
      loadAgendas();
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
