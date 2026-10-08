from django.db import models

class Cargo(models.Model):
    nome = models.CharField(max_length=100, unique=True, verbose_name="Nome do Cargo")

    def __str__(self):
        return self.nome

    class Meta:
        verbose_name = "Cargo"
        verbose_name_plural = "Cargos"
        ordering = ['nome']

class Colaborador(models.Model):
    TIPO_CHOICES = [
        ('TECNICO', 'Técnico'),
        ('SUPERVISOR', 'Supervisor'),
        ('AUDITOR', 'Auditor'),
        ('OUTRO', 'Outro'),
    ]
    SETOR_CHOICES = [
        ('ATIVACAO', 'Ativação'),
        ('MANUTENCAO', 'Manutenção'),
    ]
    CONTRATACAO_CHOICES = [
        ('CLT', 'CLT'),
        ('PJ', 'PJ'),
    ]
    nome = models.CharField(max_length=200, verbose_name="Nome do Colaborador")
    cargo = models.ForeignKey(Cargo, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Cargo", related_name='colaboradores')
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='TECNICO')
    setor = models.CharField(max_length=20, choices=SETOR_CHOICES, blank=True, null=True)
    contratacao = models.CharField(max_length=10, choices=CONTRATACAO_CHOICES, blank=True, null=True, verbose_name="CLT / PJ")
    ativo = models.BooleanField(default=True)
    
    supervisor = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='liderados', verbose_name="Supervisor")

    def __str__(self):
        return self.nome

    class Meta:
        verbose_name = "Colaborador"
        verbose_name_plural = "Colaboradores"


class AlocacaoMensal(models.Model):
    colaborador = models.ForeignKey(Colaborador, on_delete=models.CASCADE, related_name='alocacoes')
    mes = models.IntegerField(verbose_name="Mês")
    ano = models.IntegerField(verbose_name="Ano")
    
    cargo = models.ForeignKey(Cargo, on_delete=models.SET_NULL, null=True, blank=True)
    supervisor = models.ForeignKey(Colaborador, on_delete=models.SET_NULL, null=True, blank=True, related_name='equipe_no_mes')
    setor = models.CharField(max_length=20, choices=Colaborador.SETOR_CHOICES, blank=True, null=True)
    contratacao = models.CharField(max_length=10, choices=Colaborador.CONTRATACAO_CHOICES, blank=True, null=True)
    contabiliza_indicadores = models.BooleanField(default=True, verbose_name="Contabiliza para Metas?")

    def __str__(self):
        return f"{self.colaborador.nome} - {self.mes:02d}/{self.ano}"

    class Meta:
        verbose_name = "Alocação Mensal"
        verbose_name_plural = "Alocações Mensais"
        unique_together = ('colaborador', 'mes', 'ano')

class Cliente(models.Model):

    nome = models.CharField(max_length=200, verbose_name="Nome do Cliente")
    contrato = models.CharField(max_length=50, blank=True, null=True, verbose_name="Contrato (IXC)")
    cidade = models.CharField(max_length=100, blank=True, null=True)
    bairro = models.CharField(max_length=100, blank=True, null=True)
    telefone_celular = models.CharField(max_length=20, blank=True, null=True)
    whatsapp = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return f"{self.nome} (Contrato: {self.contrato})"

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"

class OrdemServico(models.Model):
    id_ixc = models.IntegerField(unique=True, verbose_name="ID IXC")
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='ordens_servico')
    colaborador = models.ForeignKey(Colaborador, on_delete=models.SET_NULL, null=True, blank=True, related_name='ordens_executadas')
    
    # Campo inteligente: Link automático com a Instalação/OS original (para Reincidência/Auditoria)
    os_original = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='os_filhas', verbose_name="OS Original Vinculada")

    
    tipo = models.CharField(max_length=100, blank=True, null=True)
    assunto = models.CharField(max_length=200, blank=True, null=True)
    setor_ixc = models.CharField(max_length=100, blank=True, null=True)
    nome_setor = models.CharField(max_length=100, blank=True, null=True, verbose_name="Nome do Setor")
    status = models.CharField(max_length=50, blank=True, null=True)
    protocolo = models.CharField(max_length=50, blank=True, null=True)
    
    data_abertura = models.DateTimeField(null=True, blank=True)
    data_fechamento = models.DateTimeField(null=True, blank=True)
    
    diagnostico = models.TextField(blank=True, null=True)
    mensagem = models.TextField(blank=True, null=True)
    
    reincidencia = models.CharField(max_length=50, blank=True, null=True, verbose_name="Reincidência")
    
    data_criacao = models.DateTimeField(auto_now_add=True)
    data_atualizacao = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"OS {self.id_ixc} - {self.cliente.nome}"

    class Meta:
        verbose_name = "Ordem de Serviço"
        verbose_name_plural = "Ordens de Serviço"
        ordering = ['-data_abertura']

