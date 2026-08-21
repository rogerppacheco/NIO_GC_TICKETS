from django.contrib import admin

from .models import Anexo, ContatoParceiro, Encaminhamento, Mascara, Mensagem, Parceiro, PerfilStaff, Ticket, ConfigRespostaTipo

admin.site.site_header = "NIO GC Tickets"
admin.site.site_title = "NIO GC Tickets"


class ContatoParceiroInline(admin.TabularInline):
    model = ContatoParceiro
    extra = 1


@admin.register(Parceiro)
class ParceiroAdmin(admin.ModelAdmin):
    list_display = ("codigo_pdv", "nome", "especialista", "ativo")
    list_filter = ("ativo",)
    search_fields = ("codigo_pdv", "nome")
    inlines = [ContatoParceiroInline]


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
    list_display = ("nome", "destino", "tipos", "ativo")
    list_filter = ("ativo",)


@admin.register(Encaminhamento)
class EncaminhamentoAdmin(admin.ModelAdmin):
    list_display = ("ticket", "destino", "criado_em", "criado_por")
    search_fields = ("ticket__protocolo", "destino")


admin.site.register(Mensagem)
admin.site.register(Anexo)


@admin.register(PerfilStaff)
class PerfilStaffAdmin(admin.ModelAdmin):
    list_display = ("user", "papel", "fte")
    list_filter = ("papel",)


@admin.register(ConfigRespostaTipo)
class ConfigRespostaTipoAdmin(admin.ModelAdmin):
    list_display = ("tipo", "atualizado_em")
    search_fields = ("tipo",)

