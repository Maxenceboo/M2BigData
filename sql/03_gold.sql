-- =============================================================================
-- COUCHE GOLD : Datamarts & Vues Métier pour Metabase
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 🏥 PILOTAGE HOSPITALIER
-- -----------------------------------------------------------------------------

-- 1. Durée + (DMS) par Service
CREATE OR REPLACE VIEW gold.vue_pilotage_dms AS
SELECT
    s.service_code AS service_code,
    COALESCE(r.service_label, s.service_code) AS service_label,
    toStartOfMonth(s.admission_ts) AS mois_admission, -- pour le group by mois, pour visualiser l'evolution des DMS au fil du temps
    countIf(s.is_ongoing = 0) AS nb_sejours_termines,
    countIf(s.is_ongoing = 1) AS nb_sejours_en_cours,
    round(avgIf(s.duree_sejour_jours, s.is_ongoing = 0), 2) AS dms_jours,
    round(medianIf(s.duree_sejour_jours, s.is_ongoing = 0), 2) AS dms_mediane_jours,
    round(minIf(s.duree_sejour_jours, s.is_ongoing = 0), 2) AS dms_min_jours,
    round(maxIf(s.duree_sejour_jours, s.is_ongoing = 0), 2) AS dms_max_jours
FROM silver.fact_sejours AS s
LEFT JOIN silver.dim_services AS r ON s.service_code = r.service_code
GROUP BY s.service_code, service_label, mois_admission
ORDER BY mois_admission, s.service_code;

-- 2. Activité quotidienne des Urgences
CREATE OR REPLACE VIEW gold.vue_pilotage_urgences AS
SELECT
    toDate(admission_ts) AS date_passage,
    count() AS nb_passages_total,
    countIf(admission_mode = 'urgence') AS nb_urgences_directes,
    countIf(discharge_mode = 'domicile') AS nb_sorties_domicile,
    countIf(discharge_mode = 'mutation') AS nb_mutations_internes,
    countIf(discharge_mode = 'transfert') AS nb_transferts_externes,
    countIf(discharge_mode = 'deces') AS nb_deces,
    countIf(is_ongoing = 1) AS nb_patients_en_cours,
    round(100.0 * countIf(discharge_mode = 'mutation' OR discharge_mode = 'transfert') / nullIf(countIf(is_ongoing = 0), 0), 2) AS taux_hospitalisation_pct
FROM silver.fact_sejours
WHERE service_code = 'URGENCES'
GROUP BY date_passage
ORDER BY date_passage;

-- 3. Taux de réadmission à 30 jours
CREATE OR REPLACE VIEW gold.vue_pilotage_readmissions_30j AS
SELECT
    toStartOfMonth(admission_ts) AS mois,
    count() AS nb_sejours_total,
    countIf(prev_discharge_ts IS NOT NULL AND dateDiff('day', prev_discharge_ts, admission_ts) BETWEEN 1 AND 30) AS nb_readmissions_30j,
    round(100.0 * countIf(prev_discharge_ts IS NOT NULL AND dateDiff('day', prev_discharge_ts, admission_ts) BETWEEN 1 AND 30) / nullIf(count(), 0), 2) AS taux_readmission_pct
FROM (
    SELECT
        stay_id,
        patient_pseudo_id,
        service_code,
        admission_ts,
        discharge_ts,
        lagInFrame(discharge_ts) OVER (
            PARTITION BY patient_pseudo_id 
            ORDER BY admission_ts 
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS prev_discharge_ts
    FROM silver.fact_sejours
    WHERE is_ongoing = 0 AND discharge_ts IS NOT NULL
)
GROUP BY mois
ORDER BY mois;

-- 4. Surveillance des constantes vitales & alertes
CREATE OR REPLACE VIEW gold.vue_pilotage_alertes AS
SELECT
    toDate(m.ts) AS jour,
    m.service_code AS service_code,
    COALESCE(r.service_label, m.service_code) AS service_label,
    count() AS nb_mesures_totales,
    countIf(m.is_alert = 1) AS nb_alertes_totales,
    countIf(m.is_alert_fc = 1) AS nb_alertes_fc,
    countIf(m.is_alert_spo2 = 1) AS nb_alertes_spo2,
    countIf(m.is_alert_temp = 1) AS nb_alertes_temp,
    round(100.0 * countIf(m.is_alert = 1) / nullIf(count(), 0), 2) AS taux_alertes_pct
FROM silver.fact_monitoring AS m
LEFT JOIN silver.dim_services AS r ON m.service_code = r.service_code
GROUP BY jour, m.service_code, service_label
ORDER BY jour, m.service_code;


-- -----------------------------------------------------------------------------
-- 🔬 RECHERCHE CLINIQUE (Conformité RGPD : Seuil de confidentialité >= 5)
-- -----------------------------------------------------------------------------

-- 1. Prévalence par Pathologie (CIM-10)
CREATE OR REPLACE VIEW gold.vue_recherche_prevalence AS
SELECT
    d.code_cim10 AS code_cim10,
    COALESCE(r.libelle, d.code_cim10) AS libelle_pathologie,
    -- Règle RGPD des petits effectifs (< 5 masqué)
    count(DISTINCT d.patient_pseudo_id) AS nb_patients_uniques,
    count() AS nb_diagnostics_total,
    countIf(d.diag_type = 'principal') AS nb_diagnostic_principal,
    countIf(d.diag_type = 'associe') AS nb_diagnostic_associe
FROM silver.fact_diagnostics AS d
LEFT JOIN silver.dim_cim10 AS r ON d.code_cim10 = r.code_cim10
GROUP BY code_cim10, libelle_pathologie
HAVING nb_patients_uniques >= 5
ORDER BY nb_patients_uniques DESC;

-- 2. Caractérisation démographique des cohortes (Âge & Sexe)
CREATE OR REPLACE VIEW gold.vue_recherche_cohortes AS
SELECT
    d.code_cim10 AS code_cim10,
    COALESCE(r.libelle, d.code_cim10) AS libelle_pathologie,
    multiIf(
        d.age_at_diagnostics < 18, '0-17 ans',
        d.age_at_diagnostics <= 35, '18-35 ans',
        d.age_at_diagnostics <= 50, '36-50 ans',
        d.age_at_diagnostics <= 65, '51-65 ans',
        d.age_at_diagnostics <= 80, '66-80 ans',
        '80+ ans'
    ) AS tranche_age,
    p.sex AS sex,
    count(DISTINCT d.patient_pseudo_id) AS nb_patients
FROM silver.fact_diagnostics AS d
JOIN silver.dim_patients AS p ON d.patient_pseudo_id = p.patient_pseudo_id
LEFT JOIN silver.dim_cim10 AS r ON d.code_cim10 = r.code_cim10
GROUP BY code_cim10, libelle_pathologie, tranche_age, sex
HAVING nb_patients >= 5 -- Règle stricte RGPD petits effectifs
ORDER BY code_cim10, tranche_age, sex;
