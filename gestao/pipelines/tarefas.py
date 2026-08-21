from __future__ import annotations

import io
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
from django.core.files.base import ContentFile

from ..models import LoteImportacao, RelatorioTarefa
from ..parceiros import indice_parceiros, resolver_parceiro_id
from ..periodo import hoje

LISTA_COLUNAS = [
    "sg_uf",
    "nm_municipio",
    "INDICADOR",
    "CD_NRBA",
    "ST_BA",
    "cd_encerramento",
    "desc_observacao",
    "desc_macro_atividade",
    "ds_atividade",
    "dt_abertura_ba",
    "dt_inicio_agendamento",
    "dt_fim_agendamento",
    "dt_inicio_execucao_real",
    "dt_fim_execucao_real",
    "nr_ordem",
    "nr_ordem_venda",
    "dt_execucao_particao",
    "ANOMES",
    "cd_sap_original",
    "cd_rede",
    "nm_pdv_rel",
    "gp_canal",
    "sg_gerencia",
    "nm_gc",
    "DT_AGENDAMENTO",
]


def _df_para_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="dados")
    return buf.getvalue()


def _salvar_relatorio(
    *,
    lote: LoteImportacao,
    tipo: str,
    parceiro_id: int | None,
    pdv_nome: str,
    total: int,
    data_ref: date,
    mensagem: str,
    df_anexo: pd.DataFrame,
    nome_arquivo: str,
    detalhes: dict | None = None,
) -> RelatorioTarefa:
    rel = RelatorioTarefa(
        lote=lote,
        tipo_relatorio=tipo,
        parceiro_id=parceiro_id,
        pdv_nome=pdv_nome,
        total=total,
        data_referencia=data_ref,
        mensagem=mensagem,
        detalhes=detalhes or {},
    )
    rel.arquivo.save(nome_arquivo, ContentFile(_df_para_bytes(df_anexo)), save=True)
    return rel


def _colunas_anexo(df: pd.DataFrame) -> list[str]:
    return [c for c in LISTA_COLUNAS if c in df.columns] or list(df.columns)


def _processar_abertas(df: pd.DataFrame, lote: LoteImportacao, data_ref: date) -> dict:
    for col in ("sg_uf", "nm_municipio", "DT_AGENDAMENTO", "nm_pdv_rel", "INDICADOR"):
        if col not in df.columns:
            raise ValueError(f"Coluna essencial ausente para TAREFAS ABERTAS: {col}")

    filtrado = df[(df["sg_uf"] == "MG") & (df["INDICADOR"] == "TAREFAS ABERTAS")].copy()
    if filtrado.empty:
        return {"modo": "abertas", "relatorios": 0, "motivo": "sem_tarefas_mg"}

    filtrado["DT_AGENDAMENTO"] = pd.to_datetime(filtrado["DT_AGENDAMENTO"], errors="coerce")
    filtrado["DT_AGENDAMENTO"] = filtrado["DT_AGENDAMENTO"].dt.tz_localize(None)
    hoje_df = filtrado[filtrado["DT_AGENDAMENTO"].dt.date == data_ref].copy()
    if hoje_df.empty:
        return {"modo": "abertas", "relatorios": 0, "motivo": "sem_agendamento_hoje"}

    indice = indice_parceiros()
    cols = _colunas_anexo(hoje_df)
    gerados = 0
    sem_parceiro = 0
    hoje_str = data_ref.strftime("%d/%m/%Y")

    for pdv_nome, df_pdv in hoje_df.groupby("nm_pdv_rel"):
        total_pdv = len(df_pdv)
        resumo_cidades = df_pdv["nm_municipio"].value_counts()
        mensagem = (
            f"📊 *Resumo de Tarefas em Aberto (MG) - {hoje_str}*\n"
            f"🏬 *PDV:* {pdv_nome}\n\n"
            f"Total de tarefas com agendamento para hoje: *{total_pdv}*\n\n"
            f"*Resumo por Cidade (Tarefas de Hoje):*\n"
        )
        for cidade, qtd in resumo_cidades.items():
            mensagem += f"- {cidade}: {qtd} tarefas\n"
        mensagem += "\n_O anexo contém o relatório detalhado das tarefas de hoje._"

        parceiro_id = resolver_parceiro_id(str(pdv_nome), indice)
        if parceiro_id is None:
            sem_parceiro += 1
        tag = str(pdv_nome).strip().replace("/", "-")
        _salvar_relatorio(
            lote=lote,
            tipo=RelatorioTarefa.TipoRelatorio.ABERTAS,
            parceiro_id=parceiro_id,
            pdv_nome=str(pdv_nome),
            total=total_pdv,
            data_ref=data_ref,
            mensagem=mensagem,
            df_anexo=df_pdv[cols],
            nome_arquivo=f"Tarefas_Abertas_{tag}_{data_ref.isoformat()}.xlsx",
            detalhes={"cidades": {str(k): int(v) for k, v in resumo_cidades.items()}},
        )
        gerados += 1

    return {
        "modo": "abertas",
        "relatorios": gerados,
        "sem_parceiro": sem_parceiro,
        "total_hoje": int(len(hoje_df)),
    }


