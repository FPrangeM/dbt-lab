{{config(
    materialized='incremental',
    partition_by='date(ref_data)',
    schema='trusted',
    pre_hook=[
        "DELETE FROM {{ this }}
         WHERE ref_data IN (SELECT DISTINCT ref_data FROM {{ ref('rh_trusted') }}
         )"
    ],
    tags="rh"
    )
}}

select * from {{ ref('rh_trusted')}}