from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, List, Any, Optional
from datetime import datetime
import pandas as pd
import yaml
import json

from .feature_store import FeatureStore

app = FastAPI(title="Feature Store API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

feature_store = None

class FeatureViewCreate(BaseModel):
    name: str
    description: str
    entities: List[str]
    features: List[Dict[str, str]]
    ttl: int = 86400
    online: bool = True

class FeatureIngest(BaseModel):
    feature_view_name: str
    entity_columns: List[str]
    event_timestamp_col: str = 'event_timestamp'
    write_online: bool = True
    data: List[Dict[str, Any]]

class OnlineFeatureRequest(BaseModel):
    feature_view_name: str
    entity_keys: List[str]

class HistoricalFeatureRequest(BaseModel):
    feature_view_name: str
    entity_columns: List[str]
    event_timestamp_col: str = 'event_timestamp'
    entities: List[Dict[str, Any]]

@app.on_event("startup")
def startup():
    global feature_store
    feature_store = FeatureStore("config/feature_store_config.yaml")

@app.get("/")
def root():
    return {"message": "Feature Store API"}

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "online_store": feature_store.online_store.ping(),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/feature-views")
def create_feature_view(data: FeatureViewCreate):
    try:
        feature_store.create_feature_view(
            name=data.name,
            description=data.description,
            entities=data.entities,
            features=data.features,
            ttl=data.ttl,
            online=data.online
        )
        return {"status": "created", "name": data.name}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/feature-views")
def list_feature_views():
    return feature_store.list_feature_views()

@app.get("/feature-views/{name}")
def get_feature_view(name: str):
    for fv in feature_store.list_feature_views():
        if fv['name'] == name:
            return fv
    raise HTTPException(status_code=404, detail="Feature view not found")

@app.delete("/feature-views/{name}")
def delete_feature_view(name: str):
    try:
        feature_store.delete_feature_view(name)
        return {"status": "deleted", "name": name}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/ingest")
def ingest_features(data: FeatureIngest):
    try:
        df = pd.DataFrame(data.data)
        
        feature_store.ingest_features(
            feature_view_name=data.feature_view_name,
            df=df,
            entity_columns=data.entity_columns,
            event_timestamp_col=data.event_timestamp_col,
            write_online=data.write_online
        )
        
        return {
            "status": "ingested",
            "rows": len(data.data),
            "feature_view": data.feature_view_name
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/features/online")
def get_online_features(request: OnlineFeatureRequest):
    try:
        df = feature_store.get_online_features(
            feature_view_name=request.feature_view_name,
            entity_keys=request.entity_keys
        )
        
        return {
            "feature_view": request.feature_view_name,
            "features": df.to_dict(orient='records')
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/features/online/{feature_view_name}/{entity_key}")
def get_online_feature(feature_view_name: str, entity_key: str):
    try:
        features = feature_store.get_online_feature(
            feature_view_name=feature_view_name,
            entity_key=entity_key
        )
        
        if features is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        
        return {
            "feature_view": feature_view_name,
            "entity_key": entity_key,
            "features": features
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/features/historical")
def get_historical_features(request: HistoricalFeatureRequest):
    try:
        entity_df = pd.DataFrame(request.entities)
        
        df = feature_store.get_historical_features(
            feature_view_name=request.feature_view_name,
            entity_df=entity_df,
            entity_columns=request.entity_columns,
            event_timestamp_col=request.event_timestamp_col
        )
        
        return {
            "feature_view": request.feature_view_name,
            "features": df.to_dict(orient='records'),
            "row_count": len(df)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/skew/{feature_view_name}")
def check_skew(feature_view_name: str):
    try:
        return feature_store.check_skew(feature_view_name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/statistics/{feature_view_name}")
def get_statistics(feature_view_name: str):
    try:
        return feature_store.get_feature_statistics(feature_view_name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))