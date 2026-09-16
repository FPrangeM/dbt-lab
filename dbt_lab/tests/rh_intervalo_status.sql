{{ config(
    severity='warn',
    tags=['qualidade', 'rh', 'observabilidade'],
    store_failures=true
) }}

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
    Data_Inicio_Afastamento >= Data_Fim_Afastamento
