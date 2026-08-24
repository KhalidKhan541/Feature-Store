import redis
import json
import yaml
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import pandas as pd

logger = logging.getLogger(__name__)

class OnlineStore:
    def __init__(self, config_path: str):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.redis_config = self.config['online_store']['redis']
        self.redis_client = self._create_client()
        self._feature_registry_key = "feature_store:registry"
    
    def _create_client(self):
        return redis.Redis(
            host=self.redis_config['host'],
            port=self.redis_config['port'],
            db=self.redis_config.get('db', 0),
            password=self.redis_config.get('password'),
            decode_responses=True,
            socket_connect_timeout=5,
            retry_on_timeout=True
        )
    
    def ping(self) -> bool:
        try:
            return self.redis_client.ping()
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            return False
    
    def _get_feature_key(self, feature_view_name: str, entity_key: str) -> str:
        return f"fv:{feature_view_name}:entity:{entity_key}"
    
    def _get_entity_features_key(self, feature_view_name: str) -> str:
        return f"fv:{feature_view_name}:entities"
    
    def write_features(self, feature_view_name: str, entity_key: str, 
                      features: Dict[str, Any], ttl: int = 86400):
        key = self._get_feature_key(feature_view_name, entity_key)
        
        feature_data = {
            'entity_key': entity_key,
            'features': features,
            'event_timestamp': datetime.utcnow().isoformat(),
            'feature_view': feature_view_name
        }
        
        pipe = self.redis_client.pipeline()
        
        pipe.set(key, json.dumps(feature_data, default=str))
        pipe.expire(key, ttl)
        
        entities_key = self._get_entity_features_key(feature_view_name)
        pipe.sadd(entities_key, entity_key)
        pipe.expire(entities_key, ttl)
        
        self._update_registry(feature_view_name, list(features.keys()), pipe)
        
        pipe.execute()
        
        logger.info(f"Written features for entity {entity_key} in {feature_view_name}")
    
    def get_features(self, feature_view_name: str, entity_key: str) -> Optional[Dict[str, Any]]:
        key = self._get_feature_key(feature_view_name, entity_key)
        
        data = self.redis_client.get(key)
        
        if data:
            return json.loads(data)
        
        return None
    
    def get_batch_features(self, feature_view_name: str, 
                          entity_keys: List[str]) -> pd.DataFrame:
        pipe = self.redis_client.pipeline()
        
        keys = [
            self._get_feature_key(feature_view_name, ek) 
            for ek in entity_keys
        ]
        
        results = pipe.mget(keys).execute()
        
        rows = []
        for entity_key, data in zip(entity_keys, results):
            if data:
                parsed = json.loads(data)
                row = {'entity_key': entity_key}
                row.update(parsed['features'])
                rows.append(row)
            else:
                rows.append({'entity_key': entity_key})
        
        return pd.DataFrame(rows)
    
    def write_batch_features(self, feature_view_name: str, 
                            entity_keys: List[str],
                            features_batch: List[Dict[str, Any]],
                            ttl: int = 86400):
        pipe = self.redis_client.pipeline()
        
        entities_key = self._get_entity_features_key(feature_view_name)
        pipe.sadd(entities_key, *entity_keys)
        pipe.expire(entities_key, ttl)
        
        for entity_key, features in zip(entity_keys, features_batch):
            key = self._get_feature_key(feature_view_name, entity_key)
            
            feature_data = {
                'entity_key': entity_key,
                'features': features,
                'event_timestamp': datetime.utcnow().isoformat(),
                'feature_view': feature_view_name
            }
            
            pipe.set(key, json.dumps(feature_data, default=str))
            pipe.expire(key, ttl)
        
        self._update_registry(feature_view_name, 
                             list(features_batch[0].keys()) if features_batch else [], 
                             pipe)
        
        pipe.execute()
        
        logger.info(f"Batch written {len(entity_keys)} entities to {feature_view_name}")
    
    def _update_registry(self, feature_view_name: str, feature_names: List[str], pipe):
        registry = self.redis_client.hget(self._feature_registry_key, feature_view_name)
        
        if registry:
            existing = json.loads(registry)
            all_features = list(set(existing.get('features', []) + feature_names))
        else:
            all_features = feature_names
        
        registry_data = {
            'features': all_features,
            'updated_at': datetime.utcnow().isoformat()
        }
        
        pipe.hset(self._feature_registry_key, feature_view_name, json.dumps(registry_data))
    
    def get_feature_view_info(self, feature_view_name: str) -> Optional[Dict[str, Any]]:
        registry = self.redis_client.hget(self._feature_registry_key, feature_view_name)
        
        if registry:
            return json.loads(registry)
        
        return None
    
    def list_feature_views(self) -> List[str]:
        return list(self.redis_client.hkeys(self._feature_registry_key))
    
    def delete_entity(self, feature_view_name: str, entity_key: str):
        key = self._get_feature_key(feature_view_name, entity_key)
        entities_key = self._get_entity_features_key(feature_view_name)
        
        pipe = self.redis_client.pipeline()
        pipe.delete(key)
        pipe.srem(entities_key, entity_key)
        pipe.execute()
        
        logger.info(f"Deleted entity {entity_key} from {feature_view_name}")
    
    def delete_feature_view(self, feature_view_name: str):
        entities_key = self._get_entity_features_key(feature_view_name)
        entity_keys = self.redis_client.smembers(entities_key)
        
        pipe = self.redis_client.pipeline()
        
        for entity_key in entity_keys:
            key = self._get_feature_key(feature_view_name, entity_key)
            pipe.delete(key)
        
        pipe.delete(entities_key)
        pipe.hdel(self._feature_registry_key, feature_view_name)
        
        pipe.execute()
        
        logger.info(f"Deleted feature view {feature_view_name} with {len(entity_keys)} entities")
    
    def get_ttl(self, feature_view_name: str, entity_key: str) -> int:
        key = self._get_feature_key(feature_view_name, entity_key)
        return self.redis_client.ttl(key)