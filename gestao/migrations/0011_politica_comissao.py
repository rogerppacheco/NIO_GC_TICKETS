from django.db import migrations, models


def criar_politica(apps, schema_editor):
    PoliticaComissao = apps.get_model("gestao", "PoliticaComissao")
    PoliticaComissao.objects.get_or_create(pk=1)


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0010_pracabtu_gdp"),
    ]

    operations = [
        migrations.AddField(
            model_name="vendaosab",
            name="oferta",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.CreateModel(
            name="PoliticaComissao",
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
                ("vigencia", models.DateField(default="2026-08-13")),
                ("canal", models.CharField(default="PAP", max_length=20)),
                ("comissao_400", models.IntegerField(default=120)),
                ("comissao_400_btu", models.IntegerField(default=0)),
                ("comissao_500", models.IntegerField(default=350)),
                ("comissao_500_btu", models.IntegerField(default=0)),
                ("comissao_600", models.IntegerField(default=350)),
                ("comissao_600_btu", models.IntegerField(default=245)),
                ("comissao_800", models.IntegerField(default=450)),
                ("comissao_800_btu", models.IntegerField(default=450)),
                ("comissao_1000", models.IntegerField(default=550)),
                ("comissao_1000_btu", models.IntegerField(default=550)),
                ("comissao_1000_mesh", models.IntegerField(default=385)),
                ("comissao_1000_mesh_btu", models.IntegerField(default=385)),
                ("comissao_fixo", models.IntegerField(default=30)),
                ("comissao_globoplay_anuncios", models.IntegerField(default=23)),
                ("comissao_globoplay_premium", models.IntegerField(default=40)),
                ("comissao_max", models.IntegerField(default=40)),
                ("comissao_paramount", models.IntegerField(default=28)),
                ("nmei_400", models.IntegerField(default=120)),
                ("nmei_500", models.IntegerField(default=100)),
                ("nmei_600", models.IntegerField(default=100)),
                ("nmei_800", models.IntegerField(default=150)),
                ("nmei_1000", models.IntegerField(default=150)),
                ("bonus_m10", models.IntegerField(default=150)),
                ("faixa_m10_alta", models.IntegerField(default=70)),
                ("faixa_m10_media", models.IntegerField(default=50)),
                ("faixa_m10_baixa", models.IntegerField(default=30)),
            ],
            options={
                "verbose_name": "Política de comissão PAP",
                "verbose_name_plural": "Políticas de comissão PAP",
            },
        ),
        migrations.RunPython(criar_politica, migrations.RunPython.noop),
    ]
