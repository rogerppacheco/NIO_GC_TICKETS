from django.urls import path

from . import views

urlpatterns = [
    path("", views.hub, name="gestao_hub"),
    path("sysmap/", views.importar_sysmap_view, name="gestao_sysmap"),
    path("osab/", views.osab_view, name="gestao_osab"),
    path("capilaridade/", views.capilaridade_view, name="gestao_capilaridade"),
    path("fpd/", views.fpd_view, name="gestao_fpd"),
    path("churn/", views.churn_view, name="gestao_churn"),
    path("comissionamento/", views.comissionamento_view, name="gestao_comissionamento"),
    path("tarefas/", views.tarefas_view, name="gestao_tarefas"),
    path("venda-indevida/", views.venda_indevida_view, name="gestao_venda_indevida"),
    path("recompra/", views.recompra_view, name="gestao_recompra"),
    path("configuracoes/", views.configs_view, name="gestao_configs"),
    path("destinatarios/", views.destinatarios_view, name="gestao_destinatarios"),
    path("destinatarios/<int:pk>/", views.destinatario_editar, name="gestao_destinatario_editar"),
    path("destinatarios/<int:pk>/excluir/", views.destinatario_excluir, name="gestao_destinatario_excluir"),
    path("destinatarios/<int:pk>/toggle/", views.destinatario_toggle, name="gestao_destinatario_toggle"),
    path("envios/", views.envios_view, name="gestao_envios"),
]
