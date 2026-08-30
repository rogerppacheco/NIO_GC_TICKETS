import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0019_parceiro_credenciamento_endereco"),
        ("gestao", "0013_vendaosab_gerencia"),
    ]

    operations = [
        migrations.AddField(
            model_name="destinatario",
            name="ranking_consolidado",
            field=models.BooleanField(
                default=False,
                help_text="Grupo único da gerência (ex.: Parceiros_PP_Nio) — aparece no Ranking VB sem depender de um PDV.",
                verbose_name="Ranking consolidado",
            ),
        ),
        migrations.AlterField(
            model_name="destinatario",
            name="parceiro",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="destinatarios_gestao",
                to="tickets.parceiro",
            ),
        ),
    ]
