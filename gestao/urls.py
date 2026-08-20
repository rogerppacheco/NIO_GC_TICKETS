from django.urls import path

from . import views

urlpatterns = [
    path("", views.hub, name="gestao_hub"),
    path("sysmap/", views.importar_sysmap_view, name="gestao_sysmap"),
    path("osab/", views.osab_view, name="gestao_osab"),
    path("capilaridade/", views.capilaridade_view, name="gestao_capilaridade"),
    path("fpd/", views.fpd_view, name="gestao_fpd"),
    path("churn/", views.churn_view, name="gestao_churn"),
    path("configuracoes/", views.configs_view, name="gestao_configs"),
]
