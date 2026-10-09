from django.contrib import admin
from .models import Perfil

@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ('user', 'setor', 'status_solicitacao', 'deve_trocar_senha')
    list_filter = ('status_solicitacao', 'deve_trocar_senha')
    search_fields = ('user__email', 'user__first_name', 'setor')
