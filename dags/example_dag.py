"""
Example Airflow DAG for DSRP MLOps project.

This DAG demonstrates a basic ML pipeline workflow structure.
Replace this with your actual pipeline DAGs.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator


default_args = {
    "owner": "dsrp",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def print_hello():
    """Simple Python callable for demonstration."""
    print("Hello from DSRP MLOps pipeline!")
    return "Hello task completed"


with DAG(
    dag_id="example_ml_pipeline",
    default_args=default_args,
    description="Example ML pipeline DAG for DSRP project",
    schedule=timedelta(days=1),
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["example", "ml", "dsrp"],
) as dag:

    start = BashOperator(
        task_id="start",
        bash_command="echo 'Starting ML pipeline...'",
    )

    hello_task = PythonOperator(
        task_id="hello_python",
        python_callable=print_hello,
    )

    end = BashOperator(
        task_id="end",
        bash_command="echo 'ML pipeline completed!'",
    )

    start >> hello_task >> end
