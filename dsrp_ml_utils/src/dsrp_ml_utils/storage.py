"""
Azure Blob Storage utilities for ML pipeline.
Works both locally and in Kubernetes.
"""

import os
from pathlib import Path
from typing import Optional, List


def get_blob_service_client():
    """Get Azure Blob Storage client from environment."""
    from azure.storage.blob import BlobServiceClient

    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if conn_str:
        return BlobServiceClient.from_connection_string(conn_str)

    account_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
    if account_url:
        from azure.identity import DefaultAzureCredential
        return BlobServiceClient(account_url, credential=DefaultAzureCredential())

    return None


def upload_to_blob(
    local_path: str,
    blob_name: str,
    container_name: str = "ml-pipeline-data",
) -> Optional[str]:
    """
    Upload a local file to Azure Blob Storage.

    Args:
        local_path: Path to local file
        blob_name: Name of the blob in storage
        container_name: Azure container name

    Returns:
        Blob URL if successful, None if Azure not configured
    """
    client = get_blob_service_client()
    if client is None:
        print(f"Azure not configured, skipping upload of {local_path}")
        return None

    container_client = client.get_container_client(container_name)

    # Create container if it doesn't exist
    if not container_client.exists():
        container_client.create_container()

    blob_client = container_client.get_blob_client(blob_name)

    with open(local_path, "rb") as f:
        blob_client.upload_blob(f, overwrite=True)

    print(f"Uploaded {local_path} -> {container_name}/{blob_name}")
    return blob_client.url


def download_from_blob(
    blob_name: str,
    local_path: str,
    container_name: str = "ml-pipeline-data",
) -> Optional[str]:
    """
    Download a file from Azure Blob Storage.

    Args:
        blob_name: Name of the blob in storage
        local_path: Path to save locally
        container_name: Azure container name

    Returns:
        Local path if successful, None if Azure not configured
    """
    client = get_blob_service_client()
    if client is None:
        print(f"Azure not configured, skipping download of {blob_name}")
        return None

    container_client = client.get_container_client(container_name)
    blob_client = container_client.get_blob_client(blob_name)

    if not blob_client.exists():
        print(f"Blob {blob_name} not found in {container_name}")
        return None

    Path(local_path).parent.mkdir(parents=True, exist_ok=True)

    with open(local_path, "wb") as f:
        f.write(blob_client.download_blob().readall())

    print(f"Downloaded {container_name}/{blob_name} -> {local_path}")
    return local_path


def blob_exists(
    blob_name: str,
    container_name: str = "ml-pipeline-data",
) -> bool:
    """Check if a blob exists in Azure storage."""
    client = get_blob_service_client()
    if client is None:
        return False

    container_client = client.get_container_client(container_name)
    blob_client = container_client.get_blob_client(blob_name)
    return blob_client.exists()


def list_blobs(
    prefix: str = "",
    container_name: str = "ml-pipeline-data",
) -> List[str]:
    """List blobs with given prefix."""
    client = get_blob_service_client()
    if client is None:
        return []

    container_client = client.get_container_client(container_name)
    return [blob.name for blob in container_client.list_blobs(name_starts_with=prefix)]


def sync_to_azure(data_dir: str, container_name: str = "ml-pipeline-data") -> int:
    """
    Sync all parquet, json, npy files from local data dir to Azure.

    Returns number of files uploaded.
    """
    client = get_blob_service_client()
    if client is None:
        print("Azure not configured, skipping sync")
        return 0

    data_path = Path(data_dir)
    extensions = (".parquet", ".json", ".npy", ".jsonl")
    count = 0

    for ext in extensions:
        for f in data_path.glob(f"*{ext}"):
            upload_to_blob(str(f), f.name, container_name)
            count += 1

    return count


def sync_from_azure(data_dir: str, container_name: str = "ml-pipeline-data") -> int:
    """
    Sync all files from Azure container to local data dir.

    Returns number of files downloaded.
    """
    client = get_blob_service_client()
    if client is None:
        print("Azure not configured, skipping sync")
        return 0

    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)

    blobs = list_blobs(container_name=container_name)
    count = 0

    for blob_name in blobs:
        local_path = data_path / blob_name
        download_from_blob(blob_name, str(local_path), container_name)
        count += 1

    return count
