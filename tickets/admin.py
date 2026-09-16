from django.contrib import admin

from .models import (
    Anexo,
    BlocoVertical,
    CheckinRotaDiaria,
    ContatoParceiro,
    Encaminhamento,
    Mascara,
    Mensagem,
    Parceiro,
    ParceiroPraca,
    PerfilStaff,
    PlanejamentoSemanalRota,
    ProcessoAnexo,
    ProcessoLink,
    ProcessoRepositorio,
    SolicitacaoVertical,
    Ticket,
    ConfigRespostaTipo,
)

admin.site.site_header = "NIO ESPECIALISTA Tickets"
admin.site.site_title = "NIO ESPECIALISTA Tickets"


class ContatoParceiroInline(admin.TabularInline):
    model = ContatoParceiro
    extra = 1


class ParceiroPracaInline(admin.TabularInline):
    model = ParceiroPraca
    extra = 1


@admin.register(Parceiro)
class ParceiroAdmin(admin.ModelAdmin):
    list_display = ("codigo_pdv", "nome", "razao_social", "especialista", "ativo")
    list_filter = ("ativo",)
    search_fields = ("codigo_pdv", "nome", "razao_social")
    inlines = [ContatoParceiroInline, ParceiroPracaInline]


@admin.register(ContatoParceiro)
class ContatoParceiroAdmin(admin.ModelAdmin):
    list_display = ("nome", "parceiro", "telefone", "ativo")
    list_filter = ("ativo", "parceiro")
    search_fields = ("nome", "email", "telefone", "parceiro__codigo_pdv")


class MensagemInline(admin.TabularInline):
    model = Mensagem
    extra = 0


class AnexoInline(admin.TabularInline):
    model = Anexo
    extra = 0


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "protocolo",
        "parceiro",
        "contato",
        "tipo",
        "status",
        "resultado_status",
        "prioridade",
        "pedido",
        "tempo_retorno_tratamento",
        "criado_em",
    )
    list_filter = ("status", "tipo", "prioridade", "parceiro")
    search_fields = (
        "protocolo",
        "pedido",
        "documento_cliente",
        "descricao",
        "resultado_status",
        "resposta_publica",
        "contato__nome",
    )
    inlines = [MensagemInline, AnexoInline]
    readonly_fields = (
        "protocolo",
        "criado_em",
        "atualizado_em",
        "resposta_iniciada_em",
        "resposta_salva_em",
        "tempo_retorno_segundos",
    )


@admin.register(Mascara)
class MascaraAdmin(admin.ModelAdmin):
    list_display = ("nome", "destino", "tipos", "enviar_email", "enviar_whatsapp", "ativo")
    list_filter = ("ativo", "enviar_email", "enviar_whatsapp")


@admin.register(Encaminhamento)
class EncaminhamentoAdmin(admin.ModelAdmin):
    list_display = ("ticket", "destino", "criado_em", "criado_por")
    search_fields = ("ticket__protocolo", "destino")


admin.site.register(Mensagem)
admin.site.register(Anexo)


@admin.register(PerfilStaff)
class PerfilStaffAdmin(admin.ModelAdmin):
    list_display = ("user", "papel", "fte", "gerencia", "tipo_destino_mascara", "whatsapp")
    list_filter = ("papel", "gerencia", "tipo_destino_mascara")


@admin.register(ConfigRespostaTipo)
class ConfigRespostaTipoAdmin(admin.ModelAdmin):
    list_display = ("tipo", "atualizado_em")
    search_fields = ("tipo",)


class ProcessoAnexoInline(admin.TabularInline):
    model = ProcessoAnexo
    extra = 0


class ProcessoLinkInline(admin.TabularInline):
    model = ProcessoLink
    extra = 0


@admin.register(ProcessoRepositorio)
class ProcessoRepositorioAdmin(admin.ModelAdmin):
    list_display = ("titulo", "categoria", "canal", "publico", "ativo", "ordem")
    list_filter = ("categoria", "canal", "publico", "ativo")
    search_fields = ("titulo", "slug", "tags", "finalidade")
    prepopulated_fields = {"slug": ("titulo",)}
    inlines = [ProcessoAnexoInline, ProcessoLinkInline]


@admin.register(ParceiroPraca)
class ParceiroPracaAdmin(admin.ModelAdmin):
    list_display = ("parceiro", "uf", "cidade", "bairro", "ativo")
    list_filter = ("uf", "ativo")
    search_fields = ("parceiro__codigo_pdv", "parceiro__nome", "cidade", "bairro")


@admin.register(CheckinRotaDiaria)
class CheckinRotaDiariaAdmin(admin.ModelAdmin):
    list_display = (
        "parceiro",
        "data",
        "tipo_rota",
        "qtd_vendedores",
        "uf",
        "cidade",
        "bairro",
        "hp_livres",
    )
    list_filter = ("tipo_rota", "uf", "data")
    search_fields = ("parceiro__codigo_pdv", "parceiro__nome", "bairro", "cidade")
    date_hierarchy = "data"


@admin.register(PlanejamentoSemanalRota)
class PlanejamentoSemanalRotaAdmin(admin.ModelAdmin):
    list_display = (
        "parceiro",
        "semana_inicio",
        "vendas_planejadas",
        "meta_referencia",
        "status_alerta",
    )
    list_filter = ("status_alerta",)
    search_fields = ("parceiro__codigo_pdv", "parceiro__nome")
    date_hierarchy = "semana_inicio"


class BlocoVerticalInline(admin.TabularInline):
    model = BlocoVertical
    extra = 0


@admin.register(SolicitacaoVertical)
class SolicitacaoVerticalAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "nome_condominio",
        "cidade",
        "uf",
        "status",
        "total_hps",
        "criado_por",
        "contato",
        "data_criacao",
    )
    list_filter = ("status", "uf")
    search_fields = ("nome_condominio", "nome_sindico", "cep", "cidade")
    inlines = [BlocoVerticalInline]

