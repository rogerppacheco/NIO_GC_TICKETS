from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0038_elite_mascara_nome_titular_cpf"),
    ]

    operations = [
        migrations.AddField(
            model_name="blocovertical",
            name="vtop_obra_id",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="blocovertical",
            name="vtop_etapa",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="blocovertical",
            name="vtop_sincronizado_em",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
