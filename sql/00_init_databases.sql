-- Initialisation des bases de données de l'EDS
CREATE DATABASE IF NOT EXISTS bronze;
CREATE DATABASE IF NOT EXISTS silver;
CREATE DATABASE IF NOT EXISTS gold;
CREATE DATABASE IF NOT EXISTS admin;

-- Table de traçabilité des exécutions du pipeline
CREATE TABLE IF NOT EXISTS admin.pipeline_runs (
    run_id UUID DEFAULT generateUUIDv4(),
    started_at DateTime DEFAULT now(),
    finished_at Nullable(DateTime),
    status LowCardinality(String), -- 'RUNNING', 'SUCCESS', 'FAILED'
    step_name String,
    files_processed Array(String),
    records_ingested UInt64,
    records_rejected UInt64,
    error_message Nullable(String)
) ENGINE = MergeTree()
ORDER BY started_at;

-- Utilisateur technique dédié pour la connexion Metabase (Lecture seule)
CREATE USER IF NOT EXISTS metabase_user IDENTIFIED WITH sha256_password BY 'MetabasePassword123!';
GRANT SELECT ON gold.* TO metabase_user;
GRANT SELECT ON system.tables TO metabase_user;
GRANT SELECT ON system.columns TO metabase_user;
GRANT SELECT ON system.databases TO metabase_user;

