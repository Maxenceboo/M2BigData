-- =============================================================================
-- COUCHE BRONZE : Tables brutes typées
-- =============================================================================

-- 1. Patients (pseudonymisés dès l'entrée du Lake)
CREATE TABLE IF NOT EXISTS bronze.patients (
    patient_pseudo_id String,
    birth_year UInt16,
    sex LowCardinality(String),
    region_code LowCardinality(String),
    source_date Date,
    source_file String,
    ingested_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (source_date, patient_pseudo_id);

-- 2. Séjours hospitaliers
CREATE TABLE IF NOT EXISTS bronze.sejours (
    stay_id String,
    patient_pseudo_id String,
    service_code LowCardinality(String),
    admission_ts DateTime,
    discharge_ts Nullable(DateTime),
    admission_mode LowCardinality(String),
    discharge_mode LowCardinality(String),
    source_date Date,
    source_file String,
    ingested_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (source_date, service_code, stay_id);

-- 3. Diagnostics (aplatis depuis le JSON)
CREATE TABLE IF NOT EXISTS bronze.diagnostics (
    stay_id String,
    code_cim10 LowCardinality(String),
    diag_type LowCardinality(String),
    source_date Date,
    source_file String,
    ingested_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (source_date, code_cim10, stay_id);

-- 4. Monitoring (constantes vitales chevet)
CREATE TABLE IF NOT EXISTS bronze.monitoring (
    stay_id String,
    ts DateTime,
    heart_rate Nullable(Int16),
    spo2 Nullable(Int16),
    temp_c Nullable(Float32),
    source_date Date,
    source_file String,
    ingested_at DateTime DEFAULT now()
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(source_date)
ORDER BY (stay_id, ts);

-- 5. Référentiels
CREATE TABLE IF NOT EXISTS bronze.ref_services (
    service_code LowCardinality(String),
    service_label String,
    source_file String,
    ingested_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY service_code;

CREATE TABLE IF NOT EXISTS bronze.ref_cim10 (
    code_cim10 LowCardinality(String),
    libelle String,
    source_file String,
    ingested_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY code_cim10;

-- 6. Évolution Lot 2026-08-29 : Description fine des services
CREATE TABLE IF NOT EXISTS bronze.ref_description_service (
    service_code LowCardinality(String),
    categorie LowCardinality(String),
    capacite_lits UInt16,
    pole LowCardinality(String),
    source_file String,
    ingested_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY service_code;

-- 7. Évolution Lot 2026-08-29 : Référentiel Nomenclature CCAM
CREATE TABLE IF NOT EXISTS bronze.ref_ccam (
    code_ccam LowCardinality(String),
    libelle String,
    tarif_euros UInt32,
    source_file String,
    ingested_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY code_ccam;

-- 8. Évolution Lot 2026-08-29 : Flux de faits Actes Médicaux
CREATE TABLE IF NOT EXISTS bronze.actes (
    stay_id String,
    code_ccam LowCardinality(String),
    acte_ts DateTime,
    source_date Date,
    source_file String,
    ingested_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (source_date, stay_id, acte_ts);

