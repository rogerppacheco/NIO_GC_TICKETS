from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0022_configuracaoosab_plano_dia"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracaoosab",
            name="plano_dia_fixo",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Se marcado, o Excel do parcial não altera o Plano dia "
                    "(definido pelo especialista)."
                ),
            ),
        ),
    ]
