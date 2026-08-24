-- Feature Store Database Schema
-- ============================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Feature Views table
CREATE TABLE IF NOT EXISTS feature_views (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    entities JSONB NOT NULL,
    features JSONB NOT NULL,
    online INTEGER DEFAULT 1,
    ttl INTEGER DEFAULT 86400,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Features table (metadata about individual features)
CREATE TABLE IF NOT EXISTS features (
    id SERIAL PRIMARY KEY,
    feature_view_name VARCHAR(255) NOT NULL,
    feature_name VARCHAR(255) NOT NULL,
    feature_type VARCHAR(50) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (feature_view_name) REFERENCES feature_views(name) ON DELETE CASCADE
);

-- Feature Values table (actual feature data)
CREATE TABLE IF NOT EXISTS feature_values (
    id SERIAL PRIMARY KEY,
    feature_view_name VARCHAR(255) NOT NULL,
    entity_key VARCHAR(500) NOT NULL,
    feature_name VARCHAR(255) NOT NULL,
    feature_value DOUBLE PRECISION,
    feature_value_str TEXT,
    event_timestamp TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (feature_view_name) REFERENCES feature_views(name) ON DELETE CASCADE
);

-- Feature Statistics table (for monitoring)
CREATE TABLE IF NOT EXISTS feature_statistics (
    id SERIAL PRIMARY KEY,
    feature_view_name VARCHAR(255) NOT NULL,
    feature_name VARCHAR(255) NOT NULL,
    statistic_type VARCHAR(50) NOT NULL,
    statistic_value DOUBLE PRECISION,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (feature_view_name) REFERENCES feature_views(name) ON DELETE CASCADE
);

-- Skew Detection Log
CREATE TABLE IF NOT EXISTS skew_log (
    id SERIAL PRIMARY KEY,
    feature_view_name VARCHAR(255) NOT NULL,
    skew_type VARCHAR(50) NOT NULL,
    details JSONB,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (feature_view_name) REFERENCES feature_views(name) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_feature_values_entity 
    ON feature_values(feature_view_name, entity_key);

CREATE INDEX IF NOT EXISTS idx_feature_values_timestamp 
    ON feature_values(feature_view_name, event_timestamp);

CREATE INDEX IF NOT EXISTS idx_feature_values_name 
    ON feature_values(feature_view_name, feature_name);

CREATE INDEX IF NOT EXISTS idx_features_view_name 
    ON features(feature_view_name);

CREATE INDEX IF NOT EXISTS idx_skew_log_view_name 
    ON skew_log(feature_view_name);

-- Create user for the feature store
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'feature_store_user') THEN
        CREATE ROLE feature_store_user WITH LOGIN PASSWORD 'feature_store_password';
    END IF;
END
$$;

-- Grant permissions
GRANT ALL PRIVILEGES ON DATABASE feature_store TO feature_store_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO feature_store_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO feature_store_user;