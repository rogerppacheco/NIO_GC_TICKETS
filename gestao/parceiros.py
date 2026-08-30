from __future__ import annotations

import re
import unicodedata

from tickets.models import Parceiro

RAZAO_ALIASES_PDV = {
    "GOMES OLIVEIRA TELECOM": "GM TELECOM",
    "LUISA SERVICOS DE TELEFONIA MOVEL": "INOVA MG",
    "VIP TELEFONIA E EQUIPAMENTOS": "POINT CELL",
}


def normalizar_razao(razao: str) -> str:
    texto = str(razao or "").upper().strip()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^A-Z0-9 ]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    for sufixo in (" LTDA", " LTDA ME", " ME", " EPP", " EIRELI", " SA"):
        if texto.endswith(sufixo):
            texto = texto[: -len(sufixo)].strip()
    return texto


def normalizar_pdv(nome: str) -> str:
    return normalizar_razao(nome)


def indice_parceiros() -> list[tuple[int, str, str, str]]:
    """id, nome, nome_norm, razao_norm (cadastro Sym/comissionamento)."""
    return [
        (
            p.id,
            p.nome,
            normalizar_pdv(p.nome),
            normalizar_razao(p.razao_social),
        )
        for p in Parceiro.objects.filter(ativo=True).order_by("nome")
    ]


def resolver_parceiro_id(nome: str, indice: list[tuple[int, str, str, str]] | None = None) -> int | None:
    """Resolve nome/razão social da planilha para o Parceiro do NIO."""
    if indice is None:
        indice = indice_parceiros()
    bruto = str(nome or "").strip()
    if not bruto:
        return None

    for pid, nome_cad, _, _ in indice:
        if nome_cad.casefold() == bruto.casefold():
            return pid

    alvo_norm = normalizar_pdv(bruto)
    if alvo_norm:
        for pid, _, pdv_norm, razao_cad in indice:
            if alvo_norm == pdv_norm or (razao_cad and alvo_norm == razao_cad):
                return pid
            if pdv_norm and (
                alvo_norm.startswith(pdv_norm + " ")
                or pdv_norm.startswith(alvo_norm + " ")
            ):
                return pid

    razao_norm = normalizar_razao(bruto)
    if not razao_norm:
        return None

    for pid, _, _, razao_cad in indice:
        if razao_cad and razao_norm == razao_cad:
            return pid

    alvo = RAZAO_ALIASES_PDV.get(razao_norm)
    if not alvo:
        for prefixo, pdv_nome in RAZAO_ALIASES_PDV.items():
            if razao_norm.startswith(prefixo):
                alvo = pdv_nome
                break
    if alvo:
        alvo_norm = normalizar_pdv(alvo)
        for pid, _, pdv_norm, _ in indice:
            if pdv_norm == alvo_norm:
                return pid

    melhor_id = None
    melhor_score = 0
    for pid, _, pdv_norm, _ in indice:
        if not pdv_norm:
            continue
        if razao_norm == pdv_norm:
            return pid
        if razao_norm.startswith(pdv_norm + " ") or pdv_norm in razao_norm.split():
            score = len(pdv_norm)
            if score > melhor_score:
                melhor_score = score
                melhor_id = pid
        elif pdv_norm in razao_norm:
            score = len(pdv_norm) - 1
            if score > melhor_score:
                melhor_score = score
                melhor_id = pid
    return melhor_id


def mapa_nome_parceiro() -> dict[str, int]:
    return {p.nome: p.id for p in Parceiro.objects.filter(ativo=True)}


_NOMES_VAZIOS = {"", "NAN", "NONE", "NAT", "-"}


def _nome_osab_ok(nome: str) -> str:
    texto = (nome or "").strip()
    if not texto or texto.upper() in _NOMES_VAZIOS:
        return ""
    return texto


def formatar_nome_pessoa(nome: str) -> str:
    """Primeira letra de cada palavra maiúscula, restante minúscula (JOAO → Joao)."""
    partes = _nome_osab_ok(nome).split()
    return " ".join(p[0].upper() + p[1:].lower() if p else "" for p in partes)


def mapa_gc_por_pdv() -> dict[str, str]:
    """DESCRICAO da OSAB → nm_gc mais frequente, já no padrão de nome."""
    from django.db.models import Count

    from .models import VendaOSAB

    mapa: dict[str, str] = {}
    rows = (
        VendaOSAB.objects.exclude(nm_gc="")
        .values("pdv_nome", "nm_gc")
        .annotate(n=Count("id"))
        .order_by("pdv_nome", "-n")
    )
    for row in rows:
        pdv = _nome_osab_ok(row["pdv_nome"])
        gc = formatar_nome_pessoa(row["nm_gc"])
        if not pdv or not gc:
            continue
        mapa.setdefault(pdv.casefold(), gc)
    return mapa


