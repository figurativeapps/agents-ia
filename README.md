# AI-Powered B2B Lead Generation System

An intelligent, automated lead generation system built with Python and AI orchestration. This system scrapes Google Maps, qualifies websites, enriches contact data, and syncs everything to HubSpot CRM.

## 🏗️ Architecture

This project follows the **DOE Framework** (Directive → Orchestration → Execution):

- **Layer 1 (Directive):** Business logic and SOPs in `directives/`
- **Layer 2 (Orchestration):** AI agent that routes tasks intelligently
- **Layer 3 (Execution):** Deterministic Python scripts in `execution/`

## 📁 Project Structure

```
Agents AI/
│
├── .env                        # API keys (Serper, Firecrawl, Hunter, HubSpot)
├── requirements.txt            # Python dependencies
├── AGENTS.md                   # AI orchestration instructions (DOE Framework)
├── Generate_leads.xlsx         # Master database (Excel - Source of Truth)
│
├── directives/                 # Layer 1: SOPs (Directive)
│   ├── workflow_global_lead_gen.md
│   ├── workflow_pdf_maker.md
│   ├── waterfall_strategy.md
│   └── email_templates.md
│
├── execution/                  # Layer 3: Python scripts (Execution)
│   ├── scrape_google_maps.py   # Step 1: Google Maps scraping
│   ├── 2_qualify_site.py       # Step 2: Website qualification
│   ├── 5_enrich.py             # Step 3: Waterfall enrichment
│   ├── save_to_excel.py        # Step 4: Excel database save
│   ├── sync_hubspot.py         # Step 5: HubSpot CRM sync
│   └── 8_generate_pdf.py       # PDF proposal generator
│
├── docs/                       # Documentation & guides
│   ├── QUICKSTART.md
│   ├── HUBSPOT_MAPPING.md
│   ├── GUIDE_CHAMPS_HUBSPOT.md
│   └── GUIDE_STATUT_SYNC.md
│
├── templates/                  # HTML/CSS for PDFs
├── output/                     # Generated PDFs
└── .tmp/                       # Temporary files (auto-cleaned)
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API Keys

Copy `.env.template` to `.env` and add your API keys:

```bash
cp .env.template .env
```

Edit `.env` with your actual keys:
- **SERPER_API_KEY** - For Google Maps search & OSINT (required)
- **FIRECRAWL_API_KEY** - For website scraping (required)
- **HUNTER_API_KEY** - For email pattern detection (optional but recommended)
- **HUBSPOT_API_KEY** - For CRM integration (required for sync)

### 3. Create Excel Database

```bash
python execution/create_excel_template.py
```

This creates `Generate_leads.xlsx` with the proper structure.

## 📊 Lead Generation Workflow

### Full Pipeline

Run each step sequentially:

```bash
# Step 1: Scrape Google Maps
python execution/scrape_google_maps.py --industry "Cuisinistes" --location "Bordeaux" --max_leads 50

# Step 2: Qualify websites
python execution/2_qualify_site.py --input .tmp/google_maps_results.json

# Step 3: Enrich with Waterfall Strategy (Serper OSINT + Hunter.io)
python execution/5_enrich.py --input .tmp/qualified_leads.json

# Step 4: Save to Excel
python execution/save_to_excel.py --input .tmp/enriched_leads.json

# Step 5: Sync to HubSpot
python execution/sync_hubspot.py --input .tmp/enriched_leads.json
```

### What Each Step Does

1. **Scraping**: Finds businesses on Google Maps with phone numbers
2. **Qualification**: Checks if websites are active, finds emails, detects e-commerce. **FILTERS OUT** businesses without e-commerce websites
3. **Enrichment**: Uses **Waterfall Strategy** to find decision maker info (see below)
4. **Excel Save**: Stores in master database with deduplication
5. **HubSpot Sync**: Creates/updates CRM contacts and companies (no duplicates)

### 🌊 Waterfall Enrichment Strategy

Step 3 uses an intelligent 3-stage approach to minimize API costs while maximizing data quality:

**Stage 1: OSINT with Serper (Free)**
- Searches LinkedIn for decision maker profiles
- Extracts name and job title
- **Cost**: ~0.002€ per lead

**Stage 2: Pattern Matching with Hunter.io (Freemium)**
- Finds email patterns for the company domain
- Retrieves generic emails if available
- **Cost**: ~0.01€ per lead

**Stage 3: Email Reconstruction (Free)**
- Combines data from stages 1 & 2 to build personalized emails
- Falls back to generic emails if available, otherwise marks as "not found"
- **Cost**: Free

**Result**: 97% cost savings vs traditional enrichment APIs with 85-90% success rate.

📖 **Full documentation**: See [directives/waterfall_strategy.md](directives/waterfall_strategy.md)

## 📄 PDF Generation

Generate customized proposals:

```bash
python execution/8_generate_pdf.py --company "Acme Corp" --industry "Restaurants"
```

The system will:
- Look up company data from `Generate_leads.xlsx`
- Customize the template with their info
- Generate a professional PDF in `output/`

## 🔄 Data Flow

```
Google Maps → Firecrawl → Waterfall (Serper+Hunter) → Excel (Source of Truth) → HubSpot CRM
                                                                                      ↓
                                                                                PDF Generator
