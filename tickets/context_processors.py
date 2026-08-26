from .acesso import eh_gestor, tem_acesso_interno, tickets_visiveis
from .models import ContatoParceiro, Parceiro, StatusTicket


def nav_counts(request):
    ctx = {"eh_gestor": False, "tem_acesso_interno": False}
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        visiveis = tickets_visiveis(user)
        ctx["eh_gestor"] = eh_gestor(user)
        ctx["tem_acesso_interno"] = tem_acesso_interno(user)
        ctx["nav_novos"] = visiveis.filter(status=StatusTicket.NOVO).count()
        ctx["nav_abertos"] = visiveis.exclude(
            status__in=[
                StatusTicket.RESOLVIDO,
                StatusTicket.FECHADO,
                StatusTicket.CANCELADO,
            ]
        ).count()

    # Portal do parceiro (PDV + contato na sessão)
    parceiro_id = request.session.get("parceiro_id")
    contato_id = request.session.get("contato_id")
    if parceiro_id and contato_id:
        contato = (
            ContatoParceiro.objects.select_related("parceiro")
            .filter(pk=contato_id, parceiro_id=parceiro_id, ativo=True)
            .first()
        )
        if contato and contato.parceiro.ativo:
            ctx["portal_contato"] = contato
            ctx["portal_parceiro"] = contato.parceiro
    elif parceiro_id:
        parceiro = Parceiro.objects.filter(pk=parceiro_id, ativo=True).first()
        if parceiro:
            ctx["portal_parceiro"] = parceiro

    return ctx
