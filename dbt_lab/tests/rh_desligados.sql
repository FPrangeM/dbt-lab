{{ config(
    severity='warn',
    tags=['rh', 'test'],
    store_failures=true
) }}

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