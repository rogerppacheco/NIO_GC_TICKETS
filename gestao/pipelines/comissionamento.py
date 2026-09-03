from __future__ import annotations

import io
import re
import tempfile
import unicodedata
from pathlib import Path

import pandas as pd
from django.core.files.base import ContentFile

from ..models import Destinatario, LoteImportacao, RelatorioComissionamento
from ..parceiros import normalizar_razao
from tickets.models import Parceiro


def _norm_texto(v) -> str:
    txt = str(v or "").strip().upper()
    txt = unicodedata.normalize("NFKD", txt)
    return "".join(c for c in txt if not unicodedata.combining(c))


def _sanitizar_nome(nome: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", str(nome or "").strip()) or "PDV"


def extrair_razoes_sociais(texto: str) -> list[str]:
    partes = re.split(r"[;\n\r]+", str(texto or ""))
    return [p.strip() for p in partes if p.strip()]


def mapa_pdv_razoes() -> dict[int, dict]:
    """parceiro_id → {pdv_nome, razoes} a partir do cadastro do PDV (+ legado destinatários)."""
    mapa: dict[int, dict] = {}
    for parceiro in Parceiro.objects.filter(ativo=True).exclude(razao_social=""):
        mapa[parceiro.id] = {
            "pdv_nome": parceiro.nome,
            "razoes": [parceiro.razao_social.strip()],
        }
    qs = (
        Destinatario.objects.filter(ativo=True, envio_comissionamento=True)
        .exclude(razoes_sociais_comissionamento="")
        .select_related("parceiro")
    )
    for dest in qs:
        extras = extrair_razoes_sociais(dest.razoes_sociais_comissionamento)
        if not extras:
            continue
        info = mapa.setdefault(
            dest.parceiro_id,
            {"pdv_nome": dest.parceiro.nome, "razoes": []},
        )
        for razao in extras:
            if razao not in info["razoes"]:
                info["razoes"].append(razao)
    for info in mapa.values():
        info["razoes"] = sorted(info["razoes"])
    return {pid: info for pid, info in mapa.items() if info["razoes"]}


def _resolver_aba(nome_alvo: str, abas) -> str | None:
    alvo = _norm_texto(nome_alvo)
    for aba in abas:
        if _norm_texto(aba) == alvo:
            return aba
    return None


def _resolver_coluna_razao(df: pd.DataFrame):
    for col in df.columns:
        col_norm = _norm_texto(col).replace("_", " ")
        if col_norm == "RAZAO SOCIAL":
            return col
    return None


def _carregar_aba(xls: pd.ExcelFile, sheet_name: str, candidatos: list[str], max_linhas: int = 20):
    df_bruto = pd.read_excel(xls, sheet_name=sheet_name, header=None)
    alvos = {_norm_texto(c).replace("_", " ") for c in candidatos}
    linha_header = None
    for i in range(min(max_linhas, len(df_bruto))):
        valores_norm = {_norm_texto(v).replace("_", " ") for v in df_bruto.iloc[i].tolist()}
        if any(a in valores_norm for a in alvos):
            linha_header = i
            break
    if linha_header is None:
        return pd.read_excel(xls, sheet_name=sheet_name)
    df = pd.read_excel(xls, sheet_name=sheet_name, header=linha_header)
    df = df.loc[:, [str(c).strip() != "" and not str(c).startswith("Unnamed") for c in df.columns]]
    return df


def _find_col(df: pd.DataFrame, aliases: list[str]):
    mapa = {_norm_texto(c).replace("_", " "): c for c in df.columns}
    for a in aliases:
        col = mapa.get(_norm_texto(a).replace("_", " "))
        if col:
            return col
    return None


def _to_float(valor) -> float:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    txt = str(valor).strip()
    if not txt:
        return 0.0
    txt = txt.replace("R$", "").replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except Exception:
        return 0.0


def _fmt_moeda(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def montar_mensagem(caminho_anexo: Path | str, pdv_nome: str, limite_pedidos: int = 15) -> tuple[str, float, float]:
    path = Path(caminho_anexo)
    engine = "pyxlsb" if path.suffix.lower() == ".xlsb" else None
    try:
        pedido_df = pd.read_excel(path, sheet_name="PEDIDO", engine=engine)
        linha_df = pd.read_excel(path, sheet_name="LINHA_A_LINHA", engine=engine)
    except Exception as exc:
        return (
            f"📁 *Comissionamento por PDV*\nPDV: *{pdv_nome}*\n\n"
            f"Não foi possível montar resumo detalhado: {exc}",
            0.0,
            0.0,
        )

    c_pedido = _find_col(pedido_df, ["DOCUMENTO DE COMPRAS", "DOCUMENTO"])
    c_item = _find_col(pedido_df, ["ITEM"])
    c_valor = _find_col(pedido_df, ["VALOR"])
    c_hana = _find_col(pedido_df, ["FORNECEDOR"])
    c_razao = _find_col(pedido_df, ["RAZÃO SOCIAL", "RAZAO SOCIAL", "RAZAO_SOCIAL"])
    c_cnpj = _find_col(pedido_df, ["CNPJ"])
    c_canal = _find_col(pedido_df, ["CANAL"])
    c_centro = _find_col(pedido_df, ["CENTRO"])
    c_ciclo = _find_col(pedido_df, ["CICLO"])
    c_sub_evento = _find_col(linha_df, ["SUB_EVENTO", "SUB EVENTO"])
    c_comissao = _find_col(linha_df, ["COMISSAO", "COMISSÃO"])

    msg = [f"📁 *Comissionamento por PDV*", f"PDV: *{pdv_nome}*"]
    total_valor_pedido = 0.0

    if c_pedido and c_item and c_valor:
        limite = min(len(pedido_df), max(1, int(limite_pedidos)))
        for i in range(limite):
            row = pedido_df.iloc[i]
            valor = _to_float(row.get(c_valor))
            total_valor_pedido += valor
            msg.extend(
                [
                    "",
                    f"Pedido: {row.get(c_pedido, '-')}",
                    f"ITEM: {row.get(c_item, '-')}",
                    f"VALOR: {_fmt_moeda(valor)}",
                    f"CÓDIGO HANA: {row.get(c_hana, '-') if c_hana else '-'}",
                    f"RAZÃO SOCIAL: {row.get(c_razao, '-') if c_razao else '-'}",
                    f"CNPJ: {row.get(c_cnpj, '-') if c_cnpj else '-'}",
                    f"CANAL: {row.get(c_canal, '-') if c_canal else '-'}",
                    f"CENTRO: {row.get(c_centro, '-') if c_centro else '-'}",
                    f"REFERÊNCIA: COMISSAO {row.get(c_ciclo, '-') if c_ciclo else '-'}",
                ]
            )
        if len(pedido_df) > limite:
            msg.append(f"\n... e mais {len(pedido_df) - limite} pedido(s) no anexo.")
    else:
        msg.append("\nNão foi possível montar bloco PEDIDO completo (colunas ausentes).")

    total_comissao = 0.0
    if c_sub_evento and c_comissao and not linha_df.empty:
        linha_tmp = linha_df[[c_sub_evento, c_comissao]].copy()
        linha_tmp[c_comissao] = linha_tmp[c_comissao].apply(_to_float)
        resumo = linha_tmp.groupby(c_sub_evento, dropna=False)[c_comissao].sum().sort_values(ascending=False)
        total_comissao = float(resumo.sum())
        msg.append("\nResumo LINHA_A_LINHA por SUB_EVENTO:")
        for sub_evento, soma in resumo.items():
            msg.append(f"- {sub_evento}: {_fmt_moeda(float(soma))}")
        msg.append(f"\nTOTAL LINHA_A_LINHA: {_fmt_moeda(total_comissao)}")
        msg.append(f"TOTAL PEDIDO: {_fmt_moeda(total_valor_pedido)}")
        diferenca = total_valor_pedido - total_comissao
        status = "OK" if abs(diferenca) < 0.01 else f"Diferença de {_fmt_moeda(diferenca)}"
        msg.append(f"Conferência total: {status}")
    else:
        msg.append("\nNão foi possível montar resumo de SUB_EVENTO/COMISSAO (colunas ausentes).")

    empresa_assunto = ""
    ciclo_assunto = ""
    if not pedido_df.empty:
        if c_razao:
            s_razao = pedido_df[c_razao].dropna()
            if not s_razao.empty:
                empresa_assunto = str(s_razao.iloc[0]).strip()
        if c_ciclo:
            s_ciclo = pedido_df[c_ciclo].dropna()
            if not s_ciclo.empty:
                raw_c = str(s_ciclo.iloc[0]).strip()
                ciclo_assunto = re.sub(r"^COMISS[ÃA]O\s*", "", raw_c, flags=re.IGNORECASE).strip()

    empresa_final = empresa_assunto or pdv_nome
    assunto_email = f"{empresa_final}_{ciclo_assunto}" if ciclo_assunto else f"{empresa_final}_[CICLO]"

    msg.append(
        "\nOrientação para envio do email: \n\n"
        "Enviar o email para recebimentonfes@niointernet.com.br\n"
        "Com cópia para: rogerio.pacheco@niointernet.com.br e PP-GestaodosParceiros@niointernet.com.br\n\n"
        "No corpo do email retirar assinatura e não escrever nada no corpo do email \n"
        f"E o assunto do email deverá ser {assunto_email}"
    )

    return "\n".join(msg), total_valor_pedido, total_comissao


def _salvar_bytes_temporario(arquivo, nome: str) -> Path:
    conteudo = arquivo.read() if hasattr(arquivo, "read") else Path(arquivo).read_bytes()
    if hasattr(arquivo, "seek"):
        arquivo.seek(0)
    sufixo = Path(nome).suffix.lower() or ".xlsx"
    tmp = tempfile.NamedTemporaryFile(suffix=sufixo, delete=False)
    tmp.write(conteudo)
    tmp.close()
    return Path(tmp.name)


def processar_comissionamento(arquivo, nome: str, lote: LoteImportacao) -> dict:
    """Separa ciclo (PEDIDO + LINHA_A_LINHA) por PDV conforme razões dos destinatários."""
    mapa = mapa_pdv_razoes()
    if not mapa:
        raise ValueError(
            "Nenhum PDV com razão social cadastrada em Parceiros "
            "(ou em Destinatários, legado)."
        )

    caminho = _salvar_bytes_temporario(arquivo, nome)
    xls = None
    try:
        engine = "pyxlsb" if caminho.suffix.lower() == ".xlsb" else None
        try:
            xls = pd.ExcelFile(caminho, engine=engine)
        except Exception as exc:
            raise ValueError(f"Não foi possível abrir o arquivo: {exc}") from exc

        aba_pedido = _resolver_aba("PEDIDO", xls.sheet_names)
        aba_linha = _resolver_aba("LINHA_A_LINHA", xls.sheet_names)
        if not aba_pedido or not aba_linha:
            raise ValueError(
                f"Abas PEDIDO e LINHA_A_LINHA obrigatórias. Encontradas: {xls.sheet_names}"
            )

        candidatos = ["RAZÃO SOCIAL", "RAZAO SOCIAL", "RAZAO_SOCIAL"]
        df_pedido = _carregar_aba(xls, aba_pedido, candidatos)
        df_linha = _carregar_aba(xls, aba_linha, candidatos)
        col_razao_pedido = _resolver_coluna_razao(df_pedido)
        col_razao_linha = _resolver_coluna_razao(df_linha)
        if not col_razao_pedido or not col_razao_linha:
            raise ValueError("Coluna 'RAZÃO SOCIAL' não encontrada em PEDIDO ou LINHA_A_LINHA.")

        # Fecha handle do arquivo antes de gerar saídas / limpeza (Windows)
        xls.close()
        xls = None

        base_nome = Path(nome).stem
        gerados = 0
        sem_linhas = 0

        for parceiro_id, info in mapa.items():
            pdv_nome = info["pdv_nome"]
            razoes_norm = {normalizar_razao(r) for r in info["razoes"]}
            mask_pedido = df_pedido[col_razao_pedido].apply(lambda v: normalizar_razao(str(v))).isin(
                razoes_norm
            )
            mask_linha = df_linha[col_razao_linha].apply(lambda v: normalizar_razao(str(v))).isin(
                razoes_norm
            )
            pedido_pdv = df_pedido[mask_pedido].copy()
            linha_pdv = df_linha[mask_linha].copy()
            if pedido_pdv.empty and linha_pdv.empty:
                sem_linhas += 1
                continue

            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                pedido_pdv.to_excel(writer, index=False, sheet_name="PEDIDO")
                linha_pdv.to_excel(writer, index=False, sheet_name="LINHA_A_LINHA")
            buf.seek(0)
            nome_saida = f"{base_nome}_{_sanitizar_nome(pdv_nome)}.xlsx"

            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp_out:
                tmp_out.write(buf.getvalue())
                caminho_out = Path(tmp_out.name)
            try:
                mensagem, total_pedido, total_comissao = montar_mensagem(caminho_out, pdv_nome)
            finally:
                caminho_out.unlink(missing_ok=True)

            rel = RelatorioComissionamento(
                lote=lote,
                parceiro_id=parceiro_id,
                pdv_nome=pdv_nome,
                qtd_pedido=int(len(pedido_pdv)),
                qtd_linha=int(len(linha_pdv)),
                total_pedido=total_pedido,
                total_comissao=total_comissao,
                mensagem=mensagem,
                detalhes={"razoes": info["razoes"]},
            )
            rel.arquivo.save(nome_saida, ContentFile(buf.getvalue()), save=True)
            gerados += 1

        return {
            "pdvs": gerados,
            "sem_linhas": sem_linhas,
            "pdvs_configurados": len(mapa),
            "arquivo": nome,
        }
    finally:
        if xls is not None:
            try:
                xls.close()
            except Exception:
                pass
        try:
            caminho.unlink(missing_ok=True)
        except PermissionError:
            pass
