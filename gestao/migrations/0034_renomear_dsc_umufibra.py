from __future__ import annotations

from django.db import migrations


RENOMEACOES = [
    ("DSC CELULARES", "NEXA", "NEXA ENERGIA & FIBRA LTDA", 8.98437047371736),
    ("UMUFIBRA", "FIBRA FACIL", "FS SERVICOS DE TELECOMUNICACOES LTDA", 4.506427899838778),
]


def renomear_dsc_e_umufibra(apps, schema_editor):
    from gestao.pipelines.parcial_vendas import _metricas, _totais_parcial

    Parceiro = apps.get_model("tickets", "Parceiro")
    VendaOSAB = apps.get_model("gestao", "VendaOSAB")
    ConfiguracaoOSAB = apps.get_model("gestao", "ConfiguracaoOSAB")
    LoteImportacao = apps.get_model("gestao", "LoteImportacao")

    alvos_por_novo: dict[str, tuple[int, float]] = {}

    for nome_antigo, nome_novo, razao_padrao, plano_fcst in RENOMEACOES:
        antigo = Parceiro.objects.filter(nome__iexact=nome_antigo).order_by("id").first()
        novo = Parceiro.objects.filter(nome__iexact=nome_novo).order_by("id").first()

        alvo = None
        if antigo and not novo:
            antigo.nome = nome_novo
            update_fields = ["nome"]
            if not (antigo.razao_social or "").strip() and razao_padrao:
                antigo.razao_social = razao_padrao
                update_fields.append("razao_social")
            antigo.save(update_fields=update_fields)
            alvo = antigo
        elif antigo and novo and antigo.id != novo.id:
            alvo = novo
            VendaOSAB.objects.filter(parceiro_id=antigo.id).update(parceiro_id=novo.id)
        elif novo:
            alvo = novo
            if not (novo.razao_social or "").strip() and razao_padrao:
                novo.razao_social = razao_padrao
                novo.save(update_fields=["razao_social"])

        VendaOSAB.objects.filter(pdv_nome__iexact=nome_antigo).update(pdv_nome=nome_novo)
        if alvo is not None:
            alvos_por_novo[nome_novo] = (int(alvo.id), float(plano_fcst))
            VendaOSAB.objects.filter(
                parceiro__isnull=True,
                pdv_nome__iexact=nome_novo,
            ).update(parceiro_id=alvo.id)
            ConfiguracaoOSAB.objects.update_or_create(
                parceiro_id=alvo.id,
                ano=2026,
                mes=11,
                defaults={"plano_dia": plano_fcst, "plano_dia_fixo": True},
            )

    if not alvos_por_novo:
        return

    # Atualiza lotes de parcial recentes (inclusive o lote de 12/11/2026 já importado)
    vendas_12_11 = {"FIBRA FACIL": 10, "NEXA": 8}
    mapa_antigo_novo = {ant.upper(): nov for ant, nov, _, _ in RENOMEACOES}
    pid_para_novo = {pid: (nov, pl) for nov, (pid, pl) in alvos_por_novo.items()}

    lotes = list(
        LoteImportacao.objects.filter(tipo="parcial", ok=True).order_by("-criado_em")[:8]
    )
    for lote in lotes:
        resumo = dict(lote.resumo or {})
        if not resumo:
            continue
        alterou = False
        sem_cadastro = list(resumo.get("sem_cadastro") or [])
        sem_upper = {str(s).strip().upper() for s in sem_cadastro}
        eh_lote_12_11 = str(resumo.get("data_ref") or "").startswith("2026-11-12") or (
            "2026-11-12" in str(lote.arquivo_nome or "")
        )

        vendas_por_id = dict(resumo.get("vendas_por_id") or {})
        for pid, (nome_novo, plano_fcst) in pid_para_novo.items():
            chave = str(pid)
            linha_exist = dict(vendas_por_id.get(chave) or {})
            if linha_exist:
                linha_exist["pdv"] = nome_novo
                vendas_por_id[chave] = linha_exist
                alterou = True
            if eh_lote_12_11 and nome_novo in sem_upper:
                v = vendas_12_11.get(nome_novo, int(linha_exist.get("vendas") or 0))
                base_linha = dict(linha_exist) if linha_exist else {"parceiro_id": pid}
                base_linha["parceiro_id"] = pid
                base_linha["pdv"] = nome_novo
                base_linha["vendas"] = v
                base_linha.update(_metricas(v, plano_fcst))
                vendas_por_id[chave] = base_linha
                alterou = True

        linhas = list(resumo.get("linhas") or [])
        novas_linhas = []
        vistos_pids: set[int] = set()
        for linha in linhas:
            nova = dict(linha or {})
            pid_raw = nova.get("parceiro_id")
            pdv_up = str(nova.get("pdv") or "").strip().upper()
            if pdv_up in mapa_antigo_novo:
                nova["pdv"] = mapa_antigo_novo[pdv_up]
                alterou = True
            if pid_raw is not None and int(pid_raw) in pid_para_novo:
                pid_int = int(pid_raw)
                vistos_pids.add(pid_int)
                nome_novo, plano_fcst = pid_para_novo[pid_int]
                nova["pdv"] = nome_novo
                if eh_lote_12_11 and nome_novo in sem_upper:
                    v = vendas_12_11.get(nome_novo, int(nova.get("vendas") or 0))
                    nova["vendas"] = v
                    nova.update(_metricas(v, plano_fcst))
                alterou = True
            novas_linhas.append(nova)

        if eh_lote_12_11:
            novo_sem = [
                s
                for s in sem_cadastro
                if str(s).strip().upper() not in {"FIBRA FACIL", "NEXA", "DSC CELULARES", "UMUFIBRA"}
            ]
            if len(novo_sem) != len(sem_cadastro):
                resumo["sem_cadastro"] = novo_sem
                alterou = True

        if alterou:
            resumo["vendas_por_id"] = vendas_por_id
            if novas_linhas:
                resumo["linhas"] = novas_linhas
                resumo.update(_totais_parcial(novas_linhas))
            lote.resumo = resumo
            lote.save(update_fields=["resumo"])


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0033_fixar_plano_dia_forecast_nov_pp"),
        ("tickets", "0040_convitereuniao"),
    ]

    operations = [
        migrations.RunPython(renomear_dsc_e_umufibra, reverse_code=migrations.RunPython.noop),
    ]
