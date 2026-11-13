from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils import timezone
from django.views.decorators.http import require_GET
from .models import OrdemServico, MetaOperacional, Colaborador, Cargo, Feriado, AlocacaoMensal, RegraAssunto, BaseCliente
from .utils import calcular_dias_uteis, garantir_alocacao_mes, get_assuntos_regras, sincronizar_assuntos_disponiveis, get_base_cliente, calcular_tt_base, garantir_base_clientes
from django.db.models import Count, Q, Q
from django.contrib import messages
from collections import Counter

# Assuntos que compõem a aba 'Colar base' do Excel (base onde o técnico é buscado pelo nome do cliente)
ASSUNTO_AUD_REPROVADA = 'CONTROLE DE QUALIDADE  EM CAMPO REPROVADA'


@login_required
def dashboard_operacoes(request):
    agora = timezone.now()
    
    try:
        mes_atual = int(request.GET.get('mes', agora.month))
        ano_atual = int(request.GET.get('ano', agora.year))
    except (ValueError, TypeError):
        mes_atual = agora.month
        ano_atual = agora.year

    # Se o usuário NÃO passou o filtro na URL e não houver dados neste mês, recua automaticamente
    if not request.GET.get('mes') and not request.GET.get('ano'):
        if not OrdemServico.objects.filter(data_fechamento__year=ano_atual, data_fechamento__month=mes_atual).exists():
            ultima_os = OrdemServico.objects.order_by('-data_fechamento').first()
            if ultima_os and ultima_os.data_fechamento:
                mes_atual = ultima_os.data_fechamento.month
                ano_atual = ultima_os.data_fechamento.year
    
    # Garante alocação do mês (se virar o mês, replica do anterior automaticamente)
    garantir_alocacao_mes(mes_atual, ano_atual)

    # Busca a meta do mês, se não achar cria uma padrão para não quebrar
    meta, created = MetaOperacional.objects.get_or_create(
        ano=ano_atual, mes=mes_atual,
        defaults={
            'ativacao_meta_volume': 6.00, 'ativacao_meta_reincidencia': 5.00, 'ativacao_meta_auditoria': 6.00,
            'manutencao_meta_volume': 6.00, 'manutencao_meta_retrabalho': 4.00, 'manutencao_meta_garantia_30d': 5.00, 'manutencao_meta_auditoria': 6.00
        }
    )

    # 1. Calcular Dias Úteis usando o nosso Utils
    dias_uteis = calcular_dias_uteis(ano_atual, mes_atual)
    trabalhados = dias_uteis['trabalhados']

    # 2. Filtrar as OS do Mês
    os_mes = OrdemServico.objects.filter(
        data_fechamento__year=ano_atual,
        data_fechamento__month=mes_atual,
        expurgo__isnull=True
    ).exclude(status__icontains='Cancelada')

    # Base 1 (ATUAL M): auditorias fechadas no mês vigente
    # Base 2 (-M): auditorias fechadas no mês anterior -> técnico também buscado na Colar base do mês vigente E ANTERIOR
    mes_ant, ano_ant = (mes_atual - 1, ano_atual) if mes_atual > 1 else (12, ano_atual - 1)
    os_mes_ant = OrdemServico.objects.filter(
        data_fechamento__year=ano_ant, data_fechamento__month=mes_ant, expurgo__isnull=True
    ).exclude(status__icontains='Cancelada')

    def _norm(s):
        return (s or '').replace('\xa0', ' ').strip().upper()

    import re
    def _norm_assunto(s):
        return re.sub(r'\s+', ' ', _norm(s))

    colar_tec, clientes_reprov = {}, set()
    colar_tec_fisc = {}
    # Junta as execuções do mês atual e mês anterior para o VLOOKUP do técnico
    for cli_nome, tec_id, assunto, nome_setor in (os_mes | os_mes_ant).order_by('-id_ixc').values_list('cliente__nome', 'colaborador_id', 'assunto', 'nome_setor'):
        if not nome_setor or _norm(nome_setor) not in ['SERVIÇO', 'SUPORTE', 'RETRABALHO']:
            continue
        ass = _norm_assunto(assunto)
        if '[OP] FIELD AUDIT' in ass:
            continue
        cli = _norm(cli_nome)
        if cli not in colar_tec:
            colar_tec[cli] = set()
        colar_tec[cli].add(tec_id)
        
    # FISC AUD: Pega TODOS os técnicos, mas APENAS do MÊS VIGENTE
    for cli_nome, tec_id, assunto, nome_setor in os_mes.order_by('-id_ixc').values_list('cliente__nome', 'colaborador_id', 'assunto', 'nome_setor'):
        if not nome_setor or _norm(nome_setor) not in ['SERVIÇO', 'SUPORTE', 'RETRABALHO']:
            continue
        ass = _norm_assunto(assunto)
        if '[OP] FIELD AUDIT' in ass:
            continue
        cli = _norm(cli_nome)
        if cli not in colar_tec_fisc:
            colar_tec_fisc[cli] = set()
        colar_tec_fisc[cli].add(tec_id)
        
    # As reprovações contam APENAS se ocorreram no mês vigente!
    for cli_nome in os_mes.filter(assunto__iexact=ASSUNTO_AUD_REPROVADA).values_list('cliente__nome', flat=True):
        clientes_reprov.add(_norm(cli_nome))
        
    aud_atual_por_tec, rep_por_tec = Counter(), Counter()
    # Pega todas as auditorias fechadas no mês VIGENTE (elas podem ser de ativações desse mês ou do anterior)
    for cli_nome in os_mes.filter(assunto__startswith='AUDITORIA').values_list('cliente__nome', flat=True):
        cli = _norm(cli_nome)
        tecnicos_ids = colar_tec.get(cli)
        if not tecnicos_ids:
            continue  # Ativação muito antiga ou não encontrada
            
        for tec_id in tecnicos_ids:
            aud_atual_por_tec[tec_id] += 1
            if cli in clientes_reprov:
                rep_por_tec[tec_id] += 1

    # Nova regra: FIELD AUDIT (FISC. AUD.)
    fisc_aud_aprov_por_tec, fisc_aud_reprov_por_tec = Counter(), Counter()
    for cli_nome, diag in os_mes.filter(assunto__icontains='[OP] FIELD AUDIT').values_list('cliente__nome', 'diagnostico'):
        cli = _norm(cli_nome)
        tecnicos_ids = colar_tec_fisc.get(cli)
        if not tecnicos_ids:
            continue
            
        for tec_id in tecnicos_ids:
            # Se for Reprovada, marca como Reprovada. Se for Aprovada, Aprovada.
            if diag and 'REPROVADA' in diag.upper():
                fisc_aud_reprov_por_tec[tec_id] += 1
            elif diag and 'APROVADA' in diag.upper():
                fisc_aud_aprov_por_tec[tec_id] += 1

    aud_por_tec = aud_atual_por_tec
    total_aud_fiber = sum(aud_por_tec.values())
    total_rep_fiber = sum(rep_por_tec.values())
    supervisores_com_aud = set()

    # 3. KPIs do Topo
    total_servicos = os_mes.filter(nome_setor__iexact='SERVIÇO').exclude(Q(assunto__icontains='AUDITORIA') | Q(assunto__icontains='REINCIDENCIA') | Q(assunto__icontains='FIELD AUDIT')).count()
    total_reincidencias = os_mes.filter(nome_setor__iexact='SUPORTE').exclude(assunto__icontains='[OP] FIELD AUDIT').count()
    total_auditorias = total_aud_fiber

    # 4. Agrupamento por Equipe e Técnico
    equipes_ativacao_dict = {}
    equipes_manutencao_dict = {}
    
    # Busca todos os técnicos que têm supervisor definido
    alocacoes = AlocacaoMensal.objects.filter(mes=mes_atual, ano=ano_atual, colaborador__tipo='TECNICO').exclude(supervisor__isnull=True).select_related('colaborador', 'supervisor')

    # De-Para dinâmico de assuntos de Garantia 30D e Suporte Ativação
    assuntos_garantia, assuntos_sup_ativacao = get_assuntos_regras()

    def calc_ating_reinc(real_pct, meta_val, is_ativacao=False):
        if not meta_val: return 0.0
        if real_pct <= 0:
            return 0.0 if is_ativacao else 400.0
        ating = (float(meta_val) / real_pct) * 100
        if not is_ativacao:
            return 400.0 if ating > 400.0 else ating
        return ating

    for aloc in alocacoes:
        tecnico = aloc.colaborador
        setor = aloc.supervisor.setor if aloc.supervisor else 'MANUTENCAO'
        
        if setor == 'MANUTENCAO':
            # Adiciona CLT ou PJ ao nome da equipe para separar os agrupamentos
            tipo_contrato = f" ({aloc.contratacao})" if aloc.contratacao else " (CLT)"
            nome_equipe = f"{aloc.supervisor.nome}{tipo_contrato}"
            target_dict = equipes_manutencao_dict
        else:
            nome_equipe = aloc.supervisor.nome
            target_dict = equipes_ativacao_dict

        if nome_equipe not in target_dict:
            target_dict[nome_equipe] = {
                'nome': nome_equipe,
                'tecnicos': [],
                'total_servicos': 0, 'total_suporte': 0, 'total_reinc': 0, 'total_auditorias': 0, 'total_reprov': 0
            }

        # Calcula métricas DO TÉCNICO
        ASSUNTOS_AUDITORIA = ['AUDITORIA', '[OP] FIELD AUDIT']

        # Serviços executados por este técnico
        t_servicos = os_mes.filter(
            nome_setor__iexact='SERVIÇO',
            colaborador=tecnico
        ).exclude(assunto__icontains='[OP] FIELD AUDIT').count()

        # Suporte executado por este técnico
        t_suporte = os_mes.filter(
            nome_setor__iexact='SUPORTE',
            colaborador=tecnico
        ).exclude(assunto__icontains='[OP] FIELD AUDIT').count()

        
        # Retrabalho/Suporte deste técnico
        if setor == 'MANUTENCAO':
            t_reinc = os_mes.filter(
                nome_setor__iexact='RETRABALHO',
                colaborador=tecnico
            ).exclude(assunto__icontains='[OP] FIELD AUDIT').count()
        else:
            # Ativação: Suporte (Reincidência) configurável no De-Para
            q_sup_ativ = Q()
            for ass_sup in assuntos_sup_ativacao:
                q_sup_ativ |= Q(assunto__icontains=ass_sup.strip())
            t_reinc = os_mes.filter(
                q_sup_ativ,
                colaborador=tecnico
            ).count()
        
        # Garantia 30D deste técnico configurável no De-Para
        q_garantia = Q()
        for ass_gart in assuntos_garantia:
            q_garantia |= Q(assunto__icontains=ass_gart.strip())
            
        t_gart = os_mes_ant.filter(
            q_garantia,
            colaborador=tecnico
        ).count()

        # Auditorias (Tanto da base atual quanto do mês anterior, contabilizadas neste mês)
        t_aud = aud_por_tec.get(tecnico.id, 0)

        # REPROVADO = auditoria do mês cujo cliente tem 'CONTROLE DE QUALIDADE EM CAMPO REPROVADA' na Colar base
        t_rep = rep_por_tec.get(tecnico.id, 0)
        
        # FISC. AUD.
        t_fisc_aprov = fisc_aud_aprov_por_tec.get(tecnico.id, 0)
        t_fisc_reprov = fisc_aud_reprov_por_tec.get(tecnico.id, 0)
        
        if t_aud:
            supervisores_com_aud.add(aloc.supervisor_id)


        # Matemáticas
        volume_total = t_servicos + t_suporte
        real_dia = float(volume_total) / float(trabalhados) if trabalhados else 0.0
        pct_ating_serv = 0.0
        if setor == 'MANUTENCAO':
            pct_ating_serv = (real_dia / float(meta.manutencao_meta_volume) * 100) if meta.manutencao_meta_volume else 0.0
        else:
            pct_ating_serv = (real_dia / float(meta.ativacao_meta_volume) * 100) if meta.ativacao_meta_volume else 0.0
            
        pct_reinc = (float(t_reinc) / float(volume_total) * 100) if volume_total else 0.0
        pct_gart = (float(t_gart) / float(volume_total) * 100) if volume_total else 0.0

        pct_ating_reinc = 0.0
        if setor == 'MANUTENCAO':
            pct_ating_reinc = calc_ating_reinc(pct_reinc, meta.manutencao_meta_retrabalho, False)
        else:
            pct_ating_reinc = calc_ating_reinc(pct_reinc, meta.ativacao_meta_reincidencia, True)

        target_dict[nome_equipe]['tecnicos'].append({
            'nome': tecnico.nome,
            'marcacao': aloc.marcacao if aloc and aloc.marcacao else '',
            'contabiliza': aloc.contabiliza_indicadores,
            'servicos': t_servicos,
            'suporte': t_suporte,
            'total_volume': volume_total,
            'real_dia': real_dia,
            'pct_ating': pct_ating_serv,
            'reincidencias': t_reinc,
            'pct_reinc': pct_reinc,
            'pct_ating_reinc': pct_ating_reinc,
            'garantia_30d': t_gart,
            'pct_gart': pct_gart,
            'auditorias': t_aud,
            'aud_atual': t_aud,
            'aud_ant': 0,
            'reprovadas': t_rep,
            'aprovadas': t_aud - t_rep,
            'fisc_aud_aprov': t_fisc_aprov,
            'fisc_aud_reprov': t_fisc_reprov,
            'pct_fisc': (float(t_aud) / float(volume_total) * 100) if volume_total else 0.0,
            'real_aud': float(t_aud) / float(trabalhados) if trabalhados else 0.0,
            'pct_ating_aud': ((float(t_aud) / float(trabalhados)) / float(meta.manutencao_meta_auditoria) * 100) if (trabalhados and meta.manutencao_meta_auditoria) else 0.0,
            'res_tecnico_vol': pct_ating_serv * 0.8,
            'res_tecnico_ret': pct_ating_reinc * 0.2,
            'resultado_tecnico': (pct_ating_serv * 0.8) + (pct_ating_reinc * 0.2)
        })

        # Soma no Subtotal da Equipe
        if aloc.contabiliza_indicadores:
            target_dict[nome_equipe]['total_servicos'] += t_servicos
            target_dict[nome_equipe]['total_suporte'] += t_suporte
            target_dict[nome_equipe]['total_volume'] = target_dict[nome_equipe].get('total_volume', 0) + volume_total
            target_dict[nome_equipe]['soma_real_dia'] = target_dict[nome_equipe].get('soma_real_dia', 0) + real_dia
            target_dict[nome_equipe]['qtd_tecnicos'] = target_dict[nome_equipe].get('qtd_tecnicos', 0) + 1
            target_dict[nome_equipe]['total_reinc'] += t_reinc
            target_dict[nome_equipe]['total_gart'] = target_dict[nome_equipe].get('total_gart', 0) + t_gart
            target_dict[nome_equipe]['total_auditorias'] += t_aud
            target_dict[nome_equipe]['total_reprov'] += t_rep
            target_dict[nome_equipe]['total_aprov'] = target_dict[nome_equipe].get('total_aprov', 0) + (t_aud - t_rep)
            target_dict[nome_equipe]['total_fisc_aprov'] = target_dict[nome_equipe].get('total_fisc_aprov', 0) + t_fisc_aprov
            target_dict[nome_equipe]['total_fisc_reprov'] = target_dict[nome_equipe].get('total_fisc_reprov', 0) + t_fisc_reprov

    # Pós-processamento Equipes para médias
    for eq in equipes_ativacao_dict.values():
        eq['real_dia_medio'] = (eq['soma_real_dia'] / eq['qtd_tecnicos']) if eq.get('qtd_tecnicos') else 0
        eq['pct_ating_medio'] = (eq['real_dia_medio'] / float(meta.ativacao_meta_volume) * 100) if meta.ativacao_meta_volume else 0
        eq['pct_reinc'] = (eq['total_reinc'] / eq['total_servicos'] * 100) if eq.get('total_servicos') else 0.0
        eq['pct_ating_reinc'] = calc_ating_reinc(eq['pct_reinc'], meta.ativacao_meta_reincidencia)
        eq['pct_fisc'] = (eq['total_auditorias'] / eq['total_servicos'] * 100) if eq.get('total_servicos') else 0.0
        eq['real_aud'] = float(eq['total_auditorias']) / float(trabalhados) if trabalhados else 0.0
        eq['pct_ating_aud'] = (eq['real_aud'] / float(meta.ativacao_meta_auditoria) * 100) if meta.ativacao_meta_auditoria else 0.0
        eq['res_tecnico_vol'] = eq['pct_ating_medio'] * 0.8
        eq['res_tecnico_ret'] = eq['pct_ating_reinc'] * 0.2
        eq['resultado_tecnico'] = (eq['pct_ating_medio'] * 0.8) + (eq['pct_ating_reinc'] * 0.2)

    for eq in equipes_manutencao_dict.values():
        eq['real_dia_medio'] = (eq['soma_real_dia'] / eq['qtd_tecnicos']) if eq.get('qtd_tecnicos') else 0
        eq['pct_ating_medio'] = (eq['real_dia_medio'] / float(meta.manutencao_meta_volume) * 100) if meta.manutencao_meta_volume else 0
        eq['pct_reinc'] = (eq['total_reinc'] / eq['total_volume'] * 100) if eq.get('total_volume') else 0.0
        eq['pct_ating_reinc'] = calc_ating_reinc(eq['pct_reinc'], meta.manutencao_meta_retrabalho)
        eq['pct_gart'] = (eq['total_gart'] / eq['total_volume'] * 100) if eq.get('total_volume') else 0.0
        eq['pct_fisc'] = (eq['total_auditorias'] / eq['total_volume'] * 100) if eq.get('total_volume') else 0.0
        eq['real_aud'] = float(eq['total_auditorias']) / float(trabalhados) if trabalhados else 0.0
        eq['pct_ating_aud'] = (eq['real_aud'] / float(meta.manutencao_meta_auditoria) * 100) if meta.manutencao_meta_auditoria else 0.0
        eq['res_tecnico_vol'] = eq['pct_ating_medio'] * 0.8
        eq['res_tecnico_ret'] = eq['pct_ating_reinc'] * 0.2
        eq['resultado_tecnico'] = (eq['pct_ating_medio'] * 0.8) + (eq['pct_ating_reinc'] * 0.2)

    # Calcular Totais Gerais
    total_ativacao = {'servicos': 0, 'reinc': 0, 'auditorias': 0, 'reprov': 0, 'aprov': 0, 'pct_reinc': 0, 'soma_real': 0, 'qtd': 0}
    for eq in equipes_ativacao_dict.values():
        total_ativacao['servicos'] += eq['total_servicos']
        total_ativacao['reinc'] += eq['total_reinc']
        total_ativacao['auditorias'] += eq['total_auditorias']
        total_ativacao['reprov'] += eq['total_reprov']
        total_ativacao['aprov'] += eq.get('total_aprov', 0)
        total_ativacao['fisc_aud_aprov'] = total_ativacao.get('fisc_aud_aprov', 0) + eq.get('total_fisc_aprov', 0)
        total_ativacao['fisc_aud_reprov'] = total_ativacao.get('fisc_aud_reprov', 0) + eq.get('total_fisc_reprov', 0)
        total_ativacao['soma_real'] += eq['soma_real_dia']
        total_ativacao['qtd'] += eq['qtd_tecnicos']
    if total_ativacao['servicos'] > 0:
        total_ativacao['pct_reinc'] = (total_ativacao['reinc'] / total_ativacao['servicos']) * 100
        total_ativacao['pct_fisc'] = (total_ativacao['auditorias'] / total_ativacao['servicos']) * 100
    else:
        total_ativacao['pct_fisc'] = 0.0
    total_ativacao['pct_ating_reinc'] = calc_ating_reinc(total_ativacao.get('pct_reinc', 0), meta.ativacao_meta_reincidencia)
    total_ativacao['real_medio'] = (total_ativacao['soma_real'] / total_ativacao['qtd']) if total_ativacao['qtd'] else 0
    total_ativacao['pct_ating'] = (total_ativacao['real_medio'] / float(meta.ativacao_meta_volume) * 100) if meta.ativacao_meta_volume else 0
    total_ativacao['res_tecnico_vol'] = total_ativacao['pct_ating'] * 0.8
    total_ativacao['res_tecnico_ret'] = total_ativacao['pct_ating_reinc'] * 0.2
    total_ativacao['resultado_tecnico'] = (total_ativacao['pct_ating'] * 0.8) + (total_ativacao['pct_ating_reinc'] * 0.2)
    
    # Auditoria no rodapé = TOTAL THE FIBER (não só do setor), conforme planilha
    volume_fiber = total_ativacao['servicos'] + sum(eq.get('total_volume', 0) for eq in equipes_manutencao_dict.values())
    qtd_sup_fiber = len(supervisores_com_aud) or 1
    aud_fiber = {
        'auditorias': total_aud_fiber,
        'reprov': total_rep_fiber,
        'aprov': total_aud_fiber - total_rep_fiber,
        'pct_fisc': (total_aud_fiber / volume_fiber * 100) if volume_fiber else 0.0,
    }
    
    # As métricas de % e atingimento de Ativação
    qtd_sup_ativ = len(set([k.split(' (')[0] for k in equipes_ativacao_dict.keys()])) or 1
    total_ativacao['pct_real_aud'] = (total_ativacao['auditorias'] / trabalhados) if trabalhados else 0.0
    total_ativacao['real_aud'] = total_ativacao['pct_real_aud'] / qtd_sup_ativ
    total_ativacao['pct_ating_aud'] = (total_ativacao['real_aud'] / float(meta.ativacao_meta_auditoria) * 100) if meta.ativacao_meta_auditoria else 0.0
    

    total_manutencao = {'servicos': 0, 'suporte': 0, 'volume': 0, 'reinc': 0, 'gart': 0, 'auditorias': 0, 'reprov': 0, 'aprov': 0, 'pct_reinc': 0, 'soma_real': 0, 'qtd': 0}
    for eq in equipes_manutencao_dict.values():
        total_manutencao['servicos'] += eq['total_servicos']
        total_manutencao['suporte'] += eq['total_suporte']
        total_manutencao['volume'] += eq.get('total_volume', 0)
        total_manutencao['reinc'] += eq['total_reinc']
        total_manutencao['gart'] += eq.get('total_gart', 0)
        total_manutencao['auditorias'] += eq['total_auditorias']
        total_manutencao['reprov'] += eq['total_reprov']
        total_manutencao['aprov'] += eq.get('total_aprov', 0)
        total_manutencao['fisc_aud_aprov'] = total_manutencao.get('fisc_aud_aprov', 0) + eq.get('total_fisc_aprov', 0)
        total_manutencao['fisc_aud_reprov'] = total_manutencao.get('fisc_aud_reprov', 0) + eq.get('total_fisc_reprov', 0)
        total_manutencao['soma_real'] += eq['soma_real_dia']
        total_manutencao['qtd'] += eq['qtd_tecnicos']
    if total_manutencao['volume'] > 0:
        total_manutencao['pct_reinc'] = (total_manutencao['reinc'] / total_manutencao['volume']) * 100
        total_manutencao['pct_gart'] = (total_manutencao['gart'] / total_manutencao['volume']) * 100
        total_manutencao['pct_fisc'] = (total_manutencao['auditorias'] / total_manutencao['volume']) * 100
    else:
        total_manutencao['pct_gart'] = 0.0
        total_manutencao['pct_fisc'] = 0.0
    total_manutencao['pct_ating_reinc'] = calc_ating_reinc(total_manutencao.get('pct_reinc', 0), meta.manutencao_meta_retrabalho)
    total_manutencao['real_medio'] = (total_manutencao['soma_real'] / total_manutencao['qtd']) if total_manutencao['qtd'] else 0
    total_manutencao['pct_ating'] = (total_manutencao['real_medio'] / float(meta.manutencao_meta_volume) * 100) if meta.manutencao_meta_volume else 0
    total_manutencao['res_tecnico_vol'] = total_manutencao['pct_ating'] * 0.8
    total_manutencao['res_tecnico_ret'] = total_manutencao['pct_ating_reinc'] * 0.2
    total_manutencao['resultado_tecnico'] = (total_manutencao['pct_ating'] * 0.8) + (total_manutencao['pct_ating_reinc'] * 0.2)
    qtd_sup_manut = len(set([k.split(' (')[0] for k in equipes_manutencao_dict.keys()])) or 1
    total_manutencao['pct_real_aud'] = (total_manutencao['auditorias'] / trabalhados) if trabalhados else 0.0
    total_manutencao['real_aud'] = total_manutencao['pct_real_aud'] / qtd_sup_manut
    total_manutencao['pct_ating_aud'] = (total_manutencao['real_aud'] / float(meta.manutencao_meta_auditoria) * 100) if meta.manutencao_meta_auditoria else 0.0

    def criar_total_rafael(eq_dict, m_meta_vol, m_meta_reinc, setor='MANUTENCAO'):
        raf_keys = [k for k in eq_dict.keys() if 'RAFAEL' in k.upper()]
        if len(raf_keys) > 1:
            total_raf = {
                'nome': 'TOTAL RAFAEL (CLT + PJ)',
                'tecnicos': [],
                'total_servicos': sum(eq_dict[k].get('total_servicos', 0) for k in raf_keys),
                'total_suporte': sum(eq_dict[k].get('total_suporte', 0) for k in raf_keys),
                'total_volume': sum(eq_dict[k].get('total_volume', 0) for k in raf_keys),
                'soma_real_dia': sum(eq_dict[k].get('soma_real_dia', 0) for k in raf_keys),
                'qtd_tecnicos': sum(eq_dict[k].get('qtd_tecnicos', 0) for k in raf_keys),
                'total_reinc': sum(eq_dict[k].get('total_reinc', 0) for k in raf_keys),
                'total_gart': sum(eq_dict[k].get('total_gart', 0) for k in raf_keys),
                'total_auditorias': sum(eq_dict[k].get('total_auditorias', 0) for k in raf_keys),
                'total_reprov': sum(eq_dict[k].get('total_reprov', 0) for k in raf_keys),
                'total_aprov': sum(eq_dict[k].get('total_aprov', 0) for k in raf_keys),
            }
            total_raf['real_dia_medio'] = (total_raf['soma_real_dia'] / total_raf['qtd_tecnicos']) if total_raf['qtd_tecnicos'] else 0
            total_raf['pct_ating_medio'] = (total_raf['real_dia_medio'] / float(m_meta_vol) * 100) if m_meta_vol else 0
            
            if setor == 'MANUTENCAO':
                total_raf['pct_reinc'] = (total_raf['total_reinc'] / total_raf['total_volume'] * 100) if total_raf['total_volume'] > 0 else 0.0
                total_raf['pct_gart'] = (total_raf['total_gart'] / total_raf['total_volume'] * 100) if total_raf['total_volume'] > 0 else 0.0
            else:
                total_raf['pct_reinc'] = (total_raf['total_reinc'] / total_raf['total_servicos'] * 100) if total_raf['total_servicos'] > 0 else 0.0
                
            total_raf['pct_ating_reinc'] = calc_ating_reinc(total_raf.get('pct_reinc', 0), m_meta_reinc)
            base_fisc = total_raf['total_volume'] if setor == 'MANUTENCAO' else total_raf['total_servicos']
            total_raf['pct_fisc'] = (total_raf['total_auditorias'] / base_fisc * 100) if base_fisc else 0.0
            total_raf['real_aud'] = (total_raf['total_auditorias'] / trabalhados) if trabalhados else 0.0
            m_meta_aud = meta.manutencao_meta_auditoria if setor == 'MANUTENCAO' else meta.ativacao_meta_auditoria
            total_raf['pct_ating_aud'] = (total_raf['real_aud'] / float(m_meta_aud) * 100) if m_meta_aud else 0.0
            total_raf['res_tecnico_vol'] = total_raf['pct_ating_medio'] * 0.8
            total_raf['res_tecnico_ret'] = total_raf['pct_ating_reinc'] * 0.2
            total_raf['resultado_tecnico'] = (total_raf['pct_ating_medio'] * 0.8) + (total_raf['pct_ating_reinc'] * 0.2)
            return total_raf
        return None

    lista_ativacao = list(equipes_ativacao_dict.values())
    total_raf_at = criar_total_rafael(equipes_ativacao_dict, meta.ativacao_meta_volume, meta.ativacao_meta_reincidencia, 'ATIVACAO')
    if total_raf_at:
        lista_ativacao.append(total_raf_at)

    lista_manut = list(equipes_manutencao_dict.values())
    total_raf_man = criar_total_rafael(equipes_manutencao_dict, meta.manutencao_meta_volume, meta.manutencao_meta_retrabalho, 'MANUTENCAO')
    if total_raf_man:
        lista_manut.append(total_raf_man)

    

    # --- BLOCO TÉCNICOS A CLASSIFICAR ---
    colabs_os = os_mes.values_list('colaborador_id', flat=True).distinct()
    
    # Técnicos que têm OS, são TECNICOS e não têm supervisor neste mês (ou não têm alocação)
    tecnicos_desconhecidos = Colaborador.objects.filter(
        id__in=colabs_os,
        tipo='TECNICO',
        ativo=True
    ).exclude(
        alocacoes__mes=mes_atual, 
        alocacoes__ano=ano_atual, 
        alocacoes__supervisor__isnull=False
    )
    
    if tecnicos_desconhecidos.exists():
        lista_sem_equipe = []
        eq_total_serv = 0
        eq_total_sup = 0
        eq_total_vol = 0
        eq_total_reinc = 0
        eq_total_gart = 0
        eq_total_aud = 0
        eq_total_rep = 0
        eq_soma_real = 0.0
        
        for tec in tecnicos_desconhecidos:
            t_serv = os_mes.filter(nome_setor__iexact='SERVIÇO', colaborador=tec).exclude(assunto__icontains='[OP] FIELD AUDIT').count()
            t_sup = os_mes.filter(nome_setor__iexact='SUPORTE', colaborador=tec).exclude(assunto__icontains='[OP] FIELD AUDIT').count()
            t_total = t_serv + t_sup
            
            t_reinc = os_mes.filter(nome_setor__iexact='RETRABALHO', colaborador=tec).exclude(assunto__icontains='[OP] FIELD AUDIT').count()
            q_garantia_desc = Q()
            for ass_gart in assuntos_garantia:
                q_garantia_desc |= Q(assunto__icontains=ass_gart.strip())
            t_gart = os_mes.filter(q_garantia_desc, colaborador=tec).count()
            t_aud = aud_por_tec.get(tec.id, 0)
            t_rep = rep_por_tec.get(tec.id, 0)
            
            real_dia = float(t_total) / float(trabalhados) if trabalhados else 0.0
            pct_ating_serv = (real_dia / float(meta.manutencao_meta_volume) * 100) if meta and meta.manutencao_meta_volume else 0.0
            pct_reinc = (float(t_reinc) / float(t_total) * 100) if t_total else 0.0
            pct_ating_reinc = (pct_reinc / float(meta.manutencao_meta_retrabalho) * 100) if meta and meta.manutencao_meta_retrabalho else 0.0
            pct_gart = (float(t_gart) / float(t_total) * 100) if t_total else 0.0
            
            lista_sem_equipe.append({
                'nome': tec.nome,
                'servicos': t_serv,
                'suporte': t_sup,
                'total_volume': t_total,
                'real_dia': real_dia,
                'pct_ating': pct_ating_serv,
                'reincidencias': t_reinc,
                'pct_reinc': pct_reinc,
                'pct_ating_reinc': pct_ating_reinc,
                'garantia_30d': t_gart,
                'pct_gart': pct_gart,
                'auditorias': t_aud,
                'reprovadas': t_rep,
                'aprovadas': t_aud - t_rep
            })
            
            eq_total_serv += t_serv
            eq_total_sup += t_sup
            eq_total_vol += t_total
            eq_total_reinc += t_reinc
            eq_total_gart += t_gart
            eq_total_aud += t_aud
            eq_total_rep += t_rep
            eq_soma_real += real_dia
        
        real_dia_medio = eq_soma_real / len(lista_sem_equipe) if lista_sem_equipe else 0
        pct_ating_medio = (real_dia_medio / float(meta.manutencao_meta_volume) * 100) if meta and meta.manutencao_meta_volume else 0.0
        pct_reinc_eq = (eq_total_reinc / eq_total_vol * 100) if eq_total_vol else 0.0
        pct_ating_reinc_eq = (pct_reinc_eq / float(meta.manutencao_meta_retrabalho) * 100) if meta and meta.manutencao_meta_retrabalho else 0.0
        pct_gart_eq = (eq_total_gart / eq_total_vol * 100) if eq_total_vol else 0.0
        
        equipe_desconhecida = {
            'supervisor': '⚠️ TÉCNICOS A CLASSIFICAR',
            'tecnicos': lista_sem_equipe,
            'total_servicos': eq_total_serv,
            'total_suporte': eq_total_sup,
            'total_volume': eq_total_vol,
            'total_reinc': eq_total_reinc,
            'total_gart': eq_total_gart,
            'total_auditorias': eq_total_aud,
            'total_reprov': eq_total_rep,
            'soma_real_dia': eq_soma_real,
            'qtd_tecnicos': len(lista_sem_equipe),
            'tipo': 'DESCONHECIDO',
            
            'real_dia_medio': real_dia_medio,
            'pct_ating_medio': pct_ating_medio,
            'pct_reinc': pct_reinc_eq,
            'pct_ating_reinc': pct_ating_reinc_eq,
            'pct_gart': pct_gart_eq
        }
        # ATENÇÃO: NÃO damos append da equipe_desconhecida na lista_manut! 
        # Assim, as pessoas do Call Center que caem aqui por engano não poluem o Dashboard principal.
        # Eles vão continuar existindo na página "Configurações", mas somem da página inicial!

    # Cálculo do indicador TT Base (%)
    base_cliente_atual = get_base_cliente(ano_atual, mes_atual)
    tt_base_pct, projecao_suporte = calcular_tt_base(
        volume_suporte=total_manutencao.get('suporte', 0),
        dias_trabalhados=dias_uteis.get('trabalhados', 1.0),
        total_dias_uteis=dias_uteis.get('total_du', 1.0),
        base_clientes=base_cliente_atual
    )

    context = {
        'mes_atual': mes_atual,
        'ano_atual': ano_atual,
        'dias_uteis': dias_uteis,
        'meta': meta,
        'total_servicos': total_servicos,
        'total_reincidencias': total_reincidencias,
        'total_auditorias': total_auditorias,
        'taxa_reincidencia': (total_reincidencias / total_servicos * 100) if total_servicos > 0 else 0,
        'equipes_ativacao': lista_ativacao,
        'equipes_manutencao': lista_manut,
        'total_ativacao': total_ativacao,
        'total_manutencao': total_manutencao,
        'base_cliente_atual': base_cliente_atual,
        'tt_base_pct': tt_base_pct,
        'projecao_suporte': projecao_suporte,
    }
    return render(request, 'operacoes/dashboard.html', context)

