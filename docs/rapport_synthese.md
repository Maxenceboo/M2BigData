# CENTRE HOSPITALIER UNIVERSITAIRE (CHU)
## Entrepôt de Données de Santé (EDS) — Rapport d'Architecture et Modélisation

* **Projet :** Entrepôt de Données de Santé (EDS)
* **Niveau :** Master 2 — Big Data & Santé
* **Auteur :** Ingénierie des Données
* **Date :** Septembre 2026
* **Version :** 2.0 (Consolidation Évolution Lot 2026-08-29)

---

## Sommaire
1. [Architecture Globale (Patron Médaillon)](#1-architecture-globale-patron-médaillon)
2. [Couche Bronze — Ingestion Incrémentale Brute](#2-couche-bronze--ingestion-incrémentale-brute)
3. [Couche Silver — Modèle en Étoile et Nettoyage Qualité](#3-couche-silver--modèle-en-étoile-et-nettoyage-qualité)
4. [Focus Technique : Pourquoi le calcul des alertes est fait en Silver et non en Gold ?](#4-focus-technique--pourquoi-le-calcul-des-alertes-est-fait-en-silver-et-non-en-gold-)
5. [Couche Gold — Vues Analytiques & Datamarts Métier](#5-couche-gold--vues-analytiques--datamarts-métier)
6. [Modèle de Données Global & Résolution des Pièges](#6-modèle-de-données-global--résolution-des-pièges)
7. [Restitution Décisionnelle & Cloisonnement des 3 Profils](#7-restitution-décisionnelle--cloisonnement-des-3-profils)

---

## 1. Architecture Globale (Patron Médaillon)

Le système repose sur une architecture en couches étanches dite « médaillon », orchestrée de bout en bout par Python et exécutée nativement dans ClickHouse en SQL :

![Architecture Globale EDS](schema_architecture.png)

### En bref :
* **Filestorage (Dépôt source) :** Zone de dépôt quotidien en lecture seule déposée par l'hôpital (formats hétérogènes : CSV, JSON imbriqué, Parquet).
* **Lake (Zone de staging sécurisée) :** Recopie locale brute avec **anonymisation immédiate à l'entrée** : hachage cryptographique déterministe salé (`HMAC-SHA256`) des identifiants patients, généralisation de la date de naissance en année (`birth_year`) et purge définitive des données directement identifiantes (`nom`, `prenom`, `nir`).
* **Bronze (ClickHouse) :** Tables typées stockant les données brutes sans altération.
* **Silver (ClickHouse) :** Nettoyage qualité, filtrage des aberrations physiologiques, déduplication temporelle et structuration en schéma en étoile (Star Schema).
* **Gold (ClickHouse) :** Vues analytiques matérialisées et vues SQL pour la restitution.
* **Metabase :** Restitution visuelle sans code avec contrôle d'accès strict par groupe d'utilisateurs.

---

## 2. Couche Bronze — Ingestion Incrémentale Brute

La couche Bronze reproduit fidèlement la granularité des fichiers sources ingérés de manière incrémentale jour par jour :

![Schéma Couche Bronze](schema_bronze.png)

### En bref :
* **Idempotence & Incrémentalité :** L'ingestion détecte automatiquement les lots déjà traités grâce à la table d'audit `admin.pipeline_runs` et évite tout doublon (`[SKIP]`).
* **Format & Stockage :** Moteur `MergeTree` partitionné par date de dépôt (`source_date`).
* **9 Tables Brutes :** 
  * Données patients (`bronze.patients`)
  * Séjours hospitaliers (`bronze.sejours`)
  * Diagnostics médicaux (`bronze.diagnostics`, dénormalisé depuis le JSON source)
  * Constantes vitales (`bronze.monitoring`, ingestion Parquet)
  * Nomenclatures et référentiels (`bronze.ref_services`, `bronze.ref_cim10`, `bronze.ref_description_service`, `bronze.ref_ccam`)
  * Actes médicaux (`bronze.actes`, nouveau flux d'évolution).

---

## 3. Couche Silver — Modèle en Étoile et Nettoyage Qualité

La couche Silver transforme les tables brutes en un modèle décisionnel propre, normalisé et prêt pour l'analyse :

![Schéma Couche Silver](schema_silver.png)

### En bref :
* **Architecture en Étoile (Star Schema) :** Composée de **4 dimensions** (`dim_patients`, `dim_services`, `dim_cim10`, `dim_ccam`) et de **4 tables de faits** (`fact_sejours`, `fact_diagnostics`, `fact_monitoring`, `fact_acte`).
* **Contrôles Qualité Appliqués en SQL (100% dans ClickHouse) :**
  1. *Déduplication Patients :* Utilisation de `ReplacingMergeTree` sur `patient_pseudo_id` en conservant l'état le plus récent.
  2. *Cohérence Temporelle Séjours :* Élimination des 68 séjours incohérents où `discharge_ts < admission_ts`. Les séjours en cours (`discharge_ts IS NULL`) sont légitimement préservés.
  3. *Filtrage Physiologique Constantes :* Exclusion des 858 relevés aberrants hors bornes physiologiques humaines (FC entre 20 et 250 bpm, SpO2 entre 50 et 100 %, Température entre 30 et 45 °C).

---

## 4. Focus Technique : Pourquoi le calcul des alertes est fait en Silver et non en Gold ?

Une décision d'ingénierie centrale de l'entrepôt réside dans la matérialisation des alertes physiologiques (`is_alert`, `alert_type`) au niveau de la table `silver.fact_monitoring` plutôt qu'à la volée dans les vues `gold`.

### 💡 Justification Architecturale :

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ ANTI-PATTERN ÉVITÉ (Calcul dans Gold) :                                     │
│ Requête Metabase / Cron ──> SCAN de 40 920 lignes ──> Re-calcul de 3 CASE   │
│                             WHEN (SpO2, FC, Temp) à CHAQUE rafraîchissement! │
│                             = Consommation CPU continue & lenteur dashboards│
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ BONNE PRATIQUE RETENUE (Pré-calcul en Silver) :                             │
│ 1. Ingestion Incrémentale : On évalue les règles physiologiques UNE SEULE    │
│    FOIS lors de l'insertion dans silver.fact_monitoring.                    │
│ 2. Stockage Compressé : ClickHouse stocke 'is_alert' sur 1 octet (UInt8)     │
│    avec un ratio de compression phénoménal sur disques en colonnes.        │
│ 3. Vues Gold Ultra-Véloces : Les requêtes Gold font juste un simple         │
│    `countIf(is_alert = 1)` vectorisé en mémoire sous la milliseconde !      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Les 3 raisons clés :
1. **Pas besoin de recalculer à chaque passage du cron :**  
   Les données du monitoring sont volumineuses (plus de 40 000 lignes par mois, des millions à l'échelle d'une année). En pré-calculant l'alerte à l'ingestion quotidienne, le travail lourd d'évaluation sémiologique n'est exécuté qu'une fois par ligne. Les crons de mise à jour nocturnes et les requêtes des tableaux de bord ne gaspillent aucun cycle CPU à réévaluer des règles statiques.
2. **Performance et réactivité utilisateur dans Metabase :**  
   Pour le directeur ou les soignants consultant le tableau de bord, une vue qui filtre sur `is_alert = 1` s'exécute instantanément en scannant une colonne binaire indexée, évitant les temps de latence de calcul sur de grands volumes.
3. **Traçabilité et auditabilité médicale :**  
   L'indicateur d'alerte et sa typologie (`hypoxie`, `tachycardie`, `bradycardie`, `fievre`, `hypothermie`) deviennent des attributs figés et historisés de la donnée clinique dans la table de faits, garantissant la reproductibilité exacte des chiffres dans le temps.

---

## 5. Couche Gold — Vues Analytiques & Datamarts Métier

La couche Gold expose des vues agrégées créées sous `SQL SECURITY DEFINER` pour autoriser la lecture sécurisée à l'utilisateur technique `metabase_user` :

![Schéma Couche Gold](schema_gold.png)

### En bref :
* **Axe Pilotage Hospitalier (4 vues) :**
  * `gold.vue_pilotage_dms` : Durée Moyenne de Séjour par service.
  * `gold.vue_pilotage_urgences` : Volume quotidien, transferts et devenir des urgences.
  * `gold.vue_pilotage_readmissions_30j` : Taux de réadmission précoce (10.54 %).
  * `gold.vue_pilotage_alertes` : Taux et typologie d'alertes vitales (7.46 %).
* **Axe Recherche Clinique & RGPD (3 vues) :**
  * `gold.vue_recherche_prevalence` : Prévalences épidémiologiques CIM-10 (diag principal vs associé).
  * `gold.vue_recherche_cohortes` : Distribution par âge et sexe avec **seuil de confidentialité strict $\ge 5$ patients**.
  * `gold.vue_recherche_synthese` : Chiffres clés globaux.
* **Axe Facturation T2A & Plateau Technique (5 vues d'évolution) :**
  * `gold.vue_pilotage_categories` : Activité et DMS par catégorie de service.
  * `gold.vue_pilotage_actes_services` : Nombre d'actes par service et moyenne par séjour (1.59).
  * `gold.vue_pilotage_actes_ccam` : Palmarès des actes cotés et valorisation financière.
  * `gold.vue_pilotage_densite_plateau` : Intensité technique et saturation des lits par acte.
  * `gold.vue_pilotage_facturation_t2a` : Recettes totales T2A par service et pôle (2,2 M€).

---

## 6. Modèle de Données Global & Résolution des Pièges

Le modèle global consolide l'ensemble des entités sans violer les principes du Big Data :

![Modèle de Données Global](schema_modele_donnees.png)

### Résolution explicite des 2 pièges du sujet :
1. **Piège du référentiel incomplet (`NEURO` absent de `description_service.csv`) :**  
   Résolu par un `LEFT JOIN` avec valeurs de repli par défaut : catégorie *« Non catégorisé »*, pôle *« Pôle Indéterminé »*, capacité de *0 lit*. Aucune donnée n'est rejetée, et l'anomalie de référentiel est visible immédiatement dans les tableaux de bord.
2. **Piège « Actes par service » sans jointure table-à-table entre faits :**  
   Dans `actes.parquet`, le service n'est pas renseigné. Pour éviter l'anti-pattern de joindre `fact_acte` et `fact_sejours` dans les requêtes Gold, le champ `service_code` a été **dénormalisé directement à l'ingestion de `silver.fact_acte`**. Les datamarts Gold interrogent ainsi une simple étoile `fact_acte ⋈ dim_services` sans aucun goulot d'étranglement mémoire.

---

## 7. Restitution Décisionnelle & Cloisonnement des 3 Profils

Metabase est connecté via un compte technique ClickHouse dédié (`metabase_user`) restreint au droit `SELECT ON gold.*` uniquement (accès `silver` et `bronze` formellement rejeté).

Les données sont restituées sur **3 tableaux de bord étanches** accessibles par 3 rôles distincts :

| Profil Métier | Compte Utilisateur | Périmètre d'Accès | Tableau de Bord Attribué |
| :--- | :--- | :--- | :--- |
| **Direction Générale** | `directeur@eds-chu.fr` | Exclusif à `🏥 Pilotage Hospitalier` | **Cockpit Pilotage Hospitalier**<br>Flux des urgences, tension des lits, DMS globale et réadmissions. |
| **Chercheur Clinique** | `chercheur@eds-chu.fr` | Exclusif à `🔬 Recherche Clinique` | **Recherche Clinique (RGPD)**<br>Cohortes épidémiologiques anonymisées avec seuil $\ge 5$ patients. |
| **Responsable DIM** | `dim@eds-chu.fr` | Exclusif à `💰 Facturation T2A & Plateau` | **Facturation T2A & Plateau Technique**<br>Cotation CCAM, recettes T2A (2,2 M€) et saturation des plateaux. |

*(Administration technique : `admin@eds-chu.fr`)*
