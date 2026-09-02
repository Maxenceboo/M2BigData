# 🏥 Analyse Métier des Indicateurs Clés (KPI) — Entrepôt de Données de Santé (EDS)

> **Document de Restitution & Analyse Décisionnelle — CHU**  
> **Source de données :** Couche Gold ClickHouse via Dashboards Metabase  
> **Période d'analyse :** Données consolidées sur le mois d'août 2026 (Cohorte de 6 000 patients uniques)

---

## 📌 Synthèse Exécutive

L'Entrepôt de Données de Santé (EDS) consolide les flux opérationnels de l'établissement à travers deux axes stratégiques distincts et cloisonnés :
1. **Le Pilotage Hospitalier (Direction & Chefs de pôle) :** Surveillance de la fluidité des parcours de soins, de la tension des urgences, de l'efficience médico-économique des services (DMS) et de la sécurité des soins (vigilance constante et réadmissions précoces).
2. **La Recherche Clinique & Épidémiologie (Praticiens & Chercheurs) :** Exploration des cohortes de patients pseudonymisées, caractérisation démographique et prévalence des pathologies CIM-10, dans le respect strict des contraintes du RGPD (Art. 9 et règle des petits effectifs $\ge 5$).

---

## 1️⃣ Axe Pilotage Hospitalier & Médico-Économique

### 📊 Tableau de Bord Récapitulatif des Métriques Clés

| Indicateur | Valeur Observée | Référentiel / Seuil | Interprétation & Diagnostic Métier |
| :--- | :---: | :---: | :--- |
| **DMS Globale CHU** | **5.15 jours** | 5.0 – 5.5 jours | Durée de séjour maîtrisée, conforme aux standards universitaires. |
| **Séjours Clôturés vs En Cours** | **6 046 / 683** | Ratio normalisé | Activité soutenue ; 683 lits occupés au moment de la clôture du lot. |
| **Passages aux Urgences (Total)** | **1 423 passages** | ~50 passages / jour | Flux régulier avec des pointes jusqu'à 82 passages/jour (pic au 21/08). |
| **Taux d'Hospitalisation post-Urgences** | **31.75 %** | 25 – 35 % | Niveau de tension modéré à fort sur les lits d'aval du CHU. |
| **Taux de Réadmission Précoce (30j)** | **10.54 %** | Cible < 12 % | Indicateur de qualité satisfaisant (637 réadmissions sur 6 046 sorties). |
| **Taux Global d'Alertes Vitales** | **7.46 %** | 5 – 8 % | Surveillance physiologique efficace (3 052 alertes sur 40 920 mesures). |

---

### ⏱️ Analyse Détaillée : Durée Moyenne de Séjour (DMS) par Pôle

![Durée Moyenne de Séjour (DMS) par Service](diag_dms_services.png)

![Détail Médico-Économique par Service](diag_dms_tableau.png)

* **Pôles lourds (Réanimation & Neurologie) :**
  * La **Réanimation** présente la DMS la plus élevée (**9.05 jours**, médiane à 8.21j). Cette durée reflète la gravité des défaillances d'organes nécessitant un sevrage ventilatoire ou hémodynamique progressif.
  * La **Neurologie** (**7.06 jours**, 1 077 séjours clôturés) concentre une patientèle âgée victime d'AVC ischémiques (`I63`) nécessitant un temps d'évaluation neurologique et d'orientation post-aiguë (SSR).
* **Pôles d'activité à fort turnover :**
  * La **Cardiologie** est le plus gros pôle en volume (**1 459 séjours**, DMS de **5.31 jours**), montrant une prise en charge protocolisée des syndromes coronariens et de l'insuffisance cardiaque.
  * La **Chirurgie** (**4.39 jours**) et la **Pédiatrie** (**3.19 jours**) affichent des DMS courtes, démontrant un virage ambulatoire et une réhabilitation précoce efficaces.
  * Les **Urgences / UHCD** (**2.15 jours**) confirment leur rôle d'unité d'observation courte durée (48h max) avant transfert ou retour à domicile.

---

### 🚑 Analyse des Flux et de la Tension aux Urgences

![Flux Quotidien et Devenir des Passages aux Urgences](diag_flux_urgences.png)

