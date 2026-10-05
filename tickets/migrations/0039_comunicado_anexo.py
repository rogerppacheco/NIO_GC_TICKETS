import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0038_elite_mascara_nome_titular_cpf"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ComunicadoAnexo",
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
                ("arquivo", models.FileField(upload_to="comunicados/%Y/%m/")),
                ("nome_original", models.CharField(blank=True, max_length=255)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                (
                    "comunicado",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="anexos",
                        to="tickets.comunicado",
                    ),
                ),
                (
                    "enviado_por",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="comunicado_anexos",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Anexo de comunicado",
                "verbose_name_plural": "Anexos de comunicados",
                "ordering": ["criado_em", "id"],
            },
        ),
    ]
