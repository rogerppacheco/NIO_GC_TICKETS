from __future__ import annotations

from ..models import PoliticaComissao, PracaBTU, VendaOSAB

PLANOS = ("400", "500", "600", "800", "1000", "1000_mesh")
ROTULOS_PLANO = {
    "400": "400 Mb",
    "500": "500 Mb",
    "600": "600 Mb",
    "800": "800 Mb",
    "1000": "1 Gb",
    "1000_mesh": "1 Gb mesh",
}
SVAS = (
    "fixo",
    "globoplay_anuncios",
    "globoplay_premium",
    "max",
    "paramount",
)


def classificar_plano(velocidade: str, oferta: str = "") -> str | None:
    txt = f"{velocidade or ''} {oferta or ''}".upper()
    compacto = txt.replace(" ", "")
    tem_mesh = "MESH" in txt
    if "1000" in txt or "1GB" in compacto or "1GIGA" in compacto:
        return "1000_mesh" if tem_mesh else "1000"
    if "800" in txt or "700" in txt:
        return "800"
    if "600" in txt:
        return "600"
    if "500" in txt:
        return "500"
    if "400" in txt:
        return "400"
    return None


def detectar_svas(velocidade: str, oferta: str = "") -> list[str]:
    txt = f"{velocidade or ''} {oferta or ''}".upper()
    achados: list[str] = []
    if "FIXO" in txt:
        achados.append("fixo")
    if "GLOBOPLAY" in txt and "PREMIUM" in txt:
        achados.append("globoplay_premium")
    elif "GLOBOPLAY" in txt:
        achados.append("globoplay_anuncios")
    if "PARAMOUNT" in txt:
        achados.append("paramount")
    if "HBO" in txt or "MAX*" in txt:
        achados.append("max")
    return achados


def pracas_btu_ativas() -> set[str]:
    return set(PracaBTU.objects.filter(ativo=True).values_list("nome_norm", flat=True))


def eh_praca_btu(municipio: str, pracas: set[str] | None = None) -> bool:
    from .resultados import normalizar_praca

    if pracas is None:
        pracas = pracas_btu_ativas()
    norm = normalizar_praca(municipio)
    return bool(norm) and norm in pracas


def valor_plano(politica: PoliticaComissao, plano: str, btu: bool) -> int:
    campo = f"comissao_{plano}" + ("_btu" if btu else "")
    valor = int(getattr(politica, campo, 0) or 0)
    if btu and valor <= 0:
        return int(getattr(politica, f"comissao_{plano}", 0) or 0)
    return valor


def valor_sva(politica: PoliticaComissao, sva: str) -> int:
    return int(getattr(politica, f"comissao_{sva}", 0) or 0)


def comissao_venda(
    venda: VendaOSAB,
    politica: PoliticaComissao,
    pracas: set[str] | None = None,
) -> tuple[str | None, float, dict]:
    plano = classificar_plano(venda.velocidade or "", getattr(venda, "oferta", "") or "")
    btu = eh_praca_btu(venda.municipio or "", pracas)
    plano_rs = valor_plano(politica, plano, btu) if plano else 0
    svas = detectar_svas(venda.velocidade or "", getattr(venda, "oferta", "") or "")
    sva_rs = sum(valor_sva(politica, s) for s in svas)
    return plano, float(plano_rs + sva_rs), {"btu": btu, "svas": svas, "plano_rs": plano_rs, "sva_rs": sva_rs}


def receita_mix(
    vendas: list[VendaOSAB],
    politica: PoliticaComissao,
    proj_gross: float,
    pracas: set[str] | None = None,
) -> dict:
    if pracas is None:
        pracas = pracas_btu_ativas()
    mix = {k: 0 for k in PLANOS}
    mix["outros"] = 0
    mix_btu = 0
    sva_qtd = {k: 0 for k in SVAS}
    realizado = 0.0
    for venda in vendas:
        plano, valor, extra = comissao_venda(venda, politica, pracas)
        if plano:
            mix[plano] += 1
        else:
            mix["outros"] += 1
        if extra["btu"]:
            mix_btu += 1
        for sva in extra["svas"]:
            sva_qtd[sva] += 1
        realizado += valor
    n = len(vendas)
    projetada = (realizado * (proj_gross / n)) if n else 0.0
    return {
        "mix": mix,
        "mix_btu": mix_btu,
        "svas": sva_qtd,
        "comissao_realizada": realizado,
        "comissao_projetada": projetada,
    }


def aplicar_politica_nos_pdvs(politica: PoliticaComissao, ano: int, mes: int) -> int:
    from ..models import ConfiguracaoOSAB

    n = 0
    for cfg in ConfiguracaoOSAB.objects.filter(ano=ano, mes=mes):
        cfg.comissao_500 = politica.comissao_500
        cfg.comissao_700 = politica.comissao_800
        cfg.comissao_1000 = politica.comissao_1000
        cfg.save(update_fields=["comissao_500", "comissao_700", "comissao_1000"])
        n += 1
    return n
