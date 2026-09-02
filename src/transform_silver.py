"""
Script de Transformation Bronze -> Silver (100% SQL ClickHouse).

Règles de Gestion et Qualité :
1. silver.dim_patients : Déduplication temporelle (version la plus récente conservée).
2. silver.dim_services & silver.dim_cim10 : Tables de dimensions dédupliquées.
3. silver.fact_sejours : Élimination des dates incohérentes (discharge_ts < admission_ts),
   conservation des séjours en cours (discharge_ts IS NULL -> is_ongoing=1), calcul de la durée en jours.
4. silver.fact_diagnostics : Calcul de l'âge au moment du diagnostic (toYear(admission_ts) - birth_year),
   clé étrangère code_cim10 sans duplication de libellé.
5. silver.fact_monitoring : Filtrage des constantes hors bornes physiologiques
   (FC [20, 250], SpO2 [50, 100], Temp [30.0, 45.0]) et calcul pré-agrégé de l'alerte médicale.
"""

import sys
from pathlib import Path

# Forcer l'encodage UTF-8 sous Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import clickhouse_connect


def get_clickhouse_client(host="localhost", port=8123, username="default", password=""):
    return clickhouse_connect.get_client(host=host, port=port, username=username, password=password)


def execute_sql_file(client, sql_file_path: Path):
    with open(sql_file_path, "r", encoding="utf-8") as f:
        content = f.read()
    statements = [s.strip() for s in content.split(";") if s.strip()]
    for stmt in statements:
        client.command(stmt)


