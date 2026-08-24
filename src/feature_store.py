import pandas as pd
import yaml
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from .offline_store import OfflineStore
from .online_store import OnlineStore
from .skew_detector import SkewDetector

logger = logging.getLogger(__name__)

class FeatureStore:
    def __init__(self, config_path: str):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.offline_store = OfflineStore(config_path)
        self.online_store = OnlineStore(config_path)
        self.skew_detector = SkewDetector(config_path)
        
        self.feature_registry = {}
        
        logger.info("Feature Store initialized")
    
    def create_feature_view(self, name: str, description: str, 
                           entities: List[str], features: List[Dict[str, str]],
                           ttl: int = 86400, online: bool = True):
        self.offline_store.create_feature_view(
            name=name,
            description=description,
            entities=entities,
            features=features,
            ttl=ttl
        )
        
        self.feature_registry[name] = {
            'description': description,
            'entities': entities,
            'features': features,
            'ttl': ttl,
            'online': online
        }
        
        logger.info(f"Created feature view: {name}")
    
    def ingest_features(self, feature_view_name: str, df: pd.DataFrame,
                       entity_columns: List[str], 
                       event_timestamp_col: str = 'event_timestamp',
                       write_online: bool = True):
        logger.info(f"Ingesting {len(df)} rows for {feature_view_name}")
        
        self.offline_store.write_features(
            feature_view_name=feature_view_name,
            df=df,
            entity_columns=entity_columns,
            event_timestamp_col=event_timestamp_col
        )
        
        if write_online and self._is_online_enabled(feature_view_name):
            entity_keys = df.apply(
                lambda row: self._make_entity_key(row, entity_columns), 
                axis=1
            ).tolist()
            
            features_list = []
            for _, row in df.iterrows():
                features = {}
                for col in df.columns:
                    if col not in entity_columns and col != event_timestamp_col:
                        val = row[col]
                        if not pd.isna(val):
                            features[col] = val
                features_list.append(features)
            
            self.online_store.write_batch_features(
                feature_view_name=feature_view_name,
                entity_keys=entity_keys,
                features_batch=features_list,
                ttl=self._get_ttl(feature_view_name)
            )
        
        logger.info(f"Completed ingestion for {feature_view_name}")
    
    def get_historical_features(self, feature_view_name: str,
                               entity_df: pd.DataFrame,
                               entity_columns: List[str],
                               event_timestamp_col: str = 'event_timestamp',
                               start_time: Optional[datetime] = None,
                               end_time: Optional[datetime] = None) -> pd.DataFrame:
        logger.info(f"Getting historical features for {feature_view_name}")
        
        result_df = self.offline_store.get_historical_features(
            feature_view_name=feature_view_name,
            entity_df=entity_df,
            entity_columns=entity_columns,
            event_timestamp_col=event_timestamp_col,
            start_time=start_time,
            end_time=end_time
        )
        
        self.skew_detector.log_training_request(
            feature_view_name=feature_view_name,
            entity_count=len(entity_df),
            feature_columns=[f['name'] for f in self._get_features(feature_view_name)]
        )
        
        return result_df
    
    def get_online_features(self, feature_view_name: str,
                           entity_keys: List[str]) -> pd.DataFrame:
        logger.info(f"Getting online features for {len(entity_keys)} entities")
        
        result_df = self.online_store.get_batch_features(
            feature_view_name=feature_view_name,
            entity_keys=entity_keys
        )
        
        self.skew_detector.log_serving_request(
            feature_view_name=feature_view_name,
            entity_count=len(entity_keys),
            feature_columns=[f['name'] for f in self._get_features(feature_view_name)]
        )
        
        return result_df
    
    def get_online_feature(self, feature_view_name: str,
                          entity_key: str) -> Optional[Dict[str, Any]]:
        result = self.online_store.get_features(
            feature_view_name=feature_view_name,
            entity_key=entity_key
        )
        
        if result:
            return result.get('features', {})
        
        return None
    
    def _make_entity_key(self, row, entity_columns: List[str]) -> str:
        entity_values = [str(row[col]) for col in entity_columns if col in row.index]
        return "|".join(entity_values)
    
    def _is_online_enabled(self, feature_view_name: str) -> bool:
        if feature_view_name in self.feature_registry:
            return self.feature_registry[feature_view_name].get('online', True)
        return True
    
    def _get_ttl(self, feature_view_name: str) -> int:
        if feature_view_name in self.feature_registry:
            return self.feature_registry[feature_view_name].get('ttl', 86400)
        return 86400
    
    def _get_features(self, feature_view_name: str) -> List[Dict[str, str]]:
        if feature_view_name in self.feature_registry:
            return self.feature_registry[feature_view_name].get('features', [])
        return []
    
    def check_skew(self, feature_view_name: str) -> Dict[str, Any]:
        return self.skew_detector.detect_skew(feature_view_name)
    
    def list_feature_views(self) -> List[Dict[str, Any]]:
        return self.offline_store.list_feature_views()
    
    def delete_feature_view(self, feature_view_name: str):
        self.offline_store.delete_feature_view(feature_view_name)
        self.online_store.delete_feature_view(feature_view_name)
        
        if feature_view_name in self.feature_registry:
            del self.feature_registry[feature_view_name]
        
        logger.info(f"Deleted feature view: {feature_view_name}")
    
    def get_feature_statistics(self, feature_view_name: str) -> Dict[str, Any]:
        features = self._get_features(feature_view_name)
        feature_names = [f['name'] for f in features]
        
        online_views = self.online_store.list_feature_views()
        
        return {
            'feature_view_name': feature_view_name,
            'feature_count': len(features),
            'feature_names': feature_names,
            'online_available': feature_view_name in online_views,
            'entities': self.feature_registry.get(feature_view_name, {}).get('entities', [])
        }