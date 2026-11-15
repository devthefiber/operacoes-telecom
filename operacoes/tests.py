import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import jwt
from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from operacoes.models import (
    AlocacaoMensal,
    BaseCliente,
    Cliente,
    Colaborador,
    Feriado,
    OrdemServico,
)
from operacoes.utils import garantir_alocacao_mes


def _fake_date_cls(ano: int, mes: int, dia: int):
    """Cria uma subclasse de datetime.date com today() fixado para testes."""
    class FakeDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(ano, mes, dia)

    return FakeDate


@override_settings(
    ALLOWED_HOSTS=['*'],
    STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage',
)
class ViradaDeAnoOperacoesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='admin_teste',
            password='123',
            is_staff=True,
            is_superuser=True,
        )
        self.client = Client()
        self.client.force_login(self.user)

        self.supervisor = Colaborador.objects.create(
            nome='SUPERVISOR MANUT',
            tipo='SUPERVISOR',
            setor='MANUTENCAO',
            ativo=True,
        )
        self.tecnico = Colaborador.objects.create(
            nome='TECNICO CAMPO 1',
            tipo='TECNICO',
            setor='MANUTENCAO',
            supervisor=self.supervisor,
            ativo=True,
        )
        AlocacaoMensal.objects.create(
            colaborador=self.tecnico,
            mes=12,
            ano=2026,
            supervisor=self.supervisor,
            setor='MANUTENCAO',
            contratacao='CLT',
        )
        self.cliente = Cliente.objects.create(nome='CLIENTE TESTE')
        OrdemServico.objects.create(
            id_ixc=900001,
            cliente=self.cliente,
            colaborador=self.tecnico,
            nome_setor='SERVIÇO',
            assunto='INSTALAÇÃO FIBRA',
            status='F',
            data_abertura=datetime.datetime(2026, 12, 15, 10, 0, tzinfo=ZoneInfo('America/Sao_Paulo')),
            data_fechamento=datetime.datetime(2026, 12, 15, 15, 0, tzinfo=ZoneInfo('America/Sao_Paulo')),
        )
        Feriado.objects.create(data=datetime.date(2026, 12, 25), descricao='Natal')

    def test_dashboard_seletor_ano_e_recuo_virada_ano(self):
        fake_jan_1 = datetime.datetime(2027, 1, 1, 9, 0, tzinfo=ZoneInfo('America/Sao_Paulo'))

        def fake_localtime(dt=None):
            return fake_jan_1 if dt is None else dt.astimezone(ZoneInfo('America/Sao_Paulo'))

        # Sem OS fechada em 01/2027, recua para 12/2026 mas oferece [2027, 2026] no select
        with patch('operacoes.views.timezone.localtime', side_effect=fake_localtime):
            resp = self.client.get(reverse('dashboard_operacoes'))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['mes_atual'], 12)
        self.assertEqual(resp.context['ano_atual'], 2026)
        self.assertEqual(resp.context['anos_disponiveis'], [2027, 2026])
        self.assertContains(resp, '<select name="ano"')
        self.assertContains(resp, '<option value="2026" selected>2026</option>')
        self.assertContains(resp, '<option value="2027" >2027</option>')
        self.assertNotContains(resp, '<input type="hidden" name="ano"')

        # Após fechar 1 OS em Jan/2027, entra em 01/2027 e permite voltar para 12/2026 pela UI
        OrdemServico.objects.create(
            id_ixc=900002,
            cliente=self.cliente,
            colaborador=self.tecnico,
            nome_setor='SERVIÇO',
            assunto='INSTALAÇÃO FIBRA',
            status='F',
            data_abertura=datetime.datetime(2027, 1, 2, 10, 0, tzinfo=ZoneInfo('America/Sao_Paulo')),
            data_fechamento=datetime.datetime(2027, 1, 2, 16, 0, tzinfo=ZoneInfo('America/Sao_Paulo')),
        )
        with patch('operacoes.views.timezone.localtime', side_effect=fake_localtime):
            resp_2027 = self.client.get(reverse('dashboard_operacoes'))

        self.assertEqual(resp_2027.status_code, 200)
        self.assertEqual(resp_2027.context['mes_atual'], 1)
        self.assertEqual(resp_2027.context['ano_atual'], 2027)
        self.assertEqual(resp_2027.context['anos_disponiveis'], [2027, 2026])
        self.assertContains(resp_2027, '<option value="2027" selected>2027</option>')

        # Voltando manualmente para 12/2026 via select (GET ?mes=12&ano=2026)
        resp_volta = self.client.get(reverse('dashboard_operacoes'), {'mes': '12', 'ano': '2026'})
        self.assertEqual(resp_volta.status_code, 200)
        self.assertEqual(resp_volta.context['mes_atual'], 12)
        self.assertEqual(resp_volta.context['ano_atual'], 2026)
        self.assertContains(resp_volta, '<option value="2026" selected>2026</option>')

    def test_feriados_inclui_ano_novo_sem_registros_e_preserva_ano_ao_salvar_excluir(self):
        # Em Jan/2027 sem nenhum feriado cadastrado em 2027, 2027 precisa aparecer no select
        with patch('datetime.date', _fake_date_cls(2027, 1, 1)):
            resp = self.client.get(reverse('configuracoes_feriados'))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['ano_selecionado'], 2027)
        self.assertEqual(resp.context['anos_disponiveis'], [2028, 2027, 2026])
        self.assertContains(resp, '<option value="2027" selected>2027</option>')

        # Cadastrar feriado em 2027 redireciona mantendo ?ano=2027
        resp_post = self.client.post(
            reverse('salvar_feriado'),
            {'data': '2027-01-01', 'descricao': 'Confraternização Universal'},
        )
        self.assertRedirects(
            resp_post,
            f"{reverse('configuracoes_feriados')}?ano=2027",
            fetch_redirect_response=False,
        )
        feriado_2027 = Feriado.objects.get(data=datetime.date(2027, 1, 1))

        resp_del = self.client.get(reverse('excluir_feriado', args=[feriado_2027.id]))
        self.assertRedirects(
            resp_del,
            f"{reverse('configuracoes_feriados')}?ano=2027",
            fetch_redirect_response=False,
        )

    def test_metas_e_base_cliente_virada_ano(self):
        with patch('datetime.date', _fake_date_cls(2027, 1, 5)):
            resp_metas = self.client.get(reverse('configuracoes_metas'))
            resp_base = self.client.get(reverse('configuracoes_base_cliente'))

        self.assertEqual(resp_metas.status_code, 200)
        self.assertEqual(resp_metas.context['ano_atual'], 2027)
        self.assertContains(resp_metas, 'id="modalAno" value="2027"')

        self.assertEqual(resp_base.status_code, 200)
        self.assertEqual(resp_base.context['ano_selecionado'], 2027)
        self.assertIn(2027, resp_base.context['anos_disponiveis'])
        self.assertIn(2028, resp_base.context['anos_disponiveis'])
        self.assertEqual(BaseCliente.objects.filter(ano=2027).count(), 12)
        self.assertEqual(BaseCliente.objects.get(ano=2027, mes=1).base, 0)

    def test_api_tecnicos_supervisores_virada_ano(self):
        token = jwt.encode(
            {'service': 'dash_estoque', 'scope': 'operacoes_equipes'},
            settings.PORTAL_JWT_SECRET,
            algorithm='HS256',
        )
        if isinstance(token, bytes):
            token = token.decode('utf-8')

        anon_client = Client()
        headers = {'HTTP_AUTHORIZATION': f'Bearer {token}'}

        # Antes de existir AlocacaoMensal em 01/2027, faz fallback para 12/2026
        with patch('datetime.date', _fake_date_cls(2027, 1, 1)):
            resp_antes = anon_client.get(reverse('api_tecnicos_supervisores'), **headers)

        self.assertEqual(resp_antes.status_code, 200)
        data_antes = resp_antes.json()
        self.assertEqual(data_antes['mes_label'], '12/2026')
        self.assertFalse(data_antes['is_mes_corrente'])
        self.assertEqual(data_antes['colaboradores'][0]['supervisor_nome'], 'SUPERVISOR MANUT')

        # Depois da replicação (03:30 ou acesso), passa a servir 01/2027 mantendo vínculos
        garantir_alocacao_mes(1, 2027)
        with patch('datetime.date', _fake_date_cls(2027, 1, 1)):
            resp_depois = anon_client.get(reverse('api_tecnicos_supervisores'), **headers)

        self.assertEqual(resp_depois.status_code, 200)
        data_depois = resp_depois.json()
        self.assertEqual(data_depois['mes_label'], '01/2027')
        self.assertTrue(data_depois['is_mes_corrente'])
        self.assertEqual(data_depois['colaboradores'][0]['supervisor_nome'], 'SUPERVISOR MANUT')
