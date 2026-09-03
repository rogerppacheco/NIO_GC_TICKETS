from django.urls import path

from . import views, views_whatsapp

urlpatterns = [
    path("", views.hub, name="gestao_hub"),
    path("gerencia/", views.gerencia_ativa_view, name="gestao_gerencia"),
    path("sysmap/", views.importar_sysmap_view, name="gestao_sysmap"),
    path("osab/", views.osab_view, name="gestao_osab"),
    path("resultados/", views.resultados_view, name="gestao_resultados"),
    path("resultados/ranking-preview/", views.ranking_preview, name="gestao_ranking_preview"),
    path("resultados/parcial-preview/", views.parcial_preview, name="gestao_parcial_preview"),
    path("resultados/vb-sem-municipio.xlsx", views.exportar_vb_sem_municipio, name="gestao_vb_sem_municipio"),
    path("modo-teste/", views.toggle_modo_teste_view, name="gestao_modo_teste"),
    path("capilaridade/", views.capilaridade_view, name="gestao_capilaridade"),
    path("fpd/", views.fpd_view, name="gestao_fpd"),
    path("churn/", views.churn_view, name="gestao_churn"),
    path("comissionamento/", views.comissionamento_view, name="gestao_comissionamento"),
    path("comissionamento/<int:pk>/download/", views.comissionamento_download_view, name="gestao_comissionamento_download"),
    path("tarefas/", views.tarefas_view, name="gestao_tarefas"),
    path("venda-indevida/", views.venda_indevida_view, name="gestao_venda_indevida"),
    path("recompra/", views.recompra_view, name="gestao_recompra"),
    path("configuracoes/", views.configs_view, name="gestao_configs"),
    path("whatsapp/", views_whatsapp.whatsapp_view, name="gestao_whatsapp"),
    path("whatsapp/status/", views_whatsapp.whatsapp_status_api, name="gestao_whatsapp_status"),
    path("whatsapp/qrcode/", views_whatsapp.whatsapp_qrcode_api, name="gestao_whatsapp_qrcode"),
    path("whatsapp/desconectar/", views_whatsapp.whatsapp_disconnect_api, name="gestao_whatsapp_disconnect"),
    path("destinatarios/", views.destinatarios_view, name="gestao_destinatarios"),
    path("destinatarios/do-grupo/", views.destinatario_do_grupo, name="gestao_destinatario_do_grupo"),
    path("destinatarios/<int:pk>/", views.destinatario_editar, name="gestao_destinatario_editar"),
    path("destinatarios/<int:pk>/excluir/", views.destinatario_excluir, name="gestao_destinatario_excluir"),
    path("destinatarios/<int:pk>/toggle/", views.destinatario_toggle, name="gestao_destinatario_toggle"),
    path("envios/", views.envios_view, name="gestao_envios"),
]
