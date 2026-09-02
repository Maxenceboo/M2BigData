"""
Script de Synchronisation et d'Anonymisation : Source FileStorage -> Lake (Staging).

Fonctionnalités :
1. Découverte automatique et incrémentale des dossiers de dépôts quotidiens.
2. Anonymisation stricte des flux Patients et Séjours (HMAC-SHA256, suppression NIR/Nom/Prénom, année de naissance).
3. Recopie sécurisée vers la zone Lake.
4. Journalisation et traçabilité via un fichier de manifeste (.sync_manifest.json).
"""

import os
import sys
import csv
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Set

# Forcer l'encodage UTF-8 pour la sortie console sous Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ajouter le répertoire racine au PYTHONPATH
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.config import SOURCE_DIR, LAKE_DIR, ANONYMIZATION_SALT
from src.anonymizer import pseudonymize_id, generalize_birth_date


def get_sync_manifest_path() -> Path:
    return LAKE_DIR / ".sync_manifest.json"


def load_sync_manifest() -> Dict:
    manifest_path = get_sync_manifest_path()
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"processed_dates": {}, "last_sync": None}
    return {"processed_dates": {}, "last_sync": None}


def save_sync_manifest(manifest: Dict) -> None:
    manifest_path = get_sync_manifest_path()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest["last_sync"] = datetime.now().isoformat()
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def discover_source_dates() -> List[str]:
    """Détecte l'ensemble des dates de dépôts disponibles dans source-filestorage."""
    dates: Set[str] = set()
    if not SOURCE_DIR.exists():
        print(f"[ERREUR] Le dossier source {SOURCE_DIR} n'existe pas.")
        return []

    for entity in ["patients", "sejours", "diagnostics", "monitoring", "referentiels", "actes"]:
        entity_dir = SOURCE_DIR / entity
        if entity_dir.exists() and entity_dir.is_dir():
            for child in entity_dir.iterdir():
                if child.is_dir() and len(child.name) == 10 and child.name.count("-") == 2:
                    dates.add(child.name)

    return sorted(list(dates))


def process_patients(source_file: Path, target_file: Path) -> int:
    """
    Lit patients.csv brut, supprime NIR/Nom/Prénom, hache patient_id et généralise birth_date.
    Écrit le fichier anonymisé dans target_file.
    """
    target_file.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    with open(source_file, "r", encoding="utf-8", newline="") as infile, \
         open(target_file, "w", encoding="utf-8", newline="") as outfile:
        
        reader = csv.DictReader(infile)
        fieldnames = ["patient_pseudo_id", "birth_year", "sex", "region_code"]
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            raw_id = row.get("patient_id", "")
            pseudo_id = pseudonymize_id(raw_id)
            birth_year = generalize_birth_date(row.get("birth_date", ""))
            sex = row.get("sex", "").strip().upper()
            region = row.get("region_code", "").strip()

            writer.writerow({
                "patient_pseudo_id": pseudo_id,
                "birth_year": birth_year if birth_year is not None else "",
                "sex": sex,
                "region_code": region
            })
            count += 1

    return count


def process_sejours(source_file: Path, target_file: Path) -> int:
    """
    Lit sejours.csv brut, remplace patient_id par patient_pseudo_id (même sel).
    Écrit le fichier dans target_file.
    """
    target_file.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    with open(source_file, "r", encoding="utf-8", newline="") as infile, \
         open(target_file, "w", encoding="utf-8", newline="") as outfile:
        
        reader = csv.DictReader(infile)
        fieldnames = [
            "stay_id", "patient_pseudo_id", "service_code", 
            "admission_ts", "discharge_ts", "admission_mode", "discharge_mode"
        ]
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            raw_patient_id = row.get("patient_id", "")
            pseudo_id = pseudonymize_id(raw_patient_id)

            writer.writerow({
                "stay_id": row.get("stay_id", "").strip(),
                "patient_pseudo_id": pseudo_id,
                "service_code": row.get("service_code", "").strip(),
                "admission_ts": row.get("admission_ts", "").strip(),
                "discharge_ts": row.get("discharge_ts", "").strip(),
                "admission_mode": row.get("admission_mode", "").strip(),
                "discharge_mode": row.get("discharge_mode", "").strip()
            })
            count += 1

    return count


def copy_file_safe(source_file: Path, target_file: Path) -> bool:
    """Copie un fichier brut vers le Lake en créant les dossiers nécessaires."""
    if not source_file.exists():
        return False
    target_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, target_file)
    return True


