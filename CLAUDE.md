# Figurative — Lead Gen, PDF Maker & Request Handler

Architecture DOE (Directive-Orchestration-Execution) à 3 couches avec 3 workflows distincts.

## Routing

| Intent utilisateur | Skill | Subagent |
|-------------------|-------|----------|
| Leads, scraping, enrichissement, prospects | `/lead_gen` | `lead_gen` |
| PDF, proposition commerciale, plaquette | `/PDF_gen` | `PDF_gen` |
| Tickets, support, modélisation 3D, webhook | `/support` | `support` |

## Script Registry

### Mode A: Lead Generation (Lead_gen)

| Script | Function | Input → Output |
|--------|----------|----------------|
| `scrape_google_maps.py` | Search businesses via Serper | Query → JSON results |
| `qualify_site.py` | Deep crawl + LLM classification + email extraction | URL → Type/Email/TechStack |
| `enrich.py` | OSINT via Serper (nom décideur, titre, LinkedIn) | Company → Name/Title/LinkedIn |
| `score_lead.py` | LLM-based ICP scoring (0-100, Hot/Warm/Cold) | Lead → Score/Priority |
| `save_to_excel.py` | Save leads to Excel (backup or `--use-excel`) | Data → `Generate_leads.xlsx` |
| `sync_hubspot.py` | Push leads to HubSpot (direct, default) | JSON → HubSpot CRM + sync log |
| `sync_from_hubspot.py` | Pull updates from HubSpot (Excel mode only) | HubSpot → Excel |
| `watch_lead_status.py` | Two-phase prospection watcher (see below) | HubSpot ↔ ClickUp ↔ R2 |
| `run_pipeline.py` | Master pipeline orchestrator (Mode A) | Args → Full pipeline |

### Mode B: PDF Generation (PDF_gen)

| Script | Function | Input → Output |
|--------|----------|----------------|
| `generate_pdf.py` | Generate PDF from HTML template | Data + Template → PDF |
| `overlay_pdf.py` | Overlay image + QR code on Canva PDF | Image + URL → PDF |
| `create_excel_template.py` | Create Excel input template | → Excel template |

### Mode C: Support (v3.0)

| Script | Function | Input → Output |
|--------|----------|----------------|
| `webhook_server.py` | Receive requests (FastAPI v3.0) | HTTP → Ticket + Validation |
| `classify_request.py` | Classify SUPPORT/MODELISATION | Text → Type + Confidence |
| `analyze_request.py` | Check completeness + estimate credits | Request → Credits + Missing info |
| `upload_files.py` | Upload files to R2 | Files → Public URLs |
| `hubspot_ticket.py` | Manage contacts, tickets, notes | Data → HubSpot objects |
| `hubspot_conversation.py` | Read/send emails via HubSpot | Email ↔ HubSpot |
| `clickup_subtask.py` | Create modeling subtask | Data → ClickUp task |
| `validation_workflow.py` | Poll pending tickets, process responses | Tickets → Validation |
| `send_notification.py` | Email admin notification | Data → SMTP |
| `diagnose_hubspot_properties.py` | Debug HubSpot fields | All modes |

## Directory Structure

```
agents_ia/
├── CLAUDE.md               # This file
├── .claude/skills/          # Skills with YAML frontmatter (lead_gen/, PDF_gen/, support/)
├── .claude/agents/          # Subagents (lead_gen, PDF_gen, support)
├── execution/               # Deterministic Python scripts
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

## Operating Principles

1. **Check Script Registry first** — Before writing code, check if a script already exists above
2. **Excel Locking** — Warn user to close `Generate_leads.xlsx` before `save_to_excel.py`
3. **HubSpot Safety** — Always Search-Before-Create (upsert by email, no duplicates)
4. **Self-anneal** — If script fails, read error, fix script, retry, update skill if needed

## Workflow

```
1. Identify Intent → Select Skill (/lead_gen, /PDF_gen, /support)
2. Load Skill → Execute scripts from registry in sequence
3. Finalize → Sync to HubSpot (primary) + Excel backup
```
