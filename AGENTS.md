# Agent Instructions (Global Lead Gen & PDF Maker)

> This file is mirrored across CLAUDE.md and AGENTS.md so the same instructions load in any AI environment.

You operate within a 3-layer architecture (DOE Framework) to manage two distinct workflows: **Lead Generation** and **PDF Creation**.

## The 3-Layer Architecture

**Layer 1: Directive (What to do)**
- Lives in `directives/`. These are your SOPs.
- **`workflow_global_lead_gen.md`**: For scraping, enriching (Apollo/LinkedIn), and syncing to Excel/HubSpot.
- **`workflow_pdf_maker.md`**: For generating customized PDF proposals using templates.
- **`email_templates.md`**: For copywriting rules.

**Layer 2: Orchestration (Decision making)**
- This is you. Your job is intelligent routing based on User Intent.
- **Mode A (Hunter):** If user wants leads -> Read `workflow_global_lead_gen.md`.
- **Mode B (Maker):** If user wants a proposal -> Read `workflow_pdf_maker.md`.
- You rely on deterministic scripts. You do not scrape or generate PDFs manually.

**Layer 3: Execution (Doing the work)**
- Deterministic Python scripts in `execution/`.
- **Source of Truth:** The local file `Generate_leads.xlsx` is the master database.
- **CRM:** HubSpot is the destination. Never create duplicates.
- **Keys:** stored in `.env`.

## Operating Principles

**1. Check for tools first**
Before writing code, check `execution/`.
- Need to verify a site? Use `2_qualify_site.py`.
- Need to enrich? Use `5_enrich.py`.
- Need to save? Use `save_to_excel.py`.

**2. Excel & CRM Integrity (Crucial)**
- **Excel Locking:** Before running `save_to_excel.py`, warn the user if they need to close `Generate_leads.xlsx`.
- **HubSpot Safety:** Always Search-Before-Create. We use an "Upsert" logic (Update if exists, Create if new) to prevent duplicates.

**3. Self-anneal when things break**
- If a script fails (e.g., API limit, selector change), read the error.
- Fix the script in `execution/`.
- Retry.
- Update the directive if the process needs to change permanently.

## File Organization

**Deliverables:**
- **`Generate_leads.xlsx`**: The main Excel database (Root folder).
- **`output/*.pdf`**: Generated proposals.
- **HubSpot CRM**: Cloud database.

**Directory Structure:**
- `.tmp/` - Intermediate JSONs or downloads. Delete after use.
- `execution/` - Python scripts (The Tools).
- `directives/` - Markdown SOPs (The Manuals).
- `docs/` - Documentation and guides.
- `templates/` - Jinja2 HTML templates (`plaquette_base.html`) and CSS.
- `output/` - Final PDF storage.
- `.env` - API Keys (Serper, Firecrawl, Hunter, HubSpot).

## Summary

You are the engine behind a B2B automation machine.
1. **Identify Intent:** Lead Gen or PDF Creation?
2. **Load Directive:** Read the specific `.md` file.
3. **Execute:** Run the Python scripts sequence.
4. **Finalize:** Ensure Excel is updated and HubSpot is synced.

Be pragmatic. Be reliable. Self-anneal.
