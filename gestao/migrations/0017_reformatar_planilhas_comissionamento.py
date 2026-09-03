from django.db import migrations
from django.core.files.base import ContentFile
import io
import pandas as pd


def reformatar_planilhas(apps, schema_editor):
    from gestao.pipelines.comissionamento import gerar_planilha_comissionamento_formatada

    RelatorioComissionamento = apps.get_model("gestao", "RelatorioComissionamento")
    for rel in RelatorioComissionamento.objects.all():
        if not rel.arquivo:
            continue
        try:
            rel.arquivo.open("rb")
            content = rel.arquivo.read()
            if not content:
                continue
            xls = io.BytesIO(content)
            try:
                pedido_df = pd.read_excel(xls, sheet_name="PEDIDO")
                linha_df = pd.read_excel(xls, sheet_name="LINHA_A_LINHA")
            except Exception:
                continue

            novo_bytes = gerar_planilha_comissionamento_formatada(pedido_df, linha_df)
            nome_arquivo = rel.arquivo.name.split("/")[-1]
            rel.arquivo.save(nome_arquivo, ContentFile(novo_bytes), save=True)
        except Exception:
            continue


class Migration(migrations.Migration):
    dependencies = [
        ("gestao", "0016_atualizar_mensagens_comissionamento"),
    ]

    operations = [
        migrations.RunPython(reformatar_planilhas, reverse_code=migrations.RunPython.noop),
    ]
