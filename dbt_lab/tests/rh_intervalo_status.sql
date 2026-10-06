-- O bloco `meta` abaixo carrega a descrição de negócio consumida pelo relatório
-- de Data Quality (dbt_lab/observability), mantendo o alerta do RH versionado
-- junto com a regra que ele descreve. Ele não altera a lógica do teste.
{{ config(
    severity='warn',
    tags=['rh', 'test'],
    store_failures=true,
    meta={
        'title': 'Intervalo de afastamento inválido',
        'audience': 'RH',
        'business_rule': 'A data de fim do afastamento não pode ser anterior à data de início do afastamento.',
        'impact': 'Datas invertidas quebram o cálculo de dias de afastamento e geram relatórios de férias e licenças incorretos.',
        'action': 'Conferir as datas de início e fim do afastamento no sistema de RH e corrigir os registros apontados.',
        'sample_columns': ['Nome', 'CPF', 'Data_Inicio_Afastamento', 'Data_Fim_Afastamento']
    }
) }}

-- Retorna os usuarios com fim de afastamento menor que o inicio.
select 
    ref_data,
    cpf,
    nome,
    Status_Afastamento,
    Data_Inicio_Afastamento,
    Data_Fim_Afastamento
from 
    {{ ref('rh_trusted') }}
where 
    Data_Fim_Afastamento < Data_Inicio_Afastamento
