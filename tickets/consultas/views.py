from __future__ import annotations

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from .dfv_powerbi_service import (
    CDOE_UFS,
    COBERTURA_DFV_TXT,
    DfvPowerBiDisabled,
    DfvPowerBiError,
    consultar_fachadas_por_cep,
    consultar_fachadas_por_cdo,
    filtrar_grupos_por_cidade,
    formatar_numeros_rua_cdoe,
    formatar_resposta_dfv_powerbi,
    formatar_resumo_cdoe,
    limpar_cep,
    limpar_codigo_cdo,
    limpar_uf,
    listar_cidades_cdoe,
    montar_grupos_rua_cdoe,
    resolver_cidade_escolhida,
)
from .helpers import wpp_para_html
from .vtal_service import (
    consultar_viabilidade,
    contexto_portal_vtal,
    fontes_vtal_ativas,
    normalizar_cep,
    normalizar_fachada,
    vtal_disponivel,
)


def _dfv_habilitado() -> bool:
    return bool(getattr(settings, "DFV_POWERBI_ENABLED", True))


@login_required
@require_GET
def consultas_hub(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "tickets/consultas/hub.html",
        {
            "dfv_enabled": _dfv_habilitado(),
            "cobertura": COBERTURA_DFV_TXT,
        },
    )


@require_http_methods(["GET", "POST"])
def consulta_dfv(request: HttpRequest) -> HttpResponse:
    ctx: dict = {
        "dfv_enabled": _dfv_habilitado(),
        "cobertura": COBERTURA_DFV_TXT,
        "cep": "",
        "erro": "",
        "mensagens_wpp": [],
        "mensagens_html": [],
        "registros": [],
    }

    if request.method == "POST":
        cep = (request.POST.get("cep") or "").strip()
        ctx["cep"] = cep
        if not _dfv_habilitado():
            ctx["erro"] = "Consulta DFV temporariamente indisponível."
        else:
            try:
                registros = consultar_fachadas_por_cep(cep)
                ctx["registros"] = registros
                partes = formatar_resposta_dfv_powerbi(cep, registros)
                ctx["mensagens_wpp"] = partes
                ctx["mensagens_html"] = [wpp_para_html(p) for p in partes]
            except DfvPowerBiDisabled:
                ctx["erro"] = "Consulta DFV (Power BI) está desligada no servidor."
            except DfvPowerBiError as exc:
                ctx["erro"] = str(exc)
            except Exception:
                ctx["erro"] = "Falha ao consultar o Power BI. Tente novamente."

    return render(request, "tickets/consultas/dfv.html", ctx)


