from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0017_perfilstaff_gerencia"),
    ]

    operations = [
        migrations.AddField(
            model_name="parceiro",
            name="razao_social",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Igual à coluna Razão Social do Sysmap/Supply (gestão de terceiros) "
                    "e do comissionamento (PEDIDO / LINHA_A_LINHA)."
                ),
                max_length=200,
                verbose_name="Razão social",
            ),
        ),
    ]