class Auditoria(models.Model):
    STATUS_AUDITORIA = [
        ('APROVADA', 'Aprovada'),
        ('REPROVADA', 'Reprovada'),
        ('RETRABALHO', 'Retrabalho'),
        ('PENDENTE', 'Pendente'),
    ]
    
    ordem_servico = models.OneToOneField(OrdemServico, on_delete=models.CASCADE, related_name='auditoria')
    auditor = models.ForeignKey(Colaborador, on_delete=models.RESTRICT, related_name='auditorias_realizadas')
    status = models.CharField(max_length=20, choices=STATUS_AUDITORIA, default='PENDENTE')
    observacoes = models.TextField(blank=True, null=True, verbose_name="Observações do Auditor")
    
    data_auditoria = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Auditoria OS {self.ordem_servico.id_ixc} - {self.status}"

    class Meta:
        verbose_name = "Auditoria"
        verbose_name_plural = "Auditorias"

class Expurgo(models.Model):
    ordem_servico = models.OneToOneField(OrdemServico, on_delete=models.CASCADE, related_name='expurgo')
    motivo = models.TextField(verbose_name="Motivo do Expurgo")
    data_expurgo = models.DateTimeField(auto_now_add=True)
    criado_por = models.CharField(max_length=100, default="Gestor", verbose_name="Quem expurgou")

    def __str__(self):
        return f"Expurgo da OS {self.ordem_servico.id_ixc}"

    class Meta:
        verbose_name = "Expurgo"
        verbose_name_plural = "Expurgos"

class Feriado(models.Model):
    data = models.DateField(unique=True, verbose_name="Data do Feriado")
    descricao = models.CharField(max_length=100, verbose_name="Descrição (Ex: Natal)")

    def __str__(self):
        return f"{self.data.strftime('%d/%m/%Y')} - {self.descricao}"

    class Meta:
        verbose_name = "Feriado"
        verbose_name_plural = "Feriados"
        ordering = ['-data']

class MetaOperacional(models.Model):
    MESES = [
        (1, 'Janeiro'), (2, 'Fevereiro'), (3, 'Março'), (4, 'Abril'),
        (5, 'Maio'), (6, 'Junho'), (7, 'Julho'), (8, 'Agosto'),
        (9, 'Setembro'), (10, 'Outubro'), (11, 'Novembro'), (12, 'Dezembro')
    ]
    ano = models.IntegerField(verbose_name="Ano", default=2026)
    mes = models.IntegerField(choices=MESES, verbose_name="Mês")
    
    # Metas de Ativação
    ativacao_meta_volume = models.DecimalField(max_digits=5, decimal_places=2, default=6.00, verbose_name="Ativação: Meta Volume")
    ativacao_meta_reincidencia = models.DecimalField(max_digits=5, decimal_places=2, default=5.00, verbose_name="Ativação: Meta Reincidência (%)")
    ativacao_meta_auditoria = models.DecimalField(max_digits=5, decimal_places=2, default=6.00, verbose_name="Ativação: Meta Auditoria")

    # Metas de Manutenção
    manutencao_meta_volume = models.DecimalField(max_digits=5, decimal_places=2, default=6.00, verbose_name="Manutenção: Meta Volume")
    manutencao_meta_retrabalho = models.DecimalField(max_digits=5, decimal_places=2, default=4.00, verbose_name="Manutenção: Meta Retrabalho (%)")
    manutencao_meta_garantia_30d = models.DecimalField(max_digits=5, decimal_places=2, default=5.00, verbose_name="Manutenção: Meta Garantia 30d (%)")
    manutencao_meta_auditoria = models.DecimalField(max_digits=5, decimal_places=2, default=6.00, verbose_name="Manutenção: Meta Auditoria")

    class Meta:
        verbose_name = "Meta Operacional"
        verbose_name_plural = "Metas Operacionais"
        unique_together = ('ano', 'mes')

    def __str__(self):
        return f"Metas de {self.get_mes_display()}/{self.ano}"