@require_http_methods(["GET", "POST"])
def consulta_cdoe(request: HttpRequest) -> HttpResponse:
    """
    Fluxo web equivalente ao bot WhatsApp:
    código → UF → cidade (se houver) → rua → números.
    """
    ctx: dict = {
        "dfv_enabled": _dfv_habilitado(),
        "cobertura": COBERTURA_DFV_TXT,
        "cdoe_ufs": CDOE_UFS,
        "passo": "codigo",
        "codigo": "",
        "uf": "",
        "cidade": "",
        "rua_idx": "",
        "erro": "",
        "cidades": [],
        "grupos": [],
        "grupo_selecionado": None,
        "mensagens_wpp": [],
        "mensagens_html": [],
    }

    if request.method == "GET" and request.GET.get("reset"):
        return redirect("consulta_cdoe")

    codigo = limpar_codigo_cdo(
        (request.POST.get("codigo") or request.GET.get("codigo") or "").strip()
    )
    uf = limpar_uf((request.POST.get("uf") or request.GET.get("uf") or "").strip())
    cidade = (request.POST.get("cidade") or request.GET.get("cidade") or "").strip()
    rua_idx_raw = (request.POST.get("rua_idx") or request.GET.get("rua_idx") or "").strip()

    ctx["codigo"] = codigo
    ctx["uf"] = uf
    ctx["cidade"] = cidade
    ctx["rua_idx"] = rua_idx_raw

    if not _dfv_habilitado():
        ctx["erro"] = "Consulta CDOE temporariamente indisponível."
        return render(request, "tickets/consultas/cdoe.html", ctx)

    if request.method == "POST" or request.GET.get("codigo"):
        if not codigo:
            ctx["erro"] = "Informe o código CDOE (ex.: 28005 ou CDOE-28005)."
            return render(request, "tickets/consultas/cdoe.html", ctx)

        if not uf:
            ctx["passo"] = "uf"
            return render(request, "tickets/consultas/cdoe.html", ctx)

        try:
            registros, codigo_encontrado = consultar_fachadas_por_cdo(codigo, uf=uf)
            ctx["codigo"] = codigo_encontrado or codigo
            grupos = montar_grupos_rua_cdoe(registros)
            ctx["grupos"] = grupos

            if not grupos:
                partes = formatar_resumo_cdoe(ctx["codigo"], [])
                ctx["passo"] = "resultado"
                ctx["mensagens_wpp"] = partes
                ctx["mensagens_html"] = [wpp_para_html(p) for p in partes]
                return render(request, "tickets/consultas/cdoe.html", ctx)

            cidades = listar_cidades_cdoe(grupos)
            ctx["cidades"] = cidades

            if len(cidades) > 1 and not cidade:
                ctx["passo"] = "cidade"
                return render(request, "tickets/consultas/cdoe.html", ctx)

            cidade_resolvida = cidade
            if len(cidades) > 1:
                cidade_resolvida = resolver_cidade_escolhida(cidade, cidades) or ""
                if not cidade_resolvida:
                    ctx["passo"] = "cidade"
                    ctx["erro"] = "Escolha uma cidade válida da lista."
                    return render(request, "tickets/consultas/cdoe.html", ctx)
            elif len(cidades) == 1:
                cidade_resolvida = cidades[0]

            ctx["cidade"] = cidade_resolvida
            grupos_cidade = filtrar_grupos_por_cidade(grupos, cidade_resolvida)
            ctx["grupos"] = grupos_cidade

            if not rua_idx_raw:
                if len(grupos_cidade) == 1:
                    rua_idx_raw = "1"
                    ctx["rua_idx"] = "1"
                else:
                    ctx["passo"] = "rua"
                    return render(request, "tickets/consultas/cdoe.html", ctx)

            try:
                rua_idx = int(rua_idx_raw)
            except ValueError:
                ctx["passo"] = "rua"
                ctx["erro"] = "Escolha uma rua válida da lista."
                return render(request, "tickets/consultas/cdoe.html", ctx)

            if rua_idx < 1 or rua_idx > len(grupos_cidade):
                ctx["passo"] = "rua"
                ctx["erro"] = "Número de rua inválido."
                return render(request, "tickets/consultas/cdoe.html", ctx)

            grupo = grupos_cidade[rua_idx - 1]
            ctx["grupo_selecionado"] = grupo
            ctx["passo"] = "resultado"
            partes = formatar_numeros_rua_cdoe(ctx["codigo"], grupo)
            ctx["mensagens_wpp"] = partes
            ctx["mensagens_html"] = [wpp_para_html(p) for p in partes]

        except DfvPowerBiDisabled:
            ctx["erro"] = "Consulta CDOE (Power BI) está desligada no servidor."
        except DfvPowerBiError as exc:
            ctx["erro"] = str(exc)
        except Exception:
            ctx["erro"] = "Falha ao consultar o Power BI. Tente novamente."

    return render(request, "tickets/consultas/cdoe.html", ctx)


@require_http_methods(["GET"])
def consulta_viabilidade(request: HttpRequest) -> HttpResponse:
    """Consulta read-only à base VTAL (forms) por CEP + fachada."""
    fontes = fontes_vtal_ativas()
    vtal_ok = vtal_disponivel()
    cep = (request.GET.get("cep") or "").strip()
    numero_fachada = (request.GET.get("numero_fachada") or "").strip()
    fonte_codigo = (request.GET.get("fonte") or "").strip()
    fonte = None
    resultados = []
    erro = ""
    buscou = bool(cep or numero_fachada)

    if fontes:
        if fonte_codigo:
            fonte = next((f for f in fontes if f.codigo == fonte_codigo), None)
        if not fonte:
            fonte = fontes[0]

    if buscou:
        if not vtal_ok or not fonte:
            erro = "Consulta VTAL indisponível neste ambiente."
        elif not normalizar_cep(cep) and not normalizar_fachada(numero_fachada):
            erro = "Informe CEP e/ou número da fachada."
        else:
            try:
                resultados = consultar_viabilidade(
                    fonte=fonte,
                    cep=cep,
                    numero_fachada=numero_fachada,
                )
            except Exception:
                erro = "Falha ao consultar a base VTAL."

    ctx = {
        "vtal_ok": vtal_ok,
        "fontes": fontes,
        "fonte": fonte,
        "cep": cep,
        "numero_fachada": numero_fachada,
        "resultados": resultados,
        "erro": erro,
        "buscou": buscou,
    }
    ctx.update(contexto_portal_vtal())
    return render(request, "tickets/consultas/viabilidade.html", ctx)
