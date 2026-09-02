-- =============================================================================
-- COUCHE GOLD : Datamarts & Vues Métier pour Metabase
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 🏥 PILOTAGE HOSPITALIER
-- -----------------------------------------------------------------------------

-- 1. Durée Moyenne de Séjour (DMS) par Service
CREATE OR REPLACE VIEW gold.vue_pilotage_dms
DEFINER = default
SQL SECURITY DEFINER
AS SELECT
    s.service_code AS service_code,
    COALESCE(r.service_label, s.service_code) AS service_label,
    countIf(s.is_ongoing = 0) AS nb_sejours_termines,
    countIf(s.is_ongoing = 1) AS nb_sejours_en_cours,
    round(avgIf(s.duree_sejour_jours, s.is_ongoing = 0), 2) AS dms_jours,
    round(medianIf(s.duree_sejour_jours, s.is_ongoing = 0), 2) AS dms_mediane_jours,
    round(minIf(s.duree_sejour_jours, s.is_ongoing = 0), 2) AS dms_min_jours,
    round(maxIf(s.duree_sejour_jours, s.is_ongoing = 0), 2) AS dms_max_jours
FROM silver.fact_sejours AS s
LEFT JOIN silver.dim_services AS r ON s.service_code = r.service_code
GROUP BY s.service_code, service_label
ORDER BY s.service_code;

-- 2. Activité quotidienne des Urgences
CREATE OR REPLACE VIEW gold.vue_pilotage_urgences
DEFINER = default
SQL SECURITY DEFINER
AS SELECT
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
CREATE OR REPLACE VIEW gold.vue_pilotage_readmissions_30j
DEFINER = default
SQL SECURITY DEFINER
AS SELECT
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
);

-- 4. Surveillance des constantes vitales & alertes
CREATE OR REPLACE VIEW gold.vue_pilotage_alertes
DEFINER = default
SQL SECURITY DEFINER
AS SELECT
    toDate(m.ts) AS jour,
    count() AS nb_mesures_totales,
    countIf(m.is_alert = 1) AS nb_alertes_totales,
    countIf(m.is_alert_fc = 1) AS nb_alertes_fc,
    countIf(m.is_alert_spo2 = 1) AS nb_alertes_spo2,
    countIf(m.is_alert_temp = 1) AS nb_alertes_temp,
    round(100.0 * countIf(m.is_alert = 1) / nullIf(count(), 0), 2) AS taux_alertes_pct
FROM silver.fact_monitoring AS m
GROUP BY jour
ORDER BY jour;


-- -----------------------------------------------------------------------------
-- 🔬 RECHERCHE CLINIQUE (Conformité RGPD : Seuil de confidentialité >= 5)
-- -----------------------------------------------------------------------------

-- 1. Prévalence par Pathologie (CIM-10)
CREATE OR REPLACE VIEW gold.vue_recherche_prevalence
DEFINER = default
SQL SECURITY DEFINER
AS SELECT
    d.code_cim10 AS code_cim10,
    COALESCE(r.libelle, d.code_cim10) AS libelle_pathologie,
    count(DISTINCT d.patient_pseudo_id) AS nb_patients_uniques,
    count() AS nb_diagnostics_total,
    countIf(d.diag_type = 'principal') AS nb_diagnostic_principal,
    countIf(d.diag_type = 'associe') AS nb_diagnostic_associe
FROM silver.fact_diagnostics AS d
LEFT JOIN silver.dim_cim10 AS r ON d.code_cim10 = r.code_cim10
GROUP BY code_cim10, libelle_pathologie
ORDER BY nb_patients_uniques DESC;

-- 2. Caractérisation démographique des cohortes (Âge & Sexe)
CREATE OR REPLACE VIEW gold.vue_recherche_cohortes
DEFINER = default
SQL SECURITY DEFINER
AS SELECT
    d.code_cim10 AS code_cim10,
    COALESCE(r.libelle, d.code_cim10) AS libelle_pathologie,
    multiIf(
        d.age_at_diagnostics < 10, '0-9 ans',
        d.age_at_diagnostics < 20, '10-19 ans',
        d.age_at_diagnostics < 30, '20-29 ans',
        d.age_at_diagnostics < 40, '30-39 ans',
        d.age_at_diagnostics < 50, '40-49 ans',
        d.age_at_diagnostics < 60, '50-59 ans',
        d.age_at_diagnostics < 70, '60-69 ans',
        d.age_at_diagnostics < 80, '70-79 ans',
        d.age_at_diagnostics < 90, '80-89 ans',
        d.age_at_diagnostics < 100, '90-99 ans',
        '100+ ans'
    ) AS tranche_age,
    p.sex AS sex,
    count(DISTINCT d.patient_pseudo_id) AS nb_patients