def mapa_sap_por_pdv() -> dict[str, str]:
    """DESCRICAO da OSAB → PDV_SAP mais frequente."""
    from django.db.models import Count

    from .models import VendaOSAB

    mapa: dict[str, str] = {}
    rows = (
        VendaOSAB.objects.exclude(pdv_sap="")
        .values("pdv_nome", "pdv_sap")
        .annotate(n=Count("id"))
        .order_by("pdv_nome", "-n")
    )
    for row in rows:
        pdv = _nome_osab_ok(row["pdv_nome"])
        sap = _nome_osab_ok(row["pdv_sap"])[:32]
        if not pdv or not sap:
            continue
        mapa.setdefault(pdv.casefold(), sap)
    return mapa


def _username_de_nome(nome: str, usados: set[str]) -> str:
    from django.contrib.auth import get_user_model

    User = get_user_model()
    slug = normalizar_pdv(nome).lower().replace(" ", ".")[:140] or "especialista"
    base = slug
    n = 2
    while base in usados or User.objects.filter(username__iexact=base).exists():
        suf = f".{n}"
        base = f"{slug[: 150 - len(suf)]}{suf}"
        n += 1
    usados.add(base)
    return base


def mapa_gerencia_por_gc() -> dict[str, str]:
    """nm_gc normalizado → GERENCIA mais frequente na OSAB."""
    from django.db.models import Count

    from .models import VendaOSAB

    mapa: dict[str, str] = {}
    rows = (
        VendaOSAB.objects.exclude(nm_gc="")
        .exclude(gerencia="")
        .values("nm_gc", "gerencia")
        .annotate(n=Count("id"))
        .order_by("nm_gc", "-n")
    )
    for row in rows:
        chave = normalizar_pdv(formatar_nome_pessoa(row["nm_gc"]))
        gerencia = _nome_osab_ok(row["gerencia"])[:120]
        if not chave or not gerencia:
            continue
        mapa.setdefault(chave, gerencia)
    return mapa


def _aplicar_gerencia_perfil(user, gerencia: str) -> bool:
    gerencia = _nome_osab_ok(gerencia)[:120]
    if not user or not gerencia:
        return False
    perfil = getattr(user, "perfil_staff", None)
    if perfil is None:
        return False
    if (perfil.gerencia or "") == gerencia:
        return False
    perfil.gerencia = gerencia
    perfil.save(update_fields=["gerencia"])
    return True


def aplicar_gerencias_osab() -> dict:
    """Preenche a gerência dos especialistas já cadastrados com o GERENCIA da OSAB."""
    from tickets.acesso import qs_equipe

    mapa = mapa_gerencia_por_gc()
    preenchidos: list[str] = []
    for user in qs_equipe():
        display = (user.get_full_name() or "").strip() or user.first_name
        gerencia = mapa.get(normalizar_pdv(display), "") or mapa.get(
            normalizar_pdv(user.first_name), ""
        )
        if _aplicar_gerencia_perfil(user, gerencia):
            preenchidos.append(user.first_name or user.username)
    return {"preenchidos": preenchidos, "mapa": mapa}


def resolver_ou_criar_especialista(nm_gc: str, cache: dict | None = None, gerencia: str = ""):
    """Encontra o especialista da equipe pelo nome ou cria com senha bloqueada."""
    from django.contrib.auth import get_user_model

    from tickets.acesso import qs_equipe
    from tickets.models import PerfilStaff

    nome = formatar_nome_pessoa(nm_gc)
    if not nome:
        return None, False
    cache = cache if cache is not None else {}
    chave = normalizar_pdv(nome)
    gerencia = _nome_osab_ok(gerencia)[:120]
    if chave in cache:
        _aplicar_gerencia_perfil(cache[chave], gerencia)
        return cache[chave], False

    for user in qs_equipe():
        display = (user.get_full_name() or "").strip() or user.first_name
        if normalizar_pdv(display) == chave or normalizar_pdv(user.first_name) == chave:
            cache[chave] = user
            _aplicar_gerencia_perfil(user, gerencia)
            return user, False

    User = get_user_model()
    usados = set(User.objects.values_list("username", flat=True))
    user = User(
        username=_username_de_nome(nome, usados),
        first_name=nome[:150],
        is_staff=True,
        is_active=True,
    )
    user.set_unusable_password()
    user.save()
    PerfilStaff.objects.create(
        user=user, papel=PerfilStaff.Papel.ESPECIALISTA, gerencia=gerencia
    )
    cache[chave] = user
    return user, True


