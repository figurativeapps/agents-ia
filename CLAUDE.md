# Agent Instructions (Global Lead Gen, PDF Maker & Request Handler)

You operate within a 3-layer architecture (DOE Framework) to manage three distinct workflows: **Lead Generation**, **PDF Creation**, and **Request Handling**.

---

## Quick Reference: Mode Selection

| User Intent | Mode | Skill to Use |
|-------------|------|--------------|
| Find leads, scrape, enrich contacts | **A (Hunter)** | `.claude/skills/hunter.md` |
| Generate PDF proposal | **B (Maker)** | `.claude/skills/maker.md` |
| Process support/modeling request | **C (Handler)** | `.claude/skills/handler.md` |

---

## Script Registry

### Mode A: Lead Generation (Hunter)

| Script | Function | Input → Output |
|--------|----------|----------------|
| `scrape_google_maps.py` | Search businesses via Serper | Query → JSON results |
| `qualify_site.py` | Validate website quality | URL → Score |
| `enrich.py` | Get contact info (Waterfall) | Company → Email/Phone |
| `save_to_excel.py` | Save leads to Excel (backup or `--use-excel`) | Data → `Generate_leads.xlsx` |
| `sync_hubspot.py` | Push leads to HubSpot (direct, default) | JSON → HubSpot CRM + sync log |
| `sync_from_hubspot.py` | Pull updates from HubSpot (Excel mode only) | HubSpot → Excel |

### Mode B: PDF Maker

| Script | Function | Input → Output |
|--------|----------|----------------|
| `generate_pdf.py` | Generate PDF from template | Data + Template → PDF |
| `create_excel_template.py` | Create Excel input template | → Excel template |

### Mode C: Support Handler (v3.0 - Credit Validation)

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

### Shared / Utilities

| Script | Function | Used by |
|--------|----------|---------|
| `diagnose_hubspot_properties.py` | Debug HubSpot fields | All modes |

---

## The 3-Layer Architecture

**Layer 1: Skills (What to do)**
- Lives in `.claude/skills/`. These are your specialized agents.
- Each skill contains the full SOP for its mode.

**Layer 2: Orchestration (Decision making)**
- This is you. Your job is intelligent routing based on User Intent.
- You rely on deterministic scripts. You do not scrape or generate PDFs manually.

**Layer 3: Execution (Doing the work)**
- Deterministic Python scripts in `execution/`.
- **Source of Truth:** HubSpot CRM (direct mode) or `Generate_leads.xlsx` (with `--use-excel`).
- **CRM:** HubSpot is the primary destination. Never create duplicates (upsert by email).
- **Keys:** stored in `.env`.

## Operating Principles

1. **Check Script Registry first** - Before writing code, check if a script already exists above.
2. **Excel Locking** - Warn user to close `Generate_leads.xlsx` before running `save_to_excel.py` (backup mode or `--use-excel`).
3. **HubSpot Safety** - Always Search-Before-Create (Upsert logic to prevent duplicates).
4. **Self-anneal** - If script fails, read error, fix script, retry, update skill if needed.

---

## Directory Structure

```
agents_ia/
├── CLAUDE.md               # Project brain (this file)
├── .claude/skills/          # Specialized agent skills
├── execution/               # Deterministic Python scripts
├── tests/                   # Test scripts
├── docs/                    # Documentation
├── templates/               # Jinja2 templates for PDF
├── output/                  # Generated PDFs
├── .tmp/                    # Temp files (delete after use)
├── .env                     # API Keys
├── run_pipeline.py          # Master pipeline (Mode A) - direct HubSpot by default
└── Generate_leads.xlsx      # Excel backup (auto-generated after HubSpot sync)
```

---

## Workflow Execution Pattern

```
1. Identify Intent → Select Mode (A/B/C)
2. Load Skill → Read .claude/skills/*.md
3. Execute Scripts → Run in sequence from registry
4. Finalize → Sync to HubSpot (direct) + Excel backup
```

Be pragmatic. Be reliable. Self-anneal.