def _processar_fechadas(df: pd.DataFrame, lote: LoteImportacao, data_ref: date) -> dict:
    for col in ("sg_uf", "nm_municipio", "dt_fim_execucao_real"):
        if col not in df.columns:
            raise ValueError(f"Coluna essencial ausente para TAREFAS FECHADAS: {col}")

    filtrado = df[df["sg_uf"] == "MG"].copy()
    filtrado["dt_fim_execucao_real"] = pd.to_datetime(filtrado["dt_fim_execucao_real"], errors="coerce")
    filtrado["dt_fim_execucao_real"] = filtrado["dt_fim_execucao_real"].dt.tz_localize(None)
    fechadas = filtrado[filtrado["dt_fim_execucao_real"].dt.date == data_ref].copy()
    if fechadas.empty:
        return {"modo": "fechadas", "relatorios": 0, "motivo": "sem_fechadas_hoje"}

    hoje_str = data_ref.strftime("%d/%m/%Y")
    total = len(fechadas)
    mensagem = (
        f"✅ *Relatório de Tarefas Fechadas (MG) - {hoje_str}*\n\n"
        f"Total fechadas hoje: *{total}*"
    )
    _salvar_relatorio(
        lote=lote,
        tipo=RelatorioTarefa.TipoRelatorio.FECHADAS,
        parceiro_id=None,
        pdv_nome="",
        total=total,
        data_ref=data_ref,
        mensagem=mensagem,
        df_anexo=fechadas[_colunas_anexo(fechadas)],
        nome_arquivo=f"Tarefas_Fechadas_HOJE_{data_ref.isoformat()}.xlsx",
    )
    return {"modo": "fechadas", "relatorios": 1, "total": total}


def _processar_futuros(df: pd.DataFrame, lote: LoteImportacao, data_ref: date) -> dict:
    for col in ("sg_uf", "nm_municipio", "DT_AGENDAMENTO"):
        if col not in df.columns:
            raise ValueError(f"Coluna essencial ausente para AGENDAMENTO-FUTUROS: {col}")

    filtrado = df[df["sg_uf"] == "MG"].copy()
    filtrado["DT_AGENDAMENTO"] = pd.to_datetime(filtrado["DT_AGENDAMENTO"], errors="coerce")
    filtrado["DT_AGENDAMENTO"] = filtrado["DT_AGENDAMENTO"].dt.tz_localize(None)
    futuros = filtrado[filtrado["DT_AGENDAMENTO"].dt.date > data_ref].copy()
    if futuros.empty:
        return {"modo": "futuros", "relatorios": 0, "motivo": "sem_futuros"}

    hoje_str = data_ref.strftime("%d/%m/%Y")
    total = len(futuros)
    mensagem = (
        f"🗓️ *Relatório de Agendamentos Futuros (MG) - {hoje_str}*\n\n"
        f"Total de agendamentos futuros: *{total}*"
    )
    _salvar_relatorio(
        lote=lote,
        tipo=RelatorioTarefa.TipoRelatorio.FUTUROS,
        parceiro_id=None,
        pdv_nome="",
        total=total,
        data_ref=data_ref,
        mensagem=mensagem,
        df_anexo=futuros[_colunas_anexo(futuros)],
        nome_arquivo=f"Agendamentos_Futuros_{data_ref.isoformat()}.xlsx",
    )
    return {"modo": "futuros", "relatorios": 1, "total": total}


def processar_tarefas(arquivo, nome: str, lote: LoteImportacao, data_referencia: date | None = None) -> dict:
    """Roteia por INDICADOR: abertas (por PDV), fechadas ou futuros (consolidado MG)."""
    data_ref = data_referencia or hoje()
    # ler_planilha lê a 1ª aba; tarefas vêm em arquivo único
    caminho = None
    try:
        conteudo = arquivo.read() if hasattr(arquivo, "read") else Path(arquivo).read_bytes()
        if hasattr(arquivo, "seek"):
            arquivo.seek(0)
        sufixo = Path(nome).suffix.lower() or ".xlsx"
        with tempfile.NamedTemporaryFile(suffix=sufixo, delete=False) as tmp:
            tmp.write(conteudo)
            caminho = Path(tmp.name)
        engine = "pyxlsb" if sufixo == ".xlsb" else None
        df = pd.read_excel(caminho, engine=engine)
    except Exception as exc:
        raise ValueError(f"Não foi possível ler o arquivo de tarefas: {exc}") from exc
    finally:
        if caminho is not None:
            try:
                caminho.unlink(missing_ok=True)
            except PermissionError:
                pass

    if "INDICADOR" not in df.columns:
        raise ValueError("Coluna INDICADOR não encontrada — não é possível tipar o arquivo.")

    tipo = df["INDICADOR"].dropna().iloc[0] if not df["INDICADOR"].dropna().empty else None
    if tipo == "TAREFAS ABERTAS":
        resumo = _processar_abertas(df, lote, data_ref)
    elif tipo == "TAREFAS FECHADAS":
        resumo = _processar_fechadas(df, lote, data_ref)
    elif tipo == "AGENDAMENTO-FUTUROS":
        resumo = _processar_futuros(df, lote, data_ref)
    else:
        raise ValueError(f"Tipo de INDICADOR desconhecido: {tipo!r}")

    resumo["arquivo"] = nome
    resumo["data_referencia"] = data_ref.isoformat()
    resumo["indicador"] = str(tipo)
    return resumo
