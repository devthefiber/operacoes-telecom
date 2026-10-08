from django.contrib import admin
from .models import Colaborador, Cliente, OrdemServico, Auditoria, Expurgo, Feriado, MetaOperacional

@admin.register(Colaborador)
class ColaboradorAdmin(admin.ModelAdmin):
    list_display = ('nome', 'cargo', 'tipo', 'setor', 'supervisor', 'ativo')
    list_filter = ('tipo', 'setor', 'supervisor', 'ativo')
    search_fields = ('nome', 'cargo')

@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ('nome', 'contrato', 'cidade', 'telefone_celular')
    search_fields = ('nome', 'contrato')
    list_filter = ('cidade',)

@admin.register(OrdemServico)
class OrdemServicoAdmin(admin.ModelAdmin):
    list_display = ('id_ixc', 'cliente', 'colaborador', 'assunto', 'status', 'data_fechamento')
    list_filter = ('status', 'tipo', 'colaborador')
    search_fields = ('id_ixc', 'cliente__nome', 'protocolo')
    date_hierarchy = 'data_abertura'
    raw_id_fields = ('cliente', 'colaborador', 'os_original')

    def esta_expurgada(self, obj):
        return hasattr(obj, 'expurgo')
    esta_expurgada.boolean = True
    esta_expurgada.short_description = "Expurgada?"

@admin.register(Expurgo)
class ExpurgoAdmin(admin.ModelAdmin):
    list_display = ('ordem_servico', 'motivo', 'criado_por', 'data_expurgo')
    search_fields = ('ordem_servico__id_ixc', 'motivo')
    raw_id_fields = ('ordem_servico',)

@admin.register(Auditoria)
class AuditoriaAdmin(admin.ModelAdmin):
    list_display = ('ordem_servico', 'auditor', 'status', 'data_auditoria')
    list_filter = ('status', 'auditor')
    search_fields = ('ordem_servico__id_ixc',)

@admin.register(Feriado)
class FeriadoAdmin(admin.ModelAdmin):
    list_display = ('data', 'descricao')
    search_fields = ('descricao',)
    date_hierarchy = 'data'

@admin.register(MetaOperacional)
class MetaOperacionalAdmin(admin.ModelAdmin):
    list_display = (
        'mes', 'ano',
        'ativacao_meta_volume', 'ativacao_meta_reincidencia', 'ativacao_meta_auditoria',
        'manutencao_meta_volume', 'manutencao_meta_retrabalho', 'manutencao_meta_garantia_30d', 'manutencao_meta_auditoria'
    )
    list_filter = ('ano', 'mes')
