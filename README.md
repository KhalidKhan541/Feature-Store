# Feature Store

A minimal feature store with PostgreSQL (offline) and Redis (online) for consistent feature serving, solving the classic training/serving skew problem.

## Features

- **Offline Store (PostgreSQL)** - Historical feature storage for training
- **Online Store (Redis)** - Low-latency feature serving for inference
- **Skew Detection** - Automatically detect training/serving inconsistency
- **REST API** - FastAPI endpoints for feature management
- **Feature Versioning** - Track feature evolution over time
- **Monitoring** - Feature freshness, coverage, and drift metrics

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Feature Store API                          │
│                    (FastAPI + Python 3.10)                       │
└─────────────────────────────────────────────────────────────────┘
                                │
           ┌────────────────────┼────────────────────┐
           │                    │                    │
           ▼                    ▼                    ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Offline Store  │    │  Online Store   │    │ Skew Detector   │
│  (PostgreSQL)   │    │    (Redis)      │    │                 │
│                 │    │                 │    │ - Feature skew  │
│ - Training data │    │ - Serving data  │    │ - Coverage      │
│ - Historical    │    │ - Low latency   │    │ - Distribution  │
│ - Batch queries │    │ - Real-time     │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
           │                    │
           ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PostgreSQL + Redis                            │
│                    (Data Layer)                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Using Docker Compose

```bash
git clone https://github.com/KhalidKhan541/Feature-Store.git
cd Feature-Store
docker-compose up -d
```

### Access API

- **API:** http://localhost:8000
- **Docs:** http://localhost:8000/docs
- **PostgreSQL:** localhost:5432
- **Redis:** localhost:6379

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/feature-views` | GET/POST | List/create feature views |
| `/feature-views/{name}` | GET/DELETE | Get/delete feature view |
| `/ingest` | POST | Ingest features |
| `/features/online` | POST | Get online features |
| `/features/online/{fv}/{key}` | GET | Get single entity features |
| `/features/historical` | POST | Get historical features |
| `/skew/{fv}` | GET | Check for skew |
| `/health` | GET | Health check |

## Usage Examples

### Create Feature View

```python
import requests

response = requests.post("http://localhost:8000/feature-views", json={
    "name": "user_features",
    "description": "User behavioral features",
    "entities": ["user_id"],
    "features": [
        {"name": "purchase_count", "type": "int"},
        {"name": "avg_order_value", "type": "float"},
        {"name": "days_since_last_purchase", "type": "int"}
    ],
    "ttl": 86400
})
```

### Ingest Features

```python
response = requests.post("http://localhost:8000/ingest", json={
    "feature_view_name": "user_features",
    "entity_columns": ["user_id"],
    "data": [
        {"user_id": "user_123", "purchase_count": 15, "avg_order_value": 89.99, "days_since_last_purchase": 3},
        {"user_id": "user_456", "purchase_count": 8, "avg_order_value": 45.50, "days_since_last_purchase": 14}
    ]
})
```

### Get Online Features (Serving)

```python
response = requests.post("http://localhost:8000/features/online", json={
    "feature_view_name": "user_features",
    "entity_keys": ["user_123", "user_456"]
})

features = response.json()["features"]
# [{"user_id": "user_123", "purchase_count": 15, ...}, ...]
```

### Get Historical Features (Training)

```python
response = requests.post("http://localhost:8000/features/historical", json={
    "feature_view_name": "user_features",
    "entity_columns": ["user_id"],
    "entities": [
        {"user_id": "user_123", "event_timestamp": "2024-01-15T10:00:00"},
        {"user_id": "user_456", "event_timestamp": "2024-01-15T10:00:00"}
    ]
})
```

### Check for Skew

```python
response = requests.get("http://localhost:8000/skew/user_features")
skew_report = response.json()
# {"has_skew": false, "skew_type": [], "statistics": {...}}
```

## Training/Serving Skew Detection

The feature store automatically monitors for:

| Skew Type | Description | Threshold |
|-----------|-------------|-----------|
| Feature Skew | Features in training missing in serving | 5% |
| Coverage Skew | Entity coverage drop | 20% |
| Distribution Skew | Temporal distribution mismatch | 2x |

### How It Works

1. **Training Request** - Logged when `get_historical_features()` is called
2. **Serving Request** - Logged when `get_online_features()` is called
3. **Skew Detection** - Compares feature sets, coverage, and distributions
4. **Alerting** - Notifications when skew exceeds thresholds

## Project Structure

```
feature-store/
├── src/
│   ├── __init__.py
│   ├── feature_store.py          # Main feature store class
│   ├── offline_store.py          # PostgreSQL offline store
│   ├── online_store.py           # Redis online store
│   ├── skew_detector.py          # Training/serving skew detection
│   └── api.py                    # FastAPI REST API
├── config/
│   └── feature_store_config.yaml # Configuration
├── migrations/
│   └── init_db.sql               # Database schema
├── tests/
│   └── test_feature_store.py     # Unit tests
├── docker-compose.yml            # Docker setup
├── Dockerfile
├── requirements.txt
└── README.md
```

## Configuration

Edit `config/feature_store_config.yaml`:

```yaml
offline_store:
  postgres:
    host: localhost
    port: 5432
    database: feature_store

online_store:
  redis:
    host: localhost
    port: 6379

skew_detection:
  thresholds:
    missing_feature_rate: 0.05
    entity_coverage_drop: 0.2
```

## Development

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run Tests

```bash
pytest tests/ -v
```

### Run Locally

```bash
uvicorn src.api:app --reload --host 0.0.0.0 --port 8000
```

## License

MIT License