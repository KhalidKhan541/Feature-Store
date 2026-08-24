import pytest
import pandas as pd
import numpy as np
import yaml
import tempfile
import os
from datetime import datetime, timedelta

from src.offline_store import OfflineStore
from src.online_store import OnlineStore
from src.skew_detector import SkewDetector

@pytest.fixture
def sample_config():
    config = {
        'offline_store': {
            'postgres': {
                'host': 'localhost',
                'port': 5432,
                'database': 'test_feature_store',
                'user': 'test_user',
                'password': 'test_password'
            }
        },
        'online_store': {
            'redis': {
                'host': 'localhost',
                'port': 6379,
                'db': 15,
                'password': None
            }
        },
        'skew_detection': {
            'enabled': True,
            'thresholds': {
                'feature_distribution_drift': 0.1,
                'missing_feature_rate': 0.05,
                'entity_coverage_drop': 0.2,
                'latency_p99_ms': 100
            }
        }
    }
    return config

@pytest.fixture
def sample_data():
    np.random.seed(42)
    n_samples = 100
    
    data = {
        'user_id': range(1, n_samples + 1),
        'feature_1': np.random.randn(n_samples) * 10,
        'feature_2': np.random.uniform(0, 100, n_samples),
        'feature_3': np.random.choice([0, 1, 2, 3], n_samples),
        'category': np.random.choice(['A', 'B', 'C'], n_samples),
        'event_timestamp': pd.date_range('2024-01-01', periods=n_samples, freq='h')
    }
    
    return pd.DataFrame(data)

@pytest.fixture
def config_file(sample_config):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(sample_config, f)
        temp_path = f.name
    
    yield temp_path
    
    os.unlink(temp_path)

def test_skew_detector_no_requests(sample_config):
    detector = SkewDetector.__new__(SkewDetector)
    detector.config = sample_config
    detector.skew_config = sample_config.get('skew_detection', {})
    detector.request_log = {}
    detector.skew_thresholds = sample_config['skew_detection']['thresholds']
    
    report = detector.detect_skew('test_feature_view')
    
    assert report['has_skew'] == False
    assert report['feature_view_name'] == 'test_feature_view'

def test_skew_detector_with_requests(sample_config):
    detector = SkewDetector.__new__(SkewDetector)
    detector.config = sample_config
    detector.skew_config = sample_config.get('skew_detection', {})
    detector.request_log = {
        'test_view': [
            {'type': 'training', 'timestamp': datetime.now().isoformat(), 
             'entity_count': 100, 'feature_columns': ['f1', 'f2']},
            {'type': 'serving', 'timestamp': datetime.now().isoformat(),
             'entity_count': 100, 'feature_columns': ['f1', 'f2']}
        ]
    }
    detector.skew_thresholds = sample_config['skew_detection']['thresholds']
    
    report = detector.detect_skew('test_view')
    
    assert 'statistics' in report
    assert report['statistics']['total_requests'] == 2

def test_skew_detector_feature_skew(sample_config):
    detector = SkewDetector.__new__(SkewDetector)
    detector.config = sample_config
    detector.skew_config = sample_config.get('skew_detection', {})
    detector.request_log = {
        'test_view': [
            {'type': 'training', 'timestamp': datetime.now().isoformat(),
             'entity_count': 100, 'feature_columns': ['f1', 'f2', 'f3']},
            {'type': 'serving', 'timestamp': datetime.now().isoformat(),
             'entity_count': 100, 'feature_columns': ['f1', 'f2']}
        ]
    }
    detector.skew_thresholds = sample_config['skew_detection']['thresholds']
    
    report = detector.detect_skew('test_view')
    
    assert report['has_skew'] == True
    assert 'feature_skew' in report['skew_type']

def test_skew_detector_coverage_skew(sample_config):
    detector = SkewDetector.__new__(SkewDetector)
    detector.config = sample_config
    detector.skew_config = sample_config.get('skew_detection', {})
    detector.request_log = {
        'test_view': [
            {'type': 'training', 'timestamp': datetime.now().isoformat(),
             'entity_count': 1000, 'feature_columns': ['f1', 'f2']},
            {'type': 'serving', 'timestamp': datetime.now().isoformat(),
             'entity_count': 100, 'feature_columns': ['f1', 'f2']}
        ]
    }
    detector.skew_thresholds = sample_config['skew_detection']['thresholds']
    
    report = detector.detect_skew('test_view')
    
    assert report['has_skew'] == True
    assert 'coverage_skew' in report['skew_type']

def test_skew_detector_recommendations(sample_config):
    detector = SkewDetector.__new__(SkewDetector)
    detector.config = sample_config
    detector.skew_config = sample_config.get('skew_detection', {})
    detector.request_log = {
        'test_view': [
            {'type': 'training', 'timestamp': datetime.now().isoformat(),
             'entity_count': 100, 'feature_columns': ['f1', 'f2', 'f3']},
            {'type': 'serving', 'timestamp': datetime.now().isoformat(),
             'entity_count': 100, 'feature_columns': ['f1', 'f2']}
        ]
    }
    detector.skew_thresholds = sample_config['skew_detection']['thresholds']
    
    summary = detector.get_skew_summary('test_view')
    
    assert 'recommendations' in summary
    assert len(summary['recommendations']) > 0

def test_online_store_key_generation():
    from src.online_store import OnlineStore
    
    store = OnlineStore.__new__(OnlineStore)
    store.config = {'online_store': {'redis': {'host': 'localhost', 'port': 6379, 'db': 0}}}
    store.redis_client = None
    store._feature_registry_key = "test:registry"
    
    key = store._get_feature_key("user_features", "user_123")
    assert key == "fv:user_features:entity:user_123"

def test_sample_data_generation(sample_data):
    assert len(sample_data) == 100
    assert 'user_id' in sample_data.columns
    assert 'feature_1' in sample_data.columns
    assert 'event_timestamp' in sample_data.columns