def sync_date_deposit(date_str: str) -> Dict:
    """
    Synchronise l'ensemble des flux pour une date donnée.
    """
    print(f"\n[INFO] Traitement du lot journalier : [{date_str}]")
    result = {
        "date": date_str,
        "synced_at": datetime.now().isoformat(),
        "patients_count": 0,
        "sejours_count": 0,
        "diagnostics_synced": False,
        "monitoring_synced": False,
        "referentiels_synced": False,
        "success": False
    }

    try:
        # 1. Patients
        src_pat = SOURCE_DIR / "patients" / date_str / "patients.csv"
        tgt_pat = LAKE_DIR / "patients" / date_str / "patients.csv"
        if src_pat.exists():
            n = process_patients(src_pat, tgt_pat)
            result["patients_count"] = n
            print(f"  [OK] Patients anonymises et copies : {n} enregistrements")

        # 2. Sejours
        src_sej = SOURCE_DIR / "sejours" / date_str / "sejours.csv"
        tgt_sej = LAKE_DIR / "sejours" / date_str / "sejours.csv"
        if src_sej.exists():
            n = process_sejours(src_sej, tgt_sej)
            result["sejours_count"] = n
            print(f"  [OK] Sejours anonymises et copies : {n} enregistrements")

        # 3. Diagnostics
        src_dia = SOURCE_DIR / "diagnostics" / date_str / "diagnostics.json"
        tgt_dia = LAKE_DIR / "diagnostics" / date_str / "diagnostics.json"
        if src_dia.exists():
            copy_file_safe(src_dia, tgt_dia)
            result["diagnostics_synced"] = True
            print("  [OK] Diagnostics JSON copies")

        # 4. Monitoring (Parquet)
        src_mon = SOURCE_DIR / "monitoring" / date_str / "monitoring.parquet"
        tgt_mon = LAKE_DIR / "monitoring" / date_str / "monitoring.parquet"
        if src_mon.exists():
            copy_file_safe(src_mon, tgt_mon)
            result["monitoring_synced"] = True
            print("  [OK] Monitoring Parquet copie")

        # 5. Referentiels (services.csv, cim10.csv, description_service.csv, ccam.csv)
        src_ref = SOURCE_DIR / "referentiels" / date_str
        tgt_ref = LAKE_DIR / "referentiels" / date_str
        if src_ref.exists():
            for ref_file in src_ref.glob("*.csv"):
                copy_file_safe(ref_file, tgt_ref / ref_file.name)
            result["referentiels_synced"] = True
            print("  [OK] Referentiels CSV copies")

        # 6. Actes Médicaux (Parquet) - Évolution Lot 2026-08-29
        src_act = SOURCE_DIR / "actes" / date_str / "actes.parquet"
        tgt_act = LAKE_DIR / "actes" / date_str / "actes.parquet"
        if src_act.exists():
            copy_file_safe(src_act, tgt_act)
            result["actes_synced"] = True
            print("  [OK] Actes Parquet copies")

        result["success"] = True
    except Exception as e:
        print(f"  [ERREUR] Erreur lors de la synchronisation de {date_str} : {e}")
        result["error"] = str(e)
        result["success"] = False

    return result


def run_sync(force: bool = False) -> None:
    """Point d'entrée principal pour synchroniser tous les dépôts non encore traités."""
    print("=" * 70)
    print("[START] DEMARRAGE DE LA SYNCHRONISATION & ANONYMISATION SOURCE -> LAKE")
    print("=" * 70)

    manifest = load_sync_manifest()
    processed_dates = manifest.get("processed_dates", {})

    available_dates = discover_source_dates()
    print(f"[INFO] Dates detectees dans source-filestorage : {available_dates}")

    dates_to_process = [
        d for d in available_dates 
        if force or d not in processed_dates or not processed_dates[d].get("success", False)
    ]

    if not dates_to_process:
        print("[INFO] Aucun nouveau lot a synchroniser. Le Lake est a jour.")
        return

    print(f"[INFO] Lots a synchroniser ({len(dates_to_process)}) : {dates_to_process}")

    for date_str in dates_to_process:
        res = sync_date_deposit(date_str)
        processed_dates[date_str] = res
        save_sync_manifest(manifest)

    print("\n" + "=" * 70)
    print("[END] SYNCHRONISATION DU LAKE TERMINEE AVEC SUCCES")
    print("=" * 70)


if __name__ == "__main__":
    force_run = "--force" in sys.argv
    run_sync(force=force_run)
