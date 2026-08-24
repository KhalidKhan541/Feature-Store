import pandas as pd
import yaml
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, Float, DateTime, Integer, JSON
import json

logger = logging.getLogger(__name__)

Base = declarative_base()

class FeatureView(Base):
    __tablename__ = 'feature_views'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String)
    entities = Column(JSON)
    features = Column(JSON)
    online = Column(Integer, default=1)
    ttl = Column(Integer, default=86400)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Feature(Base):
    __tablename__ = 'features'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    feature_view_name = Column(String, nullable=False)
    feature_name = Column(String, nullable=False)
    feature_type = Column(String, nullable=False)
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class FeatureValue(Base):
    __tablename__ = 'feature_values'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    feature_view_name = Column(String, nullable=False)
    entity_key = Column(String, nullable=False)
    feature_name = Column(String, nullable=False)
    feature_value = Column(Float)
    feature_value_str = Column(String)
    event_timestamp = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class OfflineStore:
    def __init__(self, config_path: str):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.db_config = self.config['offline_store']['postgres']
        self.engine = self._create_engine()
        self._init_db()
    
    def _create_engine(self):
        conn_str = (
            f"postgresql://{self.db_config['user']}:{self.db_config['password']}"
            f"@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}"
        )
        return create_engine(conn_str)
    
    def _init_db(self):
        Base.metadata.create_all(self.engine)
        logger.info("Offline store database initialized")
    
    def create_feature_view(self, name: str, description: str, entities: List[str], 
                           features: List[Dict[str, str]], ttl: int = 86400):
        with self.engine.connect() as conn:
            existing = conn.execute(
                text("SELECT id FROM feature_views WHERE name = :name"),
                {"name": name}
            ).fetchone()
            
            if existing:
                logger.warning(f"Feature view {name} already exists")
                return
            
            conn.execute(
                text("""
                    INSERT INTO feature_views (name, description, entities, features, ttl)
                    VALUES (:name, :description, :entities, :features, :ttl)
                """),
                {
                    "name": name,
                    "description": description,
                    "entities": json.dumps(entities),
                    "features": json.dumps(features),
                    "ttl": ttl
                }
            )
            conn.commit()
            
            for feature in features:
                conn.execute(
                    text("""
                        INSERT INTO features (feature_view_name, feature_name, feature_type, description)
                        VALUES (:fv_name, :f_name, :f_type, :f_desc)
                    """),
                    {
                        "fv_name": name,
                        "f_name": feature['name'],
                        "f_type": feature['type'],
                        "f_desc": feature.get('description', '')
                    }
                )
            conn.commit()
            
            logger.info(f"Created feature view: {name}")
    
    def write_features(self, feature_view_name: str, df: pd.DataFrame, 
                       entity_columns: List[str], event_timestamp_col: str = 'event_timestamp'):
        logger.info(f"Writing {len(df)} rows to offline store for {feature_view_name}")
        
        with self.engine.connect() as conn:
            result = conn.execute(
                text("SELECT features FROM feature_views WHERE name = :name"),
                {"name": feature_view_name}
            ).fetchone()
            
            if not result:
                raise ValueError(f"Feature view {feature_view_name} not found")
            
            features = json.loads(result[0])
            feature_names = [f['name'] for f in features]
            
            for _, row in df.iterrows():
                entity_key = self._make_entity_key(row, entity_columns)
                event_ts = row[event_timestamp_col] if event_timestamp_col in df.columns else datetime.utcnow()
                
                for feature_name in feature_names:
                    if feature_name in df.columns:
                        value = row[feature_name]
                        
                        if pd.isna(value):
                            continue
                        
                        conn.execute(
                            text("""
                                INSERT INTO feature_values 
                                (feature_view_name, entity_key, feature_name, feature_value, event_timestamp)
                                VALUES (:fv_name, :entity_key, :f_name, :f_value, :event_ts)
                                ON CONFLICT (feature_view_name, entity_key, feature_name, event_timestamp) 
                                DO UPDATE SET feature_value = :f_value
                            """),
                            {
                                "fv_name": feature_view_name,
                                "entity_key": entity_key,
                                "f_name": feature_name,
                                "f_value": float(value) if isinstance(value, (int, float)) else None,
                                "event_ts": event_ts
                            }
                        )
            
            conn.commit()
            
            logger.info(f"Written features for {len(df)} entities")
    
    def _make_entity_key(self, row, entity_columns: List[str]) -> str:
        entity_values = [str(row[col]) for col in entity_columns if col in row.index]
        return "|".join(entity_values)
    
    def get_historical_features(self, feature_view_name: str, 
                               entity_df: pd.DataFrame,
                               entity_columns: List[str],
                               event_timestamp_col: str = 'event_timestamp',
                               start_time: Optional[datetime] = None,
                               end_time: Optional[datetime] = None) -> pd.DataFrame:
        logger.info(f"Fetching historical features for {feature_view_name}")
        
        with self.engine.connect() as conn:
            result = conn.execute(
                text("SELECT features FROM feature_views WHERE name = :name"),
                {"name": feature_view_name}
            ).fetchone()
            
            if not result:
                raise ValueError(f"Feature view {feature_view_name} not found")
            
            features = json.loads(result[0])
            feature_names = [f['name'] for f in features]
            
            results = []
            
            for _, entity_row in entity_df.iterrows():
                entity_key = self._make_entity_key(entity_row, entity_columns)
                event_ts = entity_row[event_timestamp_col] if event_timestamp_col in entity_df.columns else datetime.utcnow()
                
                feature_values = {}
                
                for feature_name in feature_names:
                    query = text("""
                        SELECT feature_value 
                        FROM feature_values
                        WHERE feature_view_name = :fv_name
                        AND entity_key = :entity_key
                        AND feature_name = :f_name
                        AND event_timestamp <= :event_ts
                        ORDER BY event_timestamp DESC
                        LIMIT 1
                    """)
                    
                    row_result = conn.execute(query, {
                        "fv_name": feature_view_name,
                        "entity_key": entity_key,
                        "f_name": feature_name,
                        "event_ts": event_ts
                    }).fetchone()
                    
                    feature_values[feature_name] = row_result[0] if row_result else None
                
                results.append({
                    **entity_row.to_dict(),
                    **feature_values
                })
            
            return pd.DataFrame(results)
    
    def get_latest_features(self, feature_view_name: str, 
                           entity_keys: List[str]) -> pd.DataFrame:
        logger.info(f"Fetching latest features for {len(entity_keys)} entities")
        
        with self.engine.connect() as conn:
            result = conn.execute(
                text("SELECT features FROM feature_views WHERE name = :name"),
                {"name": feature_view_name}
            ).fetchone()
            
            if not result:
                raise ValueError(f"Feature view {feature_view_name} not found")
            
            features = json.loads(result[0])
            feature_names = [f['name'] for f in features]
            
            results = []
            
            for entity_key in entity_keys:
                feature_values = {}
                
                for feature_name in feature_names:
                    query = text("""
                        SELECT feature_value 
                        FROM feature_values
                        WHERE feature_view_name = :fv_name
                        AND entity_key = :entity_key
                        AND feature_name = :f_name
                        ORDER BY event_timestamp DESC
                        LIMIT 1
                    """)
                    
                    row = conn.execute(query, {
                        "fv_name": feature_view_name,
                        "entity_key": entity_key,
                        "f_name": feature_name
                    }).fetchone()
                    
                    feature_values[feature_name] = row[0] if row else None
                
                results.append({
                    'entity_key': entity_key,
                    **feature_values
                })
            
            return pd.DataFrame(results)
    
    def delete_feature_view(self, feature_view_name: str):
        with self.engine.connect() as conn:
            conn.execute(
                text("DELETE FROM feature_values WHERE feature_view_name = :name"),
                {"name": feature_view_name}
            )
            conn.execute(
                text("DELETE FROM features WHERE feature_view_name = :name"),
                {"name": feature_view_name}
            )
            conn.execute(
                text("DELETE FROM feature_views WHERE name = :name"),
                {"name": feature_view_name}
            )
            conn.commit()
            
            logger.info(f"Deleted feature view: {feature_view_name}")
    
    def list_feature_views(self) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            result = conn.execute(text("SELECT * FROM feature_views")).fetchall()
            
            return [
                {
                    'name': row.name,
                    'description': row.description,
                    'entities': json.loads(row.entities),
                    'features': json.loads(row.features),
                    'ttl': row.ttl,
                    'created_at': row.created_at
                }
                for row in result
            ]