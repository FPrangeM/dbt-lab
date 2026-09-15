{{config(
    materialized='table',
    schema='trusted',
    partition_by='date(ref_data)'
    )
}}

select
  regexp_extract('./data/extract_rh_2026-07-13.csv', '\d{4}-\d{2}-\d{2}') AS ref_data,
  Nome,
  CPF,
  Unidade,
  Data_Nascimento,
  Data_Admissao,
  case 
    when upper(Status_Afastamento) = 'DESLIGADO' then 'DESLIGADO'
    else 'ATIVO'
    end as Status,
  Status_Afastamento,
  Data_Inicio_Afastamento,
  Data_Fim_Afastamento,
  Data_Desligamento,
  split(filename,'/')[-1] as filename
from raw.rh