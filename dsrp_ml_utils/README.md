# DSRP ML Utils

Utility library for ML pipelines in the DSRP Machine Learning Engineering course.

## Installation

```bash
pip install dsrp-ml-utils
```

With Azure storage support:
```bash
pip install dsrp-ml-utils[azure]
```

## Quick Start

```python
from dsrp_ml_utils import (
    load_imdb_database,
    add_derived_features,
    extract_top_genres,
    normalize_embeddings,
)

# Load and prepare data
movies = load_imdb_database("data/movies_base.parquet", "data/omdb_raw.jsonl")
movies = add_derived_features(movies)

# Extract metadata
genres = extract_top_genres(movies, top_n=10)
```

## Features

### Data Loading
- `load_imdb_database()` - Load and combine IMDB data with OMDB enrichment
- `add_derived_features()` - Add computed features (log votes, normalized year, etc.)

### Metadata Extraction
- `extract_top_genres()` - Get most frequent genres
- `extract_decades()` - Get decades present in dataset

### Query Generation
- `generate_template_queries()` - Generate synthetic queries for LTR training

### Candidate Retrieval
- `normalize_embeddings()` - L2 normalize embeddings for cosine similarity
- `get_candidates_for_query()` - Retrieve top-K candidate movies

### Relevance Scoring
- `compute_relevance_score()` - Calculate relevance scores with adjustable emphasis
- `assign_relevance_labels()` - Convert continuous scores to discrete labels

### MLflow Integration
- `search_best_model()` - Search for best run by metric
- `get_artifact_uri_production()` - Get production model artifact URI

### Azure Storage (optional)
- `upload_to_blob()` / `download_from_blob()` - File operations
- `sync_to_azure()` / `sync_from_azure()` - Batch sync operations
- `blob_exists()` / `list_blobs()` - Storage queries

## License

MIT
