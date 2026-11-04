import calendar
from datetime import date, datetime
from .models import Feriado

def calcular_dias_uteis(ano, mes):
    """
    Retorna o total de dias úteis no mês, os dias trabalhados (D-1) 
    e os dias faltantes, considerando:
    Seg-Sex = 1, Sábado = 0.5, Domingo/Feriado = 0
    """
    hoje = date.today()
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    
    # Buscar feriados do mês no banco de dados
    feriados = set(Feriado.objects.filter(data__year=ano, data__month=mes).values_list('data', flat=True))
    
    total_du = 0.0
    trabalhados = 0.0
    
    for dia in range(1, ultimo_dia + 1):
        data_atual = date(ano, mes, dia)
        
        # Ignora se for feriado
        if data_atual in feriados:
            continue
            
        dia_semana = data_atual.weekday() # 0 = Seg, 5 = Sáb, 6 = Dom
        peso = 0.0
        
        if dia_semana < 5:  # Seg a Sex
            peso = 1.0
        elif dia_semana == 5:  # Sábado (5)
            peso = 0.5
        # Domingo (6) é 0.0, então não soma nada
            
        total_du += peso
        
        # Se for no passado ou hoje (vamos considerar D-1 para cravarmos)
        # Se hoje for o mesmo mês/ano, soma apenas se o dia for menor que hoje
        if ano < hoje.year or (ano == hoje.year and mes < hoje.month):
            trabalhados += peso
        elif ano == hoje.year and mes == hoje.month and dia < hoje.day:
            trabalhados += peso

    # Regra de negócio: se o mês fechou inteiro, trabalhados é igual ao total
    if trabalhados == 0 and (ano < hoje.year or (ano == hoje.year and mes < hoje.month)):
        trabalhados = total_du
        
    return {
        'total_du': total_du,
        'trabalhados': trabalhados if trabalhados > 0 else 1.0, # Evitar divisão por zero
        'faltantes': total_du - trabalhados if (total_du - trabalhados) > 0 else 0
    }

def garantir_alocacao_mes(mes, ano):
    """
    Se o mês solicitado não tiver nenhuma alocação configurada,
    busca automaticamente o mês anterior e replica toda a equipe e metas operacionais.
    """
    from .models import AlocacaoMensal, MetaOperacional
    if not AlocacaoMensal.objects.filter(mes=mes, ano=ano).exists():
        mes_ant = 12 if mes == 1 else mes - 1
        ano_ant = ano - 1 if mes == 1 else ano
        alocacoes_ant = AlocacaoMensal.objects.filter(mes=mes_ant, ano=ano_ant)
        if alocacoes_ant.exists():
            novas = [
                AlocacaoMensal(
                    colaborador=a.colaborador,
                    mes=mes,
                    ano=ano,
                    cargo=a.cargo,
                    supervisor=a.supervisor,
                    setor=a.setor,
                    contratacao=a.contratacao,
                    marcacao=a.marcacao,
                    contabiliza_indicadores=a.contabiliza_indicadores,
                )
                for a in alocacoes_ant
            ]
            AlocacaoMensal.objects.bulk_create(novas)

        # Replicar metas operacionais caso não existam no mês novo
        if not MetaOperacional.objects.filter(mes=mes, ano=ano).exists():
            meta_ant = MetaOperacional.objects.filter(mes=mes_ant, ano=ano_ant).first()
            if meta_ant:
                MetaOperacional.objects.create(
                    ano=ano,
                    mes=mes,
                    ativacao_meta_volume=meta_ant.ativacao_meta_volume,
                    ativacao_meta_reincidencia=meta_ant.ativacao_meta_reincidencia,
                    ativacao_meta_auditoria=meta_ant.ativacao_meta_auditoria,
                    manutencao_meta_volume=meta_ant.manutencao_meta_volume,
                    manutencao_meta_retrabalho=meta_ant.manutencao_meta_retrabalho,
                    manutencao_meta_garantia_30d=meta_ant.manutencao_meta_garantia_30d,
                    manutencao_meta_auditoria=meta_ant.manutencao_meta_auditoria,
                )

def get_assuntos_regras():
    """
    Retorna os conjuntos de assuntos ativos para Garantia 30D e Suporte Ativação.
    Se a tabela ainda não tiver dados, usa os padrões como fallback defensivo.
    """
    from .models import RegraAssunto
    
    padrao_garantia = [
        '[OP] REINCIDENCIA - SEM ACESSO',
        '[OP] REINCIDENCIA - INTERNET LENTA - CASA',
        '[OP] REINCIDENCIA - SEM ACESSO - APARTAMENTO',
        '[OP] REINCIDENCIA - POTENCIA ALTA - CASA',
        '[OP] REINCIDENCIA - TROCA DE EQUIPAMENTOS - CASA',
        '[OP] REINCIDENCIA - FIBRA ROMPIDA[CASA]',
        '[OP] REINCIDENCIA - POTENCIA ALTA - APARTAMENTO'
    ]
    padrao_sup_ativ = [
        'SUPORTE INTERVALO  16 A 30 DIAS APOS ATIVAÇÃO',
        'SUPORTE APOS 24 HORAS'
    ]
    
    try:
        assuntos_gart = list(RegraAssunto.objects.filter(tipo_regra='GARANTIA_30D', ativo=True).values_list('assunto', flat=True))
        if not assuntos_gart:
            assuntos_gart = padrao_garantia
            
        assuntos_sup = list(RegraAssunto.objects.filter(tipo_regra='SUPORTE_ATIVACAO', ativo=True).values_list('assunto', flat=True))
        if not assuntos_sup:
            assuntos_sup = padrao_sup_ativ
            
        return assuntos_gart, assuntos_sup
    except Exception:
        return padrao_garantia, padrao_sup_ativ

