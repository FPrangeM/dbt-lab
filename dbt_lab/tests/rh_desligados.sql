-- O bloco `meta` abaixo carrega a descrição de negócio consumida pelo relatório
-- de Data Quality (dbt_lab/observability), mantendo o alerta do RH versionado
-- junto com a regra que ele descreve. Ele não altera a lógica do teste.
{{ config(
    severity='warn',
    tags=['rh', 'test'],
    store_failures=true,
    meta={
        'title': 'Colaboradores desligados sem data de desligamento',
        'audience': 'RH',
        'business_rule': 'Todo colaborador com status DESLIGADO precisa ter a data de desligamento preenchida.',
        'impact': 'Sem a data de desligamento não é possível calcular tempo de casa, e os indicadores de turnover e de quadro de colaboradores ficam incorretos.',
        'action': 'Preencher a data de desligamento no sistema de RH para os colaboradores apontados e reenviar o extrato semanal.',
        'sample_columns': ['Nome', 'CPF', 'Status', 'Data_Desligamento']
    }
) }}

-- Calcula a quantidade de usuarios com o status desligado, porem sem data de desligamento.
SELECT
    ref_data,
    cpf,
    nome,
    status,
    data_desligamento
FROM 
    {{ ref('rh_trusted') }}
WHERE 
    (status = 'DESLIGADO' AND data_desligamento IS NULL)