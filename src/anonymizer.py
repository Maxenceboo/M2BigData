"""
Module de Pseudonymisation et d'Anonymisation RGPD (Art. 9).
Fournit des fonctions cryptographiques et de généralisation pour protéger
l'identité des patients avant tout transfert vers l'entrepôt.
"""

import hmac
import hashlib
from typing import Optional
from src.config import ANONYMIZATION_SALT, PSEUDO_PREFIX


def pseudonymize_id(raw_id: str, salt: str = ANONYMIZATION_SALT, prefix: str = PSEUDO_PREFIX) -> str:
    """
    Génère un pseudonyme déterministe, stable et irréversible à partir d'un identifiant patient.
    
    Utilise l'algorithme HMAC-SHA256 avec une clé secrète (sel).
    Le résultat est tronqué à 16 caractères hexadécimaux pour rester compact tout en évitant les collisions.
    """
    if not raw_id or not isinstance(raw_id, str):
        return ""
    clean_id = raw_id.strip()
    h = hmac.new(salt.encode('utf-8'), clean_id.encode('utf-8'), hashlib.sha256)
    return f"{prefix}{h.hexdigest()[:16]}"


def generalize_birth_date(birth_date_str: str) -> Optional[int]:
    """
    Généralise une date de naissance complète (ex: '1985-04-12') en son année de naissance ('1985').
    Supprime le jour et le mois pour réduire le risque de réidentification.
    """
    if not birth_date_str or not isinstance(birth_date_str, str):
        return None
    parts = birth_date_str.strip().split("-")
    if len(parts) >= 1 and parts[0].isdigit() and len(parts[0]) == 4:
        return int(parts[0])
    return None
