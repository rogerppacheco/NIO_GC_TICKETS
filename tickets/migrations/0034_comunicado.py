import sys

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


TITULO_REGUA = "Régua de bloqueio do serviço Nio Fibra"

CORPO_REGUA = (
    "Tema importante: o time de cobrança mudou a régua de bloqueio do serviço. "
    "É importante deixar claro para os parceiros essa mudança.\n\n"
    "Pré-pago (apenas vendas na modalidade cartão de crédito):\n"
    "• Bloqueio 5 dias após o vencimento — já era assim e se mantém.\n\n"
    "Híbrido (vendas na modalidade DACC / boleto):\n"
    "• Vencimento: 25 dias após a instalação\n"
    "• Bloqueio:\n"
    "  – Instalações até 13/09: bloqueio 30 dias após o vencimento\n"
    "  – Instalações a partir de 14/09: bloqueio 19 dias após o vencimento"
)


def _em_teste() -> bool:
    if any(a == "test" or a.startswith("test") for a in sys.argv):
        return True
    return False


def criar_primeiro_comunicado(apps, schema_editor):
    if _em_teste():
        return
    Comunicado = apps.get_model("tickets", "Comunicado")
    if Comunicado.objects.filter(titulo=TITULO_REGUA).exists():
        return
    Comunicado.objects.create(
        titulo=TITULO_REGUA,
        corpo=CORPO_REGUA,
        ativo=True,
        publico="parceiros",
        publicado_em=timezone.now(),
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0033_rota_arranjo_locais"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Comunicado",
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
                ("titulo", models.CharField(max_length=180, verbose_name="Título")),
                ("corpo", models.TextField(verbose_name="Comunicado")),
                (
                    "ativo",
                    models.BooleanField(
                        default=True,
                        help_text="Se desmarcado, deixa de aparecer no login e no sininho.",
                    ),
                ),
                (
                    "publico",
                    models.CharField(
                        choices=[
                            ("parceiros", "Parceiros (PDV)"),
                            ("equipe", "Equipe interna"),
                            ("todos", "Parceiros e equipe"),
                        ],
                        db_index=True,
                        default="parceiros",
                        max_length=20,
                        verbose_name="Público",
                    ),
                ),
                (
                    "publicado_em",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                (
                    "criado_por",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="comunicados_criados",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Comunicado",
                "verbose_name_plural": "Comunicados",
                "ordering": ["-publicado_em", "-criado_em"],
            },
        ),
        migrations.CreateModel(
            name="ComunicadoLeitura",
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
                ("entendeu", models.BooleanField(default=True)),
                ("lido_em", models.DateTimeField(auto_now_add=True)),
                (
                    "comunicado",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="leituras",
                        to="tickets.comunicado",
                    ),
                ),
                (
                    "ticket",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="comunicado_leituras",
                        to="tickets.ticket",
                    ),
                ),
                (
                    "usuario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comunicado_leituras",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Leitura de comunicado",
                "verbose_name_plural": "Leituras de comunicados",
                "ordering": ["-lido_em"],
            },
        ),
        migrations.AddConstraint(
            model_name="comunicadoleitura",
            constraint=models.UniqueConstraint(
                fields=("comunicado", "usuario"),
                name="uniq_comunicado_usuario_leitura",
            ),
        ),
        migrations.RunPython(criar_primeiro_comunicado, noop),
    ]
