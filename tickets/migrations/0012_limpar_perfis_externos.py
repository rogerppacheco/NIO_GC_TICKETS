from django.db import migrations


KEEP_GESTOR_USERNAMES = {"roger", "admin"}


def limpar_perfis_de_outros_sistemas(apps, schema_editor):
    PerfilStaff = apps.get_model("tickets", "PerfilStaff")
    Parceiro = apps.get_model("tickets", "Parceiro")
    for perfil in PerfilStaff.objects.select_related("user"):
        if perfil.papel == "especialista":
            continue
        username = (perfil.user.username or "").lower()
        if username in KEEP_GESTOR_USERNAMES:
            continue
        perfil.delete()

    ids_ok = list(
        PerfilStaff.objects.filter(papel="especialista").values_list("user_id", flat=True)
    )
    Parceiro.objects.exclude(especialista_id__isnull=True).exclude(
        especialista_id__in=ids_ok
    ).update(especialista_id=None)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0011_especialista_tempo_tratamento"),
    ]

    operations = [
        migrations.RunPython(limpar_perfis_de_outros_sistemas, noop),
    ]
