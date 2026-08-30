from django.urls import path

from . import views

urlpatterns = [
    path("", views.consultas_hub, name="consultas_hub"),
    path("dfv/", views.consulta_dfv, name="consulta_dfv"),
    path("cdoe/", views.consulta_cdoe, name="consulta_cdoe"),
    path("viabilidade/", views.consulta_viabilidade, name="consulta_viabilidade"),
]
