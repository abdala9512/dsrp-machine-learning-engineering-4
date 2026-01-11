import mlflow
from typing import List


def search_best_model(
        experiment_names: List[str] = [],
        metric_name: str = "ndcg5"
    ) -> str:
    """Search Best Run ID of given experiments
    """
    runs_  = mlflow.search_runs(experiment_names=experiment_names)
    best_run = runs_.loc[runs_[f'metrics.{metric_name}'].idxmax()]

    
    return best_run['run_id'], best_run["artifact_uri"]



def get_artifact_uri_production(model_name: str) -> str:

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    client = mlflow.MlflowClient()
    for mv in client.search_model_versions(f"name='{model_name}'"):
        model = dict(mv)
        if model["current_stage"] == "Production":
            production_model = model

    _run_id = production_model.get("run_id")
    return mlflow.get_run(_run_id).info.artifact_uri