@user_passes_test(lambda u: u.is_staff, login_url='/')
def configuracoes(request):
    import datetime
    from .models import OrdemServico, Colaborador, Cargo, AlocacaoMensal

    hoje = datetime.date.today()
    mes_atual = int(request.GET.get('mes', hoje.month))
    ano_atual = int(request.GET.get('ano', hoje.year))

    # Garante que o mês tenha alocação (se virar o mês, replica do anterior automaticamente)
    garantir_alocacao_mes(mes_atual, ano_atual)

    # Quem tem OS no banco
    colabs_com_os = OrdemServico.objects.values_list('colaborador_id', flat=True).distinct()

    supervisores = Colaborador.objects.filter(ativo=True, tipo='SUPERVISOR')
    
    # Técnicos que devem aparecer: têm OS no banco ou já têm alocação no mês
    tecnicos_qs = Colaborador.objects.filter(ativo=True, tipo='TECNICO').filter(
        Q(id__in=colabs_com_os) | Q(alocacoes__mes=mes_atual, alocacoes__ano=ano_atual)
    ).distinct()

    # Prepara a lista de técnicos com os dados de alocação DO MÊS
    tecnicos_alocados = []
    for tec in tecnicos_qs:
        aloc = AlocacaoMensal.objects.filter(colaborador=tec, mes=mes_atual, ano=ano_atual).first()
        tecnicos_alocados.append({
            'id': tec.id,
            'nome': tec.nome,
            'tipo': tec.tipo,
            'cargo_nome': aloc.cargo.nome if aloc and aloc.cargo else None,
            'cargo_id': aloc.cargo.id if aloc and aloc.cargo else None,
            'setor': aloc.setor if aloc else None,
            'contratacao': aloc.contratacao if aloc else None,
            'supervisor_nome': aloc.supervisor.nome if aloc and aloc.supervisor else None,
            'supervisor_id': aloc.supervisor.id if aloc and aloc.supervisor else None,
            'marcacao': aloc.marcacao if aloc and aloc.marcacao else (tec.marcacao or ''),
            'contabiliza': aloc.contabiliza_indicadores if aloc else True,
        })

    # Alerta de pendência: Tem OS neste mês mas não tem supervisor na alocação deste mês
    # Vamos cruzar OSs geradas no mês atual
    os_mes = OrdemServico.objects.filter(data_abertura__year=ano_atual, data_abertura__month=mes_atual)
    colabs_os_mes = os_mes.values_list('colaborador_id', flat=True).distinct()
    
    tecnicos_pendentes = Colaborador.objects.filter(
        id__in=colabs_os_mes,
        tipo='TECNICO',
        ativo=True
    ).exclude(
        alocacoes__mes=mes_atual,
        alocacoes__ano=ano_atual,
        alocacoes__supervisor__isnull=False
    ).count()

    # Verifica se já existe alguma alocação neste mês
    tem_alocacoes = AlocacaoMensal.objects.filter(mes=mes_atual, ano=ano_atual).exists()

    todos_colaboradores = Colaborador.objects.filter(ativo=True)
    cargos = Cargo.objects.all()

    context = {
        'mes_atual': mes_atual,
        'ano_atual': ano_atual,
        'tem_alocacoes': tem_alocacoes,
        'supervisores': supervisores,
        'tecnicos_alocados': tecnicos_alocados,
        'tecnicos_pendentes': tecnicos_pendentes,
        'todos_colaboradores': todos_colaboradores,
        'cargos': cargos,
        'tipos': Colaborador.TIPO_CHOICES,
        'setores': Colaborador.SETOR_CHOICES,
        'contratacoes': Colaborador.CONTRATACAO_CHOICES,
        'marcacoes': Colaborador.MARCACAO_CHOICES
    }
    return render(request, 'operacoes/configuracoes.html', context)

