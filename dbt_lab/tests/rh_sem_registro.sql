-- O bloco `meta` abaixo carrega a descrição de negócio consumida pelo relatório
-- de Data Quality (dbt_lab/observability), mantendo o alerta do RH versionado
-- junto com a regra que ele descreve. Ele não altera a lógica do teste.
{{ config(
    severity='warn',
    tags=['rh', 'test'],
    store_failures=true,
    meta={
        'title': 'Colaboradores que sumiram do extrato semanal',
        'audience': 'RH',
        'business_rule': 'Um colaborador presente no extrato da semana anterior não pode desaparecer do extrato atual.',
        'impact': 'A ausência pode ser um erro na extração ou um desligamento não registrado. Nos dois casos o quadro de colaboradores da empresa fica subestimado.',
        'action': 'Confirmar com a operação se os colaboradores apontados foram desligados. Se não foram, solicitar o reenvio do extrato da semana.',
        'sample_columns': ['Nome', 'CPF', 'Unidade']
    }
) }}


-- Retorna os usuarios que apareceram em reports anteriores, mas perderam o registro no atual.
{% set var_ref_data = "(select max(ref_data) from " ~ ref('rh_trusted') ~ ")" %}

with atual as (
    select *
    from {{ ref('rh_trusted') }}
    where ref_data = {{ var_ref_data }}
),

anterior as (
    select *
    from trusted.rh_historico_trusted
    where ref_data = {{ var_ref_data }} - 7 
),

consolidado as (
    select * from atual
    union all
    select * from anterior
)

select * from (
    select 
        *
    from consolidado
    qualify count(distinct ref_data) over(partition by cpf) = 1
    order by nome
)
where ref_data = {{ var_ref_data }} - 7
