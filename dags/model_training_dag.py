"""
LightGBM LTR Model Training DAG.

This DAG trains a LightGBM ranker model using the synthetic LTR dataset,
performs hyperparameter optimization, and registers the model to MLflow.

Prerequisites:
- ltr_synthetic_dataset.parquet in Azure Blob Storage
- MLflow tracking server configured (DagsHub)

Note: Uses custom airflow-ml image with pre-installed dependencies.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sdk import Variable
from kubernetes.client import models as k8s


# Standard resources for lightweight tasks
resource_requirements = k8s.V1ResourceRequirements(
    requests={"cpu": "500m", "memory": "1Gi", "ephemeral-storage": "2Gi"},
    limits={"cpu": "1000m", "memory": "4Gi", "ephemeral-storage": "6Gi"},
)

# ML training resources (LightGBM with hyperopt)
ml_training_requirements = k8s.V1ResourceRequirements(
    requests={"cpu": "1500m", "memory": "4Gi", "ephemeral-storage": "4Gi"},
    limits={"cpu": "3000m", "memory": "8Gi", "ephemeral-storage": "10Gi"},
)


def generate_pod_config(resources: k8s.V1ResourceRequirements = None):
    """Generate Kubernetes pod configuration with resource limits."""
    pod_resources = resources if resources is not None else resource_requirements
    return k8s.V1Pod(
        spec=k8s.V1PodSpec(
            containers=[
                k8s.V1Container(
                    name="base",
                    resources=pod_resources
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
# Configuration
# =============================================================================

MODEL_NAME = "ltr-dsrpflix-prd"
EXPERIMENT_NAME = "LTR - Airflow Pipeline"
TEST_SIZE = 0.2
RANDOM_STATE = 42
MAX_HYPEROPT_EVALS = 15

FEATURE_COLS = [
    "sim_embedding",
    "imdb_rating",
    "imdb_votes_log",
]


# =============================================================================
# Utility Functions
# =============================================================================

def get_blob_service_client():
    """Get Azure Blob Storage client from Airflow variables."""
    from azure.storage.blob import BlobServiceClient

    credentials = Variable.get("azure_storage_credentials")
    account_name = Variable.get("azure_storage_account_name")

    return BlobServiceClient(
        account_url=account_name,
        credential=credentials
    )


def read_parquet_from_blob(container: str, blob_name: str):
    """Read parquet file from Azure Blob Storage."""
    from io import BytesIO
    import polars as pl

    blob_service_client = get_blob_service_client()
    blob_client = blob_service_client.get_blob_client(
        container=container,
        blob=blob_name
    )
    return pl.read_parquet(BytesIO(blob_client.download_blob().readall()))


# =============================================================================
# Metrics Functions
# =============================================================================

def dcg(relevances):
    """Discounted Cumulative Gain."""
    import numpy as np
    relevances = np.array(relevances)
    discounts = 1 / np.log2(np.arange(2, len(relevances) + 2))
    return np.sum(relevances * discounts)


def ndcg_at_k(true_rels, pred_scores, k=10):
    """Compute NDCG@k for a single query."""
    import numpy as np
    idx = np.argsort(-pred_scores)[:k]
    sorted_true = np.array(true_rels)[idx]

    dcg_k = dcg(sorted_true)

    ideal_sorted_true = np.sort(true_rels)[::-1][:k]
    idcg_k = dcg(ideal_sorted_true)

    return float(dcg_k / idcg_k if idcg_k > 0 else 0.0)


# =============================================================================
# Task Functions
# =============================================================================

def train_ltr_model():
    """Train LightGBM ranker with hyperparameter optimization and register to MLflow."""
    import json
    import os
    import numpy as np
    import polars as pl
    import lightgbm as lgb
    import mlflow
    import dagshub
    from mlflow.models.signature import infer_signature
    from hyperopt import STATUS_OK, Trials, fmin, hp, tpe
    from loguru import logger

    logger.info("Initializing MLflow tracking...")

    # Set DagsHub token from Airflow Variables
    dagshub_token = Variable.get("dagshub_token")
    os.environ["DAGSHUB_USER_TOKEN"] = dagshub_token

    # Initialize DagsHub MLflow
    dagshub.init(
        repo_owner='abdala9512',
        repo_name='dsrp-machine-learning-engineering-4',
        mlflow=True
    )

    # Load dataset
    logger.info("Loading LTR dataset...")
    ltr_df = read_parquet_from_blob("ml-pipeline-data", "airflow-prod/ltr_synthetic_dataset.parquet")
    logger.info(f"Dataset shape: {ltr_df.shape}")
    logger.info(f"Unique queries: {ltr_df['query_id'].n_unique()}")

    # Filter available feature columns
    feature_cols = [c for c in FEATURE_COLS if c in ltr_df.columns]
    logger.info(f"Features: {feature_cols}")

    # Prepare data
    X = ltr_df.select(feature_cols).to_numpy()
    y = ltr_df["label"].to_numpy()

    # Split by queries
    qid_list = ltr_df["query_id"].unique().to_list()
    np.random.seed(RANDOM_STATE)
    np.random.shuffle(qid_list)

    split_idx = int(len(qid_list) * (1 - TEST_SIZE))
    train_ids = qid_list[:split_idx]
    test_ids = qid_list[split_idx:]

    logger.info(f"Train queries: {len(train_ids)}, Test queries: {len(test_ids)}")

    # Filter datasets
    ltr_train = ltr_df.filter(pl.col("query_id").is_in(train_ids))
    ltr_test = ltr_df.filter(pl.col("query_id").is_in(test_ids))

    X_train = ltr_train.select(feature_cols).to_numpy()
    y_train = ltr_train["label"].to_numpy()
    train_groups = ltr_train.group_by("query_id", maintain_order=True).len()["len"].to_numpy()

    X_test = ltr_test.select(feature_cols).to_numpy()
    y_test = ltr_test["label"].to_numpy()
    test_groups = ltr_test.group_by("query_id", maintain_order=True).len()["len"].to_numpy()

    logger.info(f"Train samples: {X_train.shape[0]}, Test samples: {X_test.shape[0]}")

    # Hyperparameter search space
    search_space = {
        "max_depth": hp.quniform("max_depth", 3, 12, 1),
        "n_estimators": hp.quniform("n_estimators", 50, 500, 50),
        "learning_rate": hp.loguniform("learning_rate", np.log(0.01), np.log(0.3)),
        "num_leaves": hp.quniform("num_leaves", 15, 127, 1),
        "min_child_samples": hp.quniform("min_child_samples", 5, 50, 5),
        "subsample": hp.uniform("subsample", 0.6, 1.0),
        "colsample_bytree": hp.uniform("colsample_bytree", 0.6, 1.0),
        "reg_alpha": hp.loguniform("reg_alpha", np.log(1e-8), np.log(10.0)),
        "reg_lambda": hp.loguniform("reg_lambda", np.log(1e-8), np.log(10.0)),
    }

    def objective(params):
        """Objective function for Hyperopt."""
        normalized_params = {
            "max_depth": int(params["max_depth"]),
            "n_estimators": int(params["n_estimators"]),
            "learning_rate": params["learning_rate"],
            "num_leaves": int(params["num_leaves"]),
            "min_child_samples": int(params["min_child_samples"]),
            "subsample": params["subsample"],
            "colsample_bytree": params["colsample_bytree"],
            "reg_alpha": params["reg_alpha"],
            "reg_lambda": params["reg_lambda"],
        }

        ranker = lgb.LGBMRanker(
            objective="lambdarank",
            boosting_type="gbdt",
            metric="ndcg",
            verbose=-1,
            **normalized_params
        )

        ranker.fit(X_train, y_train, group=train_groups)
        predictions = ranker.predict(X_test)

        # Calculate mean NDCG per query
        ndcg_scores = []
        idx = 0
        for g in test_groups:
            y_true_q = y_test[idx:idx+g]
            preds_q = predictions[idx:idx+g]
            ndcg_scores.append(ndcg_at_k(y_true_q, preds_q, k=10))
            idx += g

        mean_ndcg = np.mean(ndcg_scores)
        logger.info(f"Mean nDCG@10: {mean_ndcg:.4f}")

        return {"loss": -mean_ndcg, "status": STATUS_OK}

    # Run hyperparameter search
    logger.info(f"Starting hyperparameter search ({MAX_HYPEROPT_EVALS} evaluations)...")
    trials = Trials()
    best_params_raw = fmin(
        fn=objective,
        space=search_space,
        algo=tpe.suggest,
        trials=trials,
        max_evals=MAX_HYPEROPT_EVALS,
    )

    # Normalize best parameters
    best_params = {
        "max_depth": int(best_params_raw["max_depth"]),
        "n_estimators": int(best_params_raw["n_estimators"]),
        "learning_rate": best_params_raw["learning_rate"],
        "num_leaves": int(best_params_raw["num_leaves"]),
        "min_child_samples": int(best_params_raw["min_child_samples"]),
        "subsample": best_params_raw["subsample"],
        "colsample_bytree": best_params_raw["colsample_bytree"],
        "reg_alpha": best_params_raw["reg_alpha"],
        "reg_lambda": best_params_raw["reg_lambda"],
    }

    logger.info(f"Best parameters: {best_params}")

    # Setup MLflow experiment
    experiment = mlflow.get_experiment_by_name(EXPERIMENT_NAME)
    if experiment is None:
        mlflow.create_experiment(EXPERIMENT_NAME)
    mlflow.set_experiment(EXPERIMENT_NAME)

    run_name = f"LGBM Ranker - Airflow - {datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def compute_metrics_per_query(y_true, predictions, groups, ks=[5, 10, 15, 20]):
        """Calculate NDCG metrics per query and average."""
        metrics = {f"nDCG_{k}": [] for k in ks}

        idx = 0
        for g in groups:
            y_true_q = y_true[idx:idx+g]
            preds_q = predictions[idx:idx+g]

            for k in ks:
                metrics[f"nDCG_{k}"].append(ndcg_at_k(y_true_q, preds_q, k=k))
            idx += g

        return {k: np.mean(v) for k, v in metrics.items()}

    with mlflow.start_run(run_name=run_name) as run:
        # Train final model
        logger.info("Training final model...")
        final_ranker = lgb.LGBMRanker(
            objective="lambdarank",
            boosting_type="gbdt",
            metric="ndcg",
            verbose=-1,
            **best_params
        )

        final_ranker.fit(X_train, y_train, group=train_groups)

        # Predictions and metrics
        train_predictions = final_ranker.predict(X_train)
        test_predictions = final_ranker.predict(X_test)

        train_metrics = compute_metrics_per_query(y_train, train_predictions, train_groups)
        test_metrics = compute_metrics_per_query(y_test, test_predictions, test_groups)

        # Log parameters
        mlflow.log_params(best_params)
        mlflow.log_params({
            "test_size": TEST_SIZE,
            "random_state": RANDOM_STATE,
            "num_features": len(feature_cols),
            "feature_names": ",".join(feature_cols),
            "train_queries": len(train_ids),
            "test_queries": len(test_ids),
            "train_samples": X_train.shape[0],
            "test_samples": X_test.shape[0],
            "hyperopt_max_evals": MAX_HYPEROPT_EVALS,
        })

        # Log metrics
        for metric_name, value in test_metrics.items():
            mlflow.log_metric(f"test_{metric_name}", value)

        for metric_name, value in train_metrics.items():
            mlflow.log_metric(f"train_{metric_name}", value)

        mlflow.log_metric("train_test_ndcg10_gap", train_metrics["nDCG_10"] - test_metrics["nDCG_10"])

        # Feature importance
        feature_importance = dict(zip(feature_cols, final_ranker.feature_importances_.tolist()))

        with open("/tmp/feature_importance.json", "w") as f:
            json.dump(feature_importance, f, indent=2)
        mlflow.log_artifact("/tmp/feature_importance.json")

        # Log model
        signature = infer_signature(X_train, train_predictions)

        mlflow.lightgbm.log_model(
            lgb_model=final_ranker,
            artifact_path="model",
            signature=signature,
            input_example=X_train[:5],
            registered_model_name=MODEL_NAME,
        )

        logger.info(f"Test nDCG@10: {test_metrics['nDCG_10']:.4f}")
        logger.info(f"Model registered: {MODEL_NAME}")
        logger.info(f"Run ID: {run.info.run_id}")

    return f"Model trained with test nDCG@10: {test_metrics['nDCG_10']:.4f}"


def promote_champion_model():
    """Promote the best model to champion alias based on metrics."""
    import os
    import mlflow
    import dagshub
    from loguru import logger

    logger.info("Checking for champion promotion...")

    # Set DagsHub token from Airflow Variables
    dagshub_token = Variable.get("dagshub_token")
    os.environ["DAGSHUB_USER_TOKEN"] = dagshub_token

    # Initialize DagsHub MLflow
    dagshub.init(
        repo_owner='abdala9512',
        repo_name='dsrp-machine-learning-engineering-4',
        mlflow=True
    )

    METRIC_TO_COMPARE = "test_nDCG_10"
    client = mlflow.MlflowClient()

    try:
        registered_model = client.get_registered_model(name=MODEL_NAME)

        # Get latest version
        latest_version = registered_model.latest_versions[0].version
        latest_run_id = registered_model.latest_versions[0].run_id
        latest_metric = mlflow.get_run(run_id=latest_run_id).data.metrics.get(METRIC_TO_COMPARE, 0)

        logger.info(f"Latest model version: v{latest_version}")
        logger.info(f"  {METRIC_TO_COMPARE}: {latest_metric:.4f}")

        # Check if champion exists
        if "champion" in registered_model.aliases:
            champion_version = registered_model.aliases["champion"]
            champion_run_id = client.get_model_version(name=MODEL_NAME, version=champion_version).run_id
            champion_metric = mlflow.get_run(run_id=champion_run_id).data.metrics.get(METRIC_TO_COMPARE, 0)

            logger.info(f"Current champion: v{champion_version}")
            logger.info(f"  {METRIC_TO_COMPARE}: {champion_metric:.4f}")

            if latest_version != champion_version:
                if latest_metric >= champion_metric:
                    client.set_registered_model_alias(
                        name=MODEL_NAME,
                        alias="champion",
                        version=latest_version
                    )
                    client.set_registered_model_alias(
                        name=MODEL_NAME,
                        alias="previous_champion",
                        version=champion_version
                    )
                    logger.info(f"Model v{latest_version} promoted to CHAMPION (improvement: {latest_metric - champion_metric:.4f})")
                    return f"Model v{latest_version} promoted to champion"
                else:
                    client.set_registered_model_alias(
                        name=MODEL_NAME,
                        alias="challenger",
                        version=latest_version
                    )
                    logger.info(f"Model v{latest_version} marked as CHALLENGER")
                    return f"Model v{latest_version} marked as challenger"
            else:
                logger.info("Latest version is already the champion")
                return "Latest version already champion"
        else:
            # No champion, promote latest
            client.set_registered_model_alias(
                name=MODEL_NAME,
                alias="champion",
                version=latest_version
            )
            logger.info(f"Model v{latest_version} set as first CHAMPION")
            return f"Model v{latest_version} set as first champion"

    except Exception as e:
        logger.error(f"Error managing model: {e}")
        raise


# =============================================================================
# DAG Definition
# =============================================================================

with DAG(
    dag_id="model_training_dag",
    default_args=default_args,
    description="Train LightGBM LTR model with hyperparameter optimization",
    schedule=timedelta(days=7),  # Weekly, after synthetic queries
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["ml", "ltr", "dsrp", "lightgbm", "mlflow"],
) as dag:

    train_model_task = PythonOperator(
        task_id="train_ltr_model",
        python_callable=train_ltr_model,
        executor_config={"pod_override": generate_pod_config(resources=ml_training_requirements)},
    )

    promote_model_task = PythonOperator(
        task_id="promote_champion_model",
        python_callable=promote_champion_model,
        executor_config={"pod_override": generate_pod_config()},
    )

    train_model_task >> promote_model_task
