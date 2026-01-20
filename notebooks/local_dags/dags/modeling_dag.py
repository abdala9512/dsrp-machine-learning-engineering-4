"""
Modeling DAG - DSRP ML Pipeline

Trains LightGBM ranker with MLflow tracking.
Can run as standalone script or Airflow DAG.
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List

import numpy as np
import polars as pl

# Configuration from environment
DATA_DIR = os.environ.get("DSRP_DATA_DIR", str(Path(__file__).parent.parent.parent / "data"))
MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "")
MLFLOW_EXPERIMENT_NAME = os.environ.get("MLFLOW_EXPERIMENT_NAME", "DSRP-LTR-Pipeline")
MODEL_NAME = os.environ.get("LTR_MODEL_NAME", "ltr-dsrpflix-pipeline")
HYPEROPT_MAX_EVALS = int(os.environ.get("HYPEROPT_MAX_EVALS", "15"))
TEST_SIZE = float(os.environ.get("LTR_TEST_SIZE", "0.2"))
RANDOM_STATE = int(os.environ.get("LTR_RANDOM_STATE", "42"))


# =============================================================================
# Helper Functions
# =============================================================================

def dcg(relevances: np.ndarray) -> float:
    """Discounted Cumulative Gain."""
    relevances = np.array(relevances)
    discounts = 1 / np.log2(np.arange(2, len(relevances) + 2))
    return float(np.sum(relevances * discounts))


def ndcg_at_k(true_rels: np.ndarray, pred_scores: np.ndarray, k: int = 10) -> float:
    """Compute NDCG@k for a single query."""
    idx = np.argsort(-pred_scores)[:k]
    sorted_true = np.array(true_rels)[idx]
    dcg_k = dcg(sorted_true)
    ideal_sorted = np.sort(true_rels)[::-1][:k]
    idcg_k = dcg(ideal_sorted)
    return dcg_k / idcg_k if idcg_k > 0 else 0.0


def compute_metrics_per_query(
    y_true: np.ndarray,
    predictions: np.ndarray,
    groups: np.ndarray,
    ks: List[int] = [5, 10, 15, 20],
) -> Dict[str, float]:
    """Compute NDCG metrics per query and average."""
    metrics = {f"nDCG_{k}": [] for k in ks}
    idx = 0
    for g in groups:
        y_true_q = y_true[idx:idx + g]
        preds_q = predictions[idx:idx + g]
        for k in ks:
            metrics[f"nDCG_{k}"].append(ndcg_at_k(y_true_q, preds_q, k=k))
        idx += g
    return {k: float(np.mean(v)) for k, v in metrics.items()}


# =============================================================================
# Task Functions
# =============================================================================

def load_and_split_data() -> Dict[str, str]:
    """Load LTR dataset and split into train/test."""
    dataset_path = os.path.join(DATA_DIR, "ltr_imdb_dataset.parquet")

    print(f"Loading dataset from {dataset_path}")
    ltr_df = pl.read_parquet(dataset_path)

    print(f"Dataset: {ltr_df.shape}, Queries: {ltr_df['query_id'].n_unique()}")

    qid_list = ltr_df["query_id"].unique().to_list()
    np.random.seed(RANDOM_STATE)
    np.random.shuffle(qid_list)

    split_idx = int(len(qid_list) * (1 - TEST_SIZE))
    train_ids = qid_list[:split_idx]
    test_ids = qid_list[split_idx:]

    print(f"Train queries: {len(train_ids)}, Test queries: {len(test_ids)}")

    train_df = ltr_df.filter(pl.col("query_id").is_in(train_ids))
    test_df = ltr_df.filter(pl.col("query_id").is_in(test_ids))

    train_path = os.path.join(DATA_DIR, "ltr_train.parquet")
    test_path = os.path.join(DATA_DIR, "ltr_test.parquet")

    train_df.write_parquet(train_path)
    test_df.write_parquet(test_path)

    print(f"Train samples: {train_df.height}, Test samples: {test_df.height}")

    return {
        "train_path": train_path,
        "test_path": test_path,
        "train_queries": len(train_ids),
        "test_queries": len(test_ids),
    }


def hyperparameter_optimization(split_info: Dict[str, str] = None) -> Dict[str, Any]:
    """Run hyperparameter optimization using Hyperopt."""
    from hyperopt import STATUS_OK, Trials, fmin, hp, tpe
    import lightgbm as lgb

    split_info = split_info or {
        "train_path": os.path.join(DATA_DIR, "ltr_train.parquet"),
        "test_path": os.path.join(DATA_DIR, "ltr_test.parquet"),
    }

    train_df = pl.read_parquet(split_info["train_path"])
    test_df = pl.read_parquet(split_info["test_path"])

    feature_cols = [c for c in train_df.columns if c.startswith("emb_")] + [
        "sim_embedding", "imdb_rating", "imdb_votes_log",
    ]
    feature_cols = [c for c in feature_cols if c in train_df.columns]

    print(f"Features: {feature_cols}")

    X_train = train_df.select(feature_cols).to_numpy()
    y_train = train_df["label"].to_numpy()
    train_groups = train_df.group_by("query_id", maintain_order=True).len()["len"].to_numpy()

    X_test = test_df.select(feature_cols).to_numpy()
    y_test = test_df["label"].to_numpy()
    test_groups = test_df.group_by("query_id", maintain_order=True).len()["len"].to_numpy()

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
        normalized = {
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
            objective="lambdarank", boosting_type="gbdt", metric="ndcg", verbose=-1, **normalized,
        )
        ranker.fit(X_train, y_train, group=train_groups)
        predictions = ranker.predict(X_test)

        ndcg_scores = []
        idx = 0
        for g in test_groups:
            ndcg_scores.append(ndcg_at_k(y_test[idx:idx + g], predictions[idx:idx + g], k=10))
            idx += g

        mean_ndcg = np.mean(ndcg_scores)
        print(f"Mean nDCG@10: {mean_ndcg:.4f}")
        return {"loss": -mean_ndcg, "status": STATUS_OK}

    print(f"Running hyperparameter optimization ({HYPEROPT_MAX_EVALS} evaluations)...")
    trials = Trials()
    best_params = fmin(fn=objective, space=search_space, algo=tpe.suggest, trials=trials, max_evals=HYPEROPT_MAX_EVALS)

    normalized_best = {
        "max_depth": int(best_params["max_depth"]),
        "n_estimators": int(best_params["n_estimators"]),
        "learning_rate": best_params["learning_rate"],
        "num_leaves": int(best_params["num_leaves"]),
        "min_child_samples": int(best_params["min_child_samples"]),
        "subsample": best_params["subsample"],
        "colsample_bytree": best_params["colsample_bytree"],
        "reg_alpha": best_params["reg_alpha"],
        "reg_lambda": best_params["reg_lambda"],
    }

    print(f"Best params: {json.dumps(normalized_best, indent=2)}")

    params_path = os.path.join(DATA_DIR, "best_params.json")
    with open(params_path, "w") as f:
        json.dump(normalized_best, f, indent=2)

    return {"best_params": normalized_best, "params_path": params_path, "feature_cols": feature_cols}


def train_final_model(split_info: Dict[str, str] = None, opt_result: Dict[str, Any] = None) -> Dict[str, Any]:
    """Train final model with best hyperparameters and log to MLflow."""
    import mlflow
    from mlflow.models.signature import infer_signature
    import lightgbm as lgb

    split_info = split_info or {
        "train_path": os.path.join(DATA_DIR, "ltr_train.parquet"),
        "test_path": os.path.join(DATA_DIR, "ltr_test.parquet"),
    }

    if opt_result is None:
        params_path = os.path.join(DATA_DIR, "best_params.json")
        with open(params_path, "r") as f:
            best_params = json.load(f)
        train_df = pl.read_parquet(split_info["train_path"])
        feature_cols = [c for c in train_df.columns if c.startswith("emb_")] + [
            "sim_embedding", "imdb_rating", "imdb_votes_log",
        ]
        feature_cols = [c for c in feature_cols if c in train_df.columns]
    else:
        best_params = opt_result["best_params"]
        feature_cols = opt_result["feature_cols"]

    train_df = pl.read_parquet(split_info["train_path"])
    test_df = pl.read_parquet(split_info["test_path"])

    X_train = train_df.select(feature_cols).to_numpy()
    y_train = train_df["label"].to_numpy()
    train_groups = train_df.group_by("query_id", maintain_order=True).len()["len"].to_numpy()

    X_test = test_df.select(feature_cols).to_numpy()
    y_test = test_df["label"].to_numpy()
    test_groups = test_df.group_by("query_id", maintain_order=True).len()["len"].to_numpy()

    if MLFLOW_TRACKING_URI:
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    experiment = mlflow.get_experiment_by_name(MLFLOW_EXPERIMENT_NAME)
    if experiment is None:
        mlflow.create_experiment(MLFLOW_EXPERIMENT_NAME)
    mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)

    run_name = f"LTR-Pipeline-{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    with mlflow.start_run(run_name=run_name) as run:
        print("Training final model...")
        ranker = lgb.LGBMRanker(
            objective="lambdarank", boosting_type="gbdt", metric="ndcg", verbose=-1, **best_params,
        )
        ranker.fit(X_train, y_train, group=train_groups)

        train_preds = ranker.predict(X_train)
        test_preds = ranker.predict(X_test)

        train_metrics = compute_metrics_per_query(y_train, train_preds, train_groups)
        test_metrics = compute_metrics_per_query(y_test, test_preds, test_groups)

        mlflow.log_params(best_params)
        mlflow.log_params({
            "feature_names": ",".join(feature_cols),
            "num_features": len(feature_cols),
            "hyperopt_max_evals": HYPEROPT_MAX_EVALS,
        })

        for metric_name, value in test_metrics.items():
            mlflow.log_metric(f"test_{metric_name}", value)
        for metric_name, value in train_metrics.items():
            mlflow.log_metric(f"train_{metric_name}", value)

        mlflow.log_metric("train_test_gap", train_metrics["nDCG_10"] - test_metrics["nDCG_10"])

        feature_importance = dict(zip(feature_cols, ranker.feature_importances_.tolist()))
        feat_imp_path = os.path.join(DATA_DIR, "feature_importance.json")
        with open(feat_imp_path, "w") as f:
            json.dump(feature_importance, f, indent=2)
        mlflow.log_artifact(feat_imp_path)

        signature = infer_signature(X_train, train_preds)
        mlflow.lightgbm.log_model(
            lgb_model=ranker, artifact_path="model", signature=signature,
            input_example=X_train[:5], registered_model_name=MODEL_NAME,
        )

        print(f"\nTest Metrics:")
        for k, v in test_metrics.items():
            print(f"  {k}: {v:.4f}")

        print(f"\nRun ID: {run.info.run_id}")

        return {
            "run_id": run.info.run_id,
            "test_metrics": test_metrics,
            "train_metrics": train_metrics,
            "model_name": MODEL_NAME,
        }


def promote_model(train_result: Dict[str, Any] = None) -> Dict[str, Any]:
    """Promote model to champion if it beats the current champion."""
    import mlflow

    if MLFLOW_TRACKING_URI:
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    client = mlflow.MlflowClient()
    metric_to_compare = "test_nDCG_10"

    try:
        registered_model = client.get_registered_model(name=MODEL_NAME)
        latest_version = registered_model.latest_versions[0].version
        latest_run_id = registered_model.latest_versions[0].run_id
        latest_metric = mlflow.get_run(run_id=latest_run_id).data.metrics.get(metric_to_compare, 0)

        print(f"Latest version: v{latest_version}, {metric_to_compare}: {latest_metric:.4f}")

        if "champion" in registered_model.aliases:
            champion_version = registered_model.aliases["champion"]
            champion_run_id = client.get_model_version(name=MODEL_NAME, version=champion_version).run_id
            champion_metric = mlflow.get_run(run_id=champion_run_id).data.metrics.get(metric_to_compare, 0)

            print(f"Champion: v{champion_version}, {metric_to_compare}: {champion_metric:.4f}")

            if latest_version != champion_version and latest_metric >= champion_metric:
                client.set_registered_model_alias(name=MODEL_NAME, alias="champion", version=latest_version)
                client.set_registered_model_alias(name=MODEL_NAME, alias="previous_champion", version=champion_version)
                print(f"Model v{latest_version} promoted to CHAMPION")
                return {"action": "promoted", "version": latest_version, "metric": latest_metric}
            elif latest_version != champion_version:
                client.set_registered_model_alias(name=MODEL_NAME, alias="challenger", version=latest_version)
                print(f"Model v{latest_version} marked as CHALLENGER")
                return {"action": "challenger", "version": latest_version, "metric": latest_metric}
            else:
                print("Latest version is already champion")
                return {"action": "no_change", "version": latest_version}
        else:
            client.set_registered_model_alias(name=MODEL_NAME, alias="champion", version=latest_version)
            print(f"Model v{latest_version} set as first CHAMPION")
            return {"action": "first_champion", "version": latest_version, "metric": latest_metric}

    except Exception as e:
        print(f"Error during promotion: {e}")
        return {"action": "error", "error": str(e)}


def save_training_summary(
    split_info: Dict[str, str] = None,
    opt_result: Dict[str, Any] = None,
    train_result: Dict[str, Any] = None,
    promote_result: Dict[str, Any] = None,
) -> str:
    """Save training summary."""
    summary = {
        "timestamp": datetime.now().isoformat(),
        "dataset": split_info or {},
        "hyperparameters": opt_result.get("best_params", {}) if opt_result else {},
        "features": opt_result.get("feature_cols", []) if opt_result else [],
        "metrics": {
            "train": train_result.get("train_metrics", {}) if train_result else {},
            "test": train_result.get("test_metrics", {}) if train_result else {},
        },
        "mlflow": {
            "run_id": train_result.get("run_id", "") if train_result else "",
            "model_name": train_result.get("model_name", "") if train_result else "",
        },
        "promotion": promote_result or {},
    }

    output_path = os.path.join(DATA_DIR, "training_summary.json")
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"Training summary saved to {output_path}")
    return output_path


# =============================================================================
# Airflow DAG (optional)
# =============================================================================

try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator

    default_args = {
        "owner": "dsrp-ml",
        "depends_on_past": False,
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
    }

    with DAG(
        dag_id="modeling",
        default_args=default_args,
        description="Train LTR model with hyperparameter optimization",
        schedule=None,
        start_date=datetime(2024, 1, 1),
        catchup=False,
        tags=["dsrp", "modeling", "ltr", "mlflow"],
    ) as dag:

        t1 = PythonOperator(task_id="load_and_split_data", python_callable=load_and_split_data)
        t2 = PythonOperator(
            task_id="hyperparameter_optimization",
            python_callable=hyperparameter_optimization,
            execution_timeout=timedelta(hours=2),
        )
        t3 = PythonOperator(task_id="train_final_model", python_callable=train_final_model)
        t4 = PythonOperator(task_id="promote_model", python_callable=promote_model)
        t5 = PythonOperator(task_id="save_training_summary", python_callable=save_training_summary)

        t1 >> t2 >> t3 >> t4 >> t5

except ImportError:
    dag = None


# =============================================================================
# Standalone execution
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Modeling Pipeline")
    parser.add_argument("--step", choices=["all", "split", "hyperopt", "train", "promote", "summary"], default="all")
    args = parser.parse_args()

    split_info = None
    opt_result = None
    train_result = None
    promote_result = None

    if args.step in ["all", "split"]:
        split_info = load_and_split_data()

    if args.step in ["all", "hyperopt"]:
        opt_result = hyperparameter_optimization(split_info)

    if args.step in ["all", "train"]:
        train_result = train_final_model(split_info, opt_result)

    if args.step in ["all", "promote"]:
        promote_result = promote_model(train_result)

    if args.step in ["all", "summary"]:
        save_training_summary(split_info, opt_result, train_result, promote_result)
