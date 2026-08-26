from django.contrib import admin

from .models import (
    AnaliseCapilaridade,
    CadastroTerceiro,
    ConfiguracaoOSAB,
    Destinatario,
    EnvioWhatsApp,
    GrossMensal,
    HistoricoChurn,
    HistoricoOSAB,
    LoteImportacao,
    MetaCapilaridade,
    RelatorioComissionamento,
    RelatorioFPD,
    RelatorioRecompra,
    RelatorioTarefa,
    RelatorioVendaIndevida,
    VendaOSAB,
    PracaBTU,
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


@admin.register(Destinatario)
class DestinatarioAdmin(admin.ModelAdmin):
    list_display = ("nome", "parceiro", "jid", "tipo", "ativo", "prioridade")
    list_filter = (
        "ativo",
        "tipo",
        "envio_capilaridade",
        "envio_fpd",
        "envio_churn",
        "envio_comissionamento",
        "envio_tarefas",
        "envio_venda_indevida",
        "envio_recompra",
        "envio_resultados",
    )
    search_fields = ("nome", "jid", "parceiro__nome", "razoes_sociais_comissionamento")


@admin.register(RelatorioComissionamento)
class RelatorioComissionamentoAdmin(admin.ModelAdmin):
    list_display = ("pdv_nome", "qtd_pedido", "qtd_linha", "criado_em", "lote")
    list_filter = ("criado_em",)
    search_fields = ("pdv_nome",)


@admin.register(RelatorioTarefa)
class RelatorioTarefaAdmin(admin.ModelAdmin):
    list_display = ("tipo_relatorio", "pdv_nome", "total", "data_referencia", "criado_em")
    list_filter = ("tipo_relatorio", "data_referencia")


@admin.register(RelatorioVendaIndevida)
class RelatorioVendaIndevidaAdmin(admin.ModelAdmin):
    list_display = ("pdv_nome", "consolidado", "total", "data_referencia", "criado_em")
    list_filter = ("consolidado", "data_referencia")


@admin.register(RelatorioRecompra)
class RelatorioRecompraAdmin(admin.ModelAdmin):
    list_display = ("pdv_nome", "consolidado", "total", "data_referencia", "criado_em")
    list_filter = ("consolidado", "data_referencia")


@admin.register(EnvioWhatsApp)
class EnvioAdmin(admin.ModelAdmin):
    list_display = ("criado_em", "tipo", "status", "parceiro", "destino_nome", "modo_teste")
    list_filter = ("tipo", "status", "modo_teste")
    search_fields = ("destino_jid", "destino_nome", "syncwa_message_id")


admin.site.register(AnaliseCapilaridade)
admin.site.register(MetaCapilaridade)
admin.site.register(ConfiguracaoOSAB)
admin.site.register(HistoricoOSAB)
admin.site.register(GrossMensal)
admin.site.register(HistoricoChurn)
admin.site.register(RelatorioFPD)
admin.site.register(PracaBTU)
