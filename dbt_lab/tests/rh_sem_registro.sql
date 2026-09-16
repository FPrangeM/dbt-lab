{{ config(
    severity='warn',
    tags=['qualidade', 'rh', 'observabilidade'],
    store_failures=true
) }}

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
