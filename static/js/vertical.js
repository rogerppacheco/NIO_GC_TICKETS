(function () {
  "use strict";

  var root = document.getElementById("vertical-app");
  if (!root) return;

  var urls = {
    dashboard: root.dataset.dashboardUrl,
    list: root.dataset.listUrl,
    item: root.dataset.itemUrl,
    viacep: root.dataset.viacepUrl,
    nominatim: root.dataset.nominatimUrl,
    config: root.dataset.configUrl,
    pdvs: root.dataset.pdvsUrl,
  };
  var canConfig = root.dataset.canConfig === "1";
  var blocos = [];
  var pdvsCache = [];
  var pdvDetalhe = { id: "", codigo: "", nome: "" };

  function csrfToken() {
    var el = document.querySelector("[name=csrfmiddlewaretoken]");
    if (el && el.value) return el.value;
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function itemUrl(id) {
    return String(urls.item || "").replace(/\/0\/?$/, "/" + id + "/");
  }

  function viacepUrl(cep) {
    return String(urls.viacep || "").replace("CEP", encodeURIComponent(cep));
  }

  function fetchJson(url, opts) {
    opts = opts || {};
    var headers = opts.headers || {};
    if (!opts.skipCsrf && opts.method && opts.method !== "GET") {
      headers["X-CSRFToken"] = csrfToken();
    }
    if (opts.json) {
      headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.json);
    }
    return fetch(url, {
      method: opts.method || "GET",
      headers: headers,
      body: opts.body,
      credentials: "same-origin",
    }).then(function (res) {
      return res.json().catch(function () {
        return {};
      }).then(function (body) {
        body._status = res.status;
        body._ok = res.ok && body.ok !== false;
        return body;
      });
    });
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showPanel(name) {
    root.querySelectorAll("[data-panel]").forEach(function (el) {
      if (el.getAttribute("data-panel") === name) el.removeAttribute("hidden");
      else el.setAttribute("hidden", "");
    });
    root.querySelectorAll(".tab").forEach(function (btn) {
      btn.classList.toggle("is-active", btn.getAttribute("data-tab") === name);
    });
    if (name === "dashboard") carregarDashboard();
    if (name === "lista") carregarLista();
    if (name === "config" && canConfig) carregarConfig();
  }

  function atualizarTotaisBlocos() {
    var total = 0;
    blocos.forEach(function (b, i) {
      total += b.total;
      var cel = document.querySelector('#lista-blocos [data-total-bloco="' + i + '"]');
      if (cel) cel.textContent = b.total;
    });
    var prevenda = Math.ceil(total * 0.1);
    document.getElementById("total-hps-geral").textContent = total;
    document.getElementById("prevenda-calc").textContent = prevenda;
    document.getElementById("input_total_hps").value = total;
    document.getElementById("input_prevenda").value = prevenda;
    document.getElementById("input_blocos_json").value = JSON.stringify(blocos);
  }

  function atualizarTabelaBlocos() {
    var tbody = document.getElementById("lista-blocos");
    tbody.innerHTML = blocos
      .map(function (b, i) {
        return (
          '<tr><td><input type="text" class="inp" data-bloco="' + i + '" data-campo="nome" value="' +
          esc(b.nome) +
          '" aria-label="Nome do bloco"></td>' +
          '<td><input type="number" min="1" class="inp" data-bloco="' + i + '" data-campo="andares" value="' +
          b.andares +
          '" aria-label="Andares"></td>' +
          '<td><input type="number" min="0" class="inp" data-bloco="' + i + '" data-campo="aptos" value="' +
          b.aptos +
          '" aria-label="Aptos por andar"></td>' +
          '<td data-total-bloco="' + i + '">' + b.total + "</td>" +
          '<td><button type="button" class="btn btn-secondary" data-rm="' + i + '">Remover</button></td></tr>'
        );
      })
      .join("");
    tbody.querySelectorAll("[data-bloco]").forEach(function (inp) {
      inp.addEventListener("input", function () {
        var b = blocos[Number(inp.getAttribute("data-bloco"))];
        var campo = inp.getAttribute("data-campo");
        if (campo === "nome") b.nome = inp.value.trim();
        else b[campo] = parseInt(inp.value, 10) || 0;
        b.total = b.andares * b.aptos;
        atualizarTotaisBlocos();
      });
    });
    tbody.querySelectorAll("[data-rm]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        blocos.splice(Number(btn.getAttribute("data-rm")), 1);
        atualizarTabelaBlocos();
      });
    });
    atualizarTotaisBlocos();
  }

  function addBloco() {
    var nome = (document.getElementById("temp_bloco").value || "").trim();
    var andares = parseInt(document.getElementById("temp_andares").value, 10) || 0;
    var aptos = parseInt(document.getElementById("temp_aptos").value, 10) || 0;
    if (!nome || andares <= 0) return;
    blocos.push({ nome: nome, andares: andares, aptos: aptos, total: andares * aptos });
    atualizarTabelaBlocos();
    document.getElementById("temp_bloco").value = "";
    document.getElementById("temp_andares").value = "";
    document.getElementById("temp_aptos").value = "";
  }

  function carregarDashboard() {
    fetchJson(urls.dashboard).then(function (body) {
      var d = (body.data || body) || {};
      document.getElementById("kpi-acionamentos").textContent = d.total_acionamentos || 0;
      document.getElementById("kpi-hps").textContent = d.total_hps || 0;
      document.getElementById("kpi-prevenda").textContent = d.total_prevenda || 0;
      document.getElementById("kpi-vendas").textContent = d.vendas_realizadas || 0;
      var tbody = document.getElementById("tbody-status");
      var rows = d.por_status || [];
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="2" class="help">Nenhum acionamento ainda.</td></tr>';
        return;
      }
      tbody.innerHTML = rows
        .map(function (s) {
          return (
            "<tr><td><span class=\"pill vertical-st vertical-st-" +
            esc(s.status) +
            '">' +
            esc(s.label || s.status) +
            "</span></td><td>" +
            (s.qtd || 0) +
            "</td></tr>"
          );
        })
        .join("");
    });
  }

  function carregarLista() {
    var tbody = document.getElementById("tbody-acionamentos");
    tbody.innerHTML = '<tr><td colspan="11" class="help">Carregando…</td></tr>';
    fetchJson(urls.list).then(function (body) {
      var lista = body.data || [];
      if (!lista.length) {
        tbody.innerHTML = '<tr><td colspan="11" class="help">Nenhum acionamento.</td></tr>';
        return;
      }
      tbody.innerHTML = "";
      lista.forEach(function (i) {
        var fotos = "";
        if (i.link_fotos_fachada) fotos += '<a href="' + esc(i.link_fotos_fachada) + '" target="_blank" rel="noopener">Fachada</a> ';
        if (i.link_carta_sindico) fotos += '<a href="' + esc(i.link_carta_sindico) + '" target="_blank" rel="noopener">Carta</a>';
        if (!fotos) fotos = "—";
        var acoes = '<button type="button" class="btn btn-secondary" data-edit="' + i.id + '">Editar</button> ';
        acoes += '<button type="button" class="btn btn-secondary" data-resend="' + i.id + '">Reenviar</button> ';
        if (i.can_edit) {
          acoes +=
            '<button type="button" class="btn btn-secondary" data-st="' +
            i.id +
            '" data-cod="' +
            esc(i.status_cod) +
            '" data-obs="' +
            esc(i.observacao) +
            '">Status</button> ';
          acoes += '<button type="button" class="btn btn-secondary" data-del="' + i.id + '">Excluir</button>';
        }
        var endereco = esc((i.logradouro || "") + ", " + (i.numero || "") + " - " + (i.bairro || ""));
        tbody.innerHTML +=
          "<tr><td>#" +
          i.id +
          "</td><td><strong>" +
          esc(i.nome) +
          "</strong><br><small>" +
          esc(i.cidade_uf || i.cidade) +
          "</small></td><td><small>" +
          endereco +
          "</small></td><td>" +
          esc(i.nome_sindico) +
          "</td><td>" +
          esc(i.contato) +
          '</td><td><span class="pill">' +
          (i.total_hps || 0) +
          "</span></td><td>" +
          (i.prevenda || 0) +
          "</td><td>" +
          fotos +
          '</td><td><span class="pill vertical-st vertical-st-' +
          esc(i.status_cod) +
          '">' +
          esc(i.status) +
          "</span></td><td><small>" +
          esc(i.criado_por_nome) +
          (i.parceiro_nome ? "<br>" + esc(i.parceiro_nome) : "") +
          "</small></td><td>" +
          acoes +
          "</td></tr>";
      });
      tbody.querySelectorAll("[data-edit]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          editarTudo(Number(btn.getAttribute("data-edit")));
        });
      });
      tbody.querySelectorAll("[data-st]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          abrirStatus(
            Number(btn.getAttribute("data-st")),
            btn.getAttribute("data-cod"),
            btn.getAttribute("data-obs") || ""
          );
        });
      });
      tbody.querySelectorAll("[data-del]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          excluir(Number(btn.getAttribute("data-del")));
        });
      });
      tbody.querySelectorAll("[data-resend]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          if (!confirm("Reenviar resumo por WhatsApp e E-mail?")) return;
          var id = btn.getAttribute("data-resend");
          fetchJson(itemUrl(id) + "resend/", { method: "POST" }).then(function (body) {
            alert((body.data && body.data.mensagem) || (body.error && body.error.message) || "Processado.");
          });
        });
      });
    });
  }

  function nomeAcionadoSessao() {
    return root.dataset.acionadoPor || "";
  }

  function carregarConfig() {
    fetchJson(urls.config).then(function (body) {
      var d = body.data || {};
      document.getElementById("cfg-destinatarios").value = d.destinatarios || "";
      document.getElementById("cfg-ativo").checked = d.ativo !== false;
    });
  }

  function salvarConfig() {
    var feedback = document.getElementById("cfg-feedback");
    fetchJson(urls.config, {
      method: "POST",
      json: {
        destinatarios: document.getElementById("cfg-destinatarios").value,
        ativo: document.getElementById("cfg-ativo").checked,
      },
    }).then(function (body) {
      feedback.textContent = body._ok ? "Configuração salva." : (body.error && body.error.message) || "Erro ao salvar.";
    });
  }

  function buscarCep() {
    var cep = (document.getElementById("inp_cep").value || "").replace(/\D/g, "");
    if (cep.length !== 8) return;
    fetchJson(viacepUrl(cep)).then(function (body) {
      if (!body._ok) {
        alert((body.error && body.error.message) || "CEP não encontrado.");
        return;
      }
      var d = body.data || {};
      document.getElementById("logradouro").value = d.logradouro || "";
      document.getElementById("bairro").value = d.bairro || "";
      document.getElementById("cidade").value = d.cidade || "";
      document.getElementById("uf").value = d.uf || "";
    });
  }

  function gerarCoordenadas() {
    var logradouro = document.getElementById("logradouro").value;
    var numero = document.getElementById("inp_numero").value;
    var bairro = document.getElementById("bairro").value;
    var cidade = document.getElementById("cidade").value;
    var uf = document.getElementById("uf").value;
    var cep = (document.getElementById("inp_cep").value || "").replace(/\D/g, "");
    if (!logradouro || !numero || !cidade || !uf) {
      alert("Preencha logradouro, número, cidade e UF (ou CEP) antes de gerar coordenadas.");
      return;
    }
    var q = [logradouro, numero, bairro, cidade, uf, "Brasil"].filter(Boolean).join(", ");
    var lat = document.getElementById("inp_lat");
    var lng = document.getElementById("inp_long");
    lat.value = "Buscando...";
    lng.value = "Buscando...";
    fetchJson(urls.nominatim + "?q=" + encodeURIComponent(q)).then(function (body) {
      var data = body.data || [];
      if (data[0] && data[0].lat && data[0].lon) {
        lat.value = Number(data[0].lat).toFixed(6);
        lng.value = Number(data[0].lon).toFixed(6);
        return;
      }
      if (cep.length === 8) {
        return fetchJson(urls.nominatim + "?postalcode=" + encodeURIComponent(cep)).then(function (body2) {
          var data2 = body2.data || [];
          if (data2[0] && data2[0].lat && data2[0].lon) {
            lat.value = Number(data2[0].lat).toFixed(6);
            lng.value = Number(data2[0].lon).toFixed(6);
          } else {
            lat.value = "";
            lng.value = "";
            alert("Não foi possível obter as coordenadas.");
          }
        });
      }
      lat.value = "";
      lng.value = "";
      alert("Não foi possível obter as coordenadas.");
    });
  }

  function setPreview(id, url) {
    var el = document.getElementById(id);
    if (!el) return;
    if (url) {
      el.hidden = false;
      el.querySelector("a").href = url;
    } else {
      el.hidden = true;
    }
  }

  function rotuloPdv(p) {
    var codigo = (p.codigo_pdv || "").trim();
    var nome = (p.nome || "").trim();
    if (codigo && nome) return codigo + " — " + nome;
    return codigo || nome || ("PDV " + p.id);
  }

  function pdvSelecionado() {
    var formSel = document.getElementById("inp_pdv");
    var modalSel = document.getElementById("vtop_pdv");
    return String((formSel && formSel.value) || (modalSel && modalSel.value) || "");
  }

  function opcoesPdv(termo, selecionado) {
    var q = (termo || "").trim().toLowerCase();
    var lista = pdvsCache.filter(function (p) {
      if (!q || String(p.id) === String(selecionado || "")) return true;
      return rotuloPdv(p).toLowerCase().indexOf(q) >= 0;
    });
    if (pdvDetalhe.id && !lista.some(function (p) { return String(p.id) === pdvDetalhe.id; })) {
      var rotuloAtual = ((pdvDetalhe.codigo || "") + " " + (pdvDetalhe.nome || "")).toLowerCase();
      if (!q || rotuloAtual.indexOf(q) >= 0 || String(selecionado) === pdvDetalhe.id) {
        lista = [{
          id: pdvDetalhe.id,
          codigo_pdv: pdvDetalhe.codigo,
          nome: pdvDetalhe.nome,
        }].concat(lista);
      }
    }
    return lista;
  }

  function renderSelectPdv(sel, termo) {
    if (!sel) return;
    var atual = sel.value || "";
    sel.innerHTML = '<option value="">Selecione o PDV</option>';
    opcoesPdv(termo, atual).forEach(function (p) {
      var opt = document.createElement("option");
      opt.value = String(p.id);
      opt.textContent = rotuloPdv(p);
      sel.appendChild(opt);
    });
    if (atual && Array.prototype.some.call(sel.options, function (o) { return o.value === String(atual); })) {
      sel.value = String(atual);
    }
  }

  function atualizarHintPdv() {
    var hint = document.getElementById("inp_pdv_hint");
    var sel = document.getElementById("inp_pdv");
    if (!hint || !sel) return;
    var opt = sel.options[sel.selectedIndex];
    if (sel.value && opt) hint.textContent = "Código SAP do Cadastro: " + opt.textContent;
    else hint.textContent = "Este código vai para o Cadastro do SmartRiser. Sem PDV vinculado o preenchimento não inicia.";
  }

  function sincronizarPdvModal() {
    var modalSel = document.getElementById("vtop_pdv");
    if (!modalSel) return;
    var formSel = document.getElementById("inp_pdv");
    var valor = (formSel && formSel.value) || "";
    var busca = document.getElementById("vtop_pdv_busca");
    renderSelectPdv(modalSel, busca ? busca.value : "");
    if (valor && Array.prototype.some.call(modalSel.options, function (o) { return o.value === valor; })) {
      modalSel.value = valor;
    }
  }

  function aplicarPdvSelecionado(id) {
    var valor = id ? String(id) : "";
    var formSel = document.getElementById("inp_pdv");
    if (formSel) {
      var busca = document.getElementById("inp_pdv_busca");
      renderSelectPdv(formSel, busca ? busca.value : "");
      if (valor && Array.prototype.some.call(formSel.options, function (o) { return o.value === valor; })) {
        formSel.value = valor;
      } else {
        formSel.value = "";
      }
    }
    sincronizarPdvModal();
    atualizarHintPdv();
  }

  function carregarPdvs() {
    if (!urls.pdvs || !document.getElementById("inp_pdv")) return;
    fetchJson(urls.pdvs).then(function (body) {
      if (!body._ok || !Array.isArray(body.data)) return;
      pdvsCache = body.data;
      aplicarPdvSelecionado(pdvDetalhe.id || pdvSelecionado());
    });
  }

  function cancelarEdicao() {
    document.getElementById("form-vertical").reset();
    document.getElementById("edit_mode_id").value = "";
    document.getElementById("tab-nova-label").textContent = "Nova solicitação";
    document.getElementById("btn-submit").textContent = "Enviar solicitação";
    document.getElementById("btn-cancelar-edicao").hidden = true;
    document.getElementById("inp_acionado_por").value = nomeAcionadoSessao();
    document.getElementById("input-arquivo-carta").required = true;
    document.getElementById("input-arquivo-fachada").required = true;
    setPreview("preview-carta", "");
    setPreview("preview-fachada", "");
    document.getElementById("resumoEnvio").hidden = true;
    document.getElementById("inp_observacao_form").value = "";
    pdvDetalhe = { id: "", codigo: "", nome: "" };
    var buscaPdv = document.getElementById("inp_pdv_busca");
    if (buscaPdv) buscaPdv.value = "";
    renderSelectPdv(document.getElementById("inp_pdv"), "");
    aplicarPdvSelecionado("");
    blocos = [];
    atualizarTabelaBlocos();
    vtopOcultarControles();
  }

  function editarTudo(id) {
    fetchJson(itemUrl(id)).then(function (body) {
      if (!body._ok) {
        alert((body.error && body.error.message) || "Não foi possível abrir a solicitação.");
        return;
      }
      var d = body.data || {};
      document.getElementById("edit_mode_id").value = d.id;
      document.getElementById("inp_acionado_por").value = d.criado_por_nome || nomeAcionadoSessao();
      document.getElementById("inp_nome").value = d.nome_condominio || "";
      document.getElementById("inp_sindico").value = d.nome_sindico || "";
      document.getElementById("inp_contato").value = d.contato || "";
      document.getElementById("inp_cep").value = d.cep || "";
      document.getElementById("logradouro").value = d.logradouro || "";
      document.getElementById("inp_numero").value = d.numero || "";
      document.getElementById("bairro").value = d.bairro || "";
      document.getElementById("cidade").value = d.cidade || "";
      document.getElementById("uf").value = d.uf || "";
      document.getElementById("inp_lat").value = d.latitude || "";
      document.getElementById("inp_long").value = d.longitude || "";
      document.getElementById("inp_infra").value = d.infraestrutura || "SUBTERRANEA";
      document.getElementById("inp_shaft").checked = !!d.possui_shaft;
      document.getElementById("input-arquivo-carta").required = false;
      document.getElementById("input-arquivo-fachada").required = false;
      setPreview("preview-carta", d.link_carta_sindico);
      setPreview("preview-fachada", d.link_fotos_fachada);
      document.getElementById("inp_observacao_form").value = d.observacao_form || d.observacao || "";
      pdvDetalhe = {
        id: d.parceiro_id ? String(d.parceiro_id) : "",
        codigo: d.parceiro_codigo || "",
        nome: d.parceiro_nome || "",
      };
      var buscaPdvEdit = document.getElementById("inp_pdv_busca");
      if (buscaPdvEdit) buscaPdvEdit.value = "";
      renderSelectPdv(document.getElementById("inp_pdv"), "");
      aplicarPdvSelecionado(pdvDetalhe.id);
      blocos = d.blocos || [];
      atualizarTabelaBlocos();
      document.getElementById("tab-nova-label").textContent = "Editar solicitação";
      document.getElementById("btn-submit").textContent = "Salvar alterações";
      document.getElementById("btn-cancelar-edicao").hidden = false;
      vtopMostrarControles();
      showPanel("nova");
    });
  }

  // --- SmartRiser / V.top ---
  var vtopModal = document.getElementById("vertical-modal-vtop");
  var vtopPollTimer = null;
  var vtopBlocosQueue = null;
  var VTOP_ATIVOS = [
    "starting", "awaiting_credentials", "awaiting_qr", "clicking_login", "logged_in", "navigating",
    "filling_obra", "filling_coords", "filling_cadastro", "uploading", "saving", "validating",
  ];

  function vtopUrl(id, acao) {
    var base = vtopModal ? vtopModal.dataset.vtopBaseUrl : "";
    return String(base).replace(/\/0\/vtop\/iniciar\/$/, "/" + id + "/vtop/" + acao + "/");
  }

  function vtopIdAtual() {
    return document.getElementById("edit_mode_id").value;
  }

  function vtopEl(id) {
    return document.getElementById(id);
  }

  function vtopMostrarControles() {
    if (!vtopModal) return;
    vtopEl("btn-vtop-smartriser").hidden = false;
    fetchJson(vtopUrl(vtopIdAtual(), "status")).then(function (body) {
      if (body.state && body.state.status && body.state.status !== "idle") {
        vtopAtualizarUiStatus(body.state);
        if (VTOP_ATIVOS.indexOf(body.state.status) >= 0) vtopIniciarPolling(vtopIdAtual());
      }
    });
  }

  function vtopOcultarControles() {
    if (!vtopModal) return;
    ["btn-vtop-smartriser", "btn-vtop-senha-pronta", "btn-vtop-fechar", "vtop-status-badge"].forEach(function (id) {
      vtopEl(id).hidden = true;
    });
    if (vtopPollTimer) {
      clearInterval(vtopPollTimer);
      vtopPollTimer = null;
    }
  }

  function vtopAlerta(msg, tipo) {
    var alerta = vtopEl("vtop-modal-alerta");
    if (!alerta) return;
    alerta.className = "vtop-alerta" + (tipo ? " is-" + tipo : "");
    alerta.textContent = msg || "";
    alerta.hidden = !msg;
  }

  function vtopAtualizarUiStatus(state) {
    var badge = vtopEl("vtop-status-badge");
    var btnSenha = vtopEl("btn-vtop-senha-pronta");
    var btnFechar = vtopEl("btn-vtop-fechar");
    var btnStart = vtopEl("btn-vtop-smartriser");
    if (!badge) return;

    if (!state) {
      badge.hidden = true;
      btnSenha.hidden = true;
      btnFechar.hidden = true;
      vtopAtualizarModalQr(null);
      return;
    }

    var st = state.status || "";
    var msg = state.message || st;
    vtopAtualizarModalQr(state);
    var cls = "vtop-st-idle";
    if (st === "awaiting_credentials" || st === "awaiting_qr") cls = "vtop-st-aguardando";
    else if (st === "done") cls = "vtop-st-done";
    else if (st === "error") cls = "vtop-st-error";
    else if (st === "paused") cls = "vtop-st-paused";
    else if (st && st !== "idle") cls = "vtop-st-ativo";
    badge.className = "pill vtop-badge " + cls;
    badge.textContent = msg.length > 80 ? msg.slice(0, 80) + "…" : msg;
    badge.title = msg;
    badge.hidden = false;

    // Produção: headless não aceita digitar na tela → reabre o modal pedindo credenciais
    if (state.needs_vtop_login || state.error === "needs_vtop_login") {
      vtopAbrirModalCredenciais(msg || "Informe usuário e senha V.tal para continuar.");
    }

    btnSenha.hidden = st !== "awaiting_credentials";
    btnSenha.classList.toggle("btn-pulse", st === "awaiting_credentials");
    if (st && st !== "idle") btnFechar.hidden = false;

    var ativo = VTOP_ATIVOS.indexOf(st) >= 0;
    btnStart.disabled = ativo;
    vtopEl("btn-vtop-modal-iniciar").disabled = ativo;

    if (["done", "error", "idle"].indexOf(st) < 0) return;
    if (vtopPollTimer) {
      clearInterval(vtopPollTimer);
      vtopPollTimer = null;
    }
    if (st === "done" && vtopBlocosQueue && vtopBlocosQueue.length > 0) {
      var concluido = vtopBlocosQueue.shift();
      if (vtopBlocosQueue.length > 0) {
        badge.textContent = "Concluído " + concluido + ". Iniciando " + vtopBlocosQueue[0] + " em 3s…";
        badge.className = "pill vtop-badge vtop-st-done";
        setTimeout(function () {
          if (vtopBlocosQueue && vtopBlocosQueue.length > 0) {
            vtopEl("vtop_bloco").value = "TODOS";
            vtopIniciarSmartRiser(!!(vtopEl("vtop_usuario").value || vtopEl("vtop_senha").value));
          }
        }, 3000);
      } else {
        vtopBlocosQueue = null;
        badge.textContent = "TODOS OS BLOCOS CONCLUÍDOS!";
        badge.className = "pill vtop-badge vtop-st-done";
        vtopAlerta("Todos os blocos foram processados com sucesso.", "ok");
      }
    } else if (st === "error" && vtopBlocosQueue && !state.needs_vtop_login) {
      vtopBlocosQueue = null;
      vtopAlerta("Erro na execução sequencial. Parado. Mensagem: " + msg, "erro");
    }
  }

  function vtopAtualizarModalQr(state) {
    var el = vtopEl("vertical-modal-vtop-qr");
    if (!el) return;
    var img = vtopEl("vtop-qr-img");
    var carregando = vtopEl("vtop-qr-carregando");
    if (!state || state.status !== "awaiting_qr") {
      el.hidden = true;
      img.removeAttribute("src");
      img.hidden = true;
      carregando.hidden = false;
      return;
    }
    var qr = state.qr_image || "";
    if (qr.indexOf("data:image/") === 0) {
      if (img.getAttribute("src") !== qr) img.setAttribute("src", qr);
      img.hidden = false;
      carregando.hidden = true;
    } else {
      img.hidden = true;
      carregando.hidden = false;
    }
    vtopEl("vtop-qr-mensagem").textContent = state.message || "";
    el.hidden = false;
  }

  function vtopIniciarPolling(id) {
    if (vtopPollTimer) clearInterval(vtopPollTimer);
    vtopPollTimer = setInterval(function () {
      fetchJson(vtopUrl(id, "status"))
        .then(function (body) {
          if (body.state) vtopAtualizarUiStatus(body.state);
        })
        .catch(function (e) {
          console.warn("[VTOP] poll falhou", e);
        });
    }, 2000);
  }

  function vtopPopularSelectBlocos() {
    var sel = vtopEl("vtop_bloco");
    var prev = sel.value;
    sel.innerHTML =
      '<option value="">— só testar login (sessão) —</option>' +
      '<option value="TODOS">— TODOS OS BLOCOS (em sequência) —</option>';
    blocos.forEach(function (b) {
      var nome = String(b.nome || "").trim();
      if (!nome) return;
      var opt = document.createElement("option");
      opt.value = nome;
      opt.textContent = nome + (b.vtop_obra_id ? " (obra " + b.vtop_obra_id + ")" : "");
      sel.appendChild(opt);
    });
    if (prev && Array.prototype.some.call(sel.options, function (o) { return o.value === prev; })) {
      sel.value = prev;
    }
  }

  function vtopAbrirModalCredenciais(alertaMsg) {
    if (!vtopIdAtual()) {
      alert("Abra uma solicitação em modo edição antes de preencher o SmartRiser.");
      return;
    }
    vtopPopularSelectBlocos();
    renderSelectPdv(vtopEl("vtop_pdv"), (vtopEl("vtop_pdv_busca") || {}).value || "");
    sincronizarPdvModal();
    vtopAlerta(alertaMsg || "", "");
    vtopEl("vtop_usuario").value = "";
    vtopEl("vtop_senha").value = "";
    vtopModal.hidden = false;
    if (vtopEl("vtop-login-senha").open) {
      setTimeout(function () { vtopEl("vtop_usuario").focus(); }, 100);
    }
  }

  function vtopIniciarSmartRiser(usarCredenciais) {
    var id = vtopIdAtual();
    if (!id) {
      alert("Abra uma solicitação em modo edição antes de preencher o SmartRiser.");
      return;
    }
    // Navegador pode autopreencher os campos mesmo com a seção fechada: só envia se aberta
    var loginSenhaAberto = usarCredenciais === true || vtopEl("vtop-login-senha").open;
    var usuario = loginSenhaAberto ? (vtopEl("vtop_usuario").value || "").trim() : "";
    var senha = loginSenhaAberto ? vtopEl("vtop_senha").value || "" : "";
    var blocoOriginal = (vtopEl("vtop_bloco").value || "").trim();

    var bloco = blocoOriginal;
    if (blocoOriginal === "TODOS") {
      if (!vtopBlocosQueue || vtopBlocosQueue.length === 0) {
        vtopBlocosQueue = blocos
          .map(function (b) { return String(b.nome || "").trim(); })
          .filter(Boolean);
      }
      if (vtopBlocosQueue.length === 0) {
        alert("Nenhum bloco cadastrado para executar.");
        return;
      }
      bloco = vtopBlocosQueue[0];
      vtopAlerta("Em sequência (" + vtopBlocosQueue.length + " restante(s)). Bloco atual: " + bloco, "info");
    } else {
      vtopBlocosQueue = null;
    }

    var payload = {};
    var pdvId = pdvSelecionado();
    if (bloco && document.getElementById("inp_pdv") && !pdvId) {
      vtopAlerta(
        "Acionamento sem PDV vinculado: não há código SAP para o Cadastro do SmartRiser.",
        "erro"
      );
      var campoPdv = vtopEl("vtop_pdv");
      if (campoPdv) campoPdv.focus();
      return;
    }
    if (usuario) payload.vtop_usuario = usuario;
    if (senha) payload.vtop_senha = senha;
    if (pdvId) payload.parceiro_id = pdvId;
    if (bloco) payload.bloco = bloco;
    else payload.somente_ate = "login";

    var btn = vtopEl("btn-vtop-smartriser");
    var btnModal = vtopEl("btn-vtop-modal-iniciar");
    btn.disabled = true;
    btnModal.disabled = true;
    btnModal.textContent = "Iniciando…";

    fetchJson(vtopUrl(id, "iniciar"), { method: "POST", json: payload })
      .then(function (body) {
        vtopEl("vtop_senha").value = "";
        if (body.state) vtopAtualizarUiStatus(body.state);
        if (body.state && (body.state.needs_vtop_login || body.state.error === "needs_vtop_login")) {
          vtopAlerta(body.state.message || "Informe usuário e senha V.tal.", "");
          btn.disabled = false;
          return;
        }
        if (!body._ok) {
          var msgErro = body.error || (body.state && body.state.message) || "Não foi possível iniciar a automação.";
          var faltaPdv = body.faltando && body.faltando.indexOf("codigo_sap") >= 0;
          if (faltaPdv) {
            vtopAlerta(msgErro, "erro");
            var campo = vtopEl("vtop_pdv");
            if (campo) campo.focus();
          } else {
            alert(msgErro);
          }
          btn.disabled = false;
          return;
        }
        vtopModal.hidden = true;
        vtopIniciarPolling(id);
      })
      .catch(function (e) {
        console.error(e);
        alert("Erro de rede ao iniciar SmartRiser.");
        btn.disabled = false;
      })
      .finally(function () {
        btnModal.disabled = false;
        btnModal.textContent = "Iniciar SmartRiser";
      });
  }

  function vtopSenhaPronta() {
    var id = vtopIdAtual();
    if (!id) return;
    fetchJson(vtopUrl(id, "senha-pronta"), { method: "POST", json: {} }).then(function (body) {
      if (!body._ok) {
        alert(body.error || "Não foi possível confirmar a senha.");
        return;
      }
      vtopAtualizarUiStatus(body.state);
    });
  }

  function vtopFecharNavegador() {
    var id = vtopIdAtual();
    var url = id ? vtopUrl(id, "fechar") : vtopModal.dataset.vtopFecharGlobalUrl;
    return fetchJson(url, { method: "POST", json: { manter_sessao: true } }).then(function (body) {
      vtopAtualizarUiStatus(body.state || { status: "idle", message: "Navegador fechado (sessão mantida)." });
      vtopEl("btn-vtop-smartriser").disabled = false;
    });
  }

  if (vtopModal) {
    vtopEl("btn-vtop-smartriser").addEventListener("click", function () {
      vtopAbrirModalCredenciais();
    });
    vtopEl("btn-vtop-modal-iniciar").addEventListener("click", function () {
      vtopIniciarSmartRiser(false);
    });
    vtopEl("btn-vtop-modal-fechar").addEventListener("click", function () {
      vtopModal.hidden = true;
    });
    vtopEl("btn-vtop-senha-pronta").addEventListener("click", vtopSenhaPronta);
    vtopEl("btn-vtop-fechar").addEventListener("click", vtopFecharNavegador);
    vtopEl("btn-vtop-qr-cancelar").addEventListener("click", function () {
      vtopFecharNavegador().then(function () {
        vtopAtualizarModalQr(null);
      });
    });
  }

  function excluir(id) {
    if (!confirm("Excluir solicitação?")) return;
    fetchJson(itemUrl(id), { method: "DELETE" }).then(function (body) {
      if (body._ok) carregarLista();
      else alert((body.error && body.error.message) || "Não foi possível excluir.");
    });
  }

  function abrirStatus(id, cod, obs) {
    document.getElementById("st-id").value = id;
    document.getElementById("st-val").value = cod || "SEM_TRATAMENTO";
    document.getElementById("st-obs").value = obs || "";
    document.getElementById("vertical-modal-status").hidden = false;
  }

  function salvarStatus() {
    var id = document.getElementById("st-id").value;
    fetchJson(itemUrl(id), {
      method: "PATCH",
      json: {
        status: document.getElementById("st-val").value,
        observacao: document.getElementById("st-obs").value,
      },
    }).then(function (body) {
      if (!body._ok) {
        alert((body.error && body.error.message) || "Não foi possível atualizar o status.");
        return;
      }
      document.getElementById("vertical-modal-status").hidden = true;
      carregarLista();
    });
  }

  function enviarFormulario() {
    var form = document.getElementById("form-vertical");
    var isEdit = !!document.getElementById("edit_mode_id").value;
    if (!isEdit) {
      document.getElementById("input-arquivo-carta").required = true;
      document.getElementById("input-arquivo-fachada").required = true;
    }
    if (blocos.length === 0) {
      alert("É obrigatório incluir pelo menos uma Estrutura de blocos antes de enviar.");
      return;
    }
    var blocoInvalido = blocos.filter(function (b) { return !b.nome || b.andares <= 0; })[0];
    if (blocoInvalido) {
      alert("Cada bloco precisa de nome e pelo menos 1 andar.");
      return;
    }
    if (!form.checkValidity()) {
      form.reportValidity();
      return;
    }
    var id = document.getElementById("edit_mode_id").value;
    var fd = new FormData(form);
    fd.set("possui_shaft", document.getElementById("inp_shaft").checked ? "on" : "");
    var btn = document.getElementById("btn-submit");
    var original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Enviando…";
    var url = isEdit ? itemUrl(id) : urls.list;
    var method = isEdit ? "PATCH" : "POST";
    fetchJson(url, { method: method, body: fd }).then(function (body) {
      var fb = document.getElementById("form-feedback");
      if (body._ok) {
        var resumo = (body.data && body.data.resumo) || "";
        if (resumo) {
          document.getElementById("resumoEnvioTexto").textContent = resumo;
          document.getElementById("resumoEnvio").hidden = false;
        }
        fb.textContent = (body.data && body.data.mensagem) || "Salvo.";
        cancelarEdicao();
        if (isEdit) {
          showPanel("lista");
        } else {
          showPanel("dashboard");
        }
      } else {
        fb.textContent = (body.error && body.error.message) || "Erro ao salvar.";
      }
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = original;
    });
  }

  root.querySelectorAll(".tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      showPanel(btn.getAttribute("data-tab"));
    });
  });
  document.getElementById("btn-dash-refresh").addEventListener("click", carregarDashboard);
  document.getElementById("btn-lista-refresh").addEventListener("click", carregarLista);
  document.getElementById("btn-add-bloco").addEventListener("click", addBloco);
  document.getElementById("btn-coords").addEventListener("click", gerarCoordenadas);
  document.getElementById("btn-submit").addEventListener("click", enviarFormulario);
  document.getElementById("btn-cancelar-edicao").addEventListener("click", cancelarEdicao);
  document.getElementById("inp_cep").addEventListener("blur", buscarCep);
  var inpPdv = document.getElementById("inp_pdv");
  if (inpPdv) {
    inpPdv.addEventListener("change", function () {
      var opt = inpPdv.options[inpPdv.selectedIndex];
      var texto = opt ? opt.textContent : "";
      var partes = texto.split(" — ");
      pdvDetalhe = {
        id: inpPdv.value,
        codigo: (partes[0] || "").trim(),
        nome: partes.slice(1).join(" — ").trim(),
      };
      sincronizarPdvModal();
      atualizarHintPdv();
    });
  }
  var buscaPdv = document.getElementById("inp_pdv_busca");
  if (buscaPdv) {
    buscaPdv.addEventListener("input", function () {
      renderSelectPdv(inpPdv, buscaPdv.value);
      atualizarHintPdv();
    });
  }
  var vtopPdv = document.getElementById("vtop_pdv");
  if (vtopPdv) {
    vtopPdv.addEventListener("change", function () {
      if (inpPdv && inpPdv.value !== vtopPdv.value) {
        inpPdv.value = vtopPdv.value;
        inpPdv.dispatchEvent(new Event("change"));
      }
    });
  }
  var vtopBuscaPdv = document.getElementById("vtop_pdv_busca");
  if (vtopBuscaPdv) {
    vtopBuscaPdv.addEventListener("input", function () {
      renderSelectPdv(vtopPdv, vtopBuscaPdv.value);
    });
  }
  carregarPdvs();
  var btnCfg = document.getElementById("btn-cfg-salvar");
  if (btnCfg) btnCfg.addEventListener("click", salvarConfig);
  document.getElementById("btn-st-salvar").addEventListener("click", salvarStatus);
  document.getElementById("btn-st-fechar").addEventListener("click", function () {
    document.getElementById("vertical-modal-status").hidden = true;
  });

  atualizarTabelaBlocos();
  carregarDashboard();
})();
