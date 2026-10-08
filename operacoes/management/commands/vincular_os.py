from django.core.management.base import BaseCommand
from operacoes.models import OrdemServico
from django.db.models import Q

class Command(BaseCommand):
    help = 'Vincula OS filhas (Auditoria/Reincidência) com a última Instalação/Manutenção do cliente'

    def handle(self, *args, **kwargs):
        self.stdout.write("Procurando OS que precisam ser vinculadas...")

        # Critério: Quais OS são "Filhas" (Reincidência ou Auditoria)?
        # - Assunto tem a palavra 'AUDITORIA' ou 'REINCIDENCIA' ou 'FIELD AUDIT'
        # - Setor é 'CONTROLE DE QUALIDADE...'
        
        filhas = OrdemServico.objects.filter(
            Q(assunto__icontains='AUDITORIA') |
            Q(assunto__icontains='REINCIDENCIA') |
            Q(assunto__icontains='FIELD AUDIT') |
            Q(assunto__icontains='CONTROLE DE QUALIDADE'),
            os_original__isnull=True,
            cliente__isnull=False
        ).order_by('data_abertura')

        self.stdout.write(f"Encontradas {filhas.count()} OS filhas para vincular.")

        vinculos = 0
        for filha in filhas:
            if not filha.data_abertura:
                continue
                
            # Procurar a última OS "Pai" deste mesmo cliente que seja ANTES da OS filha
            # OS Pai NÃO PODE ser auditoria ou reincidência
            # E preferencialmente com assunto de Instalação ou Reparo
            pai = OrdemServico.objects.filter(
                cliente=filha.cliente,
                data_fechamento__lte=filha.data_abertura
            ).exclude(
                Q(assunto__icontains='AUDITORIA') |
                Q(assunto__icontains='REINCIDENCIA') |
                Q(assunto__icontains='FIELD AUDIT') |
                Q(assunto__icontains='CONTROLE DE QUALIDADE')
            ).order_by('-data_fechamento').first()

            if pai:
                filha.os_original = pai
                filha.save(update_fields=['os_original'])
                vinculos += 1

        self.stdout.write(self.style.SUCCESS(f"Concluído! Foram criados {vinculos} vínculos inteligentes."))
