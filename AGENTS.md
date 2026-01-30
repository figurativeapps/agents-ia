# Agent Instructions (Global Lead Gen, PDF Maker & Request Handler)

> This file is mirrored across CLAUDE.md and AGENTS.md so the same instructions load in any AI environment.

You operate within a 3-layer architecture (DOE Framework) to manage three distinct workflows: **Lead Generation**, **PDF Creation**, and **Request Handling**.

---

## Quick Reference: Mode Selection

| User Intent | Mode | Directive to Load |
|-------------|------|-------------------|
| Find leads, scrape, enrich contacts | **A (Hunter)** | `workflow_global_lead_gen.md` |
| Generate PDF proposal | **B (Maker)** | `workflow_pdf_maker.md` |
| Process support/modeling request | **C (Handler)** | `workflow_request_handler.md` |

---

## Script Registry

### Mode A: Lead Generation (Hunter)

| Script | Function | Input → Output |
|--------|----------|----------------|
| `scrape_google_maps.py` | Search businesses via Serper | Query → JSON results |
| `2_qualify_site.py` | Validate website quality | URL → Score |
| `5_enrich.py` | Get contact info (Apollo/Hunter) | Company → Email/Phone |
| `save_to_excel.py` | Save leads to Excel | Data → `Generate_leads.xlsx` |
| `sync_hubspot.py` | Push leads to HubSpot | Excel → HubSpot CRM |
| `sync_from_hubspot.py` | Pull updates from HubSpot | HubSpot → Excel |

**Directives:** `workflow_global_lead_gen.md`, `waterfall_strategy.md`, `email_templates.md`

### Mode B: PDF Maker

| Script | Function | Input → Output |
|--------|----------|----------------|
| `8_generate_pdf.py` | Generate PDF from template | Data + Template → PDF |
| `create_excel_template.py` | Create Excel input template | → Excel template |

**Directives:** `workflow_pdf_maker.md`

### Mode C: Support Handler

| Script | Function | Input → Output |
|--------|----------|----------------|
| `webhook_server.py` | Receive requests (FastAPI) | HTTP → Redis queue |
| `classify_request.py` | Classify SUPPORT/MODELISATION | Text → Type + Confidence |
| `upload_files.py` | Upload files to R2 | Files → Public URLs |
| `hubspot_ticket.py` | Manage contacts, tickets, notes | Data → HubSpot objects |
| `clickup_subtask.py` | Create modeling subtask | Data → ClickUp task |
| `send_notification.py` | Email admin notification | Data → SMTP |
| `test_request_handler.py` | Test full workflow | Payload → Results |

**Directives:** `workflow_request_handler.md`, `classify_request.md`, `create_hubspot_ticket.md`, `create_clickup_subtask.md`, `notify_admin.md`

**Documentation:** `docs/PROCESSUS_SUPPORT.md`

### Shared / Utilities

| Script | Function | Used by |
|--------|----------|---------|
| `diagnose_hubspot_properties.py` | Debug HubSpot fields | All modes |

---

## The 3-Layer Architecture

**Layer 1: Directive (What to do)**
- Lives in `directives/`. These are your SOPs.
- Load the appropriate workflow file based on user intent.

**Layer 2: Orchestration (Decision making)**
- This is you. Your job is intelligent routing based on User Intent.
- You rely on deterministic scripts. You do not scrape or generate PDFs manually.

**Layer 3: Execution (Doing the work)**
- Deterministic Python scripts in `execution/`.
- **Source of Truth:** The local file `Generate_leads.xlsx` is the master database.
- **CRM:** HubSpot is the destination. Never create duplicates.
- **Keys:** stored in `.env`.

## Operating Principles

1. **Check Script Registry first** - Before writing code, check if a script already exists above.
2. **Excel Locking** - Warn user to close `Generate_leads.xlsx` before running `save_to_excel.py`.
3. **HubSpot Safety** - Always Search-Before-Create (Upsert logic to prevent duplicates).
4. **Self-anneal** - If script fails, read error, fix script, retry, update directive if needed.

---

## Directory Structure

```
agents_ia/
├── directives/     # SOPs (9 files) - What to do
├── execution/      # Scripts (16 files) - How to do it
├── docs/           # Documentation
├── templates/      # Jinja2 templates for PDF
├── output/         # Generated PDFs
├── .tmp/           # Temp files (delete after use)
├── .env            # API Keys
└── Generate_leads.xlsx  # Master database
```

---

## Workflow Execution Pattern

```
1. Identify Intent → Select Mode (A/B/C)
2. Load Directive → Read workflow_*.md
3. Execute Scripts → Run in sequence from registry
4. Finalize → Sync to Excel/HubSpot
```

Be pragmatic. Be reliable. Self-anneal.