@user_passes_test(lambda u: u.is_staff, login_url='/')
def salvar_colaborador(request):
    import datetime
    from django.contrib import messages
    from django.shortcuts import redirect, get_object_or_404
    from .models import Colaborador, Cargo, AlocacaoMensal
    
    if request.method == 'POST':
        colaborador_id = request.POST.get('colaborador_id')
        tipo = request.POST.get('tipo')
        cargo_id = request.POST.get('cargo_id')
        setor = request.POST.get('setor')
        contratacao = request.POST.get('contratacao')
        supervisor_id = request.POST.get('supervisor_id')
        marcacao = request.POST.get('marcacao', '')
        contabiliza_indicadores = request.POST.get('contabiliza_indicadores') == 'on'
        
        mes = int(request.POST.get('mes', datetime.date.today().month))
        ano = int(request.POST.get('ano', datetime.date.today().year))
        
        cargo_obj = Cargo.objects.get(id=cargo_id) if cargo_id else None
        supervisor_obj = Colaborador.objects.get(id=supervisor_id) if supervisor_id else None

        if colaborador_id:
            c = get_object_or_404(Colaborador, id=colaborador_id)
            c.tipo = tipo
            # Atualiza tb o cadastro principal para legado/futuro
            c.cargo = cargo_obj
            c.setor = setor
            c.contratacao = contratacao
            c.supervisor = supervisor_obj
            c.marcacao = marcacao
            c.save()
            
            # Atualiza ou cria a alocacao mensal
            aloc, _ = AlocacaoMensal.objects.get_or_create(
                colaborador=c,
                mes=mes,
                ano=ano
            )
            aloc.cargo = cargo_obj
            aloc.setor = setor
            aloc.contratacao = contratacao
            aloc.supervisor = supervisor_obj
            aloc.marcacao = marcacao
            aloc.contabiliza_indicadores = contabiliza_indicadores
            aloc.save()
            
            messages.success(request, f'Colaborador {c.nome} atualizado para {mes:02d}/{ano} com sucesso!')
            
    return redirect(f'/configuracoes/?mes={mes}&ano={ano}')

