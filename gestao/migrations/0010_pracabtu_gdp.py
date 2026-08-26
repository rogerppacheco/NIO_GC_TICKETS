from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0009_resultados"),
    ]

    operations = [
        migrations.AddField(
            model_name="pracabtu",
            name="ativo",
            field=models.BooleanField(db_index=True, default=True),
        ),
        migrations.AddField(
            model_name="pracabtu",
            name="atualizado_em",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name="pracabtu",
            name="cod_ibge",
            field=models.CharField(blank=True, max_length=16),
        ),
        migrations.AddField(
            model_name="pracabtu",
            name="fonte",
            field=models.CharField(
                choices=[("gdp", "GDP"), ("manual", "Manual")],
                db_index=True,
                default="manual",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="pracabtu",
            name="portfolio",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="pracabtu",
            name="uf",
            field=models.CharField(blank=True, db_index=True, max_length=2),
        ),
        migrations.AlterModelOptions(
            name="pracabtu",
            options={
                "ordering": ["uf", "nome"],
                "verbose_name": "Praça BTU",
                "verbose_name_plural": "Praças BTU",
            },
        ),
    ]
