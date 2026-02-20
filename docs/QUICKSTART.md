# Quick Start

## Setup

```bash
pip install -r requirements.txt
cp .env.template .env   # Ajouter vos API keys
python execution/create_excel_template.py   # Crée Generate_leads.xlsx
```

### API Keys requises (.env)

| Service | Usage | Lien |
|---------|-------|------|
| Serper | Google Maps scraping | https://serper.dev |
| Firecrawl | Website qualification | https://firecrawl.dev |
| Hunter.io | Email pattern (optionnel) | https://hunter.io |
| HubSpot | CRM sync | https://app.hubspot.com |

---

## Mode A : Lead Generation

```bash
# Pipeline complet (50 leads)
python execution/run_pipeline.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50

# Ou étape par étape
python execution/scrape_google_maps.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50
python execution/qualify_site.py --input .tmp/google_maps_results.json
python execution/enrich.py --input .tmp/qualified_leads.json
python execution/save_to_excel.py --input .tmp/enriched_leads.json
python execution/sync_hubspot.py --input .tmp/enriched_leads.json
```

## Mode B : PDF

```bash
python execution/generate_pdf.py --company "La Belle Cuisine"
# Output: output/La_Belle_Cuisine_proposal.pdf
```

## Mode C : Webhook Server

```bash
uvicorn execution.webhook_server:app --host 0.0.0.0 --port 5000
```

---

## Tips

- Tester d'abord avec `--max_leads 5`
- Fermer Excel avant `save_to_excel.py`
- Limites free tier : Serper 2500/mois, Firecrawl 500/mois, Hunter 50/mois
- Backup `Generate_leads.xlsx` régulièrement

## Troubleshooting

| Problème | Solution |
|----------|----------|
| Module not found | `pip install -r requirements.txt` |
| API key not found | Vérifier `.env` (pas d'espaces) |
| Permission denied Excel | Fermer le fichier |
| Rate limit | Attendre 60s, auto-retry intégré |
