"""
Example Airflow DAG for DSRP MLOps project.

This DAG demonstrates a basic ML pipeline workflow structure.
Replace this with your actual pipeline DAGs.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sdk import Variable




default_args = {
    "owner": "dsrp",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

def check_dependencies():
    """Check if the dependencies are installed."""
    try:
        from azure.storage.blob import BlobServiceClient
        from io import BytesIO
        import polars as pl

        print("Dependencies checked successfully")

    except Exception as e:
        print(f"Error checking dependencies: {e}")
        return False

    return True

def load_and_write_data():
    """Load and write data to a file."""

    from azure.storage.blob import BlobServiceClient
    from io import BytesIO
    import polars as pl


    credentials = Variable.get("azure_storage_credentials")
    account_name = Variable.get("azure_storage_account_name")

    blob_service_client = BlobServiceClient(
        account_url=account_name,
        credential=credentials
    )
    blob_client = blob_service_client.get_blob_client( 
        container="ml-pipeline-data", 
        blob="ltr_imdb_dataset.parquet"
    )
    blob_data = blob_client.download_blob().readall()

    data_ = pl.read_parquet(BytesIO(blob_data))


    buffer = BytesIO()
    blob_client = blob_service_client.get_blob_client( 
        container="ml-pipeline-data", 
        blob="airflow-prod/test.parquet"
    )
    data_.write_parquet(buffer)
    blob_client.upload_blob(buffer, overwrite=True)


with DAG(
    dag_id="feature_engineering_dag",
    default_args=default_args,
    description="Example ML pipeline DAG for DSRP project",
    schedule=timedelta(days=1),
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["example", "ml", "dsrp"],
) as dag:

    check_dependencies = PythonOperator(
        task_id="check_dependencies",
        python_callable=check_dependencies,
    )

    load_and_write_data = PythonOperator(
        task_id="load_and_write_data",
        python_callable=load_and_write_data,
    )

    check_dependencies >> load_and_write_data