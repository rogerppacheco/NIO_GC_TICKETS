import json
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import GuiaPendencia

@login_required
def guia_solucoes_view(request):
    guias = GuiaPendencia.objects.all()
    guias_data = [
        {
            "id": g.id,
            "codigo": g.codigo,
            "descricao": g.descricao,
            "search_term": f"{g.codigo} - {g.descricao}",
            "quando_acontece": g.quando_acontece,
            "esteira": g.esteira,
            "agendavel": g.agendavel,
            "elegivel_mem_crv": g.elegivel_mem_crv,
            "elegivel_pav": g.elegivel_pav,
            "tratamento_humano_discador": g.tratamento_humano_discador,
            "tratamento_humano_whatsapp": g.tratamento_humano_whatsapp,
            "nota": g.nota,
        }
        for g in guias
    ]
    return render(request, "tickets/guia_solucoes.html", {
        "guias_json": json.dumps(guias_data)
    })
