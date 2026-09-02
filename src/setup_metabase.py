"""
Script de Déploiement Haute Fidélité des Tableaux de Bord Metabase :
1. Connexion et synchronisation ClickHouse
2. Collections étanches (🏥 Pilotage Hospitalier vs 🔬 Recherche Clinique)
3. Cartes KPI (Scorecards grand format), Graphiques horizontaux, Linéaires & Aires
4. Mise en page riche avec Bannières Markdown et intercalaires de section
5. Configuration soignée des visualisations (couleurs, libellés en français, légendes, axes)
6. Cloisonnement strict des droits d'accès RGPD
"""

import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.setup_users import setup_clickhouse_user, setup_metabase_users, MB_SQL_USER, MB_SQL_PASS

METABASE_URL = "http://localhost:3000"
ADMIN_EMAIL = "admin@eds-chu.fr"
ADMIN_PASS = "AdminPassword123!"


def get_session():
    payload = {"username": ADMIN_EMAIL, "password": ADMIN_PASS}
    req = urllib.request.Request(
        f"{METABASE_URL}/api/session",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    res = urllib.request.urlopen(req)
    return json.loads(res.read())["id"]


def api_get(endpoint, token):
    req = urllib.request.Request(
        f"{METABASE_URL}{endpoint}",
        headers={"X-Metabase-Session": token}
    )
    res = urllib.request.urlopen(req)
    return json.loads(res.read().decode("utf-8"))


def api_post(endpoint, payload, token):
    req = urllib.request.Request(
        f"{METABASE_URL}{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Metabase-Session": token}
    )
    res = urllib.request.urlopen(req)
    return json.loads(res.read().decode("utf-8"))


def api_put(endpoint, payload, token):
    req = urllib.request.Request(
        f"{METABASE_URL}{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Metabase-Session": token},
        method="PUT"
    )
    res = urllib.request.urlopen(req)
    return json.loads(res.read().decode("utf-8"))


def api_delete(endpoint, token):
    req = urllib.request.Request(
        f"{METABASE_URL}{endpoint}",
        headers={"X-Metabase-Session": token},
        method="DELETE"
    )
    try:
        urllib.request.urlopen(req)
    except Exception:
        pass


def create_or_update_card(name, display, sql, viz_settings, collection_id, db_id, token, existing_cards):
    card = next((c for c in existing_cards if c["name"] == name and c.get("collection_id") == collection_id), None)
    card_payload = {
        "name": name,
        "dataset_query": {
            "type": "native",
            "native": {"query": sql},
            "database": db_id
        },
        "display": display,
        "visualization_settings": viz_settings,
        "collection_id": collection_id
    }
    if not card:
        card = api_post("/api/card", card_payload, token)
        print(f"  [+] Question créée : {card['name']}")
    else:
        api_put(f"/api/card/{card['id']}", card_payload, token)
        print(f"  [~] Question mise à jour : {card['name']}")
    return card


