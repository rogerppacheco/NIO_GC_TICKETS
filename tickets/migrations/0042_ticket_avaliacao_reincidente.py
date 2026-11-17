import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0041_reparo_mascara_cpf"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="avaliacao_retorno",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Avaliação do parceiro sobre o retorno (1 a 5 estrelas).",
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(5),
                ],
                verbose_name="Nota do retorno (CSAT)",
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="avaliacao_retorno_em",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Avaliado em",
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="reincidente",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text="Marcado quando o parceiro reabre o mesmo protocolo após resolução.",
                verbose_name="Reincidente",
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="reaberto_em",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Reaberto em",
            ),
        ),
    ]
