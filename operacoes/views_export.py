import csv
from django.http import HttpResponse

@login_required(login_url='/login/')
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
        import unicodedata
        if not s: return ''
        s = unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('utf-8')
        return s.strip().upper()
        
    def _norm_assunto(s):
        import re
        return re.sub(r'\s+', ' ', _norm(s))
        
    ASSUNTO_AUD_REPROVADA = "CONTROLE DE QUALIDADE EM CAMPO REPROVADA"
    
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
    
    # Criar a resposta CSV
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="Base_Operacoes_{mes_atual:02d}_{ano_atual}.csv"'
    
    writer = csv.writer(response, delimiter=';')
    writer.writerow([
        'ID OS', 'Protocolo', 'Data Abertura', 'Data Fechamento',
        'Cliente', 'Setor Original', 'Assunto Original', 'Técnico Original',
        'Considerado Serviço?', 'Considerado Suporte?', 'Garantia 30d?',
        'Técnicos Pontuados (Por Cliente)',
        'Classificação FIELD AUDIT', 'Técnicos do Field Audit (Mês Vigente)'
    ])
    
    # Pegamos todas as OS de serviço, suporte, retrabalho, e auditorias para exportar
    oss = os_mes.all().select_related('cliente', 'colaborador')
    for os_obj in oss:
        c_nome = _norm(os_obj.cliente.nome) if os_obj.cliente else ''
        n_setor = _norm(os_obj.nome_setor) if os_obj.nome_setor else ''
        assunto = _norm_assunto(os_obj.assunto) if os_obj.assunto else ''
        
        c_servico = 'NÃO'
        c_suporte = 'NÃO'
        c_gart = 'NÃO'
        c_field_audit = '-'
        t_pontuados = ''
        t_fisc = ''
        
        # Ignoramos assuntos de auditoria e reincidência pro Serviço/Suporte
        if n_setor in ['SERVIÇO', 'SUPORTE', 'RETRABALHO'] and 'AUDITORIA' not in assunto and 'REINCIDENCIA' not in assunto and '[OP] FIELD AUDIT' not in assunto:
            if n_setor == 'SERVIÇO': c_servico = 'SIM'
            elif n_setor == 'SUPORTE' or n_setor == 'RETRABALHO': c_suporte = 'SIM'
            
            # Garantia 30d
            if os_obj.data_abertura:
                os_ant = OrdemServico.objects.filter(
                    cliente=os_obj.cliente,
                    nome_setor__iexact='SERVIÇO',
                    data_fechamento__lt=os_obj.data_abertura,
                    data_fechamento__gte=os_obj.data_abertura - datetime.timedelta(days=30)
                ).exclude(Q(assunto__icontains='AUDITORIA') | Q(assunto__icontains='REINCIDENCIA') | Q(assunto__icontains='[OP] FIELD AUDIT')).exists()
                if os_ant: c_gart = 'SIM'

        if '[OP] FIELD AUDIT' in assunto:
            if os_obj.diagnostico and 'REPROVADA' in os_obj.diagnostico.upper():
                c_field_audit = 'REPROVADA'
            elif os_obj.diagnostico and 'APROVADA' in os_obj.diagnostico.upper():
                c_field_audit = 'APROVADA'
            else:
                c_field_audit = 'N/A'
                
            ids = colar_tec_fisc.get(c_nome, set())
            t_fisc = ", ".join([tecnicos_dict.get(id, str(id)) for id in ids])
            
        # Para auditoria ou ordens gerais, lista os técnicos de colar_tec
        ids2 = colar_tec.get(c_nome, set())
        t_pontuados = ", ".join([tecnicos_dict.get(id, str(id)) for id in ids2])
            
        writer.writerow([
            os_obj.id_ixc,
            os_obj.protocolo,
            os_obj.data_abertura.strftime('%Y-%m-%d %H:%M:%S') if os_obj.data_abertura else '',
            os_obj.data_fechamento.strftime('%Y-%m-%d %H:%M:%S') if os_obj.data_fechamento else '',
            os_obj.cliente.nome if os_obj.cliente else '',
            os_obj.nome_setor,
            os_obj.assunto,
            os_obj.colaborador.nome if os_obj.colaborador else '',
            c_servico,
            c_suporte,
            c_gart,
            t_pontuados,
            c_field_audit,
            t_fisc
        ])
        
    return response