def sincronizar_assuntos_disponiveis():
    """
    Sincroniza todos os assuntos de OrdemServico que ainda não estão em RegraAssunto.
    Garante que os padrões de Garantia 30D e Suporte Ativação fiquem pré-mapeados e ativos.
    """
    from .models import RegraAssunto, OrdemServico
    
    padrao_garantia = [
        '[OP] REINCIDENCIA - SEM ACESSO',
        '[OP] REINCIDENCIA - INTERNET LENTA - CASA',
        '[OP] REINCIDENCIA - SEM ACESSO - APARTAMENTO',
        '[OP] REINCIDENCIA - POTENCIA ALTA - CASA',
        '[OP] REINCIDENCIA - TROCA DE EQUIPAMENTOS - CASA',
        '[OP] REINCIDENCIA - FIBRA ROMPIDA[CASA]',
        '[OP] REINCIDENCIA - POTENCIA ALTA - APARTAMENTO'
    ]
    padrao_sup_ativ = [
        'SUPORTE INTERVALO  16 A 30 DIAS APOS ATIVAÇÃO',
        'SUPORTE APOS 24 HORAS'
    ]

    # Pre-criar padrões de garantia
    for ass in padrao_garantia:
        RegraAssunto.objects.get_or_create(
            assunto=ass,
            defaults={'tipo_regra': 'GARANTIA_30D', 'ativo': True}
        )

    # Pre-criar padrões de suporte ativação
    for ass in padrao_sup_ativ:
        RegraAssunto.objects.get_or_create(
            assunto=ass,
            defaults={'tipo_regra': 'SUPORTE_ATIVACAO', 'ativo': True}
        )

    # Identificar todos os outros assuntos existentes no banco de OS
    assuntos_existentes = set(RegraAssunto.objects.values_list('assunto', flat=True))
    novos_assuntos = OrdemServico.objects.exclude(assunto__isnull=True).exclude(assunto='').values_list('assunto', flat=True).distinct()
    
    a_criar = []
    for ass in novos_assuntos:
        ass_clean = (ass or '').strip()
        if ass_clean and ass_clean not in assuntos_existentes:
            assuntos_existentes.add(ass_clean)
            a_criar.append(RegraAssunto(assunto=ass_clean, tipo_regra='OUTROS', ativo=False))
            
    if a_criar:
        RegraAssunto.objects.bulk_create(a_criar, ignore_conflicts=True)


def garantir_base_clientes(ano=2026):
    """
    Garante que os 12 meses do ano tenham registro de Base de Clientes.
    Para 2026: Jan-Set = 0, Out = 31836 (padrão inicial), Nov-Dez = 0.
    """
    from .models import BaseCliente
    for mes in range(1, 13):
        valor_padrao = 31836 if (ano == 2026 and mes == 10) else 0
        obj, created = BaseCliente.objects.get_or_create(
            ano=ano, mes=mes,
            defaults={'base': valor_padrao}
        )
        # Se foi criado com 0 em Out/2026 ou se já existia com 0 em Out/2026 sem personalização
        if ano == 2026 and mes == 10 and obj.base == 0 and created:
            obj.base = 31836
            obj.save()


def get_base_cliente(ano, mes):
    """Retorna a base de clientes cadastrada para o mês/ano."""
    from .models import BaseCliente
    garantir_base_clientes(ano)
    bc = BaseCliente.objects.filter(ano=ano, mes=mes).first()
    return bc.base if bc else 0


def calcular_tt_base(volume_suporte, dias_trabalhados, total_dias_uteis, base_clientes):
    """
    Calcula a taxa TT Base (%) projetada para o mês:
    ((Volume Suporte / Dias Trabalhados) * Dias Úteis Totais) / Base de Clientes * 100
    Se o mês já encerrou (dias_trabalhados >= total_dias_uteis), resulta em (Volume Suporte / Base) * 100.
    """
    if not base_clientes or base_clientes <= 0 or not dias_trabalhados or dias_trabalhados <= 0:
        return 0.0, 0.0
    
    projecao_suporte = (float(volume_suporte) / float(dias_trabalhados)) * float(total_dias_uteis)
    tt_base_pct = (projecao_suporte / float(base_clientes)) * 100.0
    return round(tt_base_pct, 2), round(projecao_suporte, 1)