def nomes_osab_distintos(extra: list[str] | None = None) -> list[str]:
    """DESCRICAO únicos da base OSAB (e nomes extras, se houver)."""
    from .models import VendaOSAB

    vistos: dict[str, str] = {}
    for bruto in VendaOSAB.objects.exclude(pdv_nome="").values_list("pdv_nome", flat=True):
        nome = _nome_osab_ok(bruto)
        if nome:
            vistos.setdefault(nome.casefold(), nome)
    for bruto in extra or ():
        nome = _nome_osab_ok(bruto)
        if nome:
            vistos.setdefault(nome.casefold(), nome)
    return sorted(vistos.values(), key=str.casefold)


def _indice_cadastro() -> tuple[dict[str, Parceiro], dict[str, Parceiro]]:
    """Chave normalizada → parceiro. Prefere nome exatamente igual (casefold)."""
    por_norm: dict[str, Parceiro] = {}
    por_exato: dict[str, Parceiro] = {}
    for p in Parceiro.objects.all().order_by("id"):
        por_exato.setdefault(p.nome.casefold().strip(), p)
        chave = normalizar_pdv(p.nome)
        if chave:
            por_norm.setdefault(chave, p)
    return por_exato, por_norm


def classificar_parceiros_osab(nomes: list[str] | None = None) -> dict:
    """Compara DESCRICAO da OSAB com o cadastro. Não cria nem apaga nada."""
    nomes = nomes if nomes is not None else nomes_osab_distintos()
    por_exato, por_norm = _indice_cadastro()
    ja_ok: list[str] = []
    grafia: list[dict[str, str]] = []
    faltando: list[str] = []
    usados_ids: set[int] = set()

    for nome in nomes:
        exato = por_exato.get(nome.casefold())
        if exato:
            ja_ok.append(exato.nome)
            usados_ids.add(exato.id)
            continue
        proximo = por_norm.get(normalizar_pdv(nome))
        if proximo:
            grafia.append({"osab": nome, "cadastro": proximo.nome})
            usados_ids.add(proximo.id)
            continue
        faltando.append(nome)

    nio_sem_osab = [
        p.nome
        for p in Parceiro.objects.all().order_by("nome")
        if p.id not in usados_ids
    ]
    gcs = mapa_gc_por_pdv()
    saps = mapa_sap_por_pdv()
    faltando_info = [
        {
            "nome": n,
            "gc": gcs.get(n.casefold(), ""),
            "sap": saps.get(n.casefold(), ""),
        }
        for n in faltando
    ]
    return {
        "ja_ok": ja_ok,
        "grafia": grafia,
        "faltando": faltando,
        "faltando_info": faltando_info,
        "nio_sem_osab": nio_sem_osab,
        "osab_nomes": nomes,
        "gcs": gcs,
    }


def _eh_placeholder_osab(codigo: str) -> bool:
    return (codigo or "").upper().startswith("OSAB-")


def _codigo_osab(nome: str, usados: set[str]) -> str:
    slug = re.sub(r"[^A-Z0-9]+", "-", normalizar_pdv(nome)).strip("-") or "PDV"
    slug = slug[:24]
    base = f"OSAB-{slug}"[:32]
    codigo = base
    n = 2
    while codigo in usados:
        suf = f"-{n}"
        codigo = f"{base[: 32 - len(suf)]}{suf}"
        n += 1
    usados.add(codigo)
    return codigo


def _codigo_para_pdv(nome: str, usados: set[str], sap: str = "") -> str:
    sap = (sap or "").strip()[:32]
    if sap and sap not in usados:
        usados.add(sap)
        return sap
    return _codigo_osab(nome, usados)


def _atualizar_placeholders_sap(usados: set[str]) -> tuple[list[str], list[str]]:
    """Troca OSAB-… pelo PDV_SAP quando o código SAP ainda não está em outro PDV."""
    sap_map = mapa_sap_por_pdv()
    atualizados: list[str] = []
    colisoes: list[str] = []
    for p in Parceiro.objects.all():
        if not _eh_placeholder_osab(p.codigo_pdv):
            continue
        sap = sap_map.get(p.nome.casefold(), "")
        if not sap:
            continue
        if sap in usados and sap != p.codigo_pdv:
            colisoes.append(p.nome)
            continue
        usados.discard(p.codigo_pdv)
        usados.add(sap)
        p.codigo_pdv = sap
        p.save(update_fields=["codigo_pdv"])
        atualizados.append(p.nome)
    return atualizados, colisoes


