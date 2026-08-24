import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np

logger = logging.getLogger(__name__)

class SkewDetector:
    def __init__(self, config_path: str):
        import yaml
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.skew_config = self.config.get('skew_detection', {})
        self.request_log = defaultdict(list)
        self.skew_thresholds = self.skew_config.get('thresholds', {
            'feature_distribution_drift': 0.1,
            'missing_feature_rate': 0.05,
            'entity_coverage_drop': 0.2,
            'latency_p99_ms': 100
        })
    
    def log_training_request(self, feature_view_name: str, 
                            entity_count: int, feature_columns: List[str]):
        self.request_log[feature_view_name].append({
            'type': 'training',
            'timestamp': datetime.utcnow().isoformat(),
            'entity_count': entity_count,
            'feature_columns': feature_columns
        })
        
        self._trim_log(feature_view_name)
    
    def log_serving_request(self, feature_view_name: str,
                           entity_count: int, feature_columns: List[str]):
        self.request_log[feature_view_name].append({
            'type': 'serving',
            'timestamp': datetime.utcnow().isoformat(),
            'entity_count': entity_count,
            'feature_columns': feature_columns
        })
        
        self._trim_log(feature_view_name)
    
    def _trim_log(self, feature_view_name: str, max_entries: int = 1000):
        if len(self.request_log[feature_view_name]) > max_entries:
            self.request_log[feature_view_name] = \
                self.request_log[feature_view_name][-max_entries:]
    
    def detect_skew(self, feature_view_name: str) -> Dict[str, Any]:
        skew_report = {
            'feature_view_name': feature_view_name,
            'timestamp': datetime.utcnow().isoformat(),
            'has_skew': False,
            'skew_type': [],
            'details': {}
        }
        
        requests = self.request_log.get(feature_view_name, [])
        
        if not requests:
            skew_report['details']['message'] = 'No requests logged yet'
            return skew_report
        
        training_requests = [r for r in requests if r['type'] == 'training']
        serving_requests = [r for r in requests if r['type'] == 'serving']
        
        if training_requests and serving_requests:
            feature_skew = self._check_feature_skew(training_requests, serving_requests)
            if feature_skew['detected']:
                skew_report['has_skew'] = True
                skew_report['skew_type'].append('feature_skew')
                skew_report['details']['feature_skew'] = feature_skew
            
            coverage_skew = self._check_coverage_skew(training_requests, serving_requests)
            if coverage_skew['detected']:
                skew_report['has_skew'] = True
                skew_report['skew_type'].append('coverage_skew')
                skew_report['details']['coverage_skew'] = coverage_skew
            
            distribution_skew = self._check_distribution_skew(training_requests, serving_requests)
            if distribution_skew['detected']:
                skew_report['has_skew'] = True
                skew_report['skew_type'].append('distribution_skew')
                skew_report['details']['distribution_skew'] = distribution_skew
        
        skew_report['statistics'] = {
            'total_requests': len(requests),
            'training_requests': len(training_requests),
            'serving_requests': len(serving_requests),
            'last_training': training_requests[-1]['timestamp'] if training_requests else None,
            'last_serving': serving_requests[-1]['timestamp'] if serving_requests else None
        }
        
        return skew_report
    
    def _check_feature_skew(self, training_requests: List[Dict], 
                           serving_requests: List[Dict]) -> Dict[str, Any]:
        training_features = set()
        for req in training_requests[-10:]:
            training_features.update(req['feature_columns'])
        
        serving_features = set()
        for req in serving_requests[-10:]:
            serving_features.update(req['feature_columns'])
        
        missing_in_serving = training_features - serving_features
        extra_in_serving = serving_features - training_features
        
        detected = bool(missing_in_serving or extra_in_serving)
        
        return {
            'detected': detected,
            'missing_in_serving': list(missing_in_serving),
            'extra_in_serving': list(extra_in_serving),
            'threshold': self.skew_thresholds['missing_feature_rate']
        }
    
    def _check_coverage_skew(self, training_requests: List[Dict],
                           serving_requests: List[Dict]) -> Dict[str, Any]:
        training_entities = [req['entity_count'] for req in training_requests[-10:]]
        serving_entities = [req['entity_count'] for req in serving_requests[-10:]]
        
        avg_training = np.mean(training_entities) if training_entities else 0
        avg_serving = np.mean(serving_entities) if serving_entities else 0
        
        if avg_training > 0:
            coverage_ratio = avg_serving / avg_training
        else:
            coverage_ratio = 1.0
        
        threshold = self.skew_thresholds['entity_coverage_drop']
        detected = coverage_ratio < (1 - threshold)
        
        return {
            'detected': detected,
            'avg_training_entities': float(avg_training),
            'avg_serving_entities': float(avg_serving),
            'coverage_ratio': float(coverage_ratio),
            'threshold': threshold
        }
    
    def _check_distribution_skew(self, training_requests: List[Dict],
                               serving_requests: List[Dict]) -> Dict[str, Any]:
        training_timestamps = [
            datetime.fromisoformat(req['timestamp']) 
            for req in training_requests[-20:]
        ]
        serving_timestamps = [
            datetime.fromisoformat(req['timestamp'])
            for req in serving_requests[-20:]
        ]
        
        if not training_timestamps or not serving_timestamps:
            return {'detected': False, 'reason': 'Insufficient data'}
        
        training_span = (max(training_timestamps) - min(training_timestamps)).total_seconds() / 3600
        serving_span = (max(serving_timestamps) - min(serving_timestamps)).total_seconds() / 3600
        
        if training_span > 0:
            temporal_ratio = serving_span / training_span
        else:
            temporal_ratio = 1.0
        
        detected = temporal_ratio > 2.0 or temporal_ratio < 0.1
        
        return {
            'detected': detected,
            'training_time_span_hours': float(training_span),
            'serving_time_span_hours': float(serving_span),
            'temporal_ratio': float(temporal_ratio)
        }
    
    def get_skew_summary(self, feature_view_name: str) -> Dict[str, Any]:
        skew_report = self.detect_skew(feature_view_name)
        
        summary = {
            'feature_view': feature_view_name,
            'status': 'SKEW DETECTED' if skew_report['has_skew'] else 'HEALTHY',
            'skew_types': skew_report['skew_type'],
            'recommendations': self._get_recommendations(skew_report)
        }
        
        return summary
    
    def _get_recommendations(self, skew_report: Dict[str, Any]) -> List[str]:
        recommendations = []
        
        if 'feature_skew' in skew_report.get('skew_type', []):
            feature_skew = skew_report['details'].get('feature_skew', {})
            if feature_skew.get('missing_in_serving'):
                recommendations.append(
                    f"Add missing features to serving pipeline: {feature_skew['missing_in_serving']}"
                )
            if feature_skew.get('extra_in_serving'):
                recommendations.append(
                    f"Remove extra features from serving: {feature_skew['extra_in_serving']}"
                )
        
        if 'coverage_skew' in skew_report.get('skew_type', []):
            recommendations.append(
                "Review entity coverage - serving is missing training entities"
            )
        
        if 'distribution_skew' in skew_report.get('skew_type', []):
            recommendations.append(
                "Temporal distribution mismatch detected - review data pipeline timing"
            )
        
        if not recommendations:
            recommendations.append("No action required - features are consistent")
        
        return recommendations