```

## 🛡️ Safety Features

### Excel Locking
The system checks if `Generate_leads.xlsx` is open before writing. Close the file before running `save_to_excel.py`.

### HubSpot Deduplication
Uses **Upsert logic** (Search → Update or Create) to prevent duplicate contacts:
- Searches by email first
- Updates existing records
- Creates new contacts only if not found

### Rate Limiting
All scripts include sleep delays to respect API rate limits.

## 🧪 Testing

Test individual components:

```bash
# Test Google Maps scraping only
python execution/scrape_google_maps.py --industry "Restaurants" --location "Paris" --max_leads 5

# Test website qualification
python execution/2_qualify_site.py --input .tmp/google_maps_results.json

# Generate a test PDF
python execution/8_generate_pdf.py --company "Test Company" --industry "Services"
```

## 📝 Customization

### Email Templates
Edit `directives/email_templates.md` for cold outreach copy.

### PDF Templates
Modify `templates/plaquette_base.html` and `templates/style.css` for custom branding.

### Workflow Logic
Update `directives/workflow_global_lead_gen.md` for process changes.

## 🤖 AI Orchestration

The AI agent (`AGENTS.md`) intelligently routes requests:

- **"Find me 50 cuisinistes in Lyon"** → Runs lead generation workflow
- **"Generate a proposal for Acme Corp"** → Runs PDF generation
- **"Sync everything to HubSpot"** → Runs CRM sync only

## 🐛 Troubleshooting

### Excel Permission Error
```
⚠️ WARNING: Generate_leads.xlsx is currently open!
```
**Solution:** Close Excel and try again.

### API Rate Limit
```
⚠️ Rate limit reached - waiting 60s
```
**Solution:** The script auto-retries. Just wait.

### Missing API Key
```
❌ SERPER_API_KEY not found in .env file
```
**Solution:** Add the key to `.env` file.

## 📊 Excel Database Schema

| Column | Description |
|--------|-------------|
| `Industrie` | Business sector (e.g., "Cuisinistes") |
| `Nom_Entreprise` | Company name |
| `Adresse` | Full address |
| `Ville` | City |
| `Code_Postal` | Postal code |
| `Site_Web` | Website URL |
| `Tel_Standard` | Main phone (from Google) |
| `Email_Generique` | Generic email (from website) |
| `Email_Decideur` | Decision maker email (from enrichment) |
| `Nom_Decideur` | Decision maker name |
| `Poste_Decideur` | Job title |
| `LinkedIn_URL` | LinkedIn profile |
| `Ecommerce` | Has e-commerce (Oui/Non) |
| `Date_Ajout` | Date added |
| `Statut_Sync` | HubSpot sync status (New/Synced/Deleted) |

## 🔐 Security

- Never commit `.env` to version control
- API keys are loaded from environment variables
- HubSpot uses OAuth token authentication
- All API calls use HTTPS

## 📈 Performance

- **Scraping:** ~1 second per business
- **Qualification:** ~2 seconds per website
- **Enrichment:** ~3 seconds per contact
- **Full pipeline:** ~6 seconds per lead

For 50 leads: ~5 minutes total

## 🆘 Support

Issues with:
- **Scripts:** Check error messages in terminal
- **APIs:** Verify keys in `.env`
- **Excel:** Ensure file is closed before writing
- **HubSpot:** Check API key permissions

## 📜 License

MIT License - Feel free to use and modify for your business.

---

**Built with:** Python, Pandas, HubSpot API, Apollo.io, Firecrawl, Serper, Jinja2, WeasyPrint