def _gerencia_do_gc(nm_gc: str, mapa: dict[str, str] | None = None) -> str:
    mapa = mapa if mapa is not None else mapa_gerencia_por_gc()
    return mapa.get(normalizar_pdv(formatar_nome_pessoa(nm_gc)), "")


def associar_parceiros_ao_especialista(user) -> list[str]:
    """Liga ao especialista os PDVs da OSAB deste GC, se estiverem livres ou num homônimo."""
    nome = formatar_nome_pessoa((user.get_full_name() or "").strip() or user.first_name)
    if not nome or not getattr(user, "pk", None):
        return []
    chave = normalizar_pdv(nome)
    gcs = mapa_gc_por_pdv()
    movidos: list[str] = []
    for p in Parceiro.objects.filter(ativo=True).select_related("especialista"):
        if normalizar_pdv(gcs.get(p.nome.casefold(), "")) != chave:
            continue
        atual = p.especialista
        if atual is not None:
            if atual.id == user.id:
                continue
            atual_nome = formatar_nome_pessoa(
                (atual.get_full_name() or "").strip() or atual.first_name
            )
            if normalizar_pdv(atual_nome) != chave:
                continue
        p.especialista = user
        p.save(update_fields=["especialista"])
        movidos.append(p.nome)
    return movidos


def _preencher_especialista_vazio(
    gcs: dict[str, str], cache_esp: dict, gerencias: dict[str, str] | None = None
) -> tuple[list[str], list[str]]:
    preenchidos: list[str] = []
    especialistas_novos: list[str] = []
    gerencias = gerencias if gerencias is not None else mapa_gerencia_por_gc()
    for p in Parceiro.objects.filter(especialista__isnull=True):
        nm_gc = gcs.get(p.nome.casefold(), "")
        user, criado_esp = resolver_ou_criar_especialista(
            nm_gc, cache_esp, gerencia=_gerencia_do_gc(nm_gc, gerencias)
        )
        if not user:
            continue
        if criado_esp:
            especialistas_novos.append(user.first_name)
        p.especialista = user
        p.save(update_fields=["especialista"])
        preenchidos.append(p.nome)
    return preenchidos, especialistas_novos


def sincronizar_parceiros_osab(nomes: list[str] | None = None) -> dict:
    """Cadastra PDVs da OSAB que ainda não existem. Não exclui nem renomeia ninguém."""
    from .models import VendaOSAB

    classif = classificar_parceiros_osab(nomes)
    usados = set(Parceiro.objects.values_list("codigo_pdv", flat=True))
    criados: list[str] = []
    especialistas_novos: list[str] = []
    gcs = mapa_gc_por_pdv()
    saps = mapa_sap_por_pdv()
    gerencias = mapa_gerencia_por_gc()
    cache_esp: dict = {}
    for nome in classif["faltando"]:
        nm_gc = gcs.get(nome.casefold(), "")
        user, criado_esp = resolver_ou_criar_especialista(
            nm_gc, cache_esp, gerencia=_gerencia_do_gc(nm_gc, gerencias)
        )
        if criado_esp and user:
            especialistas_novos.append(user.first_name)
        parceiro = Parceiro.objects.create(
            codigo_pdv=_codigo_para_pdv(nome, usados, saps.get(nome.casefold(), "")),
            nome=nome[:120],
            ativo=True,
            especialista=user,
        )
        criados.append(parceiro.nome)
        VendaOSAB.objects.filter(parceiro__isnull=True, pdv_nome__iexact=nome).update(
            parceiro_id=parceiro.id
        )
    sap_atualizados, sap_colisoes = _atualizar_placeholders_sap(usados)
    esp_preenchidos, esp_novos_existentes = _preencher_especialista_vazio(
        gcs, cache_esp, gerencias
    )
    especialistas_novos.extend(esp_novos_existentes)
    gerencias_aplicadas = aplicar_gerencias_osab()
    classif["criados"] = criados
    classif["especialistas_novos"] = especialistas_novos
    classif["codigos_sap"] = sap_atualizados
    classif["sap_colisoes"] = sap_colisoes
    classif["especialistas_preenchidos"] = esp_preenchidos
    classif["gcs"] = gcs
    classif["gerencias"] = gerencias_aplicadas.get("preenchidos", [])
    return classif
