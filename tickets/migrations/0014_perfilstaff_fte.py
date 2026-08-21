from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0013_isolar_auth_do_schema"),
    ]

    operations = [
        migrations.AddField(
            model_name="perfilstaff",
            name="fte",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("1.00"),
                help_text="1.00 representa tempo integral e 0.5 representa meio período.",
                max_digits=3,
                verbose_name="FTE",
            ),
        ),
    ]
