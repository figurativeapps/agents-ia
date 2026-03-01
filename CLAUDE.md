# Figurative — Lead Gen, PDF Maker & Request Handler

## Garde-fous critiques

1. **HubSpot Safety** — Always Search-Before-Create (upsert by email, no duplicates)
2. **Excel Locking** — Warn user to close `Generate_leads.xlsx` before `save_to_excel.py`
3. **Self-anneal** — If script fails, read error, fix script, retry, update skill if needed
4. **Check existing scripts first** — Before writing code, check if a script already exists in `execution/`

## Skills disponibles

| Skill | Description | Déclenché quand |
|-------|-------------|-----------------|
| `lead_gen` | Pipeline de génération de leads B2B (scrape → qualify → enrich → score → sync) | Leads, scraping, enrichissement, prospects, sync HubSpot, Google Maps |
| `PDF_gen` | Génération de PDF commerciaux (WeasyPrint/Jinja2 + overlay Canva) | PDF, proposition commerciale, plaquette, devis |
| `support` | Traitement des demandes support & modélisation 3D (webhook → ticket → validation) | Tickets, support, modélisation 3D, webhook, validation crédits |

Chaque skill a sa documentation complète dans `.claude/skills/<nom>/SKILL.md` avec le pipeline séquentiel, les scripts à exécuter, et les garde-fous spécifiques.

## Workflow

```
1. Identifier l'intent utilisateur → Charger le skill correspondant
2. Lire le SKILL.md → Suivre le checklist étape par étape
3. Exécuter les scripts de execution/ → Vérifier les résultats
4. Si erreur → Corriger, réessayer, mettre à jour le skill si besoin
```

## Directory Structure

```
agents_ia/
├── CLAUDE.md               # This file (project brain)
├── .claude/skills/          # Skills with YAML frontmatter (lead_gen/, PDF_gen/, support/)
├── execution/               # Deterministic Python scripts (shared across skills)
├── tests/                   # Test scripts
├── docs/                    # Documentation
├── templates/               # Jinja2 templates for PDF
├── output/                  # Generated PDFs
├── .tmp/                    # Temp files (delete after use)
└── .env                     # API Keys
```

## Prospection Watcher (`watch_lead_status.py`)

Two-phase polling script running on VPS:

- **Phase 1 (NEW→OPEN)**: User writes a HubSpot note on the contact with description, client site URL, and image(s), then sets `hs_lead_status=OPEN`. Script parses the note (extracts text, URL, images), creates ClickUp subtask under Prospection (86c8cryhk) with prospect info comment + custom fields "lien ra" and "Titre snapshot" (both empty).
- **Phase 2 (COMPLETE→IN_PROGRESS)**: Admin fills "lien ra" with AR link, "Titre snapshot" with overlay title, attaches snapshot.png + qrcode.png, sets subtask to COMPLETE. Script generates PDF (overlay_pdf with "Titre snapshot" as title), uploads to R2, creates HubSpot note, sets `hs_lead_status=IN_PROGRESS`.