@user_passes_test(lambda u: u.is_staff, login_url='/')
def excluir_papel(request, id):
    # Não exclui o funcionário, apenas tira o cargo de supervisor ou técnico, voltando a ser OUTRO
    c = get_object_or_404(Colaborador, id=id)
    c.tipo = 'OUTRO'
    c.cargo = None
    c.setor = None
    c.supervisor = None
    c.contratacao = None
    c.save()
    messages.success(request, f'Papel de {c.nome} removido. Ele voltou para a base geral.')
    return redirect('configuracoes')

@user_passes_test(lambda u: u.is_staff, login_url='/')
def salvar_cargo(request):
    if request.method == 'POST':
        cargo_id = request.POST.get('cargo_id')
        nome = request.POST.get('nome')
        if cargo_id:
            cargo = get_object_or_404(Cargo, id=cargo_id)
            cargo.nome = nome
            cargo.save()
            messages.success(request, 'Cargo atualizado com sucesso!')
        elif nome:
            Cargo.objects.get_or_create(nome=nome)
            messages.success(request, 'Cargo criado com sucesso!')
    return redirect('configuracoes')

@user_passes_test(lambda u: u.is_staff, login_url='/')
def excluir_cargo(request, id):
    cargo = get_object_or_404(Cargo, id=id)
    cargo.delete()
    messages.success(request, f'Cargo {cargo.nome} excluído com sucesso.')
    return redirect('configuracoes')

