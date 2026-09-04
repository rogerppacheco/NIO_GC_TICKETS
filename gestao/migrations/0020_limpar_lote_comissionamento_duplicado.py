from django.db import migrations


def limpar_lote_duplicado(apps, schema_editor):
    LoteImportacao = apps.get_model("gestao", "LoteImportacao")
    RelatorioComissionamento = apps.get_model("gestao", "RelatorioComissionamento")

    lotes = list(
        LoteImportacao.objects.filter(
            tipo="comissionamento",
            ok=True,
        ).order_by("criado_em", "id")
    )
    if len(lotes) > 1:
        primeiro = lotes[0]
        for excedente in lotes[1:]:
            RelatorioComissionamento.objects.filter(lote=excedente).delete()
            excedente.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0019_alter_destinatario_razoes_sociais_comissionamento_and_more"),
    ]

    operations = [
        migrations.RunPython(limpar_lote_duplicado, reverse_code=migrations.RunPython.noop),
    ]
