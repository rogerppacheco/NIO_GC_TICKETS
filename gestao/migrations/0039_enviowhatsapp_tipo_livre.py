from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0038_enviowhatsapp_tipo_clima"),
    ]

    operations = [
        migrations.AlterField(
            model_name="enviowhatsapp",
            name="tipo",
            field=models.CharField(
                choices=[
                    ("capilaridade", "Capilaridade"),
                    ("osab", "OSAB"),
                    ("fpd", "FPD"),
                    ("fpd_critico", "FPD crítico"),
                    ("churn", "Churn"),
                    ("comissionamento", "Comissionamento"),
                    ("tarefas", "Tarefas"),
                    ("venda_indevida", "Venda indevida"),
                    ("recompra", "Recompra"),
                    ("parcial", "Parcial de vendas"),
                    ("acumulado", "Acumulado do mês"),
                    ("ranking", "Ranking VB"),
                    ("resumo", "Resumo geral"),
                    ("mascara", "Máscara de atendimento"),
                    ("comunicado", "Comunicado"),
                    ("clima", "Clima operacional"),
                    ("livre", "Mensagem livre"),
                    ("teste", "Teste WhatsApp"),
                ],
                db_index=True,
                max_length=30,
            ),
        ),
    ]
