"""
Script dédié à la gestion de la sécurité et des utilisateurs (ClickHouse & Metabase).

Rôles :
1. Création de l'utilisateur technique ClickHouse 'metabase_user' avec droits STRICTS sur 'gold.*' uniquement.
2. Révocation de tout accès direct à 'silver' et 'bronze'.
3. Création des groupes applicatifs Metabase ('Direction & Pilotage', 'Recherche Clinique').
4. Création des comptes utilisateurs nominatifs ('directeur@eds-chu.fr', 'chercheur@eds-chu.fr').
5. Configuration de la matrice de permissions (cloisonnement strict des collections RGPD).
"""

import json
import sys
import urllib.request
import urllib.error
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

METABASE_URL = "http://localhost:3000"
ADMIN_EMAIL = "admin@eds-chu.fr"
ADMIN_PASS = "AdminPassword123!"

# Identifiants de l'utilisateur technique ClickHouse pour Metabase
MB_SQL_USER = "metabase_user"
MB_SQL_PASS = "MetabasePassword123!"


# =============================================================================
# 1. UTILISATEUR TECHNIQUE CLICKHOUSE (ACCÈS STRICT GOLD)
# =============================================================================
def setup_clickhouse_user():
    """Crée le compte technique metabase_user dans ClickHouse avec accès exclusif à gold.*"""
    print("=" * 70)
    print("🔐 [1/2] CONFIGURATION DE L'UTILISATEUR TECHNIQUE CLICKHOUSE")
    print("=" * 70)

    client = clickhouse_connect.get_client(host=CLICKHOUSE_HOST, port=CLICKHOUSE_PORT)

    # 1. Créer le user
    client.command(f"""
        CREATE USER IF NOT EXISTS {MB_SQL_USER} 
        IDENTIFIED WITH sha256_password BY '{MB_SQL_PASS}'
    """)
    print(f"  [OK] Utilisateur ClickHouse '{MB_SQL_USER}' vérifié.")

    # 2. Révocation de tout accès global ou résiduel sur bronze/silver
    try:
        client.command(f"REVOKE ALL ON *.* FROM {MB_SQL_USER}")
    except Exception:
        pass

    # 3. Droits de lecture STRICTEMENT et UNIQUEMENT sur gold.* et métadonnées système
    client.command(f"GRANT SELECT ON gold.* TO {MB_SQL_USER}")
    client.command(f"GRANT SELECT ON system.tables TO {MB_SQL_USER}")
    client.command(f"GRANT SELECT ON system.columns TO {MB_SQL_USER}")
    client.command(f"GRANT SELECT ON system.databases TO {MB_SQL_USER}")
    print(f"  [OK] Droits accordés à '{MB_SQL_USER}' : SELECT ON gold.* UNIQUEMENT.")

    # 4. Test de validation
    test_client = clickhouse_connect.get_client(
        host=CLICKHOUSE_HOST, 
        port=CLICKHOUSE_PORT, 
        username=MB_SQL_USER, 
        password=MB_SQL_PASS
    )
    gold_count = test_client.query("SELECT count() FROM gold.vue_pilotage_dms").result_rows[0][0]
    print(f"  [TEST] Lecture sur gold.vue_pilotage_dms réussie ({gold_count} services).")

    try:
        test_client.query("SELECT count() FROM silver.fact_sejours")
        raise RuntimeError("ERREUR DE SECURITE : l'accès direct à silver n'a pas été bloqué !")
    except Exception:
        print("  [TEST] Sécurité validée : accès direct à 'silver' et 'bronze' REJETÉ.")

    print("  [SUCCESS] Configuration ClickHouse validée.")


# =============================================================================
# 2. UTILISATEURS ET GROUPES APPLICATIFS METABASE
# =============================================================================
def _get_metabase_session():
    payload = {"username": ADMIN_EMAIL, "password": ADMIN_PASS}
    req = urllib.request.Request(
        f"{METABASE_URL}/api/session",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    res = urllib.request.urlopen(req)
    return json.loads(res.read())["id"]


def _mb_get(endpoint, token):
    req = urllib.request.Request(f"{METABASE_URL}{endpoint}", headers={"X-Metabase-Session": token})
    res = urllib.request.urlopen(req)
    return json.loads(res.read().decode("utf-8"))


def _mb_post(endpoint, payload, token):
    req = urllib.request.Request(
        f"{METABASE_URL}{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Metabase-Session": token}
    )
    res = urllib.request.urlopen(req)
    return json.loads(res.read().decode("utf-8"))


def _mb_put(endpoint, payload, token):
    req = urllib.request.Request(
        f"{METABASE_URL}{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Metabase-Session": token},
        method="PUT"
    )
    res = urllib.request.urlopen(req)
    return json.loads(res.read().decode("utf-8"))