@user_passes_test(lambda u: u.is_staff, login_url='/')
def configuracoes_metas(request):
    metas = MetaOperacional.objects.all().order_by('-ano', '-mes')
    
    # Calcular dias uteis dinâmicos para visualização
    for m in metas:
        m.dias_uteis_calculado = calcular_dias_uteis(m.ano, m.mes)['total_du']

    

    context = {
        'metas': metas,
        'meses': MetaOperacional.MESES
    }
    return render(request, 'operacoes/configuracoes_metas.html', context)

@user_passes_test(lambda u: u.is_staff, login_url='/')
def configuracoes_feriados(request):
    import datetime
    ano_atual = datetime.date.today().year
    
    ano_selecionado = request.GET.get('ano', str(ano_atual))
    try:
        ano_selecionado = int(ano_selecionado)
    except:
        ano_selecionado = ano_atual
        
    feriados = Feriado.objects.filter(data__year=ano_selecionado).order_by('data')
    
    anos_disponiveis = Feriado.objects.dates('data', 'year').values_list('data__year', flat=True).distinct().order_by('data__year')
    if not anos_disponiveis:
        anos_disponiveis = [ano_atual]
        
    

    context = {
        'feriados': feriados,
        'ano_selecionado': ano_selecionado,
        'anos_disponiveis': anos_disponiveis,
    }
    return render(request, 'operacoes/configuracoes_feriados.html', context)

@user_passes_test(lambda u: u.is_staff, login_url='/')
def salvar_meta(request):
    if request.method == 'POST':
        meta_id = request.POST.get('meta_id')
        ano = request.POST.get('ano')
        mes = request.POST.get('mes')
        
        # Ativação
        a_vol = request.POST.get('ativacao_meta_volume', 0)
        a_reinc = request.POST.get('ativacao_meta_reincidencia', 0)
        a_aud = request.POST.get('ativacao_meta_auditoria', 0)
        
        # Manutenção
        m_vol = request.POST.get('manutencao_meta_volume', 0)
        m_ret = request.POST.get('manutencao_meta_retrabalho', 0)
        m_gar = request.POST.get('manutencao_meta_garantia_30d', 0)
        m_aud = request.POST.get('manutencao_meta_auditoria', 0)

        if meta_id:
            m = get_object_or_404(MetaOperacional, id=meta_id)
            m.ano = ano
            m.mes = mes
            m.ativacao_meta_volume = a_vol
            m.ativacao_meta_reincidencia = a_reinc
            m.ativacao_meta_auditoria = a_aud
            m.manutencao_meta_volume = m_vol
            m.manutencao_meta_retrabalho = m_ret
            m.manutencao_meta_garantia_30d = m_gar
            m.manutencao_meta_auditoria = m_aud
            m.save()
            messages.success(request, 'Meta atualizada com sucesso!')
        else:
            # Tenta criar. Se já existe ano+mes, avisa.
            if MetaOperacional.objects.filter(ano=ano, mes=mes).exists():
                messages.error(request, 'Já existe uma meta cadastrada para este Mês e Ano!')
            else:
                MetaOperacional.objects.create(
                    ano=ano,
                    mes=mes,
                    ativacao_meta_volume=a_vol,
                    ativacao_meta_reincidencia=a_reinc,
                    ativacao_meta_auditoria=a_aud,
                    manutencao_meta_volume=m_vol,
                    manutencao_meta_retrabalho=m_ret,
                    manutencao_meta_garantia_30d=m_gar,
                    manutencao_meta_auditoria=m_aud
                )
                messages.success(request, 'Meta criada com sucesso!')
                
    return redirect('configuracoes_metas')

