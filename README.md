# DOE Framework - AI Agent Automation

> A multi-agent automation framework following the Directive-Orchestration-Execution pattern for B2B operations.

---

## What is the DOE Framework?

DOE (Directive → Orchestration → Execution) is a three-layer architecture for building AI-powered automation systems:

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1: DIRECTIVES          (directives/*.md)             │
│  → Business logic and standard operating procedures         │
├─────────────────────────────────────────────────────────────┤
│  LAYER 2: ORCHESTRATION       (AGENTS.md)                   │
│  → AI agent that decides which workflow to execute          │
├─────────────────────────────────────────────────────────────┤
│  LAYER 3: EXECUTION           (execution/*.py)              │
│  → Deterministic Python scripts that do the actual work     │
└─────────────────────────────────────────────────────────────┘
```

**Core Principle**: The AI agent reads directives (SOPs) and executes pre-built scripts. It doesn't write code on the fly.

---

## Key Features

- **Multi-Agent**: Support for multiple independent workflows (Lead Gen, Document Creation, Request Handling)
- **Self-Healing**: Agents can detect errors, fix scripts, and retry
- **No-Code SOPs**: Business logic defined in markdown files
- **Modular Scripts**: Reusable Python tools for common tasks
- **API-First**: Integrates with HubSpot, ClickUp, cloud storage, and LLMs

---

## Project Structure

```
agents_ia/
├── AGENTS.md              # Agent orchestration instructions
├── directives/            # Business logic and workflows (SOPs)
│   ├── workflow_*.md
│   └── *.md
├── execution/             # Python automation scripts
│   ├── scrape_*.py
│   ├── enrich_*.py
│   └── *.py
├── docs/                  # Documentation
├── templates/             # Document templates
├── .env                   # API keys (not versioned)
└── Generate_leads.xlsx    # Master database
```

---

## Operating Modes

The framework supports 3 distinct operating modes:

| Mode | Purpose | Example Use Case |
|------|---------|------------------|
| **Mode A** | Data collection and enrichment | B2B lead generation, web scraping |
| **Mode B** | Document generation | PDF proposals, reports |
| **Mode C** | Request processing | Support tickets, task automation |

Each mode has its own set of directives and scripts.

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

Check `AGENTS.md` for the complete script registry and usage instructions.

---

## How It Works

### 1. User Request
*"Find 50 B2B leads in Lyon"*

### 2. Agent Reads Directives
The AI agent loads `directives/workflow_*.md` based on the request type.

### 3. Agent Executes Scripts
Runs the appropriate sequence from `execution/`:
```
scrape → qualify → enrich → save → sync
```

### 4. Results
Data stored in Excel and synced to CRM.

---

## Core Components

### Directives (Layer 1)

Markdown files defining:
- Workflow steps
- Business rules
- API strategies
- Email templates

### Scripts (Layer 3)

Python tools for:
- Web scraping
- Data enrichment
- CRM synchronization
- Document generation
- API integrations

### Orchestration (Layer 2)

The AI agent (`AGENTS.md`) that:
- Routes requests to the right workflow
- Executes scripts in sequence
- Handles errors and retries
- Ensures data integrity

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
- Redis (task queue)
- WeasyPrint (PDF generation)

See `requirements.txt` for full list.

---

## Documentation

- `AGENTS.md` - Agent instructions and script registry
- `docs/QUICKSTART.md` - Getting started guide
- `directives/` - Individual workflow documentation

---

## License

MIT License - Free to use and modify.

---

**Architecture Pattern**: Directive-Orchestration-Execution (DOE)
**Use Case**: B2B Automation, Lead Generation, Document Processing
