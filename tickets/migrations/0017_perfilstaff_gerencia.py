from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0016_email_gestao_e_mascaras"),
    ]

    operations = [
        migrations.AddField(
            model_name="perfilstaff",
            name="gerencia",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Mesmo valor da coluna GERENCIA da OSAB. Meus/Outros só mostram PDVs desta gerência.",
                max_length=120,
                verbose_name="Gerência",
            ),
        ),
    ]
