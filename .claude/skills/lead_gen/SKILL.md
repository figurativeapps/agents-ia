---
name: lead_gen
description: "Pipeline de génération de leads B2B : scrape Google Maps via Serper, qualifie les sites web via LLM + deep crawl (email de contact), enrichit les contacts via OSINT (nom/titre/LinkedIn), score les leads par LLM, et synchronise vers HubSpot CRM. USE WHEN: l'utilisateur demande des leads, du scraping, de l'enrichissement, des prospects, une sync HubSpot, des entreprises Google Maps, une recherche par industrie ou de la découverte de contacts."
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
- **Output :** `.tmp/google_maps_results.json`

### Etape 2 : Qualification des sites (LLM + Deep Crawl)
- **Script :** `execution/qualify_site.py`
- **Input :** `.tmp/google_maps_results.json --industry "{industry}"`
- **Output :** `.tmp/qualified_leads.json`
- **Action :** Deep crawl (homepage + pages contact/mentions légales), extraction email de contact du site, classification LLM (Manufacturer/Service/Unknown), détection e-commerce, détection tech stack
- **Email :** L'email de contact trouvé sur le site est stocké dans `Email_Generique` — c'est l'email principal utilisé pour HubSpot
- **Filtre :** Garde uniquement Business_Type=Manufacturer (e-commerce non requis)
- **Fallback :** Si ANTHROPIC_API_KEY absent, utilise la classification par keywords

### Etape 3 : Enrichissement (OSINT)
- **Script :** `execution/enrich.py`
- **Input :** `.tmp/qualified_leads.json`
- **Action :** Recherche OSINT via Serper pour trouver le nom du décideur, son poste et son profil LinkedIn
- **Note :** L'email de contact provient du site web (étape 2). L'enrichissement ne cherche PAS d'email.

### Etape 3b : Scoring LLM
- **Script :** `execution/score_lead.py`
- **Input :** `.tmp/enriched_leads.json --industry "{industry}"`
- **Action :** Score chaque lead 0-100 via Claude Haiku, classe en Hot/Warm/Cold
- **Critères :** Fit ICP (40%) + Complétude données (30%) + Qualité site (20%) + Confiance (10%)
- **Fallback :** Si ANTHROPIC_API_KEY absent, scoring déterministe

### Etape 4 : Sync HubSpot (mode par defaut)
- **Script :** `execution/sync_hubspot.py`
- **Logique Upsert :**
  1. Chercher contact par email (anti-duplication)
  2. Si existe -> Mettre à jour champs manquants
  3. Si n'existe pas -> Créer contact + entreprise associée
- **Email synced :** `Email_Generique` (email de contact du site web)
- **Log :** `.tmp/sync_log_YYYYMMDD_HHMMSS.json`
- **Jamais de doublons**

### Etape 5 : Backup Excel (automatique apres sync)
- **Script :** `execution/save_to_excel.py --backup-mode`
- **Output :** `Generate_leads.xlsx` avec Statut_Sync=Synced
- **Email vide :** Affiché comme "Non renseigné" dans l'Excel
- **IMPORTANT :** Demander à l'utilisateur de fermer le fichier Excel avant exécution
- Desactivable avec `--no-backup`

### Mode alternatif : Excel d'abord (ancien workflow)
- Ajouter `--use-excel` au pipeline pour utiliser l'ancien flow : Excel -> HubSpot

---

## Commandes utiles

```bash
# Pipeline complet (defaut)
python execution/run_pipeline.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50

# Sans backup Excel
python execution/run_pipeline.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50 --no-backup

# Scripts individuels
python execution/scrape_google_maps.py --industry "Restaurants" --location "Paris"
python execution/qualify_site.py --input .tmp/google_maps_results.json --industry "Restaurants"
python execution/enrich.py --input .tmp/qualified_leads.json
python execution/score_lead.py --input .tmp/enriched_leads.json --industry "Restaurants"
python execution/sync_hubspot.py --input .tmp/enriched_leads.json --write-log
```

---

## Clés API requises / optionnelles

| Clé | Requis | Usage |
|-----|--------|-------|
| `SERPER_API_KEY` | Oui | Scraping Google Maps + OSINT LinkedIn |
| `FIRECRAWL_API_KEY` | Oui | Deep crawl sites web (qualification + extraction email) |
| `HUBSPOT_API_KEY` | Oui | Sync CRM |
| `ANTHROPIC_API_KEY` | Recommandé | Qualification LLM + Scoring LLM |

---

## Garde-fous
- Ne jamais scraper sans input `industry` + `location`
- Ne jamais push vers HubSpot sans vérification Upsert
- Le pipeline fonctionne avec les clés minimales (Serper + Firecrawl + HubSpot)
- Chaque étape optionnelle a un fallback si la clé API est absente
- Si un script échoue, lire l'erreur, corriger, réessayer (self-anneal)
- Les fichiers `.tmp/` sont temporaires — les supprimer après usage
