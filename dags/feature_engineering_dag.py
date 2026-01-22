"""
Example Airflow DAG for DSRP MLOps project.

This DAG demonstrates a basic ML pipeline workflow structure.
Replace this with your actual pipeline DAGs.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sdk import Variable
from kubernetes.client import models as k8s
import polars as pl

# Pod override to install DAG-specific dependencies at runtime
# This isolates dependencies per DAG instead of installing globally
# Using init container to install dependencies before the main task runs
# IMPORTANT: We install to /opt/dag-deps (not /home/airflow/.local) to avoid
# overwriting the base Airflow installation
FEATURE_ENG_POD_OVERRIDE = k8s.V1Pod(
    spec=k8s.V1PodSpec(
        init_containers=[
            k8s.V1Container(
                name="install-deps",
                image="apache/airflow:3.0.1",
                command=["/bin/sh", "-c"],
                args=["pip install --target=/opt/dag-deps 'polars>=1.35.2' 'azure-storage-blob'"],
                volume_mounts=[
                    k8s.V1VolumeMount(
                        name="dag-deps",
                        mount_path="/opt/dag-deps"
                    )
                ]
            )
        ],
        containers=[
            k8s.V1Container(
                name="base",
                env=[
                    k8s.V1EnvVar(
                        name="PYTHONPATH",
                        value="/opt/dag-deps"
                    )
                ],
                volume_mounts=[
                    k8s.V1VolumeMount(
                        name="dag-deps",
                        mount_path="/opt/dag-deps"
                    )
                ]
            )
        ],
        volumes=[
            k8s.V1Volume(
                name="dag-deps",
                empty_dir=k8s.V1EmptyDirVolumeSource()
            )
        ]
    )
)

default_args = {
    "owner": "dsrp",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

# =============================================================================
# Utility Functions
# =============================================================================

def get_blob_service_client():
    """Get Azure Blob Storage client from environment."""
    from azure.storage.blob import BlobServiceClient

    credentials = Variable.get("azure_storage_credentials")
    account_name = Variable.get("azure_storage_account_name")

    return  BlobServiceClient(
        account_url=account_name,
        credential=credentials
    )

def load_data_from_blob():
    """Load data from blob storage."""
    from io import BytesIO
    import polars as pl

    blob_service_client = get_blob_service_client()
    blob_client = blob_service_client.get_blob_client(
        container="ml-pipeline-data",
        blob="ltr_imdb_dataset.parquet"
    )
    return pl.read_parquet(BytesIO(blob_client.download_blob().readall()))


def write_data_to_blob(data: pl.DataFrame):
    """Write data to blob storage."""
    from io import BytesIO
    import polars as pl

    blob_service_client = get_blob_service_client()
    blob_client = blob_service_client.get_blob_client(
        container="ml-pipeline-data",
        blob="airflow-prod/test.parquet"
    )
    buffer = BytesIO()
    data.write_parquet(buffer)
    blob_client.upload_blob(buffer.getvalue(), overwrite=True)


# =============================================================================
# Task Functions
# =============================================================================

def check_dependencies():
    """Check if the dependencies are installed."""
    try:
        from azure.storage.blob import BlobServiceClient  # noqa: F401
         # noqa: F401
        import polars as pl  # noqa: F401

        print("Dependencies checked successfully")

    except Exception as e:
        print(f"Error checking dependencies: {e}")
        return False

    return True


def load_and_write_data():
    """Load and write data to a file."""

    data = load_data_from_blob()
    write_data_to_blob(data)
    return "Data loaded and written to blob storage"


with DAG(
    dag_id="feature_engineering_dag",
    default_args=default_args,
    description="Example ML pipeline DAG for DSRP project",
    schedule=timedelta(days=1),
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["example", "ml", "dsrp"],
) as dag:

    check_dependencies_task = PythonOperator(
        task_id="check_dependencies",
        python_callable=check_dependencies,
        executor_config={"pod_override": FEATURE_ENG_POD_OVERRIDE},
    )

    load_and_write_data_task = PythonOperator(
        task_id="load_and_write_data",
        python_callable=load_and_write_data,
        executor_config={"pod_override": FEATURE_ENG_POD_OVERRIDE},
    )

    check_dependencies_task >> load_and_write_data_task