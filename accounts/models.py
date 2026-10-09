from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

class Perfil(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')
    
    # Campo customizado para forçar a criação de nova senha
    deve_trocar_senha = models.BooleanField(default=True)
    
    # Novos campos para gestão de acesso
    setor = models.CharField(max_length=100, blank=True, null=True, verbose_name="Setor / Cargo")
    
    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('APROVADO', 'Aprovado'),
        ('REJEITADO', 'Rejeitado'),
    ]
    status_solicitacao = models.CharField(max_length=20, choices=STATUS_CHOICES, default='APROVADO', verbose_name="Status de Acesso")

    def __str__(self):
        return self.user.username

@receiver(post_save, sender=User)
def criar_perfil_usuario(sender, instance, created, **kwargs):
    if created:
        Perfil.objects.create(user=instance)
