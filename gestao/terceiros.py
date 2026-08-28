from __future__ import annotations

import re
from datetime import date, datetime

import pandas as pd
from django.utils import timezone

from .excel import ler_planilha
from .models import CadastroTerceiro
from .parceiros import indice_parceiros, resolver_parceiro_id

CARGO_VENDEDOR_CTPS = "VENDEDOR"
CARGO_OPERADOR_BACKOFFICE_INDICADOR = "OPERADOR BACK-OFFICE INDICADOR"
CARGO_OPERADOR_VENDA_INTERNA = "OPERADOR VENDA INTERNA"
CARGOS_AUDITORIA_DEDICADOS = frozenset(
    {CARGO_OPERADOR_BACKOFFICE_INDICADOR, CARGO_OPERADOR_VENDA_INTERNA}
)

COLUNAS_ALVO = {
    "razao_social": r"raz.*social",
    "nome_terceiro": r"^terceiro$",
    "cpf": r"^cpf$",
    "email": r"^email$",
    "chave_acesso": r"chave\s*de\s*acesso",
    "vinculo": r"v.*nculo",
    "cargo_funcao": r"cargo.*fun",
    "situacao_empresa": r"(?:situa.*terceiro.*empresa|^status$)",
    "situacao_funcional": r"situa.*funcional",
    "situacao_contrato": r"situa.*terceiro.*contrato",
    "data_alocacao": r"data\s*aloca",
    "data_desalocacao": r"data\s*desaloca",
    "data_inativacao": r"data\s*inativa",
}


def normalizar_chave_tt(valor) -> str | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    texto = str(valor).strip().upper()
    if texto.endswith(".0"):
        texto = texto[:-2]
    return texto or None


def normalizar_cargo_ctps(cargo) -> str:
    return re.sub(r"\s+", " ", str(cargo or "").strip().upper())


def cargo_eh_supervisor(cargo) -> bool:
    cargo_norm = normalizar_cargo_ctps(cargo)
    return cargo_norm == "SUPERVISOR" or cargo_norm.startswith("SUPERVISOR ")


def cargo_elegivel_capilaridade(cargo) -> bool:
    """Volume de capilaridade: VENDEDOR e variações (ex. VENDEDOR EXTERNO)."""
    cargo_norm = normalizar_cargo_ctps(cargo)
    return cargo_norm == CARGO_VENDEDOR_CTPS or cargo_norm.startswith(f"{CARGO_VENDEDOR_CTPS} ")


def _funcional_elegivel(situacao_funcional) -> bool:
    funcional = str(situacao_funcional or "").strip().lower()
    return funcional in {"ativo", "recontratação", "recontratacao"}


def _situacao_desativada(valor) -> bool:
    return str(valor or "").strip().lower() == "desativado"


def terceiro_elegivel_capilaridade(situacao_empresa, situacao_funcional, situacao_contrato) -> bool:
    empresa = str(situacao_empresa or "").strip().lower()
    if _situacao_desativada(empresa):
        return False
    contrato = str(situacao_contrato or "").strip().lower()
    return empresa == "ativo" and _funcional_elegivel(situacao_funcional) and contrato == "alocado"


def terceiro_ativo_para_auditoria(terceiro: CadastroTerceiro | None) -> bool:
    if terceiro is None:
        return False
    return terceiro_elegivel_capilaridade(
        terceiro.situacao_empresa,
        terceiro.situacao_funcional,
        terceiro.situacao_contrato,
    )


def classificar_cargo_auditoria(cargo_norm: str) -> str | None:
    if not cargo_norm or cargo_elegivel_capilaridade(cargo_norm) or cargo_eh_supervisor(cargo_norm):
        return None
    if cargo_norm == CARGO_OPERADOR_BACKOFFICE_INDICADOR:
        return "operador_backoffice_indicador"
    if cargo_norm == CARGO_OPERADOR_VENDA_INTERNA:
        return "operador_venda_interna"
    return "nao_vendedor"


def mapa_terceiros_por_chave() -> dict[str, CadastroTerceiro]:
    mapa: dict[str, CadastroTerceiro] = {}
    for registro in CadastroTerceiro.objects.all():
        chave = normalizar_chave_tt(registro.chave_acesso)
        if chave and chave not in mapa:
            mapa[chave] = registro
    return mapa


def chaves_elegiveis_capilaridade() -> set[str]:
    chaves: set[str] = set()
    for registro in CadastroTerceiro.objects.all():
        if not terceiro_elegivel_capilaridade(
            registro.situacao_empresa,
            registro.situacao_funcional,
            registro.situacao_contrato,
        ):
            continue
        chave = normalizar_chave_tt(registro.chave_acesso)
        if chave:
            chaves.add(chave)
    return chaves


def listar_terceiros_do_parceiro(parceiro_id: int) -> list[CadastroTerceiro]:
    indice = indice_parceiros()
    por_id = list(CadastroTerceiro.objects.filter(parceiro_id=parceiro_id))
    vistos = {t.id for t in por_id}
    extras = []
    for terceiro in CadastroTerceiro.objects.filter(parceiro__isnull=True):
        if terceiro.id in vistos:
            continue
        if resolver_parceiro_id(terceiro.razao_social or "", indice) == parceiro_id:
            extras.append(terceiro)
    return por_id + extras


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [
            "__".join(str(x) for x in col if str(x) != "nan").strip("_") for col in df.columns
        ]
    return df


