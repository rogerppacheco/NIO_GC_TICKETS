from django.db import migrations


def isolar_logins(apps, schema_editor):
    from tickets.isolamento_auth import isolar_auth_schema

    resultado = isolar_auth_schema(schema_editor.connection)
    if resultado.get("motivo") == "nao_postgres":
        return
    print(
        "auth isolado:",
        resultado,
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0012_limpar_perfis_externos"),
    ]

    operations = [
        migrations.RunPython(isolar_logins, noop),
    ]
