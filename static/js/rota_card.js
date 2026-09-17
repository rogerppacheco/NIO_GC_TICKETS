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
    blocoArranjo: document.getElementById("bloco-arranjo"),
    blocoMesmaRota: document.getElementById("bloco-mesma-rota"),
    blocoDividir: document.getElementById("bloco-dividir-bairros"),
    blocoRotas: document.getElementById("bloco-rotas"),
    passoPlanoN: document.getElementById("passo-plano-n"),
    metaHint: document.getElementById("meta-semana-hint"),
    alertaSemana: document.getElementById("alerta-semana"),
    alertaTitulo: document.getElementById("alerta-semana-titulo"),
    alertaMsg: document.getElementById("alerta-semana-msg"),
    qtdEquipes: document.getElementById("qtd_equipes"),
    equipes: document.getElementById("rota-equipes"),
    vbDia: document.getElementById("planejamento_vb_dia"),
    horaInicio: document.getElementById("horario_inicio"),
    horaFim: document.getElementById("horario_fim"),
    vendas: document.getElementById("vendas_planejadas_semana"),
    qtdContratacoes: document.getElementById("qtd_contratacoes"),
    qtdDesligamentos: document.getElementById("qtd_desligamentos"),
    resumo: document.getElementById("rota-resumo"),
    resumoEquipes: document.getElementById("rota-resumo-equipes"),
    resumoPessoas: document.getElementById("rota-resumo-pessoas"),
    resumoVb: document.getElementById("rota-resumo-vb"),
    resumoHora: document.getElementById("rota-resumo-hora"),
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
    dfvChips: document.getElementById("dfv-chips"),
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
    agendasTimer: null,
    ufsItems: null,
    locaisPorEquipe: {},
    dfvFoco: 0,
    rotasReq: 0,
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

  function fmtHora(v) {
    if (!v) return "";
    return String(v).slice(0, 5);
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

  function indicesCampo() {
    var saida = [];
    lerEquipes().forEach(function (eq, idx) {
      if (eq.atuacao !== "DIGITAL") saida.push(idx);
    });
    return saida;
  }

  function mesmaRota() {
    return radioVal("mesma_rota", "sim") === "sim";
  }

  function dividirBairros() {
    return radioVal("dividir_bairros", "nao") === "sim";
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
    if (el.resumoHora) {
      var ini = fmtHora(el.horaInicio && el.horaInicio.value);
      var fim = fmtHora(el.horaFim && el.horaFim.value);
      el.resumoHora.textContent = ini && fim ? ini + "–" + fim : "";
    }
    var rh = [];
    var c = qtdContratacoes();
    var d = qtdDesligamentos();
    if (c) rh.push("+" + c + " contratação" + (c === 1 ? "" : "ões"));
    if (d) rh.push(d + " desligamento" + (d === 1 ? "" : "s"));
    el.resumoRh.textContent = rh.join(" · ");
  }

  async function syncLocal() {
    var campo = indicesCampo();
    var precisa = campo.length > 0;
    show(el.blocoArranjo, precisa);
    show(el.blocoMesmaRota, precisa && campo.length > 1);
    show(el.blocoDividir, precisa && campo.length === 1);
    if (el.passoPlanoN) el.passoPlanoN.textContent = precisa ? "3" : "2";
    if (!precisa) {
      el.blocoRotas.innerHTML = "";
      resetDfv();
      return;
    }
    await renderRotas();
  }

  function syncRh() {
    show(el.qtdContratacoes, radioVal("houve_contratacao", "nao") === "sim");
    show(el.qtdDesligamentos, radioVal("houve_desligamento", "nao") === "sim");
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
        "<p class=\"rota-equipe-n\">" +
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

  function locDe(block) {
    return {
      block: block,
      uf: block.querySelector("[data-loc=uf]"),
      cidade: block.querySelector("[data-loc=cidade]"),
      bairro: block.querySelector("[data-loc=bairro]"),
      extras: block.querySelector("[data-loc=extras]"),
      fonte: block.querySelector("[data-loc=fonte]"),
      fieldUf: block.querySelector("[data-field=uf]"),
      fieldCidade: block.querySelector("[data-field=cidade]"),
      fieldBairro: block.querySelector("[data-field=bairro]"),
      spinUf: block.querySelector("[data-spin=uf]"),
      spinCidade: block.querySelector("[data-spin=cidade]"),
      spinBairro: block.querySelector("[data-spin=bairro]"),
    };
  }

  function snapshotLocais() {
    if (!el.blocoRotas) return;
    el.blocoRotas.querySelectorAll(".rota-rota").forEach(function (block) {
      var loc = locDe(block);
      var extras = [];
      block.querySelectorAll("[data-loc=bairro-extra]").forEach(function (sel) {
        if (sel.value) extras.push(sel.value);
      });
      state.locaisPorEquipe[block.dataset.equipe] = {
        uf: loc.uf ? loc.uf.value : "",
        cidade: loc.cidade ? loc.cidade.value : "",
        bairro: loc.bairro ? loc.bairro.value : "",
        bairros: extras,
      };
    });
  }

  function lerLocais() {
    var saida = [];
    if (!el.blocoRotas) return saida;
    el.blocoRotas.querySelectorAll(".rota-rota").forEach(function (block) {
      var loc = locDe(block);
      var extras = [];
      block.querySelectorAll("[data-loc=bairro-extra]").forEach(function (sel) {
        if (sel.value) extras.push(sel.value.trim());
      });
      saida.push({
        equipe: Number(block.dataset.equipe),
        uf: loc.uf ? loc.uf.value : "",
        cidade: loc.cidade ? loc.cidade.value : "",
        bairro: loc.bairro ? loc.bairro.value : "",
        bairros: extras,
      });
    });
    return saida;
  }

  function localPrincipal() {
    var locais = lerLocais();
    return locais[0] || { uf: "", cidade: "", bairro: "", bairros: [] };
  }

  function montarEquipesPayload() {
    var equipes = lerEquipes();
    var locais = lerLocais();
    var mesma = indicesCampo().length < 2 || mesmaRota();
    var dividir = indicesCampo().length === 1 && dividirBairros();
    if (mesma && locais[0]) {
      equipes.forEach(function (eq) {
        if (eq.atuacao === "DIGITAL") return;
        eq.uf = locais[0].uf;
        eq.cidade = locais[0].cidade;
        eq.bairro = locais[0].bairro;
        if (dividir) eq.bairros = locais[0].bairros || [];
      });
      return equipes;
    }
    locais.forEach(function (loc) {
      var eq = equipes[loc.equipe];
      if (!eq || eq.atuacao === "DIGITAL") return;
      eq.uf = loc.uf;
      eq.cidade = loc.cidade;
      eq.bairro = loc.bairro;
    });
    return equipes;
  }

  function todosLocaisDfv() {
    var lista = [];
    lerLocais().forEach(function (loc) {
      if (loc.uf && loc.cidade && loc.bairro) {
        lista.push({
          uf: loc.uf,
          cidade: loc.cidade,
          bairro: loc.bairro,
          rotulo: loc.bairro + " · " + loc.cidade + "/" + loc.uf,
        });
      }
      (loc.bairros || []).forEach(function (b) {
        if (loc.uf && loc.cidade && b) {
          lista.push({
            uf: loc.uf,
            cidade: loc.cidade,
            bairro: b,
            rotulo: b + " · " + loc.cidade + "/" + loc.uf,
          });
        }
      });
    });
    var seen = {};
    return lista.filter(function (item) {
      var key = item.uf + "|" + item.cidade + "|" + item.bairro;
      if (seen[key]) return false;
      seen[key] = true;
      return true;
    });
  }

  function htmlSelect(loc, empty, disabled) {
    return (
      '<div class="rota-control">' +
      '<select class="rota-input" data-loc="' +
      loc +
      '"' +
      (disabled ? " disabled" : "") +
      '><option value="">' +
      empty +
      "</option></select>" +
      '<span class="rota-spinner" data-spin="' +
      loc +
      '" hidden></span></div>'
    );
  }

  function htmlRotaBlock(idx, titulo, ajuda, preset, comExtras) {
    preset = preset || {};
    var extraHtml = "";
    if (comExtras) {
      extraHtml =
        '<div data-loc="extras"></div>' +
        '<button type="button" class="btn btn-secondary btn-sm rota-add-bairro" data-add-bairro>Adicionar outro bairro</button>';
    }
    return (
      '<article class="rota-rota" data-equipe="' +
      idx +
      '"><h3>' +
      titulo +
      "</h3>" +
      (ajuda ? '<p class="help">' + ajuda + "</p>" : "") +
      '<div class="rota-local">' +
      '<div class="rota-field" data-field="uf"><label>UF</label>' +
      htmlSelect("uf", "Selecione", false) +
      "</div>" +
      '<div class="rota-field" data-field="cidade"><label>Cidade</label>' +
      htmlSelect("cidade", "Selecione a UF", true) +
      "</div>" +
      '<div class="rota-field" data-field="bairro"><label>' +
      (comExtras ? "Bairro 1" : "Bairro") +
      "</label>" +
      htmlSelect("bairro", "Selecione a cidade", true) +
      '<p class="help" data-loc="fonte"></p></div></div>' +
      extraHtml +
      "</article>"
    );
  }

  function renderExtras(block, values) {
    var box = block.querySelector("[data-loc=extras]");
    if (!box) return;
    var keep = values && values.length ? values : [];
    var atuais = [];
    box.querySelectorAll("[data-loc=bairro-extra]").forEach(function (sel) {
      atuais.push(sel.value);
    });
    var lista = keep.length ? keep : atuais;
    if (!lista.length) lista = [""];
    box.innerHTML = lista
      .map(function (valor, i) {
        return (
          '<div class="rota-field rota-bairro-extra"><label>Bairro ' +
          (i + 2) +
          "</label><div class=\"rota-bairro-extra-row\">" +
          htmlSelect("bairro-extra", "Selecione a cidade", true) +
          (lista.length > 1
            ? '<button type="button" class="rota-remove-bairro" data-remove-bairro="' +
              i +
              '" aria-label="Remover bairro ' +
              (i + 2) +
              '">×</button>'
            : "") +
          "</div></div>"
        );
      })
      .join("");
    lista.forEach(function (valor, i) {
      var sel = box.querySelectorAll("[data-loc=bairro-extra]")[i];
      if (sel) sel.setAttribute("data-keep", valor || "");
    });
  }

  async function renderRotas() {
    var reqId = ++state.rotasReq;
    snapshotLocais();
    var campo = indicesCampo();
    var mesma = campo.length < 2 || mesmaRota();
    var dividir = campo.length === 1 && dividirBairros();
    if (!mesma && campo.length > 1) {
      var base = state.locaisPorEquipe[campo[0]] || {};
      campo.forEach(function (idx, pos) {
        if (pos === 0) return;
        var cur = state.locaisPorEquipe[idx];
        if (!cur || !cur.uf) {
          state.locaisPorEquipe[idx] = {
            uf: base.uf || "",
            cidade: base.cidade || "",
            bairro: "",
            bairros: [],
          };
        }
      });
    }
    var html = "";
    if (mesma) {
      var idx = campo[0];
      var preset = state.locaisPorEquipe[idx] || {};
      html = htmlRotaBlock(
        idx,
        campo.length > 1 ? "Rota compartilhada" : "Local da rota",
        campo.length > 1 ? "Esse local vale para todas as equipes PAP ou mistas." : "",
        preset,
        dividir
      );
    } else {
      html = campo
        .map(function (idx) {
          var preset = state.locaisPorEquipe[idx] || {};
          return htmlRotaBlock(
            idx,
            "Rota da equipe " + (idx + 1),
            "UF, cidade e bairro só desta equipe.",
            preset,
            false
          );
        })
        .join("");
    }
    el.blocoRotas.innerHTML = html;
    if (reqId !== state.rotasReq) return;
    if (dividir) {
      var first = el.blocoRotas.querySelector(".rota-rota");
      var preset0 = state.locaisPorEquipe[campo[0]] || {};
      renderExtras(first, preset0.bairros || [""]);
    }
    var blocks = el.blocoRotas.querySelectorAll(".rota-rota");
    for (var i = 0; i < blocks.length; i++) {
      await hidratarRota(blocks[i], state.locaisPorEquipe[blocks[i].dataset.equipe] || {});
    }
    renderDfvChips();
    scheduleDfv();
  }

  async function ensureUfs() {
    if (state.ufsItems && state.ufsItems.length) return state.ufsItems;
    if (!state.pdvId) return [];
    var out = await api(withPdv(urls.ufs));
    state.ufsItems = out.data.ok ? out.data.data.items || [] : [];
    return state.ufsItems;
  }

  async function hidratarRota(block, preset) {
    var loc = locDe(block);
    var uf = preset.uf || "";
    var cidade = preset.cidade || "";
    var bairro = preset.bairro || "";
    setFieldBusy(loc.fieldUf, true);
    setSpinner(loc.spinUf, true);
    try {
      var ufs = await ensureUfs();
      fillSelect(loc.uf, ufs, "uf", "uf", uf);
    } finally {
      setSpinner(loc.spinUf, false);
      setFieldBusy(loc.fieldUf, false);
    }
    await loadCidadesBlock(block, uf, cidade, bairro, preset.bairros || []);
  }

  function bumpReq(block, key) {
    var n = (Number(block.getAttribute("data-req-" + key)) || 0) + 1;
    block.setAttribute("data-req-" + key, String(n));
    return n;
  }

  function isCurrentReq(block, key, id) {
    return Number(block.getAttribute("data-req-" + key)) === id;
  }

  async function loadCidadesBlock(block, uf, selectedCidade, selectedBairro, extraBairros) {
    var loc = locDe(block);
    var reqId = bumpReq(block, "cidade");
    loc.cidade.disabled = true;
    loc.bairro.disabled = true;
    setFieldBusy(loc.fieldCidade, true);
    fillSelect(loc.bairro, [], "bairro", "bairro", "", "Selecione a cidade");
    if (loc.fonte) loc.fonte.textContent = uf ? "Selecione a cidade para carregar os bairros." : "";
    if (!uf) {
      fillSelect(loc.cidade, [], "cidade", "cidade");
      setFieldBusy(loc.fieldCidade, false);
      return;
    }
    setSpinner(loc.spinCidade, true);
    try {
      var out = await api(withPdv(urls.cidades, { uf: uf }));
      if (!isCurrentReq(block, "cidade", reqId)) return;
      if (!out.data.ok) return;
      fillSelect(loc.cidade, out.data.data.items, "cidade", "cidade", selectedCidade);
      loc.cidade.disabled = false;
    } finally {
      if (isCurrentReq(block, "cidade", reqId)) {
        setSpinner(loc.spinCidade, false);
        setFieldBusy(loc.fieldCidade, false);
      }
    }
    if (selectedCidade || loc.cidade.value) {
      await loadBairrosBlock(block, uf, loc.cidade.value || selectedCidade, selectedBairro, extraBairros);
    }
  }

  async function loadBairrosBlock(block, uf, cidade, preserveBairro, extraBairros) {
    var loc = locDe(block);
    var reqId = bumpReq(block, "bairros");
    var keep = (preserveBairro || "").trim();
    if (!(uf && cidade)) {
      fillSelect(loc.bairro, [], "bairro", "bairro", "", "Selecione a cidade");
      loc.bairro.disabled = true;
      return;
    }
    loc.bairro.disabled = true;
    setFieldBusy(loc.fieldBairro, true);
    setSpinner(loc.spinBairro, true);
    try {
      var out = await api(withPdv(urls.bairros, { uf: uf, cidade: cidade }));
      if (!isCurrentReq(block, "bairros", reqId)) return;
      var items = out.data.ok ? out.data.data.items || [] : [];
      var empty = out.data.ok ? "Selecione o bairro" : "Lista indisponível";
      fillSelect(loc.bairro, items, "bairro", "bairro", keep, empty);
      loc.bairro.disabled = items.length === 0;
      if (loc.fonte) {
        loc.fonte.textContent = items.length
          ? items.length + " bairros disponíveis"
          : "Nenhum bairro disponível para esta cidade.";
      }
      block.querySelectorAll("[data-loc=bairro-extra]").forEach(function (sel, i) {
        var extraKeep = Array.isArray(extraBairros)
          ? extraBairros[i] || ""
          : sel.getAttribute("data-keep") || "";
        fillSelect(sel, items, "bairro", "bairro", extraKeep, "Selecione o bairro");
        sel.disabled = items.length === 0;
      });
    } finally {
      if (isCurrentReq(block, "bairros", reqId)) {
        setSpinner(loc.spinBairro, false);
        setFieldBusy(loc.fieldBairro, false);
      }
    }
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

  function resetDfv() {
    state.dfvResumo = null;
    state.bairroReq += 1;
    show(el.dfvEmpty, true);
    show(el.dfvLoading, false);
    show(el.dfvErro, false);
    show(el.dfvConteudo, false);
    if (el.dfvChips) {
      el.dfvChips.innerHTML = "";
      show(el.dfvChips, false);
    }
    el.dfvLocal.textContent = "Selecione o bairro";
  }

  function renderDfvChips() {
    if (!el.dfvChips) return;
    var lista = todosLocaisDfv();
    if (lista.length < 2) {
      el.dfvChips.innerHTML = "";
      show(el.dfvChips, false);
      return;
    }
    if (state.dfvFoco >= lista.length) state.dfvFoco = 0;
    el.dfvChips.innerHTML = lista
      .map(function (item, i) {
        return (
          '<button type="button" class="rota-dfv-chip' +
          (i === state.dfvFoco ? " is-on" : "") +
          '" data-dfv="' +
          i +
          '">' +
          item.bairro +
          "</button>"
        );
      })
      .join("");
    show(el.dfvChips, true);
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
    renderDfvChips();
    var lista = todosLocaisDfv();
    if (!lista.length || !precisaLocal()) {
      resetDfv();
      return;
    }
    if (state.dfvFoco >= lista.length) state.dfvFoco = 0;
    var alvo = lista[state.dfvFoco];
    state.bairroTimer = setTimeout(function () {
      loadDfv(alvo.uf, alvo.cidade, alvo.bairro);
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
    setRadio("mesma_rota", "sim");
    setRadio("dividir_bairros", "nao");
    state.locaisPorEquipe = {};
    renderEquipes([{ atuacao: "PAP", pessoas: 1 }]);
    setRadio("houve_contratacao", "nao");
    setRadio("houve_desligamento", "nao");
    el.qtdContratacoes.value = "";
    el.qtdDesligamentos.value = "";
    if (el.vendas) el.vendas.value = "";
    if (el.vbDia) el.vbDia.value = "0";
    if (el.horaInicio) el.horaInicio.value = "";
    if (el.horaFim) el.horaFim.value = "";
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
    state.locaisPorEquipe = {};
    var locPadrao = checkin.local || {};
    equipes.forEach(function (eq, idx) {
      if ((eq.atuacao || "PAP") === "DIGITAL") return;
      state.locaisPorEquipe[idx] = {
        uf: eq.uf || locPadrao.uf || "",
        cidade: eq.cidade || locPadrao.cidade || "",
        bairro: eq.bairro || locPadrao.bairro || "",
        bairros: eq.bairros || [],
      };
    });
    setRadio("mesma_rota", checkin.mesma_rota === false ? "nao" : "sim");
    setRadio("dividir_bairros", checkin.dividir_bairros ? "sim" : "nao");
    renderEquipes(equipes);
    var c = Number(checkin.qtd_contratacoes) || 0;
    var d = Number(checkin.qtd_desligamentos) || 0;
    setRadio("houve_contratacao", c > 0 ? "sim" : "nao");
    setRadio("houve_desligamento", d > 0 ? "sim" : "nao");
    el.qtdContratacoes.value = c > 0 ? String(c) : "";
    el.qtdDesligamentos.value = d > 0 ? String(d) : "";
    if (el.vbDia) el.vbDia.value = String(Number(checkin.planejamento_vb_dia) || 0);
    if (el.horaInicio) el.horaInicio.value = fmtHora(checkin.horario_inicio);
    if (el.horaFim) el.horaFim.value = fmtHora(checkin.horario_fim);
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
    if (!data.checkin && data.defaults) {
      var campo0 = indicesCampo()[0];
      if (campo0 !== undefined) {
        state.locaisPorEquipe[campo0] = {
          uf: data.defaults.uf || "",
          cidade: data.defaults.cidade || "",
          bairro: data.defaults.bairro || "",
          bairros: [],
        };
      }
    }
    await syncLocal();
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
          " VBs" +
          (info.horario_inicio && info.horario_fim
            ? " · " + fmtHora(info.horario_inicio) + "–" + fmtHora(info.horario_fim)
            : "") +
          "\">" +
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
    state.ufsItems = null;
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
    if (t.id === "horario_inicio" || t.id === "horario_fim") syncResumo();
    if (t.name && t.name.indexOf("atuacao_") === 0) {
      syncLocal();
    }
    if (t.name === "mesma_rota" || t.name === "dividir_bairros") {
      syncLocal();
    }
    if (t.name === "pessoas_equipe") syncResumo();
  });
  el.form.addEventListener("input", function (ev) {
    var t = ev.target;
    if (!t) return;
    if (
      t.name === "pessoas_equipe" ||
      t.id === "qtd_contratacoes" ||
      t.id === "qtd_desligamentos" ||
      t.id === "planejamento_vb_dia" ||
      t.id === "horario_inicio" ||
      t.id === "horario_fim"
    ) {
      syncResumo();
    }
  });

  el.qtdEquipes.addEventListener("change", function () {
    renderEquipes();
  });

  el.form.addEventListener("change", function (ev) {
    var t = ev.target;
    if (!t || !el.blocoRotas || !el.blocoRotas.contains(t)) return;
    var block = t.closest(".rota-rota");
    if (!block) return;
    var loc = locDe(block);
    if (t.getAttribute("data-loc") === "uf") {
      loadCidadesBlock(block, loc.uf.value, "", "", []).then(function () {
        snapshotLocais();
        scheduleDfv();
      });
      return;
    }
    if (t.getAttribute("data-loc") === "cidade") {
      block.querySelectorAll("[data-loc=bairro-extra]").forEach(function (sel) {
        sel.removeAttribute("data-keep");
        sel.value = "";
      });
      loadBairrosBlock(block, loc.uf.value, loc.cidade.value, "", []).then(function () {
        snapshotLocais();
        scheduleDfv();
      });
      return;
    }
    if (t.getAttribute("data-loc") === "bairro" || t.getAttribute("data-loc") === "bairro-extra") {
      snapshotLocais();
      scheduleDfv();
    }
  });

  el.form.addEventListener("click", function (ev) {
    var add = ev.target.closest("[data-add-bairro]");
    if (add) {
      var block = add.closest(".rota-rota");
      if (!block) return;
      snapshotLocais();
      var extras = (state.locaisPorEquipe[block.dataset.equipe] || {}).bairros || [];
      extras.push("");
      renderExtras(block, extras);
      loadBairrosBlock(block, locDe(block).uf.value, locDe(block).cidade.value, locDe(block).bairro.value, extras);
      return;
    }
    var remove = ev.target.closest("[data-remove-bairro]");
    if (remove) {
      var bloco = remove.closest(".rota-rota");
      if (!bloco) return;
      snapshotLocais();
      var atual = (state.locaisPorEquipe[bloco.dataset.equipe] || {}).bairros || [];
      var idxRem = Number(remove.getAttribute("data-remove-bairro"));
      if (!isNaN(idxRem)) atual.splice(idxRem, 1);
      if (!atual.length) atual = [""];
      state.locaisPorEquipe[bloco.dataset.equipe] = Object.assign(
        {},
        state.locaisPorEquipe[bloco.dataset.equipe] || {},
        { bairros: atual }
      );
      renderExtras(bloco, atual);
      loadBairrosBlock(
        bloco,
        locDe(bloco).uf.value,
        locDe(bloco).cidade.value,
        locDe(bloco).bairro.value,
        atual
      );
      scheduleDfv();
      return;
    }
    var chip = ev.target.closest("[data-dfv]");
    if (chip) {
      state.dfvFoco = Number(chip.getAttribute("data-dfv")) || 0;
      scheduleDfv();
    }
  });

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

    var equipes = montarEquipesPayload();
    var principal = localPrincipal();
    var payload = {
      data: state.dia,
      pdv: state.pdvId,
      equipes: equipes,
      qtd_vendedores: totalPessoas(),
      qtd_contratacoes: qtdContratacoes(),
      qtd_desligamentos: qtdDesligamentos(),
      planejamento_vb_dia: Number(el.vbDia && el.vbDia.value) || 0,
      horario_inicio: (el.horaInicio && el.horaInicio.value) || "",
      horario_fim: (el.horaFim && el.horaFim.value) || "",
      mesma_rota: mesmaRota(),
      dividir_bairros: dividirBairros(),
      uf: principal.uf || "",
      cidade: principal.cidade || "",
      bairro: principal.bairro || "",
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
        " VBs" +
        (salvo.horario_inicio && salvo.horario_fim
          ? " · " + fmtHora(salvo.horario_inicio) + "–" + fmtHora(salvo.horario_fim)
          : "") +
        ".";
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
