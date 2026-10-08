from django.core.management.base import BaseCommand
from django.db import connections
from operacoes.models import Cliente, Colaborador, OrdemServico
from django.utils import timezone
import datetime

class Command(BaseCommand):
    help = 'Importa as Ordens de Serviço da tabela relatorio_os_setembro gerada pelo Airflow'

    def dictfetchall(self, cursor):
        "Return all rows from a cursor as a dict"
        columns = [col[0] for col in cursor.description]
        return [
            dict(zip(columns, row))
            for row in cursor.fetchall()
        ]

    def handle(self, *args, **kwargs):
        self.stdout.write("Conectando ao banco do Airflow (DW)...")
        
        try:
            with connections['dw'].cursor() as cursor:
                cursor.execute('SELECT * FROM relatorio_os_setembro')
                rows = self.dictfetchall(cursor)
            
            self.stdout.write(self.style.SUCCESS(f"Sucesso! {len(rows)} registros encontrados na tabela do Airflow."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Erro ao ler banco DW do Airflow: {e}"))
            return

        novas_os = 0
        clientes_criados = 0
        tecnicos_criados = 0

        self.stdout.write("Carregando cache do banco local (isso deixa o processo 100x mais rápido)...")
        cache_clientes = {c.nome: c for c in Cliente.objects.all()}
        cache_tecnicos = {t.nome: t for t in Colaborador.objects.filter(tipo='TECNICO')}
        cache_os = {os.id_ixc: os for os in OrdemServico.objects.all()}

        novas_os_list = []
        update_os_list = []

        self.stdout.write("Processando linhas na memória...")
        seen_ids = set()

        for row in rows:
            id_ixc = row.get('ID')
            if not id_ixc or str(id_ixc).lower() == 'none':
                continue
            
            id_ixc = int(float(id_ixc))
            
            if id_ixc in seen_ids:
                continue
            seen_ids.add(id_ixc)

            # 1. Tratar o Cliente
            nome_cliente = str(row.get('Cliente', '')).strip()
            if not nome_cliente or nome_cliente.lower() == 'none':
                nome_cliente = "CLIENTE NÃO IDENTIFICADO"
                
            cliente = cache_clientes.get(nome_cliente)
            if not cliente:
                cliente = Cliente.objects.create(
                    nome=nome_cliente,
                    contrato=str(row.get('Contrato', '')),
                    cidade=str(row.get('Cidade', '')),
                    bairro=str(row.get('Bairro', '')),
                    telefone_celular=str(row.get('Telefone celular', '')),
                    whatsapp=str(row.get('Whatsapp', ''))
                )
                cache_clientes[nome_cliente] = cliente
                clientes_criados += 1

            # 2. Tratar o Colaborador (Técnico)
            nome_tecnico = str(row.get('Colaborador', '')).strip()
            tecnico = None
            if nome_tecnico and nome_tecnico.lower() != 'none':
                tecnico = cache_tecnicos.get(nome_tecnico)
                if not tecnico:
                    tecnico = Colaborador.objects.create(nome=nome_tecnico, tipo='TECNICO')
                    cache_tecnicos[nome_tecnico] = tecnico
                    tecnicos_criados += 1

            # Datas
            def parse_date(date_str):
                if not date_str or str(date_str).lower() in ['none', 'nat', '']:
                    return None
                try:
                    return datetime.datetime.strptime(str(date_str)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
                except Exception as e:
                    return None

            data_abertura = parse_date(row.get('Abertura'))
            data_fechamento = parse_date(row.get('Fechamento'))

            # 3. Preparar a Ordem de Serviço
            os_obj = cache_os.get(id_ixc)
            
            if not os_obj:
                nova_os = OrdemServico(
                    id_ixc=id_ixc,
                    cliente=cliente,
                    colaborador=tecnico,
                    tipo=str(row.get('Tipo', '')),
                    assunto=str(row.get('Assunto', '')),
                    setor_ixc=str(row.get('Setor_ID', '')),
                    nome_setor=str(row.get('Setor', '')),
                    status=str(row.get('Status', '')),
                    protocolo=str(row.get('Protocolo', '')),
                    diagnostico=str(row.get('Diagnóstico', '')),
                    mensagem=str(row.get('Mensagem', '')),
                    data_abertura=data_abertura,
                    data_fechamento=data_fechamento,
                )
                novas_os_list.append(nova_os)
                novas_os += 1
            else:
                mudou = False
                if os_obj.cliente_id != (cliente.id if cliente else None): os_obj.cliente_id = cliente.id if cliente else None; mudou = True
                if os_obj.colaborador_id != (tecnico.id if tecnico else None): os_obj.colaborador_id = tecnico.id if tecnico else None; mudou = True
                if os_obj.tipo != str(row.get('Tipo', '')): os_obj.tipo = str(row.get('Tipo', '')); mudou = True
                if os_obj.assunto != str(row.get('Assunto', '')): os_obj.assunto = str(row.get('Assunto', '')); mudou = True
                if os_obj.setor_ixc != str(row.get('Setor_ID', '')): os_obj.setor_ixc = str(row.get('Setor_ID', '')); mudou = True
                if os_obj.nome_setor != str(row.get('Setor', '')): os_obj.nome_setor = str(row.get('Setor', '')); mudou = True
                if os_obj.status != str(row.get('Status', '')): os_obj.status = str(row.get('Status', '')); mudou = True
                if os_obj.protocolo != str(row.get('Protocolo', '')): os_obj.protocolo = str(row.get('Protocolo', '')); mudou = True
                if os_obj.diagnostico != str(row.get('Diagnóstico', '')): os_obj.diagnostico = str(row.get('Diagnóstico', '')); mudou = True
                if os_obj.mensagem != str(row.get('Mensagem', '')): os_obj.mensagem = str(row.get('Mensagem', '')); mudou = True
                if os_obj.data_abertura != data_abertura: os_obj.data_abertura = data_abertura; mudou = True
                if os_obj.data_fechamento != data_fechamento: os_obj.data_fechamento = data_fechamento; mudou = True
                
                if mudou:
                    update_os_list.append(os_obj)

        self.stdout.write("Salvando no banco de dados...")
        if novas_os_list:
            OrdemServico.objects.bulk_create(novas_os_list, batch_size=500)
        
        if update_os_list:
            OrdemServico.objects.bulk_update(
                update_os_list, 
                ['cliente', 'colaborador', 'tipo', 'assunto', 'setor_ixc', 'nome_setor', 'status', 'protocolo', 'diagnostico', 'mensagem', 'data_abertura', 'data_fechamento'], 
                batch_size=500
            )

        self.stdout.write(self.style.SUCCESS(f"Importação Concluída em velocidade recorde!"))
        self.stdout.write(f"- Clientes Novos: {clientes_criados}")
        self.stdout.write(f"- Técnicos Novos: {tecnicos_criados}")
        self.stdout.write(f"- OS Criadas: {novas_os}")
        self.stdout.write(f"- OS Atualizadas: {len(update_os_list)}")