![Taux d'Hospitalisation post-Urgences (%)](diag_taux_hospitalisation.png)

Sur les **1 423 passages** répertoriés au mois d'août :
* **Sorties Domicile (45.9 %, 653 patients) :** Urgences ressenties ou traumatologie légère traitées sans nécessiter d'admission hospitalière.
* **Hospitalisations en Aval (31.75 %, 418 patients) :**
  * **228 mutations internes** vers les services spécialisés du CHU (Cardio, Réa, Pneumo).
  * **190 transferts externes** vers d'autres établissements du GHT (Groupement Hospitalier de Territoire) pour réguler la charge capacitaire.
* **Décès aux Urgences (14.5 %, 206 patients) :** Taux traduisant l'accueil de situations d'urgence vitale dépassée (arrêts cardio-respiratoires extra-hospitaliers acheminés par le SAMU).

---

### 🩺 Télésurveillance & Alertes des Constantes Vitales

![Volume de Monitoring & Mesures Normales vs Alertes](diag_monitoring_alertes.png)

![Décomposition des Alertes Vitales par Typologie](diag_alertes_typologie.png)

Sur **40 920 mesures** analysées en temps réel par les capteurs de chevet :
* **Volume d'alertes :** **3 052 alertes** détectées (soit **7.46 %** des mesures).
* **Décomposition sémiologique des alertes :**
  1. **Hypoxie ($SpO_2 < 92\%$) :** **1 127 alertes (36.9 %)**. Première cause d'alerte, très corrélée au volume de patients BPCO (`J44`) et pneumopathies (`J18`).
  2. **Anomalies Thermiques ($T < 36^\circ\text{C}$ ou $\ge 38.5^\circ\text{C}$) :** **1 082 alertes (35.5 %)**. Vigilance infectieuse (sepsis, décompensation fébrile).
  3. **Fréquence Cardiaque ($FC < 50$ ou $> 120\text{ bpm}$) :** **843 alertes (27.6 %)**. Troubles du rythme, tachycardies de stress ou bradycardies iatrogènes.

---

## 2️⃣ Axe Recherche Clinique & Épidémiologie (RGPD)

### 🧬 Prévalence des Pathologies (Classification CIM-10)

![Prévalence Globale par Pathologie (CIM-10)](diag_prevalence_cim10.png)

![Rôle des Pathologies : Diagnostic Principal vs Associé](diag_roles_pathologies.png)

#### 💡 Constats Épidémiologiques :
1. **Les comorbidités chroniques omniprésentes :**
   * L'infection urinaire (`N39`), le diabète de type 2 (`E11`) et l'insuffisance cardiaque (`I50`) touchent chacun **plus d'un tiers de la patientèle hospitalisée** (~2 200 patients).
   * Ces pathologies interviennent très majoritairement en **diagnostic associé** (~65% des cas), illustrant le profil polypathologique fréquent en milieu hospitalier.
2. **Les épisodes aigus / motifs d'admission directe :**
   * L'appendicite (`K35`), l'infarctus (`I21`), l'AVC (`I63`) et les pneumopathies (`J18`) sont codés **à 100% comme diagnostics principaux**. Ils constituent le déclencheur direct du séjour.

---

### 👥 Caractérisation Démographique & Pyramide des Âges

![Distribution Démographique Globale (Âge & Sexe)](diag_demographie_age_sexe.png)

![Cohortes Cliniques Détaillées (Règle RGPD Effectifs ≥ 5)](diag_cohortes_rgpd.png)

| Tranche d'Âge | Femmes | Hommes | Total Patients | % Cohorte Globale |
| :---: | :---: | :---: | :---: | :---: |
| **0 – 9 ans** | 261 | 297 | 558 | 4.4 % |
| **10 – 19 ans** | 309 | 329 | 638 | 5.0 % |
| **20 – 29 ans** | 412 | 460 | 872 | 6.8 % |
| **30 – 39 ans** | 410 | 433 | 843 | 6.6 % |
| **40 – 49 ans** | 557 | 681 | 1 238 | 9.7 % |
| **50 – 59 ans** | 696 | 686 | 1 382 | 10.8 % |
| **60 – 69 ans** | **1 140** | **1 248** | **2 388** | **18.7 % (Pic)** |
| **70 – 79 ans** | **959** | **996** | **1 955** | **15.3 %** |
| **80 – 89 ans** | 728 | 669 | 1 397 | 10.9 % |
| **90 – 99 ans** | 450 | 422 | 872 | 6.8 % |

* **Concentration gériatrique :** Plus de **51 % des patients** ont plus de 60 ans, avec un sommet sur la tranche 60-69 ans (2 388 patients).
* **Ratio Sexes :**
  * Surmortalité/surmorbidité masculine entre 40 et 79 ans (notamment facteurs de risque cardiovasculaire et tabagisme).
  * Inversion du ratio au-delà de 80 ans en faveur des femmes (espérance de vie féminine plus élevée).

---

### 🛡️ Conformité RGPD & Cloisonnement des Données

1. **Pseudonymisation irréversible à l'entrée :**
   * Hachage cryptographique déterministe salé (`HMAC-SHA256`).
   * Les identifiants directs (`nom`, `prenom`, `nir`) ont été purgés dès la zone de staging Lake.
   * La date de naissance a été tronquée en année (`birth_year`).
2. **Règle des petits effectifs ($\ge 5$) :**
   * Toutes les cohortes de recherche clinique croisant pathologie, tranche d'âge et sexe garantissent un seuil minimal de 5 patients uniques.
   * Aucune cellule unitaire ne permet d'isoler ou de ré-identifier un individu.
3. **Cloisonnement applicatif Metabase :**
   * Les profils **Direction** n'ont accès qu'aux indicateurs agrégés de gestion hospitalière.
   * Les profils **Chercheurs** n'ont accès qu'aux cohortes épidémiologiques pseudonymisées, sans lien possible vers les parcours nominatifs.

---

## 3️⃣ Recommandations Opérationnelles pour l'Établissement

1. **Gestion des lits d'aval aux Urgences :** Avec un taux d'hospitalisation de **31.75 %**, l'optimisation des sorties en fin de matinée dans les services de médecine (Cardio, Pneumo) est la clé pour désengorger les urgences entre 14h et 18h.
2. **Prévention des Réadmissions 30j (10.54 %) :** Mettre en place un protocole de suivi post-hospitalisation renforcé (téléconsultation à J+7) ciblé en priorité sur les patients âgés insuffisants cardiaques (`I50`) et BPCO (`J44`).
3. **Optimisation des Alertes Constantes (7.46 %) :** Ajuster les plages de sensibilité des oxymètres de chevet chez les patients BPCO connus (pour lesquels une $SpO_2$ entre 88% et 92% est souvent tolérée physiologiquement) afin de réduire la fatigue d'alarme des équipes soignantes.
