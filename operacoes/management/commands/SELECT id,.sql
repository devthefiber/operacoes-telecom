SELECT id,
       id_ixc,
       tipo,
       assunto,
       status,
       protocolo,
       data_abertura,
       data_fechamento,
       diagnostico,
       mensagem,
       reincidencia,
       data_criacao,
       data_atualizacao,
       cliente_id,
       colaborador_id,
       os_original_id
FROM public.operacoes_ordemservico
LIMIT 1000;