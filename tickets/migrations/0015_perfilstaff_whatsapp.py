from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0014_perfilstaff_fte"),
    ]

    operations = [
        migrations.AddField(
            model_name="perfilstaff",
            name="whatsapp",
            field=models.CharField(
                blank=True,
                help_text="Número com DDI para receber as máscaras (especialista). Ex.: 5531999999999.",
                max_length=40,
                verbose_name="WhatsApp",
            ),
        ),
    ]
