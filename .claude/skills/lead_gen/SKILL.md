---
name: lead_gen
description: "Pipeline de génération de leads B2B : scrape Google Maps via Serper, qualifie les sites web, enrichit les contacts via waterfall Hunter.io/OSINT, et synchronise vers HubSpot CRM. USE WHEN: l'utilisateur demande des leads, du scraping, de l'enrichissement, des prospects, une sync HubSpot, des entreprises Google Maps, une recherche par industrie ou de la découverte de contacts."
---

# Skill: Lead_gen — Lead Generation B2B

## Inputs requis
- `industry` (ex: "Cuisinistes")
- `location` (ex: "Bordeaux")
- `max_leads` (ex: 50)

Si l'utilisateur ne fournit pas tous les inputs, les lui demander avant de commencer.

---

## Pipeline séquentiel

### Etape 1 : Scraping Google Maps
- **Script :** `execution/scrape_google_maps.py`
- **Input :** `--industry "{industry}" --location "{location}" --max_leads {max_leads}`
- **Output :** `.tmp/scraped_leads.json`

### Etape 2 : Qualification des sites
- **Script :** `execution/qualify_site.py`
- **Input :** `.tmp/scraped_leads.json`
- **Output :** `.tmp/qualified_leads.json`
- **Action :** Vérifie site actif, cherche emails génériques

### Etape 3 : Enrichissement (Waterfall Strategy)
- **Script :** `execution/enrich.py`
- **Input :** `.tmp/qualified_leads.json`
- **Stratégie cascade (coût optimisé) :**
  1. **OSINT Serper** (gratuit) — Recherche nom décideur + LinkedIn
  2. **Hunter.io pattern** (freemium) — Format email de l'entreprise
  3. **Reconstruction email** (gratuit) — Combine nom + pattern + domaine
- **Indicateurs de source :** `reconstructed` | `hunter_generic` | `not_found`

### Etape 4 : Sync HubSpot (mode par defaut)
- **Script :** `execution/sync_hubspot.py`
- **Logique Upsert :**
  1. Chercher contact par email (anti-duplication)
  2. Si existe → Mettre à jour champs manquants
  3. Si n'existe pas → Créer contact + entreprise associée
- **Log :** `.tmp/sync_log_YYYYMMDD_HHMMSS.json`
- **Jamais de doublons**

### Etape 5 : Backup Excel (automatique apres sync)
- **Script :** `execution/save_to_excel.py --backup-mode`
- **Output :** `Generate_leads.xlsx` avec Statut_Sync=Synced
- **IMPORTANT :** Demander à l'utilisateur de fermer le fichier Excel avant exécution
- Desactivable avec `--no-backup`

### Mode alternatif : Excel d'abord (ancien workflow)
- Ajouter `--use-excel` au pipeline pour utiliser l'ancien flow : Excel → HubSpot

---

## Commandes utiles

```bash
# Pipeline complet (direct HubSpot + backup Excel, defaut)
python execution/run_pipeline.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50

# Sans backup Excel
python execution/run_pipeline.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50 --no-backup

# Ancien workflow (Excel d'abord)
python execution/run_pipeline.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50 --use-excel

# Scripts individuels
python execution/scrape_google_maps.py --industry "Restaurants" --location "Paris"
python execution/enrich.py --input .tmp/qualified_leads.json
python execution/sync_hubspot.py --input .tmp/enriched_leads.json --write-log
python execution/sync_from_hubspot.py
```

---

## Garde-fous
- Ne jamais scraper sans input `industry` + `location`
- Ne jamais push vers HubSpot sans vérification Upsert
- Si un script échoue, lire l'erreur, corriger, réessayer (self-anneal)
- Les fichiers `.tmp/` sont temporaires — les supprimer après usage
