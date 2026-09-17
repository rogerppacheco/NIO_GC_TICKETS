from django.db import migrations, models


def preencher_gerencia_dos_lotes(apps, schema_editor):
    LoteImportacao = apps.get_model("gestao", "LoteImportacao")
    PerfilStaff = apps.get_model("tickets", "PerfilStaff")
    mapa = {
        perfil.user_id: (perfil.gerencia or "").strip()[:120]
        for perfil in PerfilStaff.objects.exclude(gerencia="")
    }
    if not mapa:
        return
    for lote in LoteImportacao.objects.filter(gerencia="", criado_por_id__isnull=False).iterator():
        gerencia = mapa.get(lote.criado_por_id) or ""
        if gerencia:
            lote.gerencia = gerencia
            lote.save(update_fields=["gerencia"])


class Migration(migrations.Migration):
    dependencies = [
        ("gestao", "0026_relatoriofpd_indicador_segmento"),
        ("tickets", "0033_rota_arranjo_locais"),
    ]

    operations = [
        migrations.AddField(
            model_name="loteimportacao",
            name="gerencia",
            field=models.CharField(
                blank=True, db_index=True, max_length=120, verbose_name="Gerência"
            ),
        ),
        migrations.RunPython(preencher_gerencia_dos_lotes, migrations.RunPython.noop),
    ]
