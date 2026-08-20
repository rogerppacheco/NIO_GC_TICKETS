from django.contrib import admin

from .models import (
    AnaliseCapilaridade,
    CadastroTerceiro,
    ConfiguracaoOSAB,
    GrossMensal,
    HistoricoChurn,
    HistoricoOSAB,
    LoteImportacao,
    MetaCapilaridade,
    RelatorioFPD,
    VendaOSAB,
)


@admin.register(LoteImportacao)
class LoteAdmin(admin.ModelAdmin):
    list_display = ("tipo", "arquivo_nome", "ok", "criado_em", "criado_por")
    list_filter = ("tipo", "ok")


@admin.register(CadastroTerceiro)
class TerceiroAdmin(admin.ModelAdmin):
    list_display = ("chave_acesso", "nome_terceiro", "parceiro", "cargo_funcao", "ativo")
    list_filter = ("ativo", "cargo_funcao")
    search_fields = ("chave_acesso", "nome_terceiro", "razao_social")


@admin.register(VendaOSAB)
class VendaAdmin(admin.ModelAdmin):
    list_display = ("pedido", "pdv_nome", "matricula_vendedor", "data_abertura", "situacao")
    search_fields = ("pedido", "pdv_nome", "matricula_vendedor")


admin.site.register(AnaliseCapilaridade)
admin.site.register(MetaCapilaridade)
admin.site.register(ConfiguracaoOSAB)
admin.site.register(HistoricoOSAB)
admin.site.register(GrossMensal)
admin.site.register(HistoricoChurn)
admin.site.register(RelatorioFPD)