FROM silver.fact_diagnostics AS d
JOIN silver.dim_patients AS p ON d.patient_pseudo_id = p.patient_pseudo_id
LEFT JOIN silver.dim_cim10 AS r ON d.code_cim10 = r.code_cim10
GROUP BY code_cim10, libelle_pathologie, tranche_age, sex
ORDER BY code_cim10, tranche_age, sex;

-- 3. Indicateurs synthétiques globaux pour la recherche
CREATE OR REPLACE VIEW gold.vue_recherche_synthese
DEFINER = default
SQL SECURITY DEFINER
AS SELECT
    count(DISTINCT patient_pseudo_id) AS nb_patients_total,
    count() AS nb_diagnostics_total,
    count(DISTINCT code_cim10) AS nb_pathologies_surveillees
FROM silver.fact_diagnostics;


-- =============================================================================
-- III. DATAMARTS EVOLUTION : PLATEAU TECHNIQUE & FACTURATION T2A (LOT 2026-08-29)
-- =============================================================================

-- KPI 1 : Activité et DMS par Catégorie de Service
CREATE OR REPLACE VIEW gold.vue_pilotage_categories
DEFINER = default
SQL SECURITY DEFINER
AS SELECT
    s.categorie AS categorie,
    s.pole AS pole,
    countIf(f.is_ongoing = 0) AS nb_sejours_termines,
    countIf(f.is_ongoing = 1) AS nb_sejours_en_cours,
    round(avgIf(f.duree_sejour_jours, f.is_ongoing = 0), 2) AS dms_jours
FROM silver.fact_sejours AS f
JOIN silver.dim_services AS s ON f.service_code = s.service_code
GROUP BY s.categorie, s.pole
ORDER BY nb_sejours_termines DESC;

-- KPI 2 : Nombre d'actes par service & moyenne par séjour
CREATE OR REPLACE VIEW gold.vue_pilotage_actes_services
DEFINER = default
SQL SECURITY DEFINER
AS SELECT
    s.service_code AS service_code,
    s.service_label AS service_label,
    s.categorie AS categorie,
    s.pole AS pole,
    count() AS nb_actes_total,
    count(DISTINCT a.stay_id) AS nb_sejours_concernes,
    round(count() / nullIf(count(DISTINCT a.stay_id), 0), 2) AS moyenne_actes_par_sejour
FROM silver.fact_acte AS a
JOIN silver.dim_services AS s ON a.service_code = s.service_code
GROUP BY s.service_code, s.service_label, s.categorie, s.pole
ORDER BY nb_actes_total DESC;

-- KPI 3 : Nombre d'actes par type d'acte CCAM
CREATE OR REPLACE VIEW gold.vue_pilotage_actes_ccam
DEFINER = default
SQL SECURITY DEFINER
AS SELECT
    c.code_ccam AS code_ccam,
    c.libelle AS libelle_acte,
    c.tarif_euros AS tarif_unitaire_euros,
    count() AS nb_actes_total,
    count() * c.tarif_euros AS montant_total_euros
FROM silver.fact_acte AS a
JOIN silver.dim_ccam AS c ON a.code_ccam = c.code_ccam
GROUP BY c.code_ccam, c.libelle, c.tarif_euros
ORDER BY nb_actes_total DESC;

-- KPI 4 : Densité d'actes par lit (Intensité du plateau technique)
CREATE OR REPLACE VIEW gold.vue_pilotage_densite_plateau
DEFINER = default
SQL SECURITY DEFINER
AS SELECT
    s.service_code AS service_code,
    s.service_label AS service_label,
    s.categorie AS categorie,
    s.pole AS pole,
    s.capacite_lits AS capacite_lits,
    count(a.stay_id) AS nb_actes_total,
    round(count(a.stay_id) / nullIf(s.capacite_lits, 0), 2) AS densite_actes_par_lit
FROM silver.dim_services AS s
LEFT JOIN silver.fact_acte AS a ON s.service_code = a.service_code
GROUP BY s.service_code, s.service_label, s.categorie, s.pole, s.capacite_lits
ORDER BY densite_actes_par_lit DESC;

-- KPI 5 : Montant facturé par service T2A (Valorisation financière des actes)
CREATE OR REPLACE VIEW gold.vue_pilotage_facturation_t2a
DEFINER = default
SQL SECURITY DEFINER
AS SELECT
    s.service_code AS service_code,
    s.service_label AS service_label,
    s.categorie AS categorie,
    s.pole AS pole,
    count() AS nb_actes_total,
    sum(c.tarif_euros) AS montant_total_t2a_euros
FROM silver.fact_acte AS a
JOIN silver.dim_services AS s ON a.service_code = s.service_code
JOIN silver.dim_ccam AS c ON a.code_ccam = c.code_ccam
GROUP BY s.service_code, s.service_label, s.categorie, s.pole
ORDER BY montant_total_t2a_euros DESC;

