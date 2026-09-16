from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("gestao", "0023_configuracaoosab_plano_dia_fixo"),
    ]

    operations = [
        migrations.CreateModel(
            name="InstanciaWhatsApp",
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
                ("nome", models.CharField(max_length=80, unique=True)),
                ("estado", models.CharField(blank=True, max_length=40)),
                ("numero", models.CharField(blank=True, max_length=40)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="instancia_whatsapp",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Instância WhatsApp",
                "verbose_name_plural": "Instâncias WhatsApp",
            },
        ),
    ]
