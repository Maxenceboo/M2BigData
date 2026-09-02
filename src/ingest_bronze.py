"""
Script d'Ingestion Lake -> ClickHouse (Couche Bronze).

Fonctionnalités :
1. Initialisation des tables Bronze dans ClickHouse.
2. Ingestion performante et par lots des fichiers CSV, JSON et Parquet depuis le Lake.
3. Aplatissement (flattening) des structures JSON imbriquées pour les diagnostics.
4. Traçabilité complète (source_date, source_file, ingested_at).
5. Déduplication d'ingestion (ne ré-insère pas les fichiers déjà ingérés).
"""

import sys
import csv
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import pyarrow.parquet as pq

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

from src.config import LAKE_DIR
import clickhouse_connect


def get_clickhouse_client(host="localhost", port=8123, username="default", password=""):
    """Crée une connexion HTTP avec le serveur ClickHouse."""
    return clickhouse_connect.get_client(
        host=host, 
        port=port, 
        username=username, 
        password=password
    )


def execute_sql_file(client, sql_file_path: Path):
    """Exécute les instructions d'un fichier SQL."""
    with open(sql_file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Découper par instruction
    statements = [s.strip() for s in content.split(";") if s.strip()]
    for stmt in statements:
        client.command(stmt)


def init_bronze_tables(client):
    """Initialise les bases de données et les tables Bronze."""
    print("[INFO] Initialisation des DDL Bronze dans ClickHouse...")
    sql_init = BASE_DIR / "sql" / "00_init_databases.sql"
    sql_bronze = BASE_DIR / "sql" / "01_bronze.sql"
    
    if sql_init.exists():
        execute_sql_file(client, sql_init)
    if sql_bronze.exists():
        execute_sql_file(client, sql_bronze)
    print("  [OK] Tables Bronze initialisees.")


def get_ingested_files(client, table_name: str) -> set:
    """Récupère la liste des fichiers déjà ingérés dans une table Bronze."""
    try:
        res = client.query(f"SELECT DISTINCT source_file FROM {table_name}")
        return set(r[0] for r in res.result_rows)
    except Exception:
        return set()


def ingest_patients(client, date_str: str) -> int:
    file_path = LAKE_DIR / "patients" / date_str / "patients.csv"
    if not file_path.exists():
        return 0

    rel_name = f"patients/{date_str}/patients.csv"
    already_ingested = get_ingested_files(client, "bronze.patients")
    if rel_name in already_ingested:
        print(f"  [SKIP] Patients {date_str} deja ingere.")
        return 0

    rows = []
    source_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            birth_year = int(r["birth_year"]) if r.get("birth_year") else 0
            rows.append((
                r["patient_pseudo_id"],
                birth_year,
                r.get("sex", ""),
                r.get("region_code", ""),
                source_date,
                rel_name
            ))

    if rows:
        client.insert(
            "bronze.patients",
            rows,
            column_names=["patient_pseudo_id", "birth_year", "sex", "region_code", "source_date", "source_file"]
        )
        print(f"  [OK] Ingestion bronze.patients [{date_str}] : {len(rows)} lignes")
    return len(rows)


def ingest_sejours(client, date_str: str) -> int:
    file_path = LAKE_DIR / "sejours" / date_str / "sejours.csv"
    if not file_path.exists():
        return 0

    rel_name = f"sejours/{date_str}/sejours.csv"
    already_ingested = get_ingested_files(client, "bronze.sejours")
    if rel_name in already_ingested:
        print(f"  [SKIP] Sejours {date_str} deja ingere.")
        return 0

    rows = []
    source_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            adm_ts = datetime.strptime(r["admission_ts"], "%Y-%m-%d %H:%M:%S") if r.get("admission_ts") else None
            dis_ts_str = r.get("discharge_ts", "").strip()
            dis_ts = datetime.strptime(dis_ts_str, "%Y-%m-%d %H:%M:%S") if dis_ts_str else None

            rows.append((
                r["stay_id"],
                r["patient_pseudo_id"],
                r.get("service_code", ""),
                adm_ts,
                dis_ts,
                r.get("admission_mode", ""),
                r.get("discharge_mode", ""),
                source_date,
                rel_name
            ))

    if rows:
        client.insert(
            "bronze.sejours",
            rows,
            column_names=[
                "stay_id", "patient_pseudo_id", "service_code", 
                "admission_ts", "discharge_ts", "admission_mode", "discharge_mode",
                "source_date", "source_file"
            ]
        )
        print(f"  [OK] Ingestion bronze.sejours [{date_str}] : {len(rows)} lignes")
    return len(rows)


def ingest_diagnostics(client, date_str: str) -> int:
    file_path = LAKE_DIR / "diagnostics" / date_str / "diagnostics.json"
    if not file_path.exists():
        return 0

    rel_name = f"diagnostics/{date_str}/diagnostics.json"
    already_ingested = get_ingested_files(client, "bronze.diagnostics")
    if rel_name in already_ingested:
        print(f"  [SKIP] Diagnostics {date_str} deja ingere.")
        return 0

    source_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    rows = []
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        for item in data:
            stay_id = item.get("stay_id", "")
            for diag in item.get("diagnostics", []):
                rows.append((
                    stay_id,
                    diag.get("code_cim10", ""),
                    diag.get("type", "principal"),
                    source_date,
                    rel_name
                ))

    if rows:
        client.insert(
            "bronze.diagnostics",
            rows,
            column_names=["stay_id", "code_cim10", "diag_type", "source_date", "source_file"]
        )
        print(f"  [OK] Ingestion bronze.diagnostics [{date_str}] : {len(rows)} lignes (aplaties)")
    return len(rows)


def ingest_monitoring(client, date_str: str) -> int:
    file_path = LAKE_DIR / "monitoring" / date_str / "monitoring.parquet"
    if not file_path.exists():
        return 0

    rel_name = f"monitoring/{date_str}/monitoring.parquet"
    already_ingested = get_ingested_files(client, "bronze.monitoring")
    if rel_name in already_ingested:
        print(f"  [SKIP] Monitoring {date_str} deja ingere.")
        return 0

    source_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    
    # Lecture optimisée via PyArrow
    table = pq.read_table(file_path)
    df = table.to_pandas()
    
    # Ajout des colonnes de métadonnées
    df["source_date"] = source_date
    df["source_file"] = rel_name
    
    # Insertion directe DataFrame dans ClickHouse
    client.insert_df(
        "bronze.monitoring",
        df[["stay_id", "ts", "heart_rate", "spo2", "temp_c", "source_date", "source_file"]]
    )
    print(f"  [OK] Ingestion bronze.monitoring [{date_str}] : {len(df)} mesures")
    return len(df)


def ingest_actes(client, date_str: str) -> int:
    file_path = LAKE_DIR / "actes" / date_str / "actes.parquet"
    if not file_path.exists():
        return 0

    rel_name = f"actes/{date_str}/actes.parquet"
    already_ingested = get_ingested_files(client, "bronze.actes")
    if rel_name in already_ingested:
        print(f"  [SKIP] Actes {date_str} deja ingere.")
        return 0

    source_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    table = pq.read_table(file_path)
    df = table.to_pandas()
    df["source_date"] = source_date
    df["source_file"] = rel_name

    client.insert_df(
        "bronze.actes",
        df[["stay_id", "code_ccam", "acte_ts", "source_date", "source_file"]]
    )
    print(f"  [OK] Ingestion bronze.actes [{date_str}] : {len(df)} actes")
    return len(df)


def ingest_referentiels(client, date_str: str):
    ref_dir = LAKE_DIR / "referentiels" / date_str
    if not ref_dir.exists():
        return

    # Services
    srv_file = ref_dir / "services.csv"
    if srv_file.exists():
        rows = []
        with open(srv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append((r["service_code"], r["service_label"], f"referentiels/{date_str}/services.csv"))
        if rows:
            client.command("TRUNCATE TABLE bronze.ref_services")
            client.insert("bronze.ref_services", rows, column_names=["service_code", "service_label", "source_file"])
            print(f"  [OK] Ingestion bronze.ref_services : {len(rows)} enregistrements")

    # CIM10
    cim_file = ref_dir / "cim10.csv"
    if cim_file.exists():
        rows = []
        with open(cim_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append((r["code_cim10"], r["libelle"], f"referentiels/{date_str}/cim10.csv"))
        if rows:
            client.command("TRUNCATE TABLE bronze.ref_cim10")
            client.insert("bronze.ref_cim10", rows, column_names=["code_cim10", "libelle", "source_file"])
            print(f"  [OK] Ingestion bronze.ref_cim10 : {len(rows)} enregistrements")

    # Description Services (Évolution)
    desc_file = ref_dir / "description_service.csv"
    if desc_file.exists():
        rows = []
        with open(desc_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append((
                    r["service_code"].strip(),
                    r.get("categorie", "").strip(),
                    int(r.get("capacite_lits", 0) or 0),
                    r.get("pole", "").strip(),
                    f"referentiels/{date_str}/description_service.csv"
                ))
        if rows:
            client.command("TRUNCATE TABLE bronze.ref_description_service")
            client.insert("bronze.ref_description_service", rows, column_names=["service_code", "categorie", "capacite_lits", "pole", "source_file"])
            print(f"  [OK] Ingestion bronze.ref_description_service : {len(rows)} enregistrements")

    # CCAM (Évolution)
    ccam_file = ref_dir / "ccam.csv"
    if ccam_file.exists():
        rows = []
        with open(ccam_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append((
                    r["code_ccam"].strip(),
                    r.get("libelle", "").strip(),
                    int(r.get("tarif_euros", 0) or 0),
                    f"referentiels/{date_str}/ccam.csv"
                ))
        if rows:
            client.command("TRUNCATE TABLE bronze.ref_ccam")
            client.insert("bronze.ref_ccam", rows, column_names=["code_ccam", "libelle", "tarif_euros", "source_file"])
            print(f"  [OK] Ingestion bronze.ref_ccam : {len(rows)} enregistrements")


def run_bronze_ingestion():
    """Exécute l'ingestion de tous les dossiers journaliers du Lake."""
    print("=" * 70)
    print("[START] INGESTION DU LAKE VERS CLICKHOUSE (COUCHE BRONZE)")
    print("=" * 70)

    try:
        client = get_clickhouse_client()
    except Exception as e:
        print(f"[ERREUR] Impossible de se connecter a ClickHouse : {e}")
        print("  Verifiez que le conteneur Docker est bien demarre (docker compose up -d).")
        return

    init_bronze_tables(client)

    # Trouver toutes les dates dans le lake
    dates = set()
    for sub in ["patients", "sejours", "diagnostics", "monitoring", "referentiels", "actes"]:
        p = LAKE_DIR / sub
        if p.exists():
            for d in p.iterdir():
                if d.is_dir() and len(d.name) == 10:
                    dates.add(d.name)

    sorted_dates = sorted(list(dates))
    print(f"\n[INFO] Dates disponibles dans le Lake : {sorted_dates}")

    total_patients = 0
    total_sejours = 0
    total_diagnostics = 0
    total_monitoring = 0
    total_actes = 0

    for date_str in sorted_dates:
        print(f"\n📥 Ingestion du lot : [{date_str}]")
        total_patients += ingest_patients(client, date_str)
        total_sejours += ingest_sejours(client, date_str)
        total_diagnostics += ingest_diagnostics(client, date_str)
        total_monitoring += ingest_monitoring(client, date_str)
        total_actes += ingest_actes(client, date_str)
        ingest_referentiels(client, date_str)

    print("\n" + "=" * 70)
    print("[END] RECAPITULATIF DES LIGNES EN BASE BRONZE :")
    tables_to_check = [
        "bronze.patients", "bronze.sejours", "bronze.diagnostics", "bronze.monitoring",
        "bronze.ref_services", "bronze.ref_cim10", "bronze.ref_description_service",
        "bronze.ref_ccam", "bronze.actes"
    ]
    for tbl in tables_to_check:
        count = client.query(f"SELECT count() FROM {tbl}").result_rows[0][0]
        print(f"  - {tbl:<32} : {count:>8} lignes")
    print("=" * 70)


if __name__ == "__main__":
    run_bronze_ingestion()