def _normalizar_nome_coluna(nome: str) -> str:
    texto = str(nome)
    if "__" in texto:
        texto = texto.split("__")[-1]
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _mapear_colunas(df: pd.DataFrame) -> dict[str, str]:
    mapa: dict[str, str] = {}
    for col in df.columns:
        norm = _normalizar_nome_coluna(col)
        for campo, padrao in COLUNAS_ALVO.items():
            if campo in mapa:
                continue
            if re.search(padrao, norm, re.IGNORECASE):
                mapa[campo] = col
    faltando = [c for c in COLUNAS_ALVO if c not in mapa]
    if faltando:
        raise ValueError("Colunas obrigatórias não encontradas: " + ", ".join(faltando))
    return mapa


def _parece_cabecalho(linha) -> bool:
    valores = [str(v).strip().lower() for v in linha.values if pd.notna(v)]
    texto = " ".join(valores)
    return "terceiro" in texto and ("cpf" in texto or "chave" in texto)


def _extrair_data_referencia(nome_arquivo: str) -> date | None:
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", nome_arquivo or "")
    if not match:
        return None
    ano, mes, dia = map(int, match.groups())
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def _parse_data(valor) -> date | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    if not texto or texto in {"NaT", "nan", "00/01/1900"}:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto[:10], fmt).date()
        except ValueError:
            continue
    parsed = pd.to_datetime(texto, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _limpar_texto(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    return str(valor).strip()


def _score_linha(linha: pd.Series, mapa: dict[str, str]) -> tuple:
    """Linha mais recente vence (inativação > desalocação > alocação)."""
    inativ = _parse_data(linha.get(mapa["data_inativacao"]))
    desaloc = _parse_data(linha.get(mapa["data_desalocacao"]))
    aloc = _parse_data(linha.get(mapa["data_alocacao"]))
    if inativ:
        return (3, inativ.toordinal())
    if desaloc:
        return (2, desaloc.toordinal())
    if aloc:
        return (1, aloc.toordinal())
    return (0, 0)


def _consolidar(df: pd.DataFrame, mapa: dict[str, str]) -> tuple[pd.DataFrame, int]:
    melhor: dict[str, pd.Series] = {}
    duplicados = 0
    for _, linha in df.iterrows():
        chave = normalizar_chave_tt(linha.get(mapa["chave_acesso"]))
        if not chave:
            continue
        if chave not in melhor:
            melhor[chave] = linha
            continue
        duplicados += 1
        if _score_linha(linha, mapa) > _score_linha(melhor[chave], mapa):
            melhor[chave] = linha
    if not melhor:
        return pd.DataFrame(), duplicados
    return pd.DataFrame(list(melhor.values())), duplicados


def importar_sysmap(arquivo, nome_arquivo: str = "") -> dict:
    nome = nome_arquivo or getattr(arquivo, "name", "arquivo")
    df = ler_planilha(arquivo, nome)
    df = _flatten_columns(df)
    if len(df) > 0 and _parece_cabecalho(df.iloc[0]):
        df = df.iloc[1:].reset_index(drop=True)
    mapa = _mapear_colunas(df)
    linhas_planilha = len(df)
    df, duplicados = _consolidar(df, mapa)
    data_ref = _extrair_data_referencia(nome) or timezone.localdate()
    indice = indice_parceiros()

    inseridos = atualizados = ignorados = 0
    agora = timezone.now()
    for _, linha in df.iterrows():
        chave = normalizar_chave_tt(linha.get(mapa["chave_acesso"]))
        if not chave:
            ignorados += 1
            continue
        empresa = _limpar_texto(linha.get(mapa["situacao_empresa"]))
        funcional = _limpar_texto(linha.get(mapa["situacao_funcional"]))
        contrato = _limpar_texto(linha.get(mapa["situacao_contrato"]))
        razao = _limpar_texto(linha.get(mapa["razao_social"]))
        dados = {
            "nome_terceiro": _limpar_texto(linha.get(mapa["nome_terceiro"]))[:200],
            "cpf": _limpar_texto(linha.get(mapa["cpf"]))[:30],
            "email": _limpar_texto(linha.get(mapa["email"]))[:200],
            "razao_social": razao[:200],
            "vinculo": _limpar_texto(linha.get(mapa["vinculo"]))[:50],
            "cargo_funcao": _limpar_texto(linha.get(mapa["cargo_funcao"]))[:100],
            "situacao_empresa": empresa[:50],
            "situacao_funcional": funcional[:80],
            "situacao_contrato": contrato[:50],
            "data_alocacao": _parse_data(linha.get(mapa["data_alocacao"])),
            "data_desalocacao": _parse_data(linha.get(mapa["data_desalocacao"])),
            "data_inativacao": _parse_data(linha.get(mapa["data_inativacao"])),
            "data_referencia": data_ref,
            "parceiro_id": resolver_parceiro_id(razao, indice),
            "ativo": terceiro_elegivel_capilaridade(empresa, funcional, contrato),
        }
        _, created = CadastroTerceiro.objects.update_or_create(
            chave_acesso=chave, defaults=dados
        )
        if created:
            inseridos += 1
        else:
            atualizados += 1

    return {
        "arquivo": nome,
        "data_referencia": data_ref.isoformat(),
        "linhas_planilha": linhas_planilha,
        "linhas_unicas": len(df),
        "inseridos": inseridos,
        "atualizados": atualizados,
        "ignorados": ignorados,
        "duplicados_planilha": duplicados,
        "total_cadastro": CadastroTerceiro.objects.count(),
        "total_ativos": CadastroTerceiro.objects.filter(ativo=True).count(),
        "total_vinculados_pdv": CadastroTerceiro.objects.filter(parceiro__isnull=False).count(),
        "processado_em": agora.isoformat(),
    }
