from prefect import flow, task
from prefect_dbt.cli.commands import DbtCoreOperation


@task
def run_rh_pipeline():
    result = DbtCoreOperation(
        commands=[
            "dbt build -s tag:rh"
        ]
    ).run()

    return result


@flow
def rh_pipeline_dbt():
    run_rh_pipeline()


if __name__ == "__main__":
    run_rh_pipeline()