# DOE Framework - AI Agent Automation

> A multi-agent automation framework following the Directive-Orchestration-Execution pattern for B2B operations.

---

## What is the DOE Framework?

DOE (Directive → Orchestration → Execution) is a three-layer architecture for building AI-powered automation systems:

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1: SKILLS              (.claude/skills/*.md)          │
│  → Specialized agent skills with full SOPs                   │
├─────────────────────────────────────────────────────────────┤
│  LAYER 2: ORCHESTRATION       (CLAUDE.md)                    │
│  → AI agent that decides which workflow to execute           │
├─────────────────────────────────────────────────────────────┤
│  LAYER 3: EXECUTION           (execution/*.py)               │
│  → Deterministic Python scripts that do the actual work      │
└─────────────────────────────────────────────────────────────┘
```

**Core Principle**: The AI agent reads skills (SOPs) and executes pre-built scripts. It doesn't write code on the fly.

---

## Key Features

- **Multi-Agent**: Support for multiple independent workflows (Lead Gen, Document Creation, Request Handling)
- **Self-Healing**: Agents can detect errors, fix scripts, and retry
- **No-Code SOPs**: Business logic defined in skill files
- **Modular Scripts**: Reusable Python tools for common tasks
- **API-First**: Integrates with HubSpot, ClickUp, cloud storage, and LLMs

---

## Project Structure

```
agents_ia/
├── CLAUDE.md                    # Project brain (auto-injected)
├── .claude/skills/              # Specialized agent skills
│   ├── lead_gen/                # Mode A: Lead Generation
│   ├── PDF_gen/                 # Mode B: PDF Proposals
│   └── support/                 # Mode C: Support/Modélisation
├── execution/                   # Deterministic Python scripts
├── tests/                       # Test scripts
├── docs/                        # Documentation
├── templates/                   # Jinja2 templates for PDF
├── output/                      # Generated PDFs
├── .env                         # API keys (not versioned)
└── Generate_leads.xlsx          # Master database (auto-generated)
```

---

## Operating Modes

| Mode | Name | Purpose | Example Use Case |
|------|------|---------|------------------|
| **A** | Lead_gen | Lead generation & enrichment | B2B lead scraping, CRM sync |
| **B** | PDF_gen | Document generation | PDF proposals, reports |
| **C** | Support | Request processing | Support tickets, 3D modeling requests |

Each mode has its own skill file in `.claude/skills/`.

---

## Quick Start

### 1. Installation

```bash
git clone <repo-url>
cd agents_ia
pip install -r requirements.txt
```

### 2. Configuration

```bash
cp .env.template .env
# Edit .env with your API keys
```

### 3. Run a Workflow

```bash
# Mode A: Lead Generation
python execution/run_pipeline.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50

# Mode C: Webhook Server
uvicorn execution.webhook_server:app --host 0.0.0.0 --port 5000
```

Check `CLAUDE.md` for the complete script registry.

---

## How It Works

### 1. User Request
*"Find 50 B2B leads in Lyon"*

### 2. Agent Loads Skill
Claude Code reads `.claude/skills/lead_gen/SKILL.md` based on the request type.

### 3. Agent Executes Scripts
Runs the appropriate sequence from `execution/`:
```
scrape → qualify → enrich → save → sync
```

### 4. Results
Data stored in Excel and synced to CRM.

---

## Safety Features

- **No Duplicates**: Upsert logic for CRM operations
- **File Locking**: Prevents concurrent Excel writes
- **Rate Limiting**: Respects API quotas
- **Self-Anneal**: Auto-fixes common errors

---

## Dependencies

- Python 3.11+
- Pandas (data manipulation)
- Requests (API calls)
- FastAPI (webhook server)
- WeasyPrint (PDF generation)

See `requirements.txt` for full list.

---

## Documentation

- `CLAUDE.md` - Agent instructions and script registry
- `.claude/skills/` - Skill files for each mode
- `docs/QUICKSTART.md` - Getting started guide

---

**Architecture Pattern**: Directive-Orchestration-Execution (DOE)
**Use Case**: B2B Automation, Lead Generation, Document Processing
