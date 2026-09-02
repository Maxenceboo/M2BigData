"""
Orchestrateur Principal du Pipeline EDS (Entrepôt de Données de Santé)

Exécute la chaîne complète de bout en bout :
1. Sync & Anonymisation : source-filestorage -> lake
2. Ingestion Bronze : lake -> ClickHouse bronze.*
3. Nettoyage & Transformation Silver : bronze -> ClickHouse silver.* (100% SQL)
4. Datamarts Métier & RGPD Gold : silver -> ClickHouse gold.*
5. [Optionnel] Déploiement/Mise à jour Metabase : --setup-metabase

Caractéristiques :
- Idempotence garantie (mécanisme de verrou par fichier + déduplication d'ingestion)
- Journalisation double (Console + Fichier logs/pipeline_YYYYMMDD_HHMMSS.log)
- Table d'audit ClickHouse admin.pipeline_runs (traçabilité temporelle et statut)
- Gestion et reprise sur erreur (codes retours standard 0=Succès, 1=Erreur)
"""

import argparse
import json
import logging
import os
import sys
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

# Encodage UTF-8 sous Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.config import CLICKHOUSE_HOST, CLICKHOUSE_PORT
import clickhouse_connect


# =============================================================================
# GESTION DES LOGS & DU VERROU D'EXECUTION (LOCK)
# =============================================================================
LOGS_DIR = BASE_DIR / "logs"
LOCK_FILE = LOGS_DIR / "pipeline.lock"


def setup_logger(is_cron: bool = False):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = LOGS_DIR / f"pipeline_{timestamp}.log"
    latest_log = LOGS_DIR / "latest.log"

    logger = logging.getLogger("eds_pipeline")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Sortie console
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # Sortie fichier horodaté
    fh = logging.FileHandler(log_filename, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Sortie latest.log
    fh_latest = logging.FileHandler(latest_log, mode="w", encoding="utf-8")
    fh_latest.setLevel(logging.INFO)
    fh_latest.setFormatter(formatter)
    logger.addHandler(fh_latest)

    if is_cron:
        cron_log = LOGS_DIR / "cron.log"
        fh_cron = logging.FileHandler(cron_log, mode="a", encoding="utf-8")
        fh_cron.setLevel(logging.INFO)
        fh_cron.setFormatter(formatter)
        logger.addHandler(fh_cron)

    return logger, log_filename


class PipelineLock:
    """Garantit qu'une seule instance du pipeline s'exécute à la fois."""
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path

    def __enter__(self):
        if self.lock_path.exists():
            try:
                with open(self.lock_path, "r", encoding="utf-8") as f:
                    lock_info = json.load(f)
                pid = lock_info.get("pid")
                started_at = lock_info.get("started_at")
                # Vérifier si le processus existe toujours
                if pid and self._is_pid_running(pid):
                    raise RuntimeError(
                        f"Une exécution du pipeline est déjà en cours (PID: {pid}, démarré le {started_at}). "
                        f"Supprimez {self.lock_path} si vous êtes certain qu'il s'agit d'un verrou orphelin."
                    )
            except (json.JSONDecodeError, OSError):
                pass

        # Créer le verrou
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "w", encoding="utf-8") as f:
            json.dump({
                "pid": os.getpid(),
                "started_at": datetime.now().isoformat()
            }, f)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lock_path.exists():
            try:
                self.lock_path.unlink()
            except Exception:
                pass

    @staticmethod
    def _is_pid_running(pid: int) -> bool:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            process = kernel32.OpenProcess(0x1000, False, pid)
            if process:
                kernel32.CloseHandle(process)
                return True
            return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False


# =============================================================================
# GESTION DE LA TABLE D'AUDIT CLICKHOUSE (admin.pipeline_runs)
# =============================================================================
def get_ch_client():
    return clickhouse_connect.get_client(host=CLICKHOUSE_HOST, port=CLICKHOUSE_PORT)


def init_audit_table(client):
    client.command("CREATE DATABASE IF NOT EXISTS admin")
    client.command("""
        CREATE TABLE IF NOT EXISTS admin.pipeline_runs (
            run_id UUID,
            started_at DateTime,
            finished_at Nullable(DateTime),
            status LowCardinality(String),
            step_name String,
            files_processed Array(String),
            records_ingested UInt64,
            records_rejected UInt64,
            error_message Nullable(String)
        ) ENGINE = MergeTree()
        ORDER BY (started_at, run_id)
    """)


def record_run_start(client, run_id: str, trigger_type: str):
    started_at = datetime.now()
    client.command(f"""
        INSERT INTO admin.pipeline_runs 
        (run_id, started_at, finished_at, status, step_name, files_processed, records_ingested, records_rejected, error_message)
        VALUES ('{run_id}', now(), NULL, 'RUNNING', 'START ({trigger_type})', [], 0, 0, NULL)
    """)
    return started_at


def record_step_progress(client, run_id: str, started_at: datetime, step_name: str, files: list = None, ingested: int = 0, rejected: int = 0):
    files = files or []
    escaped_files = [f"'{f}'" for f in files]
    files_str = f"[{', '.join(escaped_files)}]"
    client.command(f"""
        INSERT INTO admin.pipeline_runs 
        (run_id, started_at, finished_at, status, step_name, files_processed, records_ingested, records_rejected, error_message)
        VALUES ('{run_id}', '{started_at.strftime('%Y-%m-%d %H:%M:%S')}', NULL, 'RUNNING', '{step_name}', {files_str}, {ingested}, {rejected}, NULL)
    """)


def record_run_success(client, run_id: str, started_at: datetime, total_ingested: int):
    client.command(f"""
        INSERT INTO admin.pipeline_runs 
        (run_id, started_at, finished_at, status, step_name, files_processed, records_ingested, records_rejected, error_message)
        VALUES ('{run_id}', '{started_at.strftime('%Y-%m-%d %H:%M:%S')}', now(), 'SUCCESS', 'ALL_STEPS_COMPLETED', [], {total_ingested}, 0, NULL)
    """)


def record_run_failure(client, run_id: str, started_at: datetime, step_name: str, error_msg: str):
    clean_err = error_msg.replace("'", "''").replace("\\", "/")[:1000]
    client.command(f"""
        INSERT INTO admin.pipeline_runs 
        (run_id, started_at, finished_at, status, step_name, files_processed, records_ingested, records_rejected, error_message)
        VALUES ('{run_id}', '{started_at.strftime('%Y-%m-%d %H:%M:%S')}', now(), 'FAILED', '{step_name}', [], 0, 0, '{clean_err}')
    """)


# =============================================================================
# POINT D'ENTREE DU PIPELINE
# =============================================================================
def run_pipeline(
    is_cron: bool = False,
    force_sync: bool = False,
    setup_metabase: bool = False,
    skip_sync: bool = False,
    skip_bronze: bool = False,
    skip_silver: bool = False,
    skip_gold: bool = False
) -> int:
    logger, log_file = setup_logger(is_cron=is_cron)
    trigger_type = "CRON" if is_cron else "MANUAL"
    run_id = str(uuid.uuid4())

    logger.info("=" * 75)
    logger.info(f"🚀 DEMARRAGE DU PIPELINE EDS [Mode: {trigger_type}] (Run ID: {run_id})")
    logger.info(f"📁 Journalisation fichier : {log_file}")
    logger.info("=" * 75)

    start_time = time.time()
    current_step = "INIT"
    ch_client = None

    try:
        with PipelineLock(LOCK_FILE):
            # 1. Connexion ClickHouse & Audit
            ch_client = get_ch_client()
            init_audit_table(ch_client)
            started_at = record_run_start(ch_client, run_id, trigger_type)
            logger.info("  [OK] Connexion ClickHouse établie et table admin.pipeline_runs initialisée.")

            # =================================================================
            # ETAPE 1 : SYNCHRONISATION SOURCE -> LAKE
            # =================================================================
            if not skip_sync:
                current_step = "1_SYNC_LAKE"
                logger.info("\n--- [ETAPE 1/4] SYNCHRONISATION & ANONYMISATION SOURCE -> LAKE ---")
                from src.sync_lake import run_sync
                run_sync(force=force_sync)
                record_step_progress(ch_client, run_id, started_at, current_step)
                logger.info("  [OK] Etape 1 (Sync Lake) validée.")
            else:
                logger.info("  [SKIP] Etape 1 (Sync Lake) ignorée.")

            # =================================================================
            # ETAPE 2 : INGESTION LAKE -> BRONZE
            # =================================================================
            if not skip_bronze:
                current_step = "2_INGEST_BRONZE"
                logger.info("\n--- [ETAPE 2/4] INGESTION BRONZE DANS CLICKHOUSE ---")
                from src.ingest_bronze import run_bronze_ingestion
                run_bronze_ingestion()
                record_step_progress(ch_client, run_id, started_at, current_step)
                logger.info("  [OK] Etape 2 (Ingestion Bronze) validée.")
            else:
                logger.info("  [SKIP] Etape 2 (Ingestion Bronze) ignorée.")

            # =================================================================
            # ETAPE 3 : TRANSFORMATION SILVER (NETTOYAGE & QUALITE SQL)
            # =================================================================
            if not skip_silver:
                current_step = "3_TRANSFORM_SILVER"
                logger.info("\n--- [ETAPE 3/4] TRANSFORMATIONS SILVER (QUALITE & SANTE 100% SQL) ---")
                from src.transform_silver import run_silver_transformations
                run_silver_transformations()
                record_step_progress(ch_client, run_id, started_at, current_step)
                logger.info("  [OK] Etape 3 (Silver Transformations) validée.")
            else:
                logger.info("  [SKIP] Etape 3 (Silver Transformations) ignorée.")

            # =================================================================
            # ETAPE 4 : DATAMARTS GOLD (KPI & CONFORMITE RGPD)
            # =================================================================
            if not skip_gold:
                current_step = "4_TRANSFORM_GOLD"
                logger.info("\n--- [ETAPE 4/4] CREATION DES VUES ANALYTIQUES GOLD (PILOTAGE & RECHERCHE) ---")
                from src.transform_gold import run_gold_transformations
                run_gold_transformations()
                record_step_progress(ch_client, run_id, started_at, current_step)
                logger.info("  [OK] Etape 4 (Gold Datamarts) validée.")
            else:
                logger.info("  [SKIP] Etape 4 (Gold Datamarts) ignorée.")

            # =================================================================
            # OPTIONNEL : SYNCHRONISATION METABASE
            # =================================================================
            if setup_metabase:
                current_step = "5_SETUP_METABASE"
                logger.info("\n--- [OPTIONNEL] SYNCHRONISATION ET MISE A JOUR DE METABASE ---")
                from src.setup_metabase import main as metabase_setup
                metabase_setup()
                record_step_progress(ch_client, run_id, started_at, current_step)
                logger.info("  [OK] Metabase synchronisé avec succès.")

            # =================================================================
            # FINALISATION & BILAN
            # =================================================================
            duration = round(time.time() - start_time, 2)
            total_sejours = ch_client.query("SELECT count() FROM silver.fact_sejours").result_rows[0][0]
            record_run_success(ch_client, run_id, started_at, total_sejours)

            logger.info("\n" + "=" * 75)
            logger.info(f"🎉 PIPELINE EDS TERMINE AVEC SUCCES EN {duration} SECONDES !")
            logger.info("=" * 75)
            logger.info("📊 RECAPITULATIF DES VOLUMES ACTUELS EN BASE :")
            for tbl in [
                "bronze.patients", "bronze.sejours", "bronze.diagnostics", "bronze.monitoring",
                "silver.dim_patients", "silver.fact_sejours", "silver.fact_diagnostics", "silver.fact_monitoring",
                "gold.vue_pilotage_dms", "gold.vue_pilotage_urgences", "gold.vue_recherche_prevalence"
            ]:
                try:
                    c = ch_client.query(f"SELECT count() FROM {tbl}").result_rows[0][0]
                    logger.info(f"  • {tbl:<32} : {c:>8} lignes")
                except Exception:
                    pass
            logger.info("=" * 75)
            return 0

    except Exception as e:
        duration = round(time.time() - start_time, 2)
        err_msg = str(e)
        logger.error("\n" + "!" * 75)
        logger.error(f"❌ ECHEC CRITIQUE DU PIPELINE A L'ETAPE [{current_step}] APRES {duration}s")
        logger.error(f"Erreur : {err_msg}")
        logger.error(traceback.format_exc())
        logger.error("!" * 75)

        if ch_client:
            try:
                record_run_failure(ch_client, run_id, started_at, current_step, err_msg)
            except Exception:
                pass
        return 1


def parse_args():
    parser = argparse.ArgumentParser(
        description="Orchestrateur Principal du Pipeline EDS (Entrepôt de Données de Santé)"
    )
    parser.add_argument("--cron", action="store_true", help="Indique une exécution automatique via planificateur Cron")
    parser.add_argument("--force", action="store_true", help="Force le re-traitement de tous les lots dans le Lake")
    parser.add_argument("--setup-metabase", action="store_true", help="Met à jour et redéploie les dashboards Metabase après l'ETL")
    parser.add_argument("--skip-sync", action="store_true", help="Ignore l'étape 1 (Sync Source -> Lake)")
    parser.add_argument("--skip-bronze", action="store_true", help="Ignore l'étape 2 (Ingestion Bronze)")
    parser.add_argument("--skip-silver", action="store_true", help="Ignore l'étape 3 (Transformations Silver)")
    parser.add_argument("--skip-gold", action="store_true", help="Ignore l'étape 4 (Datamarts Gold)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    code = run_pipeline(
        is_cron=args.cron,
        force_sync=args.force,
        setup_metabase=args.setup_metabase,
        skip_sync=args.skip_sync,
        skip_bronze=args.skip_bronze,
        skip_silver=args.skip_silver,
        skip_gold=args.skip_gold
    )
    sys.exit(code)