@user_passes_test(lambda u: u.is_staff, login_url='/')
def salvar_feriado(request):
    if request.method == 'POST':
        feriado_id = request.POST.get('feriado_id')
        data = request.POST.get('data')
        descricao = request.POST.get('descricao')
        if feriado_id:
            f = get_object_or_404(Feriado, id=feriado_id)
            f.data = data
            f.descricao = descricao
            f.save()
            messages.success(request, 'Feriado atualizado com sucesso!')
        else:
            Feriado.objects.create(data=data, descricao=descricao)
            messages.success(request, 'Feriado cadastrado com sucesso!')
    return redirect('configuracoes_feriados')

@user_passes_test(lambda u: u.is_staff, login_url='/')
def excluir_feriado(request, id):
    f = get_object_or_404(Feriado, id=id)
    f.delete()
    messages.success(request, f'Feriado {f.descricao} excluído com sucesso.')
    return redirect('configuracoes_feriados')

from .models import Expurgo

@user_passes_test(lambda u: u.is_staff, login_url='/')
def gestao_expurgos(request):
    import datetime
    agora = datetime.datetime.now()
    limite_data = agora - datetime.timedelta(days=90)

    ASSUNTOS_DEFEITO = [
        'INSTRUTIVA-ORDEM DE SERVIÇO REPROVADA',
        'CORRETIVA-ORDEM DE SERVIÇO REPROVADA',
        'CONTROLE DE QUALIDADE  EM CAMPO REPROVADA',
        'SERVIÇO REPROVADO PELO CONTROLE DE QUALIDADE',
        '[RTB] ORDEM DE SERVIÇO REPROVADA',
        '[OP] REINCIDENCIA - SEM ACESSO',
        '[OP] REINCIDENCIA - INTERNET LENTA - CASA',
        '[OP] REINCIDENCIA - SEM ACESSO - APARTAMENTO',
        '[OP] REINCIDENCIA - POTENCIA ALTA - CASA',
        '[OP] REINCIDENCIA - TROCA DE EQUIPAMENTOS - CASA',
        '[OP] REINCIDENCIA - FIBRA ROMPIDA[CASA]',
        '[OP] REINCIDENCIA - POTENCIA ALTA - APARTAMENTO',
        '[OP] REINCIDENCIA - FIBRA ROMPIDA - APARTAMENTO',
        '[OP] REINCIDENCIA - INTERNET LENTA - APARTAMENTO',
        '[OP] REINCIDENCIA - PONTO MESH - CASA',
        '[OP] REINCIDENCIA - PONTO MESH - APARTAMENTO',
        'SUPORTE INTERVALO  16 A 30 DIAS APOS ATIVAÇÃO',
        'SUPORTE APOS 24 HORAS'
    ]

    q_defeitos = Q()
    for ass_def in ASSUNTOS_DEFEITO:
        q_defeitos |= Q(assunto__icontains=ass_def.strip())

    oss_passiveis = OrdemServico.objects.filter(
        q_defeitos,
        data_fechamento__gte=limite_data,
        expurgo__isnull=True
    ).exclude(status__icontains='Cancelada').select_related('cliente', 'colaborador').order_by('-data_fechamento')

    expurgos = Expurgo.objects.select_related('ordem_servico', 'ordem_servico__cliente', 'ordem_servico__colaborador').order_by('-data_expurgo')
    return render(request, 'operacoes/expurgos.html', {'expurgos': expurgos, 'oss_passiveis': oss_passiveis})

@user_passes_test(lambda u: u.is_staff, login_url='/')
def registrar_expurgo(request):
    if request.method == 'POST':
        id_ixc = request.POST.get('id_ixc')
        motivo = request.POST.get('motivo')
        try:
            os = OrdemServico.objects.get(id_ixc=id_ixc)
            # Verifica se já está expurgada
            if hasattr(os, 'expurgo'):
                messages.error(request, f'A OS {id_ixc} já possui um expurgo registrado.')
            else:
                Expurgo.objects.create(ordem_servico=os, motivo=motivo, criado_por="Gestor")
                messages.success(request, f'Expurgo registrado com sucesso para a OS {id_ixc}.')
        except OrdemServico.DoesNotExist:
            messages.error(request, f'OS {id_ixc} não encontrada no banco de dados. O técnico precisa executar primeiro ou o sistema precisa sincronizar.')
    return redirect('gestao_expurgos')

@user_passes_test(lambda u: u.is_staff, login_url='/')
def remover_expurgo(request, id):
    if request.method == 'POST':
        e = get_object_or_404(Expurgo, id=id)
        os_id = e.ordem_servico.id_ixc
        e.delete()
        messages.success(request, f'Expurgo desfeito com sucesso para a OS {os_id}. Ela voltará a contar nas estatísticas.')
    return redirect('gestao_expurgos')

@user_passes_test(lambda u: u.is_staff, login_url='/')
def replicar_mes_anterior(request):
    from django.contrib import messages
    from django.shortcuts import redirect
    from .models import AlocacaoMensal
    
    mes = int(request.GET.get('mes'))
    ano = int(request.GET.get('ano'))
    
    # Mês anterior
    mes_ant = mes - 1
    ano_ant = ano
    if mes_ant == 0:
        mes_ant = 12
        ano_ant -= 1
        
    alocacoes_ant = AlocacaoMensal.objects.filter(mes=mes_ant, ano=ano_ant)
    
    if not alocacoes_ant.exists():
        messages.warning(request, f"Nenhuma alocação encontrada em {mes_ant:02d}/{ano_ant} para replicar.")
        return redirect(f'/configuracoes/?mes={mes}&ano={ano}')
        
    count = 0
    for aloc in alocacoes_ant:
        obj, created = AlocacaoMensal.objects.update_or_create(
            colaborador=aloc.colaborador,
            mes=mes,
            ano=ano,
            defaults={
                'cargo': aloc.cargo,
                'supervisor': aloc.supervisor,
                'setor': aloc.setor,
                'contratacao': aloc.contratacao,
                'marcacao': aloc.marcacao,
                'contabiliza_indicadores': aloc.contabiliza_indicadores,
            }
        )
        if created:
            count += 1
            
    messages.success(request, f"Sucesso! Foram replicadas as classificações de {mes_ant:02d}/{ano_ant} para {mes:02d}/{ano}.")
    return redirect(f'/configuracoes/?mes={mes}&ano={ano}')

import csv
from django.http import HttpResponse
import datetime

