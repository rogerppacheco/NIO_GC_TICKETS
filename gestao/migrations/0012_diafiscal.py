from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0011_politica_comissao"),
    ]

    operations = [
        migrations.CreateModel(
            name="DiaFiscal",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("data", models.DateField(db_index=True, unique=True)),
                ("peso_vl", models.FloatField(default=1.0)),
                ("peso_gross", models.FloatField(default=1.0)),
                ("feriado", models.BooleanField(default=False)),
                ("observacao", models.CharField(blank=True, max_length=100)),
            ],
            options={
                "verbose_name": "Dia fiscal (DU)",
                "verbose_name_plural": "Calendário de pesos DU",
                "ordering": ["data"],
            },
        ),
    ]
