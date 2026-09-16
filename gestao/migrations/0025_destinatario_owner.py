from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("gestao", "0024_instancia_whatsapp"),
    ]

    operations = [
        migrations.AddField(
            model_name="destinatario",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                db_index=True,
                help_text="Lista pessoal do especialista/gerência. Vazio = lista da gestão.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="destinatarios_whatsapp",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
