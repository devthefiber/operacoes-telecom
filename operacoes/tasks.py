from celery import shared_task
from django.core.management import call_command
import logging

logger = logging.getLogger(__name__)

@shared_task(bind=True, name="sincronizar_dados_do_airflow")
def sincronizar_dados_do_airflow(self):
    """
    Task assíncrona que puxa os dados do Airflow e depois 
    roda a inteligência de linkar as Ordens de Serviço (Reincidências)
    """
    try:
        logger.info("Iniciando importação de OS do DW do Airflow...")
        # Chama o comando que criamos anteriormente
        call_command('importar_os_airflow')
        
        logger.info("Importação concluída. Iniciando vínculo inteligente de OS...")
        # Chama o comando que linka a OS filha com a OS pai
        call_command('vincular_os')
        
        logger.info("Sincronização 100% concluída com sucesso!")
        return "Sincronização concluída com sucesso!"
    except Exception as e:
        logger.error(f"Erro na sincronização do Airflow: {str(e)}")
        raise e