def exportar_base(request):
    mes_atual = int(request.GET.get('mes', datetime.date.today().month))
    ano_atual = int(request.GET.get('ano', datetime.date.today().year))
    
    if mes_atual == 1:
        mes_ant, ano_ant = 12, ano_atual - 1
    else:
        mes_ant, ano_ant = mes_atual - 1, ano_atual

    # Base principal
    os_mes = OrdemServico.objects.filter(data_fechamento__year=ano_atual, data_fechamento__month=mes_atual)
    os_mes_ant = OrdemServico.objects.filter(data_fechamento__year=ano_ant, data_fechamento__month=mes_ant)
    
    def _norm(s):
        return (s or '').replace('\xa0', ' ').strip().upper()
        
    def _norm_assunto(s):
        import re
        return re.sub(r'\s+', ' ', _norm(s))
        
    colar_tec = {}
    colar_tec_fisc = {}
    for cli_nome, tec_id, assunto, nome_setor in (os_mes | os_mes_ant).order_by('-id_ixc').values_list('cliente__nome', 'colaborador_id', 'assunto', 'nome_setor'):
        if not nome_setor or _norm(nome_setor) not in ['SERVIÇO', 'SUPORTE', 'RETRABALHO']:
            continue
        ass = _norm_assunto(assunto)
        if '[OP] FIELD AUDIT' in ass: continue
        cli = _norm(cli_nome)
        if cli not in colar_tec: colar_tec[cli] = set()
        colar_tec[cli].add(tec_id)
        
    for cli_nome, tec_id, assunto, nome_setor in os_mes.order_by('-id_ixc').values_list('cliente__nome', 'colaborador_id', 'assunto', 'nome_setor'):
        if not nome_setor or _norm(nome_setor) not in ['SERVIÇO', 'SUPORTE', 'RETRABALHO']:
            continue
        ass = _norm_assunto(assunto)
        if '[OP] FIELD AUDIT' in ass: continue
        cli = _norm(cli_nome)
        if cli not in colar_tec_fisc: colar_tec_fisc[cli] = set()
        colar_tec_fisc[cli].add(tec_id)

    clientes_reprov = set(os_mes.filter(assunto__iexact=ASSUNTO_AUD_REPROVADA).values_list('cliente__nome', flat=True))
    clientes_reprov = set([_norm(c) for c in clientes_reprov])
    
    # Precache de nomes de colaboradores
    tecnicos_dict = {t.id: t.nome for t in Colaborador.objects.all()}
    
    tipo = request.GET.get('tipo', 'servicos')
    setor_req = request.GET.get('setor', 'manutencao').upper()
    
    alocacoes = AlocacaoMensal.objects.filter(mes=mes_atual, ano=ano_atual).select_related('supervisor')
    tec_validos = set()
    for aloc in alocacoes:
        aloc_setor = aloc.supervisor.setor if aloc.supervisor else 'MANUTENCAO'
        if aloc_setor.upper() == setor_req:
            tec_validos.add(aloc.colaborador_id)
            
    # Criar a resposta CSV
    response = HttpResponse(content_type='text/csv')
    assuntos_garantia, assuntos_sup_ativacao = get_assuntos_regras()
    
    if tipo == 'servicos':
        response['Content-Disposition'] = f'attachment; filename="Base_Servicos_Suporte_{mes_atual:02d}_{ano_atual}.csv"'
        writer = csv.writer(response, delimiter=';')
        writer.writerow([
            'ID OS', 'Protocolo', 'Data Abertura', 'Data Fechamento', 'Data Final', 'Cliente', 
            'Setor Original', 'Assunto', 'Técnico Original', 'Garantia 30d?'
        ])
        oss = os_mes.filter(nome_setor__in=['SERVIÇO', 'SUPORTE', 'RETRABALHO'], colaborador_id__in=tec_validos).exclude(assunto__icontains='AUDITORIA').exclude(assunto__icontains='[OP] FIELD AUDIT').select_related('cliente', 'colaborador')
        
        for os_obj in oss:
            assunto_norm = _norm_assunto(os_obj.assunto) if os_obj.assunto else ''
            c_gart = 'SIM' if any(a.upper() in assunto_norm for a in assuntos_garantia) else 'NÃO'
            
            writer.writerow([
                os_obj.id_ixc, os_obj.protocolo, 
                os_obj.data_abertura.strftime('%Y-%m-%d %H:%M') if os_obj.data_abertura else '',
                os_obj.data_fechamento.strftime('%Y-%m-%d %H:%M') if os_obj.data_fechamento else '',
                os_obj.data_fechamento.strftime('%Y-%m-%d %H:%M') if os_obj.data_fechamento else '',
                os_obj.cliente.nome if os_obj.cliente else '', os_obj.nome_setor, os_obj.assunto, os_obj.colaborador.nome if os_obj.colaborador else '',
                c_gart
            ])
            
    elif tipo == 'ativacoes':
        response['Content-Disposition'] = f'attachment; filename="Base_Servicos_Reincidencias_Ativacao_{mes_atual:02d}_{ano_atual}.csv"'
        writer = csv.writer(response, delimiter=';')
        writer.writerow([
            'ID OS', 'Protocolo', 'Data Abertura', 'Data Fechamento', 'Data Final', 'Cliente', 
            'Setor Original', 'Assunto', 'Técnico Original'
        ])
        
        q_sup_ativ = Q()
        for ass_sup in assuntos_sup_ativacao:
            q_sup_ativ |= Q(assunto__icontains=ass_sup.strip())
            
        q_geral = Q(nome_setor__iexact='SERVIÇO') | (Q(nome_setor__iexact='SUPORTE') & q_sup_ativ)
        
        oss = os_mes.filter(q_geral, colaborador_id__in=tec_validos).exclude(assunto__icontains='[OP] FIELD AUDIT').select_related('cliente', 'colaborador')
        
        for os_obj in oss:
            writer.writerow([
                os_obj.id_ixc, os_obj.protocolo, 
                os_obj.data_abertura.strftime('%Y-%m-%d %H:%M') if os_obj.data_abertura else '',
                os_obj.data_fechamento.strftime('%Y-%m-%d %H:%M') if os_obj.data_fechamento else '',
                os_obj.data_fechamento.strftime('%Y-%m-%d %H:%M') if os_obj.data_fechamento else '',
                os_obj.cliente.nome if os_obj.cliente else '', os_obj.nome_setor, os_obj.assunto, os_obj.colaborador.nome if os_obj.colaborador else ''
            ])
            
    elif tipo == 'auditoria':
        response['Content-Disposition'] = f'attachment; filename="Base_Auditoria_Qualidade_{mes_atual:02d}_{ano_atual}.csv"'
        writer = csv.writer(response, delimiter=';')
        writer.writerow([
            'ID OS', 'Protocolo', 'Data Abertura', 'Data Fechamento', 'Data Final', 'Cliente',
            'Status', 'Qtd Técnicos', 'Técnicos Penalizados/Premiados (Mês Atual e Anterior)'
        ])
        oss = os_mes.filter(assunto__startswith='AUDITORIA').select_related('cliente')
        for os_obj in oss:
            c_nome = _norm(os_obj.cliente.nome) if os_obj.cliente else ''
            ids2 = colar_tec.get(c_nome, set())
            ids_validos = [t for t in ids2 if t in tec_validos]
            
            if not ids_validos:
                continue # Pula se não tem nenhum técnico da Manutenção
                
            status = 'REPROVADA' if c_nome in clientes_reprov else 'APROVADA'
            
            for tec_id in ids_validos:
                nome_tec = tecnicos_dict.get(tec_id, str(tec_id))
                writer.writerow([
                    os_obj.id_ixc, os_obj.protocolo, 
                    os_obj.data_abertura.strftime('%Y-%m-%d %H:%M') if os_obj.data_abertura else '',
                    os_obj.data_fechamento.strftime('%Y-%m-%d %H:%M') if os_obj.data_fechamento else '',
                    os_obj.data_fechamento.strftime('%Y-%m-%d %H:%M') if os_obj.data_fechamento else '',
                    os_obj.cliente.nome if os_obj.cliente else '', status, len(ids_validos), nome_tec
                ])
            
    elif tipo == 'field_audit':
        response['Content-Disposition'] = f'attachment; filename="Base_Field_Audit_{mes_atual:02d}_{ano_atual}.csv"'
        writer = csv.writer(response, delimiter=';')
        writer.writerow([
            'ID OS', 'Protocolo', 'Data Abertura', 'Data Fechamento', 'Data Final', 'Cliente', 'Assunto',
            'Diagnóstico Original', 'Status Final', 'Qtd Técnicos', 'Técnicos Penalizados/Premiados (APENAS Mês Vigente)'
        ])
        oss = os_mes.filter(assunto__icontains='[OP] FIELD AUDIT').select_related('cliente')
        for os_obj in oss:
            c_nome = _norm(os_obj.cliente.nome) if os_obj.cliente else ''
            ids = colar_tec_fisc.get(c_nome, set())
            
            if not ids:
                continue # Idêntico ao dashboard
            
            c_field_audit = 'N/A'
            if os_obj.diagnostico and 'REPROVADA' in os_obj.diagnostico.upper():
                c_field_audit = 'REPROVADA'
            elif os_obj.diagnostico and 'APROVADA' in os_obj.diagnostico.upper():
                c_field_audit = 'APROVADA'
                
            for tec_id in ids:
                if tec_id not in tec_validos:
                    continue
                nome_tec = tecnicos_dict.get(tec_id, str(tec_id))
                writer.writerow([
                    os_obj.id_ixc, os_obj.protocolo, 
                    os_obj.data_abertura.strftime('%Y-%m-%d %H:%M') if os_obj.data_abertura else '',
                    os_obj.data_fechamento.strftime('%Y-%m-%d %H:%M') if os_obj.data_fechamento else '',
                    os_obj.data_fechamento.strftime('%Y-%m-%d %H:%M') if os_obj.data_fechamento else '',
                    os_obj.cliente.nome if os_obj.cliente else '', os_obj.assunto, os_obj.diagnostico,
                    c_field_audit, len(ids), nome_tec
                ])
            
    return response

# ==========================================
# GESTÃO DE USUÁRIOS (CENTRALIZADA NO HUB THE FIBER)
# ==========================================
@login_required
def settings_users_view(request):
    """Redireciona para as configurações operacionais já que os usuários são geridos centralizadamente pelo Hub."""
    messages.info(request, 'O gerenciamento de usuários agora é centralizado no Hub The Fiber.')
    return redirect('configuracoes')

# ==========================================
# DE-PARA DE ASSUNTOS (GARANTIA 30D / SUPORTE ATIVAÇÃO)
# ==========================================
@user_passes_test(lambda u: u.is_staff, login_url='/')
def configuracoes_assuntos(request):
    from .models import RegraAssunto
    from .utils import sincronizar_assuntos_disponiveis

    # Sincroniza novos assuntos detectados no banco de OS
    sincronizar_assuntos_disponiveis()

    tipo_filtro = request.GET.get('tipo', 'TODOS').upper()
    busca = request.GET.get('q', '').strip()

    qs = RegraAssunto.objects.all().order_by('tipo_regra', 'assunto')

    if tipo_filtro == 'GARANTIA':
        qs = qs.filter(tipo_regra='GARANTIA_30D')
    elif tipo_filtro == 'SUPORTE':
        qs = qs.filter(tipo_regra='SUPORTE_ATIVACAO')
    elif tipo_filtro == 'OUTROS':
        qs = qs.filter(tipo_regra='OUTROS')

    if busca:
        qs = qs.filter(assunto__icontains=busca)

    total_geral = RegraAssunto.objects.count()
    total_garantia = RegraAssunto.objects.filter(tipo_regra='GARANTIA_30D', ativo=True).count()
    total_suporte = RegraAssunto.objects.filter(tipo_regra='SUPORTE_ATIVACAO', ativo=True).count()
    total_outros = RegraAssunto.objects.filter(tipo_regra='OUTROS').count()

    context = {
        'regras': qs,
        'tipo_filtro': tipo_filtro,
        'busca': busca,
        'tipos_choices': RegraAssunto.TIPO_CHOICES,
        'total_geral': total_geral,
        'total_garantia': total_garantia,
        'total_suporte': total_suporte,
        'total_outros': total_outros,
    }
    return render(request, 'operacoes/configuracoes_assuntos.html', context)


