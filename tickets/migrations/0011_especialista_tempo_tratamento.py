from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def criar_perfis_existentes(apps, schema_editor):
    User = apps.get_model("auth", "User")
    PerfilStaff = apps.get_model("tickets", "PerfilStaff")
    for user in User.objects.filter(is_staff=True):
        PerfilStaff.objects.get_or_create(
            user_id=user.id,
            defaults={"papel": "gestor"},
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tickets", "0010_reparo_mascara"),
    ]

    operations = [
        migrations.AddField(
            model_name="parceiro",
            name="especialista",
            field=models.ForeignKey(
                blank=True,
                help_text="Responsável NIO por este PDV. Vê e trata as demandas deste parceiro.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="parceiros_especialista",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Especialista",
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="resposta_iniciada_em",
            field=models.DateTimeField(
                blank=True,
                help_text="Momento em que o atendente clicou em Responder.",
                null=True,
                verbose_name="Início do tratamento",
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="resposta_salva_em",
            field=models.DateTimeField(
                blank=True,
                help_text="Momento em que a resposta foi salva.",
                null=True,
                verbose_name="Fim do tratamento",
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="tempo_retorno_segundos",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Tempo entre clicar em Responder e Salvar resposta (primeira vez).",
                null=True,
                verbose_name="Retorno de tratamento (s)",
            ),
        ),
        migrations.CreateModel(
            name="PerfilStaff",
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
                (
                    "papel",
                    models.CharField(
                        choices=[
                            ("gestor", "Gestor"),
                            ("especialista", "Especialista"),
                        ],
                        db_index=True,
                        default="especialista",
                        max_length=20,
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="perfil_staff",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Perfil interno",
                "verbose_name_plural": "Perfis internos",
            },
        ),
        migrations.RunPython(criar_perfis_existentes, noop),
    ]
