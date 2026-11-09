# Generated manually

from __future__ import annotations

from django.db import migrations

# Forecast oficial (FORECAST M+1 REDE VB NOV - PARCEIROS Pp.xlsx).
# Reaplica os valores e marca plano_dia_fixo=True para que importações de parcial
# (ex.: data - *.xlsx) não sobrescrevam mais o plano nas Metas.
FORECAST_NOV_PP: list[tuple[str, float]] = [
    ("FABRETTI", 11.235141229275127),
    ("F.S.M COMERCIO", 9.894152522960209),
    ("MULTI TELECOM", 10.012105095536269),
    ("GM TELECOM", 8.043071386814892),
    ("VISION", 5.506063941557712),
    ("IGOR CRISTIANO", 7.956374956249173),
    ("CENTRALNET", 5.5089840458906245),
    ("ALLVO TELECOM", 4.479389439316168),
    ("GENESIS", 4.957015709515338),
    ("SUPORTE SMART", 2.9834827606363428),
    ("DHARMA TELECOM", 0.5),
    ("T E R GROWTH", 2.9710513403796623),
    ("ATOS TELECOM", 9.950719766952654),
    ("IMPACTO REPRESENTACOES", 6.999401910841296),
    ("INOVA PARTICIPACOES", 6.538293891092974),
    ("F B FIBRA", 5.418165353327455),
    ("CEV SOLUCOES", 5.000234810946605),
    ("CONECTA PAP", 3.9641361237595376),
    ("BRAZIL NET", 3.2089756050770277),
    ("UPFIBER TELECOM", 2.49076360616545),
    ("NF ASSESSORIA", 1.985247363074163),
    ("MASTERPRISE", 0.7299999999999999),
    ("BRAVOSFIBRA", 16.24070644373246),
    ("DSC CELULARES", 8.98437047371736),
    ("JAWO", 4.521247334410624),
    ("UMUFIBRA", 4.506427899838778),
    ("AGILE", 4.531721499727745),
    ("CH TELECOM", 3.0120825657554424),
    ("RAPID CONECTA", 1.55),
    ("ALFA", 0.0),
    ("AMAZONTECH", 9.976846572208741),
    ("CONEXA", 7.020984497588257),
    ("D DOS SANTOS", 2.5198677090055734),
    ("LIDER TELECOM AM", 3.0359283912398363),
    ("G P TELECOM", 2.957176523989336),
    ("NOVA VELOX", 2.4829033766901167),
    ("NETVENDAS", 2.0046613138915035),
    ("NORTE TECH", 1.460067135421973),
    ("FENIX ES", 4.904986426794219),
    ("J PEREIRA TELECOMUNICACAO", 4.097261980032675),
    ("ARGUS", 4.017317638465752),
    ("K&K", 2.276363570849751),
    ("AGS TELECOM", 2.475710567801527),
    ("JS TELECOM", 1.4709792176180334),
    ("CONNECTX", 1.0046079102092018),
    ("NOSSA FIBRA", 0.8305923337031192),
    ("MAFORTE", 0.5397988669588463),
    ("SYNKED", 0.5232332865672926),
    ("LISBOA RR", 0.0),
]

PARES_SINONIMOS = {
    "BRAVOSFIBRA": ["BRAVOS"],
    "JAWO": ["JAVO TELECOM", "JAVO"],
    "ALLVO TELECOM": ["ALLVO"],
    "NORTE TECH": ["NORTE TECNOLOGIA"],
    "F.S.M COMERCIO": ["F.S.M", "FSM COMERCIO", "FSM"],
}


def aplicar_e_fixar_forecast_nov_pp(apps, schema_editor):
    from gestao.parceiros import normalizar_pdv, normalizar_razao, resolver_parceiro_id
    from gestao.periodo import periodo_ativo

    Parceiro = apps.get_model("tickets", "Parceiro")
    ConfiguracaoOSAB = apps.get_model("gestao", "ConfiguracaoOSAB")
    LoteImportacao = apps.get_model("gestao", "LoteImportacao")

    parceiros = list(Parceiro.objects.filter(ativo=True).order_by("nome"))
    if not parceiros:
        return

    indice = [
        (
            p.id,
            p.nome,
            normalizar_pdv(p.nome),
            normalizar_razao(p.razao_social),
        )
        for p in parceiros
    ]

    try:
        ano_ativo, mes_ativo = periodo_ativo()
    except Exception:
        ano_ativo, mes_ativo = 2026, 11

    periodos = {(2026, 11), (int(ano_ativo), int(mes_ativo))}

    plano_por_pid: dict[int, float] = {}
    for nome_rede, valor in FORECAST_NOV_PP:
        nomes_busca = [nome_rede] + PARES_SINONIMOS.get(nome_rede, [])
        for candidato in nomes_busca:
            pid = resolver_parceiro_id(candidato, indice)
            if pid is not None:
                plano_por_pid[int(pid)] = float(valor)

    if not plano_por_pid:
        return

    for ano, mes in periodos:
        for pid, valor in plano_por_pid.items():
            obj, criado = ConfiguracaoOSAB.objects.get_or_create(
                parceiro_id=pid,
                ano=ano,
                mes=mes,
                defaults={"plano_dia": valor, "plano_dia_fixo": True},
            )
            if criado:
                continue
            campos = []
            if float(obj.plano_dia or 0.0) != float(valor):
                obj.plano_dia = valor
                campos.append("plano_dia")
            if not bool(getattr(obj, "plano_dia_fixo", False)):
                obj.plano_dia_fixo = True
                campos.append("plano_dia_fixo")
            if campos:
                obj.save(update_fields=campos)

    from gestao.pipelines.parcial_vendas import _metricas, _totais_parcial

    lotes = list(
        LoteImportacao.objects.filter(tipo="parcial", ok=True).order_by("-criado_em")[:8]
    )
    for lote in lotes:
        resumo = dict(lote.resumo or {})
        if not resumo:
            continue
        alterou = False
        vendas_por_id = dict(resumo.get("vendas_por_id") or {})
        for k, linha in list(vendas_por_id.items()):
            try:
                pid = int(k)
            except (TypeError, ValueError):
                continue
            if pid in plano_por_pid:
                novo_plano = plano_por_pid[pid]
                plano_val = novo_plano if novo_plano > 0 else None
                vendas = int((linha or {}).get("vendas") or 0)
                nova_linha = dict(linha or {})
                nova_linha.update(_metricas(vendas, plano_val))
                vendas_por_id[k] = nova_linha
                alterou = True

        linhas = list(resumo.get("linhas") or [])
        novas_linhas = []
        for linha in linhas:
            pid = (linha or {}).get("parceiro_id")
            if pid is not None and int(pid) in plano_por_pid:
                novo_plano = plano_por_pid[int(pid)]
                plano_val = novo_plano if novo_plano > 0 else None
                vendas = int((linha or {}).get("vendas") or 0)
                nova_linha = dict(linha)
                nova_linha.update(_metricas(vendas, plano_val))
                novas_linhas.append(nova_linha)
                alterou = True
            else:
                novas_linhas.append(linha)

        if alterou:
            resumo["vendas_por_id"] = vendas_por_id
            if novas_linhas:
                resumo["linhas"] = novas_linhas
                resumo.update(_totais_parcial(novas_linhas))
            lote.resumo = resumo
            lote.save(update_fields=["resumo"])


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0032_atualizar_plano_dia_forecast_nov_pp"),
    ]

    operations = [
        migrations.RunPython(
            aplicar_e_fixar_forecast_nov_pp,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
