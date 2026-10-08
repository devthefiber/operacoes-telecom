from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_operacoes, name='dashboard_operacoes'),
    path('exportar/', views.exportar_base, name='exportar_base'),
    path('configuracoes/', views.configuracoes, name='configuracoes'),
        path('configuracoes/replicar/', views.replicar_mes_anterior, name='replicar_mes_anterior'),
    path('configuracoes/salvar/', views.salvar_colaborador, name='salvar_colaborador'),
    path('configuracoes/excluir/<int:id>/', views.excluir_papel, name='excluir_papel'),
    path('configuracoes/salvar_cargo/', views.salvar_cargo, name='salvar_cargo'),
    path('configuracoes/excluir_cargo/<int:id>/', views.excluir_cargo, name='excluir_cargo'),
    path('configuracoes/metas/', views.configuracoes_metas, name='configuracoes_metas'),
    path('configuracoes/feriados/', views.configuracoes_feriados, name='configuracoes_feriados'),
    path('configuracoes/metas/salvar/', views.salvar_meta, name='salvar_meta'),
    path('configuracoes/metas/salvar_feriado/', views.salvar_feriado, name='salvar_feriado'),
    path('configuracoes/metas/excluir_feriado/<int:id>/', views.excluir_feriado, name='excluir_feriado'),
    path('expurgos/', views.gestao_expurgos, name='gestao_expurgos'),
    path('expurgos/registrar/', views.registrar_expurgo, name='registrar_expurgo'),
    path('expurgos/remover/<int:id>/', views.remover_expurgo, name='remover_expurgo'),
]
