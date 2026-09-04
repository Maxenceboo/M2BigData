# 🏥 Entrepôt de Données de Santé (EDS) — CHU

> **Projet Fil Rouge — Master 2 Big Data & Santé**  
> Conception, modélisation dimensionnelle (Star Schema), architecture médaillon et restitution décisionnelle sous **ClickHouse** et **Metabase**.

---

## 📑 Accès Rapide aux Livrables & Documents Clés

Le dossier d'évaluation et la documentation complète sont disponibles aux formats PDF et Markdown :

| Document | Format | Description |
| :--- | :---: | :--- |
| **Rapport de Synthèse de Référence** | [📄 **Version PDF**](docs/rapport_synthese.pdf) &nbsp;\|&nbsp; [📝 Version Markdown](docs/rapport_synthese.md) | **Dossier complet d'évaluation (12 pages)** : Besoins, sources, architecture justifiée, chaîne ELT, justification Silver vs Gold pour les alertes, résolution des pièges (`NEURO`, zéro jointure fact-fact), métriques et dashboards. |
| **Dossier d'Analyse Métier & KPIs** | [📝 Version Markdown](docs/analyse_kpi_metier.md) | Analyse approfondie des 3 axes hospitaliers : Pilotage, Recherche clinique (RGPD ≥ 5), Facturation T2A & Plateau technique. |
| **Gestion des Accès & Sécurité** | [📝 Version Markdown](docs/gestion_acces_metabase.md) | Matrice de droits, comptes de test Metabase et politique de sécurité étanche (ClickHouse DEFINER & collections). |

---

## 🏛️ Architecture & Choix Technologiques

Le système repose sur une architecture **Médaillon (Lake → Bronze → Silver → Gold)** entièrement conteneurisée :

```
[ Fichiers Bruts SIH ] (source-filestorage/)
          │
          ▼
[ Module d'Anonymisation & Sécurité ] (HMAC-SHA256, purge nom/prénom/NIR, troncature année)
          │
          ▼
[ Couche BRONZE ] ──> Tables brutes typées ClickHouse (MergeTree, ingestion quotidienne incrémentale)
          │
          ▼
[ Couche SILVER ] ──> Modèle en étoile (Star Schema : 4 Dimensions, 4 Tables de faits indépendantes)
          │
          ▼
[ Couche GOLD ]   ──> 12 Datamarts analytiques sécurisés (DEFINER = default SQL SECURITY DEFINER)
          │
          ▼
[ RESTITUTION ]   ──> Tableaux de bord Metabase cloisonnés par profil métier
```

* **ClickHouse (OLAP Docker) :** Moteur colonnaire analytique exécutant **100% des transformations en SQL natif vectorisé** (anti-pattern Pandas banni pour le passage à l'échelle).
* **Metabase (BI Docker) :** Restitution décisionnelle moderne avec cloisonnement étanche des droits par groupe.
* **Orchestration Python :** Pipeline léger d'ordonnancement, de contrôle de séquence et de traçabilité idempotente (`admin.pipeline_runs`).

---

## 🚀 Démarrage Rapide

### 1. Prérequis
- Docker Desktop opérationnel.
- Python 3.10+ avec environnement virtuel.

### 2. Lancement de l'Infrastructure
```bash
# Démarrer ClickHouse et Metabase
docker compose up -d

# Vérifier la santé des conteneurs
docker ps
```

### 3. Exécution du Pipeline ELT
```bash
# Activer le venv et lancer l'ingestion incrémentale complète (Lots 2026-08-01 à 2026-08-29)
.venv\Scripts\python.exe src/run_pipeline.py
```

### 4. Tests Automatisés & Non-Régression
```bash
.venv\Scripts\pytest.exe -v
```

---

## 👥 Comptes de Test Metabase & Cloisonnement des Droits

L'interface Metabase est accessible à l'adresse : **`http://localhost:3000`**

| Profil Métier | Adresse Email | Mot de passe | Périmètre & Droits Autorisés |
| :--- | :--- | :--- | :--- |
| **Direction Générale** | `directeur@eds-chu.fr` | `DirecteurPassword123!` | Collection **🏥 Pilotage Hospitalier** (DMS, flux urgences, réadmissions 30j, alertes vitales). |
| **Chercheur Clinique** | `chercheur@eds-chu.fr` | `ChercheurPassword123!` | Collection **🔬 Recherche Clinique** (Données pseudonymisées, prévalence CIM-10, règle du secret statistique N ≥ 5). |
| **DIM / Facturation** | `dim@eds-chu.fr` | `DimPassword123!` | Collection **💰 Facturation T2A & Plateau Technique** (Actes CCAM, recettes 2,2 M€, saturation des lits). |
| **Administrateur Technique** | `admin@eds-chu.fr` | `AdminPassword123!` | Administration globale de l'instance et gestion des groupes. |

---

## 🏷️ Tags & Versions Git

- **`partie-1`** / **`v1.0.0`** : Socle initial de l'EDS (Ingestion Bronze, Modèle Silver initial, 7 datamarts Gold, dashboards Pilotage et Recherche).
- **`partie-2`** / **`v2.0.0`** : Lot d'évolution 2026-08-29 (Ingestion incrémentale, extension Silver `dim_ccam` & `fact_acte`, 5 nouveaux datamarts T2A, dashboards DIM et dossier de synthèse consolidé).