@user_passes_test(lambda u: u.is_staff, login_url='/')
def salvar_regra_assunto(request):
    from .models import RegraAssunto
    from django.http import JsonResponse

    if request.method == 'POST':
        regra_id = request.POST.get('regra_id')
        tipo_regra = request.POST.get('tipo_regra')
        # Checkbox ou flag via AJAX
        ativo = request.POST.get('ativo') in ['true', 'True', '1', 'on']

        if regra_id:
            regra = get_object_or_404(RegraAssunto, id=regra_id)
            if tipo_regra:
                regra.tipo_regra = tipo_regra
            regra.ativo = ativo
            regra.save()

            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax'):
                return JsonResponse({'status': 'ok', 'id': regra.id, 'ativo': regra.ativo, 'tipo_regra': regra.tipo_regra})

            messages.success(request, f"Regra para '{regra.assunto}' atualizada com sucesso!")

    return redirect(request.META.get('HTTP_REFERER') or 'configuracoes_assuntos')


@user_passes_test(lambda u: u.is_staff, login_url='/')
def adicionar_regra_assunto(request):
    from .models import RegraAssunto

    if request.method == 'POST':
        assunto = request.POST.get('assunto', '').strip()
        tipo_regra = request.POST.get('tipo_regra', 'GARANTIA_30D')
        ativo = request.POST.get('ativo') == 'on'

        if assunto:
            regra, created = RegraAssunto.objects.get_or_create(
                assunto=assunto,
                defaults={'tipo_regra': tipo_regra, 'ativo': ativo}
            )
            if not created:
                regra.tipo_regra = tipo_regra
                regra.ativo = ativo
                regra.save()
                messages.info(request, f"Assunto '{assunto}' já existia e foi atualizado.")
            else:
                messages.success(request, f"Assunto '{assunto}' cadastrado com sucesso!")

    return redirect(request.META.get('HTTP_REFERER') or 'configuracoes_assuntos')


@user_passes_test(lambda u: u.is_staff, login_url='/')
def excluir_regra_assunto(request, id):
    from .models import RegraAssunto

    regra = get_object_or_404(RegraAssunto, id=id)
    regra.tipo_regra = 'OUTROS'
    regra.ativo = False
    regra.save()
    messages.success(request, f"Assunto '{regra.assunto}' desmarcado e movido para Outros/Desconsiderar.")
    return redirect(request.META.get('HTTP_REFERER') or 'configuracoes_assuntos')


# ==========================================
# BASE DE CLIENTES (TT BASE)
# ==========================================
@user_passes_test(lambda u: u.is_staff, login_url='/')
def configuracoes_base_cliente(request):
    import datetime
    from .models import BaseCliente
    from .utils import garantir_base_clientes

    ano_atual = datetime.date.today().year
    try:
        ano_selecionado = int(request.GET.get('ano', ano_atual))
    except (ValueError, TypeError):
        ano_selecionado = ano_atual

    garantir_base_clientes(ano_selecionado)

    bases = BaseCliente.objects.filter(ano=ano_selecionado).order_by('mes')

    # Anos disponíveis para filtro
    anos_disponiveis = list(BaseCliente.objects.values_list('ano', flat=True).distinct().order_by('-ano'))
    if ano_selecionado not in anos_disponiveis:
        anos_disponiveis.append(ano_selecionado)
        anos_disponiveis.sort(reverse=True)

    context = {
        'bases': bases,
        'ano_selecionado': ano_selecionado,
        'anos_disponiveis': anos_disponiveis,
    }
    return render(request, 'operacoes/configuracoes_base_cliente.html', context)


@user_passes_test(lambda u: u.is_staff, login_url='/')
def salvar_base_cliente(request):
    from .models import BaseCliente
    from django.http import JsonResponse

    if request.method == 'POST':
        base_id = request.POST.get('id')
        base_valor = request.POST.get('base', '0').strip()

        try:
            base_valor_int = int(base_valor.replace('.', '').replace(',', ''))
        except (ValueError, TypeError):
            base_valor_int = 0

        if base_id:
            obj = get_object_or_404(BaseCliente, id=base_id)
            obj.base = base_valor_int
            obj.save()

            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax'):
                return JsonResponse({'status': 'ok', 'id': obj.id, 'base': obj.base, 'mes': obj.get_mes_display()})

            messages.success(request, f"Base de {obj.get_mes_display()}/{obj.ano} atualizada para {obj.base} clientes.")

    return redirect(request.META.get('HTTP_REFERER') or 'configuracoes_base_cliente')


@require_GET
def api_tecnicos_supervisores(request):
    """
    Endpoint JSON somente leitura para integração interna (ex: dash_estoque).
    Retorna a lista de técnicos/colaboradores e seus supervisores na alocação
    do mês corrente (com fallback para a versão mensal mais recente caso o mês
    corrente ainda não tenha sido populado).
    Autenticação: sessão autenticada OU Bearer JWT assinado com PORTAL_JWT_SECRET
    e claim scope='operacoes_equipes'.
    """
    import datetime
    import jwt
    from django.conf import settings
    from django.http import JsonResponse

    autorizado = bool(request.user and request.user.is_authenticated)
    if not autorizado:
        auth_header = request.headers.get('Authorization', '').strip()
        if auth_header.lower().startswith('bearer '):
            token = auth_header[7:].strip()
            try:
                payload = jwt.decode(
                    token,
                    settings.PORTAL_JWT_SECRET,
                    algorithms=['HS256'],
                )
                if payload.get('scope') == 'operacoes_equipes':
                    autorizado = True
            except Exception:
                autorizado = False

    if not autorizado:
        return JsonResponse({'detail': 'Não autorizado.'}, status=401)

    hoje = datetime.date.today()
    try:
        mes_req = int(request.GET.get('mes', hoje.month))
        ano_req = int(request.GET.get('ano', hoje.year))
        if not (1 <= mes_req <= 12):
            raise ValueError('mes inválido')
    except (ValueError, TypeError):
        mes_req, ano_req = hoje.month, hoje.year

    mes_ref, ano_ref = mes_req, ano_req
    if not AlocacaoMensal.objects.filter(mes=mes_ref, ano=ano_ref).exists():
        mais_recente = (
            AlocacaoMensal.objects.order_by('-ano', '-mes')
            .values('ano', 'mes')
            .first()
        )
        if mais_recente:
            mes_ref = mais_recente['mes']
            ano_ref = mais_recente['ano']

    alocacoes = (
        AlocacaoMensal.objects.filter(
            mes=mes_ref,
            ano=ano_ref,
            colaborador__ativo=True,
        )
        .select_related('colaborador', 'colaborador__cargo', 'supervisor', 'cargo')
        .order_by('colaborador__nome')
    )

    colaboradores = []
    ids_incluidos = set()
    for aloc in alocacoes:
        col = aloc.colaborador
        sup = aloc.supervisor
        cargo_obj = aloc.cargo or col.cargo
        colaboradores.append({
            'id': col.id,
            'nome': col.nome,
            'tipo': col.tipo,
            'setor': aloc.setor or col.setor or '',
            'contratacao': aloc.contratacao or col.contratacao or '',
            'cargo': cargo_obj.nome if cargo_obj else '',
            'supervisor_id': sup.id if sup else None,
            'supervisor_nome': sup.nome if sup else '',
            'supervisor_setor': (sup.setor or '') if sup else '',
        })
        ids_incluidos.add(col.id)

    # Inclui técnicos ativos que ainda não tenham linha na alocação do mês (usando supervisor base se houver)
    restantes = (
        Colaborador.objects.filter(ativo=True, tipo='TECNICO')
        .exclude(id__in=ids_incluidos)
        .select_related('supervisor', 'cargo')
        .order_by('nome')
    )
    for col in restantes:
        sup = col.supervisor
        colaboradores.append({
            'id': col.id,
            'nome': col.nome,
            'tipo': col.tipo,
            'setor': col.setor or '',
            'contratacao': col.contratacao or '',
            'cargo': col.cargo.nome if col.cargo else '',
            'supervisor_id': sup.id if sup else None,
            'supervisor_nome': sup.nome if sup else '',
            'supervisor_setor': (sup.setor or '') if sup else '',
        })

    supervisores = [
        {
            'id': s.id,
            'nome': s.nome,
            'setor': s.setor or '',
        }
        for s in Colaborador.objects.filter(ativo=True, tipo='SUPERVISOR').order_by('nome')
    ]

    return JsonResponse({
        'status': 'ok',
        'mes_referencia': mes_ref,
        'ano_referencia': ano_ref,
        'mes_label': f'{mes_ref:02d}/{ano_ref}',
        'is_mes_corrente': (mes_ref == mes_req and ano_ref == ano_req),
        'supervisores': supervisores,
        'colaboradores': colaboradores,
    })




