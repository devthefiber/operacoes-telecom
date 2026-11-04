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
