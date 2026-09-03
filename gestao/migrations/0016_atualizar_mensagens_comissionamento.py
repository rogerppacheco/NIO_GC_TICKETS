from django.db import migrations
import re


def atualizar_mensagens(apps, schema_editor):
    RelatorioComissionamento = apps.get_model("gestao", "RelatorioComissionamento")
    for rel in RelatorioComissionamento.objects.all():
        msg = (rel.mensagem or "").strip()
        if not msg:
            continue
        if "Orientação para envio do email" in msg or "Orientaçaõ para envio do email" in msg:
            continue

        m_razao = re.search(r"RAZ[ÃA]O SOCIAL:\s*(.+)", msg, flags=re.IGNORECASE)
        empresa = m_razao.group(1).strip() if m_razao else ""
        if not empresa or empresa == "-":
            empresa = (rel.pdv_nome or "").strip()

        m_ciclo = re.search(r"REFER[ÊE]NCIA:\s*(?:COMISSAO\s*)?([^\n\r]+)", msg, flags=re.IGNORECASE)
        ciclo = m_ciclo.group(1).strip() if m_ciclo else ""
        ciclo = re.sub(r"^COMISS[ÃA]O\s*", "", ciclo, flags=re.IGNORECASE).strip()

        assunto_email = f"{empresa}_{ciclo}" if ciclo and ciclo != "-" else f"{empresa}_[CICLO]"

        bloco = (
            "\n\nOrientação para envio do email: \n\n"
            "Enviar o email para recebimentonfes@niointernet.com.br\n"
            "Com cópia para: rogerio.pacheco@niointernet.com.br e PP-GestaodosParceiros@niointernet.com.br\n\n"
            "No corpo do email retirar assinatura e não escrever nada no corpo do email \n"
            f"E o assunto do email deverá ser {assunto_email}"
        )
        rel.mensagem = msg + bloco
        rel.save(update_fields=["mensagem"])


class Migration(migrations.Migration):
    dependencies = [
        ("gestao", "0015_lote_parcial"),
    ]

    operations = [
        migrations.RunPython(atualizar_mensagens, reverse_code=migrations.RunPython.noop),
    ]
