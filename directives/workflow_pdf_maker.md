# WORKFLOW : PDF PROPOSAL MAKER

## 1. OBJECTIVE
Generate customized PDF proposals for leads using company-specific data.

## 2. INPUTS REQUIRED
- `company_name`: Name of the company
- `contact_name`: Decision maker name (optional)
- `industry`: Industry sector
- `template`: Template to use (default: "plaquette_base.html")

## 3. PROCESS

### STEP 1: GATHER DATA
- **Source:** Read from `Generate_leads.xlsx`
- **Action:** Extract company information by name
- **Fallback:** If not in Excel, prompt user for manual input

### STEP 2: CUSTOMIZE TEMPLATE
- **Script:** `execution/8_generate_pdf.py`
- **Template:** `templates/plaquette_base.html`
- **Action:**
  - Load Jinja2 template
  - Inject company data (name, industry, contact info)
  - Apply custom styling from `templates/style.css`

### STEP 3: GENERATE PDF
- **Tool:** WeasyPrint
- **Output:** `output/{company_name}_proposal.pdf`
- **Format:** Professional, branded PDF document

## 4. CUSTOMIZATION POINTS

The template supports these variables:
- `{{ company_name }}` - Company name
- `{{ contact_name }}` - Decision maker name
- `{{ industry }}` - Industry sector
- `{{ our_company }}` - Your company name
- `{{ value_proposition }}` - Custom value prop
- `{{ services }}` - List of services
- `{{ cta }}` - Call to action

## 5. QUALITY CHECKS
- Verify all placeholders are filled
- Check PDF rendering quality
- Ensure proper formatting
- Validate file size (< 5MB recommended)

## 6. DELIVERY
- Save to `output/` folder
- Optionally attach to HubSpot contact record
- Ready for email campaign