def run_silver_transformations():
    print("=" * 70)
    print("[START] EXECUTION DES TRANSFORMATIONS COUCHE SILVER (100% SQL)")
    print("=" * 70)

    client = get_clickhouse_client()

    # 1. Initialiser ou mettre à jour le schéma Silver
    print("[INFO] Initialisation des tables Silver...")
    client.command("DROP TABLE IF EXISTS silver.fact_diagnostics")
    client.command("DROP TABLE IF EXISTS silver.fact_monitoring")
    client.command("DROP TABLE IF EXISTS silver.fact_acte")
    client.command("DROP TABLE IF EXISTS silver.dim_services")
    client.command("DROP TABLE IF EXISTS silver.dim_ccam")
    sql_silver = BASE_DIR / "sql" / "02_silver.sql"
    execute_sql_file(client, sql_silver)
    print("  [OK] Schéma Silver vérifié.")

    # 2. Dimensions Référentiels
    print("\n[INFO] Transformation silver.dim_services, silver.dim_cim10 & silver.dim_ccam...")
    client.command("TRUNCATE TABLE silver.dim_services")
    client.command("""
        INSERT INTO silver.dim_services (service_code, service_label, categorie, capacite_lits, pole)
        SELECT 
            s.service_code,
            s.service_label,
            if(d.service_code = '' OR d.categorie = '', 'Non catégorisé', d.categorie) AS categorie,
            if(d.service_code = '', 0, d.capacite_lits) AS capacite_lits,
            if(d.service_code = '' OR d.pole = '', 'Pôle Indéterminé', d.pole) AS pole
        FROM bronze.ref_services s
        LEFT JOIN bronze.ref_description_service d ON s.service_code = d.service_code
    """)
    srv_count = client.query("SELECT count() FROM silver.dim_services").result_rows[0][0]
    print(f"  [OK] silver.dim_services : {srv_count} services chargés (avec hiérarchie et pôles)")

    client.command("TRUNCATE TABLE silver.dim_ccam")
    client.command("""
        INSERT INTO silver.dim_ccam (code_ccam, libelle, tarif_euros)
        SELECT DISTINCT code_ccam, libelle, tarif_euros
        FROM bronze.ref_ccam
    """)
    ccam_count = client.query("SELECT count() FROM silver.dim_ccam").result_rows[0][0]
    print(f"  [OK] silver.dim_ccam : {ccam_count} actes CCAM chargés")

    client.command("TRUNCATE TABLE silver.dim_cim10")
    client.command("""
        INSERT INTO silver.dim_cim10 (code_cim10, libelle)
        SELECT DISTINCT code_cim10, libelle
        FROM bronze.ref_cim10
    """)
    cim_count = client.query("SELECT count() FROM silver.dim_cim10").result_rows[0][0]
    print(f"  [OK] silver.dim_cim10 : {cim_count} pathologies chargées")

    # 3. Dimension Patients (Déduplication temporelle)
    print("\n[INFO] Transformation & Déduplication silver.dim_patients...")
    client.command("TRUNCATE TABLE silver.dim_patients")
    client.command("""
        INSERT INTO silver.dim_patients (patient_pseudo_id, birth_year, sex, region_code, updated_at)
        SELECT
            patient_pseudo_id,
            argMax(birth_year, source_date) AS birth_year,
            argMax(sex, source_date) AS sex,
            argMax(region_code, source_date) AS region_code,
            max(source_date) AS updated_at
        FROM bronze.patients
        GROUP BY patient_pseudo_id
    """)
    bronze_pat = client.query("SELECT count() FROM bronze.patients").result_rows[0][0]
    silver_pat = client.query("SELECT count() FROM silver.dim_patients").result_rows[0][0]
    print(f"  [OK] silver.dim_patients : {silver_pat} patients uniques (depuis {bronze_pat} lignes brutes, {bronze_pat - silver_pat} doublons fusionnés)")

    # 4. FACT Séjours (Validation temporelle et calcul durée)
    print("\n[INFO] Transformation & Contrôle Qualité silver.fact_sejours...")
    client.command("TRUNCATE TABLE silver.fact_sejours")
    client.command("""
        INSERT INTO silver.fact_sejours (
            stay_id, patient_pseudo_id, service_code, 
            admission_ts, discharge_ts, admission_mode, discharge_mode, 
            is_ongoing, duree_sejour_heures, duree_sejour_jours
        )
        SELECT
            stay_id,
            patient_pseudo_id,
            service_code,
            admission_ts,
            discharge_ts,
            admission_mode,
            discharge_mode,
            if(discharge_ts IS NULL, 1, 0) AS is_ongoing,
            if(discharge_ts IS NOT NULL, round(dateDiff('second', admission_ts, discharge_ts) / 3600.0, 2), NULL) AS duree_sejour_heures,
            if(discharge_ts IS NOT NULL, round(dateDiff('second', admission_ts, discharge_ts) / 86400.0, 2), NULL) AS duree_sejour_jours
        FROM bronze.sejours
        WHERE discharge_ts IS NULL OR discharge_ts >= admission_ts
    """)
    bronze_sej = client.query("SELECT count() FROM bronze.sejours").result_rows[0][0]
    silver_sej = client.query("SELECT count() FROM silver.fact_sejours").result_rows[0][0]
    invalid_sej = bronze_sej - silver_sej
    ongoing_sej = client.query("SELECT count() FROM silver.fact_sejours WHERE is_ongoing = 1").result_rows[0][0]
    print(f"  [OK] silver.fact_sejours : {silver_sej} séjours valides")
    print(f"       - {invalid_sej} séjours incohérents écartés (discharge < admission)")
    print(f"       - {ongoing_sej} séjours en cours légitimement conservés")

    # 5. FACT Diagnostics (Calcul âge au diagnostic, code_cim10 pur, patient_pseudo_id)
    print("\n[INFO] Transformation silver.fact_diagnostics (avec calcul age_at_diagnostics & patient_pseudo_id)...")
    client.command("""
        INSERT INTO silver.fact_diagnostics (stay_id, patient_pseudo_id, age_at_diagnostics, code_cim10, diag_type)
        SELECT DISTINCT
            d.stay_id,
            s.patient_pseudo_id,
            toUInt8(greatest(0, toYear(s.admission_ts) - p.birth_year)) AS age_at_diagnostics,
            d.code_cim10,
            d.diag_type
        FROM bronze.diagnostics AS d
        JOIN bronze.sejours AS s ON d.stay_id = s.stay_id
        JOIN silver.dim_patients AS p ON s.patient_pseudo_id = p.patient_pseudo_id
    """)
    silver_dia = client.query("SELECT count() FROM silver.fact_diagnostics").result_rows[0][0]
    print(f"  [OK] silver.fact_diagnostics : {silver_dia} diagnostics enregistrés avec calcul d'âge")

    # 6. FACT Monitoring (Filtrage bornes physiologiques, précalcul alertes et service_code)
    print("\n[INFO] Transformation & Filtrage physiologique silver.fact_monitoring...")
    client.command("TRUNCATE TABLE silver.fact_monitoring")
    client.command("""
        INSERT INTO silver.fact_monitoring (
            stay_id, service_code, ts, heart_rate, spo2, temp_c, 
            is_alert, is_alert_fc, is_alert_spo2, is_alert_temp, alert_reasons
        )
        SELECT
            m.stay_id,
            s.service_code,
            m.ts,
            m.heart_rate,
            m.spo2,
            m.temp_c,
            if((m.heart_rate < 50 OR m.heart_rate > 120) OR (m.spo2 < 92) OR (m.temp_c < 36.0 OR m.temp_c >= 38.5), 1, 0) AS is_alert,
            if(m.heart_rate < 50 OR m.heart_rate > 120, 1, 0) AS is_alert_fc,
            if(m.spo2 < 92, 1, 0) AS is_alert_spo2,
            if(m.temp_c < 36.0 OR m.temp_c >= 38.5, 1, 0) AS is_alert_temp,
            concat_ws(',',
                if(m.heart_rate < 50 OR m.heart_rate > 120, 'FC_ANORMALE', ''),
                if(m.spo2 < 92, 'HYPOXIE', ''),
                if(m.temp_c < 36.0 OR m.temp_c >= 38.5, 'TEMP_ANORMALE', '')
            ) AS alert_reasons
        FROM bronze.monitoring AS m
        JOIN bronze.sejours AS s ON m.stay_id = s.stay_id
        WHERE (m.heart_rate IS NULL OR (m.heart_rate >= 20 AND m.heart_rate <= 250))
          AND (m.spo2 IS NULL OR (m.spo2 >= 50 AND m.spo2 <= 100))
          AND (m.temp_c IS NULL OR (m.temp_c >= 30.0 AND m.temp_c <= 45.0))
    """)
    bronze_mon = client.query("SELECT count() FROM bronze.monitoring").result_rows[0][0]
    silver_mon = client.query("SELECT count() FROM silver.fact_monitoring").result_rows[0][0]
    outliers_mon = bronze_mon - silver_mon
    alerts_mon = client.query("SELECT count() FROM silver.fact_monitoring WHERE is_alert = 1").result_rows[0][0]
    print(f"  [OK] silver.fact_monitoring : {silver_mon} mesures physiologiques valides")
    print(f"       - {outliers_mon} mesures aberrantes écartées")
    print(f"       - {alerts_mon} alertes vitales détectées")

    # 6. Table de Faits Actes Médicaux (Évolution Lot 2026-08-29)
    print("\n[INFO] Transformation silver.fact_acte...")
    client.command("TRUNCATE TABLE silver.fact_acte")
    client.command("""
        INSERT INTO silver.fact_acte (
            stay_id, service_code, code_ccam, acte_ts
        )
        SELECT
            a.stay_id,
            if(s.service_code != '', s.service_code, if(b.service_code != '', b.service_code, 'INCONNU')) AS service_code,
            a.code_ccam,
            a.acte_ts
        FROM bronze.actes AS a
        LEFT JOIN silver.fact_sejours AS s ON a.stay_id = s.stay_id
        LEFT JOIN bronze.sejours AS b ON a.stay_id = b.stay_id
    """)
    silver_actes = client.query("SELECT count() FROM silver.fact_acte").result_rows[0][0]
    print(f"  [OK] silver.fact_acte : {silver_actes} actes médicaux intégrés")

    print("\n" + "=" * 70)
    print("[END] RECAPITULATIF DE LA COUCHE SILVER :")
    tables_to_check = [
        "silver.dim_patients", "silver.dim_services", "silver.dim_ccam", "silver.dim_cim10",
        "silver.fact_sejours", "silver.fact_diagnostics", "silver.fact_monitoring", "silver.fact_acte"
    ]
    for tbl in tables_to_check:
        count = client.query(f"SELECT count() FROM {tbl}").result_rows[0][0]
        print(f"  - {tbl:<25} : {count:>8} lignes")
    print("=" * 70)


if __name__ == "__main__":
    run_silver_transformations()