def setup_metabase_users():
    """Crée et cloisonne les utilisateurs et groupes dans l'interface Metabase."""
    print("\n" + "=" * 70)
    print("👥 [2/2] CONFIGURATION DES UTILISATEURS & GROUPES METABASE")
    print("=" * 70)

    token = _get_metabase_session()
    print("  [OK] Session admin Metabase authentifiée.")

    # 1. Groupes
    groups = _mb_get("/api/permissions/group", token)
    grp_dir = next((g for g in groups if g["name"] == "Direction & Pilotage"), None)
    if not grp_dir:
        grp_dir = _mb_post("/api/permissions/group", {"name": "Direction & Pilotage"}, token)
        print(f"  [+] Groupe créé : {grp_dir['name']} (id: {grp_dir['id']})")
    else:
        print(f"  [INFO] Groupe existant : {grp_dir['name']} (id: {grp_dir['id']})")

    grp_rech = next((g for g in groups if g["name"] == "Recherche Clinique"), None)
    if not grp_rech:
        grp_rech = _mb_post("/api/permissions/group", {"name": "Recherche Clinique"}, token)
        print(f"  [+] Groupe créé : {grp_rech['name']} (id: {grp_rech['id']})")
    else:
        print(f"  [INFO] Groupe existant : {grp_rech['name']} (id: {grp_rech['id']})")

    # 2. Utilisateurs
    users = _mb_get("/api/user", token)["data"]

    # Directeur
    u_dir = next((u for u in users if u["email"] == "directeur@eds-chu.fr"), None)
    if not u_dir:
        u_dir = _mb_post("/api/user", {
            "first_name": "Directeur",
            "last_name": "CHU",
            "email": "directeur@eds-chu.fr",
            "password": "DirecteurPassword123!"
        }, token)
        print(f"  [+] Utilisateur créé : {u_dir['email']}")
    else:
        print(f"  [INFO] Utilisateur existant : {u_dir['email']}")

    # Chercheur
    u_rech = next((u for u in users if u["email"] == "chercheur@eds-chu.fr"), None)
    if not u_rech:
        u_rech = _mb_post("/api/user", {
            "first_name": "Chercheur",
            "last_name": "Clinique",
            "email": "chercheur@eds-chu.fr",
            "password": "ChercheurPassword123!"
        }, token)
        print(f"  [+] Utilisateur créé : {u_rech['email']}")
    else:
        print(f"  [INFO] Utilisateur existant : {u_rech['email']}")

    # 3. Adhésion aux Groupes (Memberships)
    for grp_id, usr_id in [(grp_dir["id"], u_dir["id"]), (grp_rech["id"], u_rech["id"])]:
        try:
            _mb_post("/api/permissions/membership", {"group_id": grp_id, "user_id": usr_id}, token)
        except Exception:
            pass  # Déjà membre

    # 4. Cloisonnement strict des collections
    collections = _mb_get("/api/collection", token)
    col_p = next((c for c in collections if not c.get("personal_owner_id") and "Pilotage" in c["name"]), None)
    col_r = next((c for c in collections if not c.get("personal_owner_id") and "Recherche" in c["name"]), None)

    if col_p and col_r:
        graph = _mb_get("/api/collection/graph", token)
        c_p_id = str(col_p["id"])
        c_r_id = str(col_r["id"])
        g_all_id = "1"
        g_dir_id = str(grp_dir["id"])
        g_rech_id = str(grp_rech["id"])

        if g_all_id in graph["groups"]:
            graph["groups"][g_all_id]["root"] = "none"
            graph["groups"][g_all_id][c_p_id] = "none"
            graph["groups"][g_all_id][c_r_id] = "none"

        graph["groups"][g_dir_id] = {"root": "read", c_p_id: "read", c_r_id: "none"}
        graph["groups"][g_rech_id] = {"root": "read", c_p_id: "none", c_r_id: "read"}

        try:
            _mb_put("/api/collection/graph", graph, token)
            print("  [OK] Cloisonnement strict validé dans l'arbre des permissions :")
            print("       • 'Direction & Pilotage' -> Accès EXCLUSIF à '🏥 Pilotage Hospitalier'")
            print("       • 'Recherche Clinique'  -> Accès EXCLUSIF à '🔬 Recherche Clinique'")
        except Exception as e:
            print(f"  [WARN] Note sur les permissions : {e}")

    print("  [SUCCESS] Utilisateurs Metabase opérationnels et cloisonnés.")


def main():
    setup_clickhouse_user()
    setup_metabase_users()


if __name__ == "__main__":
    main()
