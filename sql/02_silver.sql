-- =============================================================================
-- COUCHE SILVER : Tables de Dimensions et de Faits (Cleaned & Deduplicated)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. DIMENSIONS
-- -----------------------------------------------------------------------------

-- Dimension Patients dédupliquée
CREATE TABLE IF NOT EXISTS silver.dim_patients (
    patient_pseudo_id String,
    birth_year UInt16,
    sex LowCardinality(String),
    region_code LowCardinality(String),
    updated_at Date
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY patient_pseudo_id;

-- Dimension Services (enrichie avec hiérarchie : service -> catégorie -> pôle)
CREATE TABLE IF NOT EXISTS silver.dim_services (
    service_code LowCardinality(String),
    service_label String,
    categorie LowCardinality(String),
    capacite_lits UInt16,
    pole LowCardinality(String)
) ENGINE = ReplacingMergeTree()
ORDER BY service_code;

-- Dimension CCAM (Nomenclature des Actes Médicaux)
CREATE TABLE IF NOT EXISTS silver.dim_ccam (
    code_ccam LowCardinality(String),
    libelle String,
    tarif_euros UInt32
) ENGINE = ReplacingMergeTree()
ORDER BY code_ccam;

-- Dimension CIM-10 (Diagnostics)
CREATE TABLE IF NOT EXISTS silver.dim_cim10 (
    code_cim10 LowCardinality(String),
    libelle String
) ENGINE = ReplacingMergeTree()
ORDER BY code_cim10;


-- -----------------------------------------------------------------------------
-- 2. TABLES DE FAITS (FACTS)
-- -----------------------------------------------------------------------------

-- FACT 1 : Séjours Hospitaliers
CREATE TABLE IF NOT EXISTS silver.fact_sejours (
    stay_id String,
    patient_pseudo_id String,
    service_code LowCardinality(String),
    admission_ts DateTime,
    discharge_ts Nullable(DateTime),
    admission_mode LowCardinality(String),
    discharge_mode LowCardinality(String),
    is_ongoing UInt8,
    duree_sejour_heures Nullable(Float32),
    duree_sejour_jours Nullable(Float32),
    created_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (service_code, admission_ts, stay_id);

-- FACT 2 : Diagnostics Posés
CREATE TABLE IF NOT EXISTS silver.fact_diagnostics (
    stay_id String,
    patient_pseudo_id String,
    age_at_diagnostics UInt8, -- Calculé avec toYear(stay.admission_ts) - patient.birth_year
    code_cim10 LowCardinality(String),
    diag_type LowCardinality(String),
    created_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (code_cim10, patient_pseudo_id, stay_id);

-- FACT 3 : Monitoring & Constantes Vitales
CREATE TABLE IF NOT EXISTS silver.fact_monitoring (
    stay_id String,
    service_code LowCardinality(String),
    ts DateTime,
    heart_rate Nullable(Int16),
    spo2 Nullable(Int16),
    temp_c Nullable(Float32),
    is_alert UInt8,
    is_alert_fc UInt8,
    is_alert_spo2 UInt8,
    is_alert_temp UInt8,
    alert_reasons LowCardinality(String)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(ts)
ORDER BY (service_code, stay_id, ts);

-- FACT 4 : Actes Médicaux (Évolution Lot 2026-08-29)
CREATE TABLE IF NOT EXISTS silver.fact_acte (
    stay_id String,
    service_code LowCardinality(String),
    code_ccam LowCardinality(String),
    acte_ts DateTime,
    created_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (service_code, code_ccam, stay_id, acte_ts);

