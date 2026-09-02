from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0014_destinatario_ranking_consolidado"),
    ]

    operations = [
        migrations.AlterField(
            model_name="loteimportacao",
            name="tipo",
            field=models.CharField(
                choices=[
                    ("sysmap", "Sysmap / Supply"),
                    ("osab", "OSAB"),
                    ("fpd", "FPD"),
                    ("churn", "Churn"),
                    ("comissionamento", "Comissionamento"),
                    ("tarefas", "Tarefas"),
                    ("venda_indevida", "Venda indevida"),
                    ("recompra", "Recompra"),
                    ("gdp", "GDP / praças BTU"),
                    ("metas", "Metas (acompanhamento)"),
                    ("parcial", "Parcial de vendas"),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
    ]
