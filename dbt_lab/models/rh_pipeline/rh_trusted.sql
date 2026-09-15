{{config(
    materialized='table',
    schema='trusted',
    tags="rh"
    )
}}

select
  date(regexp_extract(filename, '\d{4}-\d{2}-\d{2}')) AS ref_data,
  Nome,
  CPF,
  Unidade,
  date(Data_Nascimento) as Data_Nascimento,
  date(Data_Admissao) as Data_Admissao,
  case 
    when upper(Status_Afastamento) = 'DESLIGADO' then 'DESLIGADO'
    else 'ATIVO'
    end as Status,
  Status_Afastamento,
  date(Data_Inicio_Afastamento) as Data_Inicio_Afastamento,
  date(Data_Fim_Afastamento) as Data_Fim_Afastamento,
  date(Data_Desligamento) as Data_Desligamento,
  -- split(filename,'/')[-1] as filename
from {{ source('raw','rh') }}