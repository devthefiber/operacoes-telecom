import os
from celery import Celery
##### Define o module de configurações padrão do Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core_project.settings')
app = Celery('core_project')
##### Lê as configurações do settings.py usando o prefixo CELERY_
app.config_from_object('django.conf:settings', namespace='CELERY')
##### Carrega tarefas de todos os aplicativos registrados (tasks.py)
app.autodiscover_tasks()

# ==========================================
# AGENDAMENTOS AUTOMÁTICOS (CELERY BEAT)
# ==========================================
from celery.schedules import crontab

app.conf.beat_schedule = {
    'sincronizar-dw-toda-madrugada': {
        'task': 'sincronizar_dados_do_airflow',
        # Executa todos os dias às 03:00 da manhã
        'schedule': crontab(hour=3, minute=0),
    },
}