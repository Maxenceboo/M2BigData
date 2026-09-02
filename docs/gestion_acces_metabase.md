# 🔐 Sécurité & Cloisonnement des Accès Metabase

> **Entrepôt de Données de Santé (EDS) — CHU**  
> Ce document décrit les deux niveaux de sécurité et de gestion des accès mis en œuvre pour Metabase.

---

## 1️⃣ Niveau 1 : Le Compte Technique Base de Données (`metabase_user`)

Metabase ne se connecte **pas** à ClickHouse avec le compte administrateur `default`. Il dispose d'un **compte technique de service dédié** nommé `metabase_user` avec un mot de passe sécurisé.

### Principe du Moindre Privilège (Least Privilege)
* **Droits accordés :** `SELECT` **strictement et uniquement sur la couche `gold.*`** (et les métadonnées système) :
  ```sql
  CREATE USER IF NOT EXISTS metabase_user IDENTIFIED WITH sha256_password BY 'MetabasePassword123!';
  GRANT SELECT ON gold.* TO metabase_user;
  GRANT SELECT ON system.tables TO metabase_user;
  GRANT SELECT ON system.columns TO metabase_user;
  GRANT SELECT ON system.databases TO metabase_user;
  ```
* **Sécurité garantie :** 
  * Aucun droit sur `silver.*` ni sur `bronze.*` (accès direct totalement refusé).
  * Les vues Gold utilisent `SQL SECURITY DEFINER` : ClickHouse résout les jointures sous-jacentes en toute sécurité sans ouvrir la couche Silver à l'utilisateur BI.
  * Aucun droit d'écriture (`INSERT`, `UPDATE`, `ALTER`).
  * Aucun droit de destruction (`DROP`, `TRUNCATE`).
  * Le script dédié [`src/setup_users.py`](file:///c:/Users/maxen/Documents/dev/cours/data/src/setup_users.py) permet de provisionner et vérifier ces droits de manière autonome.

---

## 2️⃣ Niveau 2 : Les Comptes Utilisateurs Applicatifs dans Metabase

Au niveau de l'interface Metabase, les soignants, directeurs et chercheurs ne partagent **aucun compte générique**. Chaque profil dispose de son propre compte et appartient à un groupe aux permissions étanches :

| Rôle | Utilisateur Metabase | Mot de passe | Groupe | Collection & Dashboard Accessible |
| :--- | :--- | :--- | :--- | :--- |
| **Direction / Cadres** | `directeur@eds-chu.fr` | `DirecteurPassword123!` | `Direction & Pilotage` | 🏥 **Tableau de Bord - Pilotage Hospitalier** *(Exclusif)* |
| **Praticiens / Chercheurs** | `chercheur@eds-chu.fr` | `ChercheurPassword123!` | `Recherche Clinique` | 🔬 **Tableau de Bord - Recherche Clinique (RGPD)** *(Exclusif)* |
| **Super Administrateur** | `admin@eds-chu.fr` | `AdminPassword123!` | `Administrators` | Configuration complète & gestion des droits |

### Règle de Cloisonnement Strict (RGPD)
* Le groupe `Direction & Pilotage` n'a **aucun accès** à la collection Recherche Clinique.
* Le groupe `Recherche Clinique` n'a **aucun accès** à la collection Pilotage Hospitalier.
* Le groupe par défaut `All Users` est bloqué en lecture (`none`) sur les collections métier pour empêcher toute fuite de données par défaut.
