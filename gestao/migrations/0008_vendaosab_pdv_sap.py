from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0007_vendaosab_nm_gc"),
    ]

    operations = [
        migrations.AddField(
            model_name="vendaosab",
            name="pdv_sap",
            field=models.CharField(
                blank=True, db_index=True, max_length=32, verbose_name="PDV_SAP"
            ),
        ),
    ]
