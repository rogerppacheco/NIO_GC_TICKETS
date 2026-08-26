from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0008_vendaosab_pdv_sap"),
    ]

    operations = [
        migrations.AddField(
            model_name="vendaosab",
            name="municipio",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=120,
                verbose_name="Município / praça",
            ),
        ),
        migrations.AddField(
            model_name="destinatario",
            name="envio_resultados",
            field=models.BooleanField(default=False, verbose_name="Resultados"),
        ),
        migrations.AddField(
            model_name="destinatario",
            name="email_resultados",
            field=models.BooleanField(default=False, verbose_name="E-mail Resultados"),
        ),
        migrations.CreateModel(
            name="PracaBTU",
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
                ("nome", models.CharField(max_length=120, verbose_name="Município / praça")),
                (
                    "nome_norm",
                    models.CharField(db_index=True, max_length=120, unique=True),
                ),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Praça BTU",
                "verbose_name_plural": "Praças BTU",
                "ordering": ["nome"],
            },
        ),
    ]
