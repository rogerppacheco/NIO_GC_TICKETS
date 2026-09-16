from .acesso import (
    eh_admin,
    eh_gerencia,
    eh_gestor,
    eh_parceiro,
    escopo_gestao,
    parceiro_de,
    tem_acesso_interno,
    tickets_da_fila,
    tickets_visiveis,
)
from .models import ContatoParceiro, StatusTicket


def nav_counts(request):
    ctx = {
        "eh_gestor": False,
        "eh_admin": False,
        "eh_gerencia": False,
        "eh_parceiro": False,
        "tem_acesso_interno": False,
    }
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        visiveis = (
            tickets_da_fila(user) if tem_acesso_interno(user) else tickets_visiveis(user)
        )
        ctx["eh_gestor"] = eh_gestor(user)
        ctx["eh_admin"] = eh_admin(user)
        ctx["eh_gerencia"] = eh_gerencia(user)
        ctx["eh_parceiro"] = eh_parceiro(user)
        ctx["tem_acesso_interno"] = tem_acesso_interno(user)
        nome = (user.first_name or "").strip() or (user.get_full_name() or "").strip()
        ctx["nav_primeiro_nome"] = nome.split()[0] if nome else user.get_username()
        ctx["nav_novos"] = visiveis.filter(status=StatusTicket.NOVO).count()
        ctx["nav_abertos"] = visiveis.exclude(
            status__in=[
                StatusTicket.RESOLVIDO,
                StatusTicket.FECHADO,
                StatusTicket.CANCELADO,
            ]
        ).count()

        pdv = parceiro_de(user)
        if pdv:
            ctx["portal_parceiro"] = pdv
            contato_id = request.session.get("contato_id")
            if contato_id:
                contato = (
                    ContatoParceiro.objects.select_related("parceiro")
                    .filter(pk=contato_id, parceiro=pdv, ativo=True)
                    .first()
                )
                if contato:
                    ctx["portal_contato"] = contato

    ctx["gestao_escopo"] = escopo_gestao(request)
    ctx["modo_teste"] = False
    ctx["modo_teste_sessao"] = False
    user = getattr(request, "user", None)
    if user and user.is_authenticated and tem_acesso_interno(user):
        from .acesso import (
            GERENCIA_TODAS,
            gerencia_seletor_valor,
            listar_gerencias,
            parceiros_gestao,
        )

        ctx["gestao_qtd_meus"] = parceiros_gestao(user, "meus").count()
        ctx["gestao_qtd_outros"] = parceiros_gestao(user, "outros").count()
        ctx["gestao_qtd_todos"] = parceiros_gestao(user, "todos").count()
        if eh_gestor(user):
            ctx["gestao_gerencias"] = listar_gerencias()
            ctx["gestao_gerencia_sel"] = gerencia_seletor_valor(request)
            ctx["gestao_gerencia_todas"] = GERENCIA_TODAS

        from gestao.messaging.syncwa import modo_teste_ativo, modo_teste_sessao

        ctx["modo_teste"] = modo_teste_ativo()
        ctx["modo_teste_sessao"] = modo_teste_sessao(request)

    try:
        from tickets.consultas.vtal_service import contexto_portal_vtal

        ctx.update(contexto_portal_vtal())
    except Exception:
        ctx.setdefault("vtal_forms_url", "")
        ctx.setdefault("vtal_ultima_importacao", None)
    return ctx
