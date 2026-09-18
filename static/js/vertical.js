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
  };
  var canConfig = root.dataset.canConfig === "1";
  var blocos = [];

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

  function atualizarTabelaBlocos() {
    var tbody = document.getElementById("lista-blocos");
    tbody.innerHTML = "";
    var total = 0;
    blocos.forEach(function (b, i) {
      total += b.total;
      tbody.innerHTML +=
        "<tr><td>" +
        esc(b.nome) +
        "</td><td>" +
        b.andares +
        "</td><td>" +
        b.aptos +
        "</td><td>" +
        b.total +
        '</td><td><button type="button" class="btn btn-secondary" data-rm="' +
        i +
        '">Remover</button></td></tr>';
    });
    var prevenda = Math.ceil(total * 0.1);
    document.getElementById("total-hps-geral").textContent = total;
    document.getElementById("prevenda-calc").textContent = prevenda;
    document.getElementById("input_total_hps").value = total;
    document.getElementById("input_prevenda").value = prevenda;
    document.getElementById("input_blocos_json").value = JSON.stringify(blocos);
    tbody.querySelectorAll("[data-rm]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        blocos.splice(Number(btn.getAttribute("data-rm")), 1);
        atualizarTabelaBlocos();
      });
    });
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
      document.getElementById("cidade_uf").value = (d.cidade || "") + (d.uf ? "/" + d.uf : "");
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
    blocos = [];
    atualizarTabelaBlocos();
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
      document.getElementById("cidade_uf").value = (d.cidade || "") + (d.uf ? "/" + d.uf : "");
      document.getElementById("inp_lat").value = d.latitude || "";
      document.getElementById("inp_long").value = d.longitude || "";
      document.getElementById("inp_infra").value = d.infraestrutura || "SUBTERRANEA";
      document.getElementById("inp_shaft").checked = !!d.possui_shaft;
      document.getElementById("input-arquivo-carta").required = false;
      document.getElementById("input-arquivo-fachada").required = false;
      setPreview("preview-carta", d.link_carta_sindico);
      setPreview("preview-fachada", d.link_fotos_fachada);
      blocos = d.blocos || [];
      atualizarTabelaBlocos();
      document.getElementById("tab-nova-label").textContent = "Editar solicitação";
      document.getElementById("btn-submit").textContent = "Salvar alterações";
      document.getElementById("btn-cancelar-edicao").hidden = false;
      showPanel("nova");
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
  var btnCfg = document.getElementById("btn-cfg-salvar");
  if (btnCfg) btnCfg.addEventListener("click", salvarConfig);
  document.getElementById("btn-st-salvar").addEventListener("click", salvarStatus);
  document.getElementById("btn-st-fechar").addEventListener("click", function () {
    document.getElementById("vertical-modal-status").hidden = true;
  });

  atualizarTabelaBlocos();
  carregarDashboard();
})();
