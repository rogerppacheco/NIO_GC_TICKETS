from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0021_alter_enviowhatsapp_tipo"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracaoosab",
            name="plano_dia",
            field=models.FloatField(
                default=0,
                help_text="Plano do dia (VB) usado no parcial quando o PDV não vem no Excel.",
            ),
        ),
    ]
