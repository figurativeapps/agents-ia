---
name: lead_gen
description: "Pipeline de g\u00e9n\u00e9ration de leads B2B : scrape Google Maps via Serper, qualifie les sites web via LLM, enrichit les contacts via waterfall \u00e9tendu (OSINT/Dropcontact/Hunter/Apollo), v\u00e9rifie les emails, score les leads par LLM, et synchronise vers HubSpot CRM. USE WHEN: l'utilisateur demande des leads, du scraping, de l'enrichissement, des prospects, une sync HubSpot, des entreprises Google Maps, une recherche par industrie ou de la d\u00e9couverte de contacts."
---

# Skill: Lead_gen — Lead Generation B2B

## Inputs requis
- `industry` (ex: "Cuisinistes")
- `location` (ex: "Bordeaux")
- `max_leads` (ex: 50)

Si l'utilisateur ne fournit pas tous les inputs, les lui demander avant de commencer.

---

## Pipeline s\u00e9quentiel

### Etape 1 : Scraping Google Maps
- **Script :** `execution/scrape_google_maps.py`
- **Input :** `--industry "{industry}" --location "{location}" --max_leads {max_leads}`
- **Output :** `.tmp/google_maps_results.json`

### Etape 2 : Qualification des sites (LLM + Firecrawl)
- **Script :** `execution/qualify_site.py`
- **Input :** `.tmp/google_maps_results.json --industry "{industry}"`
- **Output :** `.tmp/qualified_leads.json`
- **Action :** Classification LLM (Manufacturer/Service/Unknown), d\u00e9tection e-commerce, d\u00e9tection tech stack (Shopify, WooCommerce, etc.), extraction emails g\u00e9n\u00e9riques
- **Filtre :** Garde uniquement Business_Type=Manufacturer (e-commerce non requis)
- **Fallback :** Si ANTHROPIC_API_KEY absent, utilise la classification par keywords

### Etape 3 : Enrichissement (Waterfall \u00c9tendu)
- **Script :** `execution/enrich.py`
- **Input :** `.tmp/qualified_leads.json`
- **Strat\u00e9gie cascade (du moins cher au plus cher, arr\u00eat d\u00e8s qu'un email est trouv\u00e9) :**
  1. **OSINT Serper** (gratuit) — Recherche nom d\u00e9cideur + LinkedIn
  2. **Dropcontact** (GDPR) — Email depuis nom + entreprise
  3. **Hunter.io** (pattern) — Format email de l'entreprise
  4. **Apollo.io** (base de donn\u00e9es) — Lookup direct contact
  5. **Reconstruction email** (gratuit) — Combine nom + pattern + domaine
- **Indicateurs de source :** `dropcontact` | `hunter_generic` | `reconstructed` | `apollo` | `not_found`
- **Cl\u00e9s optionnelles :** DROPCONTACT_API_KEY, APOLLO_API_KEY (le pipeline fonctionne avec seulement SERPER + HUNTER)

### Etape 3b : V\u00e9rification Email
- **Script :** `execution/verify_email.py`
- **Input :** `.tmp/enriched_leads.json`
- **Action :** V\u00e9rifie chaque email via MillionVerifier API, supprime les emails invalides
- **Cl\u00e9 optionnelle :** MILLIONVERIFIER_API_KEY (si absent, \u00e9tape saut\u00e9e)

### Etape 3c : Scoring LLM
- **Script :** `execution/score_lead.py`
- **Input :** `.tmp/enriched_leads.json --industry "{industry}"`
- **Action :** Score chaque lead 0-100 via Claude Haiku, classe en Hot/Warm/Cold
- **Crit\u00e8res :** Fit ICP (40%) + Compl\u00e9tude donn\u00e9es (30%) + Qualit\u00e9 site (20%) + Confiance (10%)
- **Fallback :** Si ANTHROPIC_API_KEY absent, scoring d\u00e9terministe

### Etape 4 : Sync HubSpot (mode par defaut)
- **Script :** `execution/sync_hubspot.py`
- **Logique Upsert :**
  1. Chercher contact par email (anti-duplication)
  2. Si existe -> Mettre \u00e0 jour champs manquants
  3. Si n'existe pas -> Cr\u00e9er contact + entreprise associ\u00e9e
- **Champs suppl\u00e9mentaires :** lead_score_ai, lead_priority, tech_stack, email_source
- **Log :** `.tmp/sync_log_YYYYMMDD_HHMMSS.json`
- **Jamais de doublons**

### Etape 5 : Backup Excel (automatique apres sync)
- **Script :** `execution/save_to_excel.py --backup-mode`
- **Output :** `Generate_leads.xlsx` avec Statut_Sync=Synced
- **IMPORTANT :** Demander \u00e0 l'utilisateur de fermer le fichier Excel avant ex\u00e9cution
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
python execution/verify_email.py --input .tmp/enriched_leads.json
python execution/score_lead.py --input .tmp/enriched_leads.json --industry "Restaurants"
python execution/sync_hubspot.py --input .tmp/enriched_leads.json --write-log
```

---

## Cl\u00e9s API requises / optionnelles

| Cl\u00e9 | Requis | Usage |
|-----|--------|-------|
| `SERPER_API_KEY` | Oui | Scraping Google Maps + OSINT LinkedIn |
| `FIRECRAWL_API_KEY` | Oui | Qualification sites web |
| `HUNTER_API_KEY` | Recommand\u00e9 | Pattern email |
| `HUBSPOT_API_KEY` | Oui | Sync CRM |
| `ANTHROPIC_API_KEY` | Recommand\u00e9 | Qualification LLM + Scoring LLM |
| `DROPCONTACT_API_KEY` | Optionnel | Enrichissement email GDPR |
| `APOLLO_API_KEY` | Optionnel | Base de donn\u00e9es contacts |
| `MILLIONVERIFIER_API_KEY` | Optionnel | V\u00e9rification email |

---

## Garde-fous
- Ne jamais scraper sans input `industry` + `location`
- Ne jamais push vers HubSpot sans v\u00e9rification Upsert
- Le pipeline fonctionne avec les cl\u00e9s minimales (Serper + Firecrawl + HubSpot)
- Chaque \u00e9tape optionnelle a un fallback si la cl\u00e9 API est absente
- Si un script \u00e9choue, lire l'erreur, corriger, r\u00e9essayer (self-anneal)
- Les fichiers `.tmp/` sont temporaires — les supprimer apr\u00e8s usage
