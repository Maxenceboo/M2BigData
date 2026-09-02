"""
Script de Création et Validation de la Couche Gold (Vues Métier Pilotage & Recherche RGPD).
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


def run_gold_transformations():
    print("=" * 70)
    print("[START] CREATION & VALIDATION DE LA COUCHE GOLD (DATAMARTS METIER)")
    print("=" * 70)

    client = get_clickhouse_client()

    # 1. Création des vues Gold
    print("[INFO] Création des vues analytiques Gold...")
    sql_gold = BASE_DIR / "sql" / "03_gold.sql"
    execute_sql_file(client, sql_gold)
    print("  [OK] Vues Gold créées avec succès.")

    # 2. Validation & Affichage des KPI Pilotage
    print("\n" + "-" * 70)
    print("🏥 APERÇU DES INDICATEURS DE PILOTAGE HOSPITALIER :")
    print("-" * 70)

    # DMS
    print("\n📌 Durée Moyenne de Séjour (DMS) par Service :")
    dms_res = client.query("""
        SELECT service_code, service_label, nb_sejours_termines, nb_sejours_en_cours, dms_jours 
        FROM gold.vue_pilotage_dms 
        ORDER BY dms_jours DESC
    """).result_rows
    for r in dms_res:
        print(f"  • {r[0]:<10} ({r[1]:<15}) : DMS = {r[4]:>5.2f} jours | Terminés: {r[2]:>4} | En cours: {r[3]:>4}")

    # Urgences
    print("\n📌 Activité des Urgences (Passages par jour) :")
    urg_res = client.query("""
        SELECT date_passage, nb_passages_total, nb_sorties_domicile, nb_mutations_internes, nb_deces, taux_hospitalisation_pct
        FROM gold.vue_pilotage_urgences
        ORDER BY date_passage
    """).result_rows
    for r in urg_res:
        print(f"  • Date {r[0]} : Total={r[1]} | Domicile={r[2]} | Hospitalisés={r[3]} | Décès={r[4]} | Taux Hosp={r[5]}%")

    # Réadmissions 30j
    print("\n📌 Taux de Réadmission à 30 jours :")
    readm_res = client.query("""
        SELECT nb_sejours_total, nb_readmissions_30j, taux_readmission_pct
        FROM gold.vue_pilotage_readmissions_30j
    """).result_rows
    for r in readm_res:
        print(f"  • Total={r[0]} | Readmission={r[1]} | Taux Readmission={r[2]}%")

    # Alertes Constantes
    print("\n📌 Synthèse des Alertes Constantes Vitales :")
    alt_res = client.query("""
        SELECT jour, sum(nb_mesures_totales), sum(nb_alertes_totales), round(100.0 * sum(nb_alertes_totales) / sum(nb_mesures_totales), 2)
        FROM gold.vue_pilotage_alertes
        GROUP BY jour
        ORDER BY jour
    """).result_rows
    for r in alt_res:
        print(f"  • Jour {r[0]} : {r[2]} alertes sur {r[1]} mesures ({r[3]}%)")

    # 3. Validation & Affichage des KPI Recherche Clinique (RGPD)
    print("\n" + "-" * 70)
    print("🔬 APERÇU DES INDICATEURS DE RECHERCHE CLINIQUE (RGPD : Seuil ≥ 5) :")
    print("-" * 70)

    # Prévalence
    print("\n📌 Prévalence par Pathologie (Top Cohortes) :")
    prev_res = client.query("""
        SELECT code_cim10, libelle_pathologie, nb_patients_uniques, nb_diagnostics_total
        FROM gold.vue_recherche_prevalence
        LIMIT 5
    """).result_rows
    for r in prev_res:
        print(f"  • [{r[0]}] {r[1]:<35} : {r[2]} patients uniques ({r[3]} diagnostics)")

    # Cohortes Âge / Sexe
    print("\n📌 Distribution Démographique des Cohortes (Échantillon) :")
    coh_res = client.query("""
        SELECT code_cim10, libelle_pathologie, tranche_age, sex, nb_patients
        FROM gold.vue_recherche_cohortes
        LIMIT 6
    """).result_rows
    for r in coh_res:
        print(f"  • [{r[0]}] {r[1]:<25} | {r[2]:<10} | Sexe {r[3]} : {r[4]} patients")

    # 4. Validation & Affichage des KPI Évolution (T2A & Plateau Technique)
    print("\n" + "-" * 70)
    print("💰 APERÇU DES INDICATEURS MÉDICO-ÉCONOMIQUES & PLATEAU TECHNIQUE (ÉVOLUTION) :")
    print("-" * 70)

    # Catégories
    print("\n📌 Activité & DMS par Catégorie de Service :")
    cat_res = client.query("SELECT categorie, pole, nb_sejours_termines, dms_jours FROM gold.vue_pilotage_categories").result_rows
    for r in cat_res:
        print(f"  • {r[0]:<15} ({r[1]:<20}) : {r[2]:>4} séjours clôturés | DMS = {r[3]:>5.2f} jours")

    # Actes & Intensité par Service
    print("\n📌 Volume d'Actes & Intensité par Séjour :")
    act_res = client.query("SELECT service_label, nb_actes_total, nb_sejours_concernes, moyenne_actes_par_sejour FROM gold.vue_pilotage_actes_services LIMIT 5").result_rows
    for r in act_res:
        print(f"  • {r[0]:<15} : {r[1]:>5} actes ({r[2]:>4} séjours) | Moyenne = {r[3]:>4.2f} actes/séjour")

    # Top CCAM
    print("\n📌 Palmarès des Actes CCAM les plus Fréquents :")
    ccam_res = client.query("SELECT libelle_acte, nb_actes_total, tarif_unitaire_euros, montant_total_euros FROM gold.vue_pilotage_actes_ccam LIMIT 5").result_rows
    for r in ccam_res:
        print(f"  • {r[0]:<32} : {r[1]:>5} actes @ {r[2]:>4}€ = {r[3]:>7}€")

    # Densité par Lit
    print("\n📌 Densité d'Actes par Lit Hospitalier (Plateau Technique) :")
    dens_res = client.query("SELECT service_label, capacite_lits, nb_actes_total, densite_actes_par_lit FROM gold.vue_pilotage_densite_plateau WHERE capacite_lits > 0 LIMIT 5").result_rows
    for r in dens_res:
        print(f"  • {r[0]:<15} : {r[1]:>3} lits | {r[2]:>5} actes | Ratio = {r[3]:>5.2f} actes/lit")

    # Facturation T2A
    print("\n📌 Facturation T2A par Service :")
    t2a_res = client.query("SELECT service_label, nb_actes_total, montant_total_t2a_euros FROM gold.vue_pilotage_facturation_t2a LIMIT 5").result_rows
    for r in t2a_res:
        print(f"  • {r[0]:<15} : {r[1]:>5} actes facturés | Total T2A = {r[2]:>7}€")

    print("\n" + "=" * 70)
    print("[END] COUCHE GOLD VALIDE ET OPERATIONNELLE")
    print("=" * 70)


if __name__ == "__main__":
    run_gold_transformations()