def main():
    print("=" * 70)
    print("[START] DEPLOIEMENT HAUTE QUALITE METABASE (DASHBOARDS DESIGN & CLOISONNEMENT)")
    print("=" * 70)

    token = get_session()
    print("  [OK] Session administrateur authentifiée.")

    # 1. Base ClickHouse & Utilisateur technique (Accès strict GOLD)
    setup_clickhouse_user()

    dbs = api_get("/api/database", token)["data"]
    ch_db = next((d for d in dbs if d["engine"] == "clickhouse"), None)
    db_details = {
        "host": "clickhouse",
        "port": 8123,
        "db": "default",
        "user": "metabase_user",
        "password": "MetabasePassword123!"
    }
    if not ch_db:
        ch_db = api_post("/api/database", {
            "name": "ClickHouse EDS",
            "engine": "clickhouse",
            "details": db_details
        }, token)
    else:
        api_put(f"/api/database/{ch_db['id']}", {
            "name": ch_db["name"],
            "engine": "clickhouse",
            "details": db_details
        }, token)
    db_id = ch_db["id"]
    print(f"  [OK] Base ClickHouse connectée via metabase_user (id: {db_id})")

    # Sync
    try:
        api_post(f"/api/database/{db_id}/sync_schema", {}, token)
    except Exception:
        pass

    # 2. Collections Métier
    collections = api_get("/api/collection", token)
    col_pilotage = next((c for c in collections if not c.get("personal_owner_id") and "Pilotage" in c["name"]), None)
    if not col_pilotage:
        col_pilotage = api_post("/api/collection", {
            "name": "🏥 Pilotage Hospitalier",
            "color": "#16A085",
            "description": "Indicateurs médico-économiques pour la Direction et les chefs de service"
        }, token)
    
    col_recherche = next((c for c in collections if not c.get("personal_owner_id") and "Recherche" in c["name"]), None)
    if not col_recherche:
        col_recherche = api_post("/api/collection", {
            "name": "🔬 Recherche Clinique",
            "color": "#F39C12",
            "description": "Données épidémiologiques et cohortes pseudonymisées conformes RGPD (seuil >= 5)"
        }, token)

    col_t2a = next((c for c in collections if not c.get("personal_owner_id") and "T2A" in c["name"]), None)
    if not col_t2a:
        col_t2a = api_post("/api/collection", {
            "name": "💰 Facturation T2A & Plateau Technique",
            "color": "#2980B9",
            "description": "Valorisation financière T2A, cotation CCAM et saturation des plateaux pour le DIM"
        }, token)

    existing_cards = api_get("/api/card", token)
    dashboards = api_get("/api/dashboard", token)

    # =========================================================================
    # 🏥 1. DASHBOARD PILOTAGE HOSPITALIER
    # =========================================================================
    print("\n" + "-" * 70)
    print("🏥 DESIGN & MISE EN PAGE : DASHBOARD PILOTAGE HOSPITALIER")
    print("-" * 70)

    dash_pilotage = next((d for d in dashboards if "Pilotage" in d["name"]), None)
    if not dash_pilotage:
        dash_pilotage = api_post("/api/dashboard", {
            "name": "Tableau de Bord - Pilotage Hospitalier",
            "description": "Cockpit d'aide à la décision : flux urgences, DMS par service, constantes vitales et réadmissions",
            "collection_id": col_pilotage["id"]
        }, token)

    # Questions Pilotage
    # KPI 1 : Passages Urgences
    c_p_kpi_urg = create_or_update_card(
        name="KPI - Total Passages Urgences",
        display="scalar",
        sql="SELECT sum(nb_passages_total) AS total_urgences FROM gold.vue_pilotage_urgences",
        viz_settings={"scalar.field": "total_urgences"},
        collection_id=col_pilotage["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # KPI 2 : DMS Globale
    c_p_kpi_dms = create_or_update_card(
        name="KPI - Durée Moyenne de Séjour Globale",
        display="scalar",
        sql="SELECT round(sum(dms_jours * nb_sejours_termines) / sum(nb_sejours_termines), 1) AS dms_globale FROM gold.vue_pilotage_dms",
        viz_settings={"scalar.field": "dms_globale", "column_settings": {'["name","dms_globale"]': {"suffix": " jours"}}},
        collection_id=col_pilotage["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # KPI 3 : Taux Réadmission
    c_p_kpi_readm = create_or_update_card(
        name="KPI - Taux de Réadmission Précoce (30j)",
        display="scalar",
        sql="SELECT round(taux_readmission_pct, 1) AS taux_readm FROM gold.vue_pilotage_readmissions_30j",
        viz_settings={"scalar.field": "taux_readm", "column_settings": {'["name","taux_readm"]': {"suffix": " %"}}},
        collection_id=col_pilotage["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # KPI 4 : Taux Alertes
    c_p_kpi_alt = create_or_update_card(
        name="KPI - Taux Global d'Alertes Constantes",
        display="scalar",
        sql="SELECT round(100.0 * sum(nb_alertes_totales) / sum(nb_mesures_totales), 1) AS taux_alertes FROM gold.vue_pilotage_alertes",
        viz_settings={"scalar.field": "taux_alertes", "column_settings": {'["name","taux_alertes"]': {"suffix": " %"}}},
        collection_id=col_pilotage["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # Graphique 1 : DMS par service (Barres horizontales)
    c_p_dms_chart = create_or_update_card(
        name="Durée Moyenne de Séjour (DMS) par Service",
        display="row",
        sql="""
        SELECT 
            service_label AS Service,
            round(dms_jours, 2) AS "DMS (Jours)"
        FROM gold.vue_pilotage_dms 
        ORDER BY dms_jours DESC
        """,
        viz_settings={
            "graph.colors": ["#16A085"],
            "graph.show_values": True,
            "graph.x_axis.title_text": "Durée moyenne (jours)",
            "graph.y_axis.title_text": "Service Hospitalier"
        },
        collection_id=col_pilotage["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # Tableau 1 : Synthèse des Séjours par Service
    c_p_dms_table = create_or_update_card(
        name="Détail Médico-Économique par Service",
        display="table",
        sql="""
        SELECT 
            service_label AS "Service",
            round(dms_jours, 2) AS "DMS (j)",
            round(dms_mediane_jours, 2) AS "Médiane (j)",
            round(dms_min_jours, 1) AS "Min (j)",
            round(dms_max_jours, 1) AS "Max (j)",
            nb_sejours_termines AS "Séjours Clôturés",
            nb_sejours_en_cours AS "Séjours En Cours"
        FROM gold.vue_pilotage_dms 
        ORDER BY dms_jours DESC
        """,
        viz_settings={},
        collection_id=col_pilotage["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # Graphique 2 : Activité Quotidienne des Urgences (Ligne multi-séries)
    c_p_urg_line = create_or_update_card(
        name="Flux Quotidien et Devenir des Passages aux Urgences",
        display="line",
        sql="""
        SELECT 
            date_passage AS "Date",
            nb_passages_total AS "Total Passages",
            nb_sorties_domicile AS "Sorties Domicile",
            (nb_mutations_internes + nb_transferts_externes) AS "Hospitalisations",
            nb_deces AS "Décès"
        FROM gold.vue_pilotage_urgences 
        ORDER BY date_passage
        """,
        viz_settings={
            "graph.colors": ["#2C3E50", "#27AE60", "#E67E22", "#E74C3C"],
            "graph.x_axis.title_text": "Date de passage",
            "graph.y_axis.title_text": "Nombre de patients",
            "line.interpolate": "monotone"
        },
        collection_id=col_pilotage["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # Graphique 3 : Taux d'Hospitalisation après urgence (Aire)
    c_p_urg_hosp = create_or_update_card(
        name="Taux d'Hospitalisation post-Urgences (%)",
        display="area",
        sql="""
        SELECT 
            date_passage AS "Date",
            taux_hospitalisation_pct AS "Taux Hospitalisation (%)"
        FROM gold.vue_pilotage_urgences 
        ORDER BY date_passage
        """,
        viz_settings={
            "graph.colors": ["#8E44AD"],
            "graph.x_axis.title_text": "Date",
            "graph.y_axis.title_text": "Taux (%)"
        },
        collection_id=col_pilotage["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # Graphique 4 : Mesures vs Alertes (Barres empilées)
    c_p_alt_bar = create_or_update_card(
        name="Volume de Monitoring & Mesures Normales vs Alertes",
        display="bar",
        sql="""
        SELECT 
            jour AS "Date",
            (nb_mesures_totales - nb_alertes_totales) AS "Mesures Conformes",
            nb_alertes_totales AS "Alertes Vitales Détectées"
        FROM gold.vue_pilotage_alertes 
        ORDER BY jour
        """,
        viz_settings={
            "stackable.stack_type": "stacked",
            "graph.colors": ["#A3E4D7", "#E74C3C"],
            "graph.x_axis.title_text": "Date",
            "graph.y_axis.title_text": "Nombre de mesures constantes"
        },
        collection_id=col_pilotage["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # Graphique 5 : Décomposition des Alertes Vitales (Barres empilées)
    c_p_alt_decomp = create_or_update_card(
        name="Décomposition des Alertes Vitales par Typologie",
        display="bar",
        sql="""
        SELECT 
            jour AS "Date",
            nb_alertes_fc AS "FC Anormale (<50 ou >120)",
            nb_alertes_spo2 AS "Hypoxie (SpO2 <92%)",
            nb_alertes_temp AS "Température (<36°C ou ≥38.5°C)"
        FROM gold.vue_pilotage_alertes 
        ORDER BY jour
        """,
        viz_settings={
            "stackable.stack_type": "stacked",
            "graph.colors": ["#E74C3C", "#2980B9", "#F39C12"],
            "graph.x_axis.title_text": "Date",
            "graph.y_axis.title_text": "Nombre d'alertes"
        },
        collection_id=col_pilotage["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # -------------------------------------------------------------------------
    # 💰 ÉVOLUTION : PLATEAU TECHNIQUE & FACTURATION T2A
    # -------------------------------------------------------------------------
    # KPI 5 : Volume Total d'Actes
    c_p_kpi_actes = create_or_update_card(
        name="KPI - Total Actes Médicaux Réalisés",
        display="scalar",
        sql="SELECT sum(nb_actes_total) AS total_actes FROM gold.vue_pilotage_actes_services",
        viz_settings={"scalar.field": "total_actes"},
        collection_id=col_t2a["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # KPI 6 : Montant Facturé T2A
    c_p_kpi_t2a = create_or_update_card(
        name="KPI - Montant Total Facturé T2A (€)",
        display="scalar",
        sql="SELECT sum(montant_total_t2a_euros) AS total_t2a FROM gold.vue_pilotage_facturation_t2a",
        viz_settings={"scalar.field": "total_t2a"},
        collection_id=col_t2a["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # KPI 7 : Densité Moyenne Plateau
    c_p_kpi_dens = create_or_update_card(
        name="KPI - Densité Moyenne d'Actes par Lit",
        display="scalar",
        sql="SELECT round(avgIf(densite_actes_par_lit, capacite_lits > 0), 1) AS densite_moyenne FROM gold.vue_pilotage_densite_plateau",
        viz_settings={"scalar.field": "densite_moyenne"},
        collection_id=col_t2a["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # Graphique 6 : Top CCAM (Barres horizontales)
    c_p_top_ccam = create_or_update_card(
        name="Palmarès des Actes CCAM les plus Fréquents",
        display="row",
        sql="""
        SELECT 
            libelle_acte AS "Acte Médical",
            nb_actes_total AS "Nombre d'actes"
        FROM gold.vue_pilotage_actes_ccam 
        ORDER BY nb_actes_total DESC
        """,
        viz_settings={
            "graph.colors": ["#16A085"],
            "graph.x_axis.title_text": "Nombre d'actes",
            "graph.y_axis.title_text": "Acte CCAM"
        },
        collection_id=col_t2a["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # Graphique 7 : Facturation T2A par Service (Barres)
    c_p_t2a_bar = create_or_update_card(
        name="Valorisation Financière T2A par Service (€)",
        display="bar",
        sql="""
        SELECT 
            service_label AS "Service",
            montant_total_t2a_euros AS "Montant T2A (€)"
        FROM gold.vue_pilotage_facturation_t2a 
        ORDER BY montant_total_t2a_euros DESC
        """,
        viz_settings={
            "graph.colors": ["#2980B9"],
            "graph.x_axis.title_text": "Service",
            "graph.y_axis.title_text": "Montant Total Facturé (€)"
        },
        collection_id=col_t2a["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # Tableau 2 : Activité et DMS par Catégorie de Service
    c_p_cat_table = create_or_update_card(
        name="Activité & DMS par Catégorie de Service",
        display="table",
        sql="""
        SELECT 
            categorie AS "Catégorie",
            pole AS "Pôle Hospitalier",
            nb_sejours_termines AS "Séjours Clôturés",
            dms_jours AS "DMS (jours)"
        FROM gold.vue_pilotage_categories 
        ORDER BY nb_sejours_termines DESC
        """,
        viz_settings={},
        collection_id=col_t2a["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # Graphique 8 : Intensité plateau technique (Densité par lit)
    c_p_dens_chart = create_or_update_card(
        name="Intensité d'Activité sur le Plateau Technique (Actes / Lit)",
        display="bar",
        sql="""
        SELECT 
            service_label AS "Service",
            densite_actes_par_lit AS "Actes / Lit"
        FROM gold.vue_pilotage_densite_plateau 
        WHERE capacite_lits > 0
        ORDER BY densite_actes_par_lit DESC
        """,
        viz_settings={
            "graph.colors": ["#E67E22"],
            "graph.x_axis.title_text": "Service Hospitalier",
            "graph.y_axis.title_text": "Ratio Actes / Lit"
        },
        collection_id=col_t2a["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # Assemblage Dashboard Pilotage
    dashcards_pilotage = [
        # Bannière Markdown
        {
            "id": -1, "card_id": None, "row": 0, "col": 0, "size_x": 24, "size_y": 2,
            "visualization_settings": {
                "virtual_card": {"display": "text"},
                "text": "# 🏥 Cockpit de Pilotage Hospitalier — Centre Hospitalier Universitaire\n*Indicateurs stratégiques de performance médico-économique, régulation des flux d'urgences et sécurité des soins.*"
            }
        },
        # 4 KPI Scorecards
        {"id": -2, "card_id": c_p_kpi_urg["id"], "row": 2, "col": 0, "size_x": 6, "size_y": 3, "visualization_settings": {}},
        {"id": -3, "card_id": c_p_kpi_dms["id"], "row": 2, "col": 6, "size_x": 6, "size_y": 3, "visualization_settings": {}},
        {"id": -4, "card_id": c_p_kpi_readm["id"], "row": 2, "col": 12, "size_x": 6, "size_y": 3, "visualization_settings": {}},
        {"id": -5, "card_id": c_p_kpi_alt["id"], "row": 2, "col": 18, "size_x": 6, "size_y": 3, "visualization_settings": {}},

        # Section 1 : DMS
        {
            "id": -6, "card_id": None, "row": 5, "col": 0, "size_x": 24, "size_y": 1,
            "visualization_settings": {
                "virtual_card": {"display": "text"},
                "text": "### ⏱️ Performance Médico-Économique & Durée Moyenne de Séjour (DMS)"
            }
        },
        {"id": -7, "card_id": c_p_dms_chart["id"], "row": 6, "col": 0, "size_x": 13, "size_y": 9, "visualization_settings": {}},
        {"id": -8, "card_id": c_p_dms_table["id"], "row": 6, "col": 13, "size_x": 11, "size_y": 9, "visualization_settings": {}},

        # Section 2 : Urgences
        {
            "id": -9, "card_id": None, "row": 15, "col": 0, "size_x": 24, "size_y": 1,
            "visualization_settings": {
                "virtual_card": {"display": "text"},
                "text": "### 🚑 Flux, Tension & Devenir des Passages aux Urgences"
            }
        },
        {"id": -10, "card_id": c_p_urg_line["id"], "row": 16, "col": 0, "size_x": 16, "size_y": 9, "visualization_settings": {}},
        {"id": -11, "card_id": c_p_urg_hosp["id"], "row": 16, "col": 16, "size_x": 8, "size_y": 9, "visualization_settings": {}},

        # Section 3 : Constantes
        {
            "id": -12, "card_id": None, "row": 25, "col": 0, "size_x": 24, "size_y": 1,
            "visualization_settings": {
                "virtual_card": {"display": "text"},
                "text": "### 🩺 Vigilance Clinique : Surveillance des Constantes Vitales en Temps Réel"
            }
        },
        {"id": -13, "card_id": c_p_alt_bar["id"], "row": 26, "col": 0, "size_x": 12, "size_y": 9, "visualization_settings": {}},
        {"id": -14, "card_id": c_p_alt_decomp["id"], "row": 26, "col": 12, "size_x": 12, "size_y": 9, "visualization_settings": {}}
    ]

    api_put(f"/api/dashboard/{dash_pilotage['id']}", {"dashcards": dashcards_pilotage}, token)
    print("  [OK] Dashboard Pilotage Hospitalier (Direction) restructuré et centré sur son périmètre.")


    # =========================================================================
    # 🔬 2. DASHBOARD RECHERCHE CLINIQUE (RGPD)
    # =========================================================================
    print("\n" + "-" * 70)
    print("🔬 DESIGN & MISE EN PAGE : DASHBOARD RECHERCHE CLINIQUE (RGPD)")
    print("-" * 70)

    dash_recherche = next((d for d in dashboards if "Recherche" in d["name"]), None)
    if not dash_recherche:
        dash_recherche = api_post("/api/dashboard", {
            "name": "Tableau de Bord - Recherche Clinique (RGPD)",
            "description": "Exploration épidémiologique et cohortes cliniques conformes RGPD (seuil >= 5 patients)",
            "collection_id": col_recherche["id"]
        }, token)

    # KPI 1 : Patients Inclus
    c_r_kpi_pat = create_or_update_card(
        name="KPI - Patients Inclus dans l'EDS",
        display="scalar",
        sql="SELECT nb_patients_total AS total_patients FROM gold.vue_recherche_synthese",
        viz_settings={"scalar.field": "total_patients"},
        collection_id=col_recherche["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # KPI 2 : Diagnostics Posés
    c_r_kpi_diag = create_or_update_card(
        name="KPI - Diagnostics Médicaux Référencés",
        display="scalar",
        sql="SELECT nb_diagnostics_total AS total_diagnostics FROM gold.vue_recherche_synthese",
        viz_settings={"scalar.field": "total_diagnostics"},
        collection_id=col_recherche["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # KPI 3 : Pathologies Surveillées
    c_r_kpi_patho = create_or_update_card(
        name="KPI - Pathologies Distinctes Surveillées",
        display="scalar",
        sql="SELECT nb_pathologies_surveillees AS nb_pathologies FROM gold.vue_recherche_synthese",
        viz_settings={"scalar.field": "nb_pathologies"},
        collection_id=col_recherche["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # Graphique 1 : Prévalence par Pathologie (Barres horizontales)
    c_r_prev_chart = create_or_update_card(
        name="Prévalence Globale par Pathologie (CIM-10)",
        display="row",
        sql="""
        SELECT 
            libelle_pathologie AS "Pathologie",
            nb_patients_uniques AS "Patients Uniques",
            nb_diagnostics_total AS "Diagnostics Totaux"
        FROM gold.vue_recherche_prevalence 
        ORDER BY nb_patients_uniques DESC
        """,
        viz_settings={
            "graph.colors": ["#2980B9", "#BDC3C7"],
            "graph.show_values": True,
            "graph.x_axis.title_text": "Nombre de patients",
            "graph.y_axis.title_text": "Pathologie CIM-10"
        },
        collection_id=col_recherche["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # Graphique 2 : Diagnostics Principaux vs Associés
    c_r_diag_roles = create_or_update_card(
        name="Rôle des Pathologies : Diagnostic Principal vs Associé",
        display="bar",
        sql="""
        SELECT 
            libelle_pathologie AS "Pathologie",
            nb_diagnostic_principal AS "Diagnostic Principal",
            nb_diagnostic_associe AS "Diagnostic Associé"
        FROM gold.vue_recherche_prevalence 
        ORDER BY (nb_diagnostic_principal + nb_diagnostic_associe) DESC
        LIMIT 8
        """,
        viz_settings={
            "graph.colors": ["#1F77B4", "#2CA02C"],
            "graph.x_axis.title_text": "Pathologie",
            "graph.y_axis.title_text": "Nombre de diagnostics"
        },
        collection_id=col_recherche["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # Graphique 3 : Démographie par Tranche d'Âge et Sexe
    c_r_demo_chart = create_or_update_card(
        name="Distribution Démographique Globale (Âge & Sexe)",
        display="bar",
        sql="""
        SELECT 
            tranche_age AS "Tranche d'âge",
            sumIf(nb_patients, sex = 'F') AS "Femmes",
            sumIf(nb_patients, sex = 'M') AS "Hommes"
        FROM gold.vue_recherche_cohortes
        GROUP BY "Tranche d'âge"
        ORDER BY "Tranche d'âge"
        """,
        viz_settings={
            "graph.colors": ["#E91E63", "#1976D2"],
            "graph.x_axis.title_text": "Tranche d'âge",
            "graph.y_axis.title_text": "Nombre de patients",
            "graph.dimensions": ["Tranche d'âge"],
            "graph.metrics": ["Femmes", "Hommes"]
        },
        collection_id=col_recherche["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    # Tableau 2 : Cohortes Détaillées avec seuil de confidentialité
    c_r_cohortes_table = create_or_update_card(
        name="Cohortes Cliniques Détaillées (Règle RGPD Effectifs ≥ 5)",
        display="table",
        sql="""
        SELECT 
            libelle_pathologie AS "Pathologie",
            tranche_age AS "Tranche d'Âge",
            sex AS "Sexe",
            nb_patients AS "Patients Inclus"
        FROM gold.vue_recherche_cohortes 
        WHERE nb_patients >= 5
        ORDER BY libelle_pathologie, tranche_age, sex
        """,
        viz_settings={},
        collection_id=col_recherche["id"], db_id=db_id, token=token, existing_cards=existing_cards
    )

    dashcards_recherche = [
        # Bannière Markdown
        {
            "id": -1, "card_id": None, "row": 0, "col": 0, "size_x": 24, "size_y": 2,
            "visualization_settings": {
                "virtual_card": {"display": "text"},
                "text": "# 🔬 Recherche Clinique & Épidémiologie — Entrepôt de Données de Santé\n*Exploration des cohortes cliniques pseudonymisées avec sel cryptographique. Conformité stricte RGPD (Art. 9 & seuil de confidentialité $\\ge 5$ patients).* "
            }
        },
        # 3 KPI Scorecards
        {"id": -2, "card_id": c_r_kpi_pat["id"], "row": 2, "col": 0, "size_x": 8, "size_y": 3, "visualization_settings": {}},
        {"id": -3, "card_id": c_r_kpi_diag["id"], "row": 2, "col": 8, "size_x": 8, "size_y": 3, "visualization_settings": {}},
        {"id": -4, "card_id": c_r_kpi_patho["id"], "row": 2, "col": 16, "size_x": 8, "size_y": 3, "visualization_settings": {}},

        # Section 1 : Prévalences
        {
            "id": -5, "card_id": None, "row": 5, "col": 0, "size_x": 24, "size_y": 1,
            "visualization_settings": {
                "virtual_card": {"display": "text"},
                "text": "### 📊 Prévalence Épidémiologique des Pathologies (CIM-10)"
            }
        },
        {"id": -6, "card_id": c_r_prev_chart["id"], "row": 6, "col": 0, "size_x": 13, "size_y": 10, "visualization_settings": {}},
        {"id": -7, "card_id": c_r_diag_roles["id"], "row": 6, "col": 13, "size_x": 11, "size_y": 10, "visualization_settings": {}},

        # Section 2 : Démographie & Cohortes
        {
            "id": -8, "card_id": None, "row": 16, "col": 0, "size_x": 24, "size_y": 1,
            "visualization_settings": {
                "virtual_card": {"display": "text"},
                "text": "### 👥 Caractérisation Démographique des Cohortes (Âge & Sexe)"
            }
        },
        {"id": -9, "card_id": c_r_demo_chart["id"], "row": 17, "col": 0, "size_x": 12, "size_y": 10, "visualization_settings": {}},
        {"id": -10, "card_id": c_r_cohortes_table["id"], "row": 17, "col": 12, "size_x": 12, "size_y": 10, "visualization_settings": {}}
    ]

    api_put(f"/api/dashboard/{dash_recherche['id']}", {"dashcards": dashcards_recherche}, token)
    print("  [OK] Dashboard Recherche Clinique entièrement restructuré et stylisé.")


    # =========================================================================
    # 💰 3. DASHBOARD FACTURATION T2A & PLATEAU TECHNIQUE (DIM)
    # =========================================================================
    print("\n" + "-" * 70)
    print("💰 DESIGN & MISE EN PAGE : DASHBOARD FACTURATION T2A & PLATEAU TECHNIQUE (DIM)")
    print("-" * 70)

    dash_t2a = next((d for d in dashboards if "T2A" in d["name"] or "Facturation" in d["name"]), None)
    if not dash_t2a:
        dash_t2a = api_post("/api/dashboard", {
            "name": "Tableau de Bord - Facturation T2A & Plateau Technique",
            "description": "Pilotage médico-économique des actes CCAM, tarification T2A et saturation des plateaux pour le DIM",
            "collection_id": col_t2a["id"]
        }, token)

    dashcards_t2a = [
        # Bannière Markdown
        {
            "id": -1, "card_id": None, "row": 0, "col": 0, "size_x": 24, "size_y": 2,
            "visualization_settings": {
                "virtual_card": {"display": "text"},
                "text": "# 💰 Département d'Information Médicale (DIM) — Facturation T2A & Plateau Technique\n*Suivi exhaustif des actes médicaux codés en CCAM, valorisation financière T2A et densité d'activité par lit.*"
            }
        },
        # 3 KPI Scorecards
        {"id": -2, "card_id": c_p_kpi_actes["id"], "row": 2, "col": 0, "size_x": 8, "size_y": 3, "visualization_settings": {}},
        {"id": -3, "card_id": c_p_kpi_t2a["id"], "row": 2, "col": 8, "size_x": 8, "size_y": 3, "visualization_settings": {}},
        {"id": -4, "card_id": c_p_kpi_dens["id"], "row": 2, "col": 16, "size_x": 8, "size_y": 3, "visualization_settings": {}},

        # Section 1 : Cotation CCAM & Recettes
        {
            "id": -5, "card_id": None, "row": 5, "col": 0, "size_x": 24, "size_y": 1,
            "visualization_settings": {
                "virtual_card": {"display": "text"},
                "text": "### 📋 Cotation CCAM & Recettes T2A par Pôle et Service"
            }
        },
        {"id": -6, "card_id": c_p_top_ccam["id"], "row": 6, "col": 0, "size_x": 12, "size_y": 9, "visualization_settings": {}},
        {"id": -7, "card_id": c_p_t2a_bar["id"], "row": 6, "col": 12, "size_x": 12, "size_y": 9, "visualization_settings": {}},

        # Section 2 : Activité Plateau
        {
            "id": -8, "card_id": None, "row": 15, "col": 0, "size_x": 24, "size_y": 1,
            "visualization_settings": {
                "virtual_card": {"display": "text"},
                "text": "### 🏥 Intensité du Plateau Technique & Activité par Catégorie"
            }
        },
        {"id": -9, "card_id": c_p_cat_table["id"], "row": 16, "col": 0, "size_x": 12, "size_y": 9, "visualization_settings": {}},
        {"id": -10, "card_id": c_p_dens_chart["id"], "row": 16, "col": 12, "size_x": 12, "size_y": 9, "visualization_settings": {}}
    ]

    api_put(f"/api/dashboard/{dash_t2a['id']}", {"dashcards": dashcards_t2a}, token)
    print("  [OK] Dashboard Facturation T2A & Plateau Technique (DIM) entièrement déployé et stylisé.")

    # 4. Utilisateurs, groupes et cloisonnement des droits
    setup_metabase_users()

    print("\n" + "=" * 70)
    print("🎉 DEPLOIEMENT HAUTE FIDELITE TERMINE !")
    print("=" * 70)
    print("URL Metabase : http://localhost:3000")
    print("• Admin :      admin@eds-chu.fr     / AdminPassword123!")
    print("• Direction :  directeur@eds-chu.fr / DirecteurPassword123!")
    print("• Chercheur :  chercheur@eds-chu.fr / ChercheurPassword123!")
    print("• DIM / T2A :  dim@eds-chu.fr       / DimPassword123!")
    print("=" * 70)


if __name__ == "__main__":
    main()
