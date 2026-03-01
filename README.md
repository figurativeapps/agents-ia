# Figurative — AI Agent Automation

> A skills-based automation framework for B2B operations powered by Claude Code.

---

## How It Works

The AI agent reads **skill files** (SOPs) and executes pre-built Python scripts. It doesn't write code on the fly.

```
┌─────────────────────────────────────────────────────────────┐
│  CLAUDE.md (root)                                            │
│  → Project brain: routing, global rules, guard rails         │
│  → Auto-injected at the start of every conversation          │
├─────────────────────────────────────────────────────────────┤
│  .claude/skills/<name>/SKILL.md                              │
│  → Detailed checklist: inputs, steps, scripts to execute     │
│  → Loaded when user intent matches the USE WHEN clause       │
├─────────────────────────────────────────────────────────────┤
│  execution/*.py                                              │
│  → Deterministic Python scripts that do the actual work      │
│  → Shared across skills (HubSpot, ClickUp, R2, etc.)        │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Features

- **Skills-Based**: Each workflow is a self-documented skill with a step-by-step checklist
- **Self-Healing**: Agent detects errors, fixes scripts, and retries automatically
- **No-Code SOPs**: Business logic defined in Markdown skill files
- **Modular Scripts**: Reusable Python tools shared across workflows
- **API-First**: Integrates with HubSpot, ClickUp, Cloudflare R2, and LLMs

---

## Project Structure

```
agents_ia/
├── CLAUDE.md                    # Project brain (auto-injected)
├── .claude/skills/              # Skills with YAML frontmatter
│   ├── lead_gen/SKILL.md        # Lead generation pipeline
│   ├── PDF_gen/SKILL.md         # PDF proposal generator
│   └── support/SKILL.md         # Support & 3D modeling requests
├── execution/                   # Deterministic Python scripts
├── tests/                       # Test scripts
├── docs/                        # Documentation
├── templates/                   # Jinja2 templates for PDF
├── output/                      # Generated PDFs
├── .env                         # API keys (not versioned)
└── Generate_leads.xlsx          # Master database (auto-generated)
```

---

## Available Skills

| Skill | Purpose | Example Use Case |
|-------|---------|------------------|
| **lead_gen** | Lead generation & enrichment | B2B lead scraping, CRM sync |
| **PDF_gen** | Document generation | PDF proposals, overlay on Canva templates |
| **support** | Request processing | Support tickets, 3D modeling requests |

Each skill has its own SKILL.md with the full pipeline, scripts, API keys, and guard rails.

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
# Lead Generation
python execution/run_pipeline.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50

# Webhook Server
uvicorn execution.webhook_server:app --host 0.0.0.0 --port 5000
```

---

## How a Skill Runs

### 1. User Request
*"Find 50 B2B leads in Lyon"*

### 2. Agent Loads Skill
Claude reads `.claude/skills/lead_gen/SKILL.md` based on the request type.

### 3. Agent Follows Checklist
Executes scripts from `execution/` in sequence:
```
scrape → qualify → enrich → score → sync → backup
```

### 4. Results
Data synced to HubSpot CRM + Excel backup.

---

## Safety Features

- **No Duplicates**: Upsert logic for CRM operations
- **File Locking**: Prevents concurrent Excel writes
- **Rate Limiting**: Respects API quotas with retry + backoff
- **Self-Anneal**: Auto-fixes common errors and updates skills

---

## Dependencies

- Python 3.11+
- Pandas, Requests, FastAPI, WeasyPrint, Anthropic SDK

See `requirements.txt` for full list.

---

## Documentation

- `CLAUDE.md` — Agent instructions and routing
- `.claude/skills/` — Skill files with full pipelines
- `docs/QUICKSTART.md` — Getting started guide

---

**Architecture**: Skills-Based AI Agent Automation
**Use Case**: B2B Lead Gen, Document Processing, Support Ticketing
