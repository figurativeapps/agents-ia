# 🚀 Quick Start Guide

## ⚡ 5-Minute Setup

### Step 1: Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Step 2: Configure API Keys

1. Copy the template:
   ```bash
   cp .env.template .env
   ```

2. Edit `.env` and add your API keys:
   - Get **Serper API key**: https://serper.dev
   - Get **Firecrawl API key**: https://firecrawl.dev
   - Get **Apollo API key**: https://apollo.io
   - Get **HubSpot API key**: https://app.hubspot.com/

### Step 3: Create Excel Database

```bash
python execution/create_excel_template.py
```

This creates `Generate_leads.xlsx` in the root folder.

---

## 🎯 Your First Lead Generation Campaign

### Example: Find 50 Cuisinistes in Bordeaux

```bash
# 1. Scrape Google Maps
python execution/scrape_google_maps.py \
  --industry "Cuisinistes" \
  --location "Bordeaux" \
  --max_leads 50

# 2. Qualify websites (check if active, get emails)
python execution/2_qualify_site.py \
  --input .tmp/google_maps_results.json

# 3. Enrich with Apollo (get decision maker emails)
python execution/5_enrich.py \
  --input .tmp/qualified_leads.json

# 4. Save to Excel master database
python execution/save_to_excel.py \
  --input .tmp/enriched_leads.json

# 5. Sync to HubSpot CRM
python execution/sync_hubspot.py \
  --input .tmp/enriched_leads.json
```

**Total time:** ~5 minutes for 50 leads

---

## 📄 Generate a PDF Proposal

```bash
python execution/8_generate_pdf.py \
  --company "La Belle Cuisine" \
  --industry "Cuisinistes"
```

The PDF will be in `output/` folder.

---

## 💡 Common Use Cases

### Use Case 1: Quick Test (5 leads)

```bash
python execution/scrape_google_maps.py --industry "Restaurants" --location "Paris" --max_leads 5
python execution/2_qualify_site.py --input .tmp/google_maps_results.json
python execution/save_to_excel.py --input .tmp/qualified_leads.json
```

### Use Case 2: Full Pipeline (50 leads with HubSpot sync)

Run all 5 steps from "Your First Campaign" above.

### Use Case 3: Bulk PDF Generation

```bash
# For a company already in your Excel
python execution/8_generate_pdf.py --company "Acme Corp"

# For a new company (manual data)
python execution/8_generate_pdf.py --company "New Corp" --industry "E-commerce" --contact "John Doe"
```

---

## 🔍 What to Expect

### After Scraping (Step 1)
You'll have a JSON file in `.tmp/` with:
- Company names
- Addresses
- Phone numbers (standard line)
- Google ratings
- Websites

### After Qualification (Step 2)
Added data:
- ✅ Website active status
- 📧 Generic emails from website
- 🛒 E-commerce detection

### After Enrichment (Step 4)
Added data:
- 👤 Decision maker name & title
- 📧 Personal email (CEO, Director, etc.)
- 📞 Direct phone line
- 💼 LinkedIn profile

### After Excel Save (Step 5)
All data is in `Generate_leads.xlsx`:
- Organized in columns
- Deduplication applied
- Ready for analysis

### After HubSpot Sync (Step 6)
In your HubSpot CRM:
- ✅ Contacts created/updated
- 🏢 Companies created/linked
- 🔄 No duplicates (upsert logic)

---

## ⚙️ Tips & Best Practices

### 1. Start Small
Test with 5-10 leads first to verify everything works.

### 2. Close Excel Before Saving
The system will warn you if `Generate_leads.xlsx` is open.

### 3. Check API Limits
- **Serper**: 2,500 searches/month (free tier)
- **Firecrawl**: 500 scrapes/month (free tier)
- **Hunter.io**: 50 credits/month (free tier)
- **HubSpot**: Unlimited on paid plans

### 4. Backup Your Excel
The Excel file is your source of truth. Back it up regularly.

---

## 🐛 Common Issues

### "Module not found"
```bash
pip install -r requirements.txt
```

### "API key not found"
Check your `.env` file has the key and no extra spaces.

### "Permission denied" on Excel
Close `Generate_leads.xlsx` in Excel before running `save_to_excel.py`.

### "Rate limit exceeded"
Wait 60 seconds and try again. Scripts auto-retry.

---

## 📊 Data Quality Checklist

After running the pipeline, check:

- [ ] All companies have phone numbers
- [ ] Active websites have emails
- [ ] Enriched contacts have decision maker names
- [ ] No duplicate entries in Excel
- [ ] HubSpot contacts are properly linked to companies

---

## 🎓 Next Steps

1. **Customize email templates** in `directives/email_templates.md`
2. **Brand your PDFs** by editing `templates/plaquette_base.html`
3. **Add new industries** by updating value propositions in `8_generate_pdf.py`
4. **Create automated campaigns** by chaining scripts in a bash script

---

## 🆘 Need Help?

- **Script errors:** Check terminal output for specific error messages
- **API issues:** Verify keys in `.env` and check API documentation
- **Excel problems:** Ensure file is closed and not corrupted
- **HubSpot sync:** Check API key has proper permissions (contacts, companies)

---

**Ready to go? Start with the 5-lead test above!** 🚀
