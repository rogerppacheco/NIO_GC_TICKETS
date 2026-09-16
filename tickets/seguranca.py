from __future__ import annotations

import secrets
import string
import time
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.utils import timezone

from .models import ContaAcesso, RegistroAcesso

if TYPE_CHECKING:
    from django.http import HttpRequest

FALHAS_LIMITE = 5
FALHAS_JANELA = 15 * 60
IDLE_SEGUNDOS = 30 * 60
SENHA_TAMANHO = 12
_ALFABETO = string.ascii_letters + string.digits


def ip_de(request: HttpRequest | None) -> str | None:
    if request is None:
        return None
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    return forwarded or request.META.get("REMOTE_ADDR") or None


def conta_de(user) -> ContaAcesso | None:
    if not user or not getattr(user, "is_authenticated", False):
        return None
    conta, _ = ContaAcesso.objects.get_or_create(user=user)
    return conta


def deve_trocar_senha(user) -> bool:
    conta = conta_de(user)
    return bool(conta and conta.must_change_password)


def marcar_troca_obrigatoria(user, obrigatorio: bool = True) -> ContaAcesso:
    conta = conta_de(user)
    if conta is None:
        conta = ContaAcesso.objects.create(user=user, must_change_password=obrigatorio)
        return conta
    conta.must_change_password = obrigatorio
    if not obrigatorio:
        conta.password_alterado_em = timezone.now()
    conta.save(update_fields=["must_change_password", "password_alterado_em"])
    return conta


def gerar_senha_temporaria() -> str:
    return "".join(secrets.choice(_ALFABETO) for _ in range(SENHA_TAMANHO))


def aplicar_senha(user, senha: str, *, must_change: bool) -> None:
    user.set_password(senha)
    user.save(update_fields=["password"])
    conta = marcar_troca_obrigatoria(user, must_change)
    if not must_change:
        conta.password_alterado_em = timezone.now()
        conta.save(update_fields=["password_alterado_em"])


def _chave_user(username: str) -> str:
    return f"login_fail:u:{(username or '').strip().casefold()}"


def _chave_ip(ip: str | None) -> str:
    return f"login_fail:ip:{ip or 'desconhecido'}"


def esta_bloqueado(username: str, ip: str | None) -> bool:
    nu = int(cache.get(_chave_user(username)) or 0)
    ni = int(cache.get(_chave_ip(ip)) or 0)
    return nu >= FALHAS_LIMITE or ni >= FALHAS_LIMITE * 3


def registrar_falha_login(username: str, ip: str | None) -> bool:
    """Incrementa contadores. Retorna True se acabou de bloquear."""
    ku, ki = _chave_user(username), _chave_ip(ip)
    nu = cache.get(ku) or 0
    ni = cache.get(ki) or 0
    cache.set(ku, nu + 1, FALHAS_JANELA)
    cache.set(ki, ni + 1, FALHAS_JANELA)
    return (nu + 1) >= FALHAS_LIMITE


def limpar_falhas_login(username: str, ip: str | None) -> None:
    cache.delete(_chave_user(username))
    cache.delete(_chave_ip(ip))


def registrar_evento(
    tipo: str,
    *,
    ator=None,
    alvo=None,
    username_tentativa: str = "",
    ip: str | None = None,
    detalhe: str = "",
) -> None:
    RegistroAcesso.objects.create(
        tipo=tipo,
        ator=ator if getattr(ator, "is_authenticated", False) else None,
        alvo=alvo,
        username_tentativa=(username_tentativa or "")[:150],
        ip=ip,
        detalhe=(detalhe or "")[:250],
    )


def invalidar_sessoes(user, manter_key: str | None = None) -> int:
    uid = str(user.pk)
    apagadas = 0
    for sessao in Session.objects.all():
        if manter_key and sessao.session_key == manter_key:
            continue
        try:
            dados = sessao.get_decoded()
        except Exception:
            continue
        if str(dados.get("_auth_user_id")) == uid:
            sessao.delete()
            apagadas += 1
    return apagadas


def tocar_atividade(request: HttpRequest) -> None:
    request.session["_last_activity"] = int(time.time())


def sessao_ociosa(request: HttpRequest) -> bool:
    ultimo = request.session.get("_last_activity")
    if not ultimo:
        return False
    return int(time.time()) - int(ultimo) > IDLE_SEGUNDOS


def garantir_conta_parceiro(parceiro, senha: str | None = None, *, must_change: bool) -> tuple:
    """Cria ou reativa o User do PDV. Retorna (user, senha_em_claro_ou_None, criado)."""
    User = get_user_model()
    username = (parceiro.codigo_pdv or "").strip()
    if not username:
        raise ValueError("PDV sem código.")
    user = parceiro.usuario
    criado = False
    if user is None:
        existente = User.objects.filter(username__iexact=username).first()
        if existente:
            try:
                existente.perfil_staff
            except ObjectDoesNotExist:
                pass
            else:
                raise ValueError(
                    f"O login “{existente.username}” já é de um membro da equipe. "
                    "Ajuste o código do PDV ou o usuário da equipe."
                )
            try:
                outro = existente.parceiro_conta
            except ObjectDoesNotExist:
                outro = None
            if outro and outro.pk != parceiro.pk:
                raise ValueError(
                    f"O login “{existente.username}” já está vinculado a outro PDV."
                )
            user = existente
        else:
            senha_uso = senha or gerar_senha_temporaria()
            user = User.objects.create_user(
                username=username,
                password=senha_uso,
                first_name=(parceiro.nome or "")[:150],
                is_staff=False,
                is_active=parceiro.ativo,
            )
            criado = True
            senha = senha_uso
            marcar_troca_obrigatoria(user, must_change)
        parceiro.usuario = user
        parceiro.save(update_fields=["usuario", "atualizado_em"])
    if senha and not criado:
        aplicar_senha(user, senha, must_change=must_change)
    user.is_active = parceiro.ativo
    user.save(update_fields=["is_active"])
    return user, senha if criado or senha else None, criado
