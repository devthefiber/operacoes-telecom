from django.urls import path
from . import views

urlpatterns = [
    # Porta de entrada única via POST JWT do Hub The Fiber
    path('portal/', views.login_portal_view, name='login_portal'),
    
    # Interceptador para redirecionar usuários não autenticados direto ao Hub
    path('login/', views.login_view, name='login'),
    
    # Encerramento de sessão e retorno ao Hub
    path('logout/', views.logout_view, name='logout'),
]
