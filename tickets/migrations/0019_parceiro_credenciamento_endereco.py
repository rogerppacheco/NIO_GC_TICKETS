from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0018_parceiro_razao_social"),
    ]

    operations = [
        migrations.AddField(
            model_name="parceiro",
            name="data_credenciamento",
            field=models.DateField(
                blank=True,
                help_text="Usada no ranking VB (Regular >6 meses · Iniciante ≤6 meses).",
                null=True,
                verbose_name="Data credenciamento",
            ),
        ),
        migrations.AddField(
            model_name="parceiro",
            name="endereco",
            field=models.TextField(blank=True, verbose_name="Endereço"),
        ),
        migrations.AddField(
            model_name="parceiro",
            name="emails_empresario",
            field=models.TextField(
                blank=True,
                help_text="Um ou mais e-mails, separados por vírgula ou quebra de linha.",
                verbose_name="E-mail(s) do empresário",
            ),
        ),
    ]
