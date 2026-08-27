from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0012_diafiscal"),
    ]

    operations = [
        migrations.AddField(
            model_name="vendaosab",
            name="gerencia",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=120,
                verbose_name="Gerência (OSAB)",
            ),
        ),
    ]
