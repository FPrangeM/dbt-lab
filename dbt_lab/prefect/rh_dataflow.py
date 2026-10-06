from prefect import flow, task
import subprocess


@task
def build_trusted():
    subprocess.run(
        ["dbt", "run", "--select", "rh_trusted"],
        check=True,
    )


@task
def test_trusted():
    subprocess.run(
        ["dbt", "test", "--select", "tag:qualidade"],
        check=True,
    )


@task
def build_historico():
    subprocess.run(
        ["dbt", "run", "--select", "rh_historico_trusted"],
        check=True,
    )


@flow
def rh_pipeline():

    build_trusted()

    # test_trusted()

    # build_historico()


if __name__ == "__main__":
    rh_pipeline()