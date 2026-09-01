"""
Configuration globale du projet Entrepôt de Données de Santé (EDS).
Gère les chemins des dossiers, le sel secret de pseudonymisation et les paramètres généraux.
"""

from pathlib import Path
import os

# Chemins de base
BASE_DIR = Path(__file__).resolve().parent.parent
SOURCE_DIR = BASE_DIR / "source-filestorage"
LAKE_DIR = BASE_DIR / "lake"

# Clé secrète / Sel pour la pseudonymisation déterministe (RGPD)
# En production, cette valeur provient d'une variable d'environnement ou d'un gestionnaire de secrets (KMS)
ANONYMIZATION_SALT = os.getenv("EDS_SALT", "CHU_SECRET_SALT_2026_RGPD_KEY_SECURE")

# Format du préfixe des identifiants pseudonymisés
PSEUDO_PREFIX = "PSEUDO_"
