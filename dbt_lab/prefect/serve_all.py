from prefect import serve
from prefect.schedules import Cron

from rh_dataflow import rh_pipeline
from rh_dataflow_dbt import rh_pipeline_dbt


if __name__ == "__main__":
    deploy_rh = rh_pipeline.to_deployment(
        name="rh_pipeline-deploy",
        schedule=Cron("5 * * * *", timezone="America/Sao_Paulo"),
        tags=["rh"],
    )

    
    deploy_rh_dbt = rh_pipeline_dbt.to_deployment(
        name="rh_pipeline_dbt-deploy",
        schedule=Cron("5 * * * *", timezone="America/Sao_Paulo"),
        tags=["rh"],
    )

    
    serve(deploy_rh,deploy_rh_dbt)