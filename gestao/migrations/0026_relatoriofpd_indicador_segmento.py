from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gestao", "0025_destinatario_owner"),
    ]

    operations = [
        migrations.AddField(
            model_name="relatoriofpd",
            name="indicador",
            field=models.CharField(
                choices=[("FPD", "FPD"), ("SPD", "SPD"), ("TPD", "TPD")],
                db_index=True,
                default="FPD",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="relatoriofpd",
            name="segmento",
            field=models.CharField(
                choices=[
                    ("todos", "Todos"),
                    ("varejo", "Varejo"),
                    ("empresarial", "Empresarial"),
                ],
                db_index=True,
                default="todos",
                max_length=16,
            ),
        ),
        migrations.AddIndex(
            model_name="relatoriofpd",
            index=models.Index(
                fields=["parceiro", "indicador", "segmento"],
                name="gestao_rela_parceir_166869_idx",
            ),
        ),
    ]
