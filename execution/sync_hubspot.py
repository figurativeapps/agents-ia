"""
STEP 6: Sync to HubSpot CRM
Syncs leads to HubSpot with deduplication logic (Upsert).

Usage:
    python sync_hubspot.py --input .tmp/enriched_leads.json
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from dotenv import load_dotenv
from hubspot import HubSpot
from hubspot.crm.contacts import SimplePublicObjectInputForCreate, ApiException
from hubspot.crm.companies import SimplePublicObjectInputForCreate as CompanyInput
from time import sleep
from datetime import datetime

# Fix Windows console encoding issues
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        # Python < 3.7
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")

# Load environment variables
load_dotenv()

# Local imports
from api_utils import sdk_call_with_retry, save_tracker_snapshot

HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')

CUSTOM_CONTACT_PROPERTIES = [
    {"name": "lead_score_ai", "label": "Lead Score AI", "type": "number", "fieldType": "number",
     "groupName": "contactinformation", "description": "AI-generated lead score (0-100)"},
    {"name": "lead_priority", "label": "Lead Priority", "type": "string", "fieldType": "text",
     "groupName": "contactinformation", "description": "Lead priority: Hot/Warm/Cold"},
    {"name": "tech_stack", "label": "Tech Stack", "type": "string", "fieldType": "text",
     "groupName": "contactinformation", "description": "Detected website tech stack"},
    {"name": "email_source", "label": "Email Source", "type": "string", "fieldType": "text",
     "groupName": "contactinformation", "description": "Source of the email (hunter, apollo, etc.)"},
]


def init_hubspot_client():
    """Initialize HubSpot API client"""
    if not HUBSPOT_API_KEY:
        raise ValueError("❌ HUBSPOT_API_KEY not found in .env file")

    return HubSpot(access_token=HUBSPOT_API_KEY)


def ensure_custom_properties(client):
    """Create custom contact properties in HubSpot if they don't exist."""
    try:
        existing = sdk_call_with_retry(
            lambda: client.crm.properties.core_api.get_all(object_type="contacts"),
            label="HubSpot get-all-properties"
        )
        existing_names = {p.name for p in existing.results}
    except Exception as e:
        print(f"  ⚠️  Could not fetch existing properties: {str(e)[:100]}")
        return

    for prop_def in CUSTOM_CONTACT_PROPERTIES:
        if prop_def["name"] in existing_names:
            continue
        try:
            sdk_call_with_retry(
                lambda pd=prop_def: client.crm.properties.core_api.create(
                    object_type="contacts",
                    property_create={
                        "name": pd["name"],
                        "label": pd["label"],
                        "type": pd["type"],
                        "fieldType": pd["fieldType"],
                        "groupName": pd["groupName"],
                        "description": pd["description"],
                    }
                ),
                label=f"HubSpot create-property-{prop_def['name']}"
            )
            print(f"  ✅ Created HubSpot property: {prop_def['name']}")
        except Exception as e:
            print(f"  ⚠️  Could not create property {prop_def['name']}: {str(e)[:100]}")


def search_contact_by_email(client, email):
    """
    Search for existing contact by email

    Returns:
        Contact ID if found, None otherwise
    """
    try:
        # Use the search API
        filter_groups = [{
            "filters": [{
                "propertyName": "email",
                "operator": "EQ",
                "value": email
            }]
        }]

        search_request = {
            "filterGroups": filter_groups,
            "properties": ["email", "firstname", "lastname", "phone", "company"]
        }

        results = sdk_call_with_retry(
            lambda: client.crm.contacts.search_api.do_search(public_object_search_request=search_request),
            label="HubSpot contact-search"
        )

        if results.total > 0:
            return results.results[0].id

        return None

    except Exception as e:
        print(f"    ⚠️  Search error: {str(e)[:50]}")
        return None


def create_or_update_company(client, lead):
    """
    Create or update company in HubSpot

    Returns:
        Company ID
    """
    company_name = lead.get('Nom_Entreprise', '')
    domain = lead.get('Site_Web', '').replace('https://', '').replace('http://', '').split('/')[0]

    if not company_name:
        return None

    try:
        # Search for existing company by domain or name
        if domain:
            filter_groups = [{
                "filters": [{
                    "propertyName": "domain",
                    "operator": "EQ",
                    "value": domain
                }]
            }]
        else:
            filter_groups = [{
                "filters": [{
                    "propertyName": "name",
                    "operator": "EQ",
                    "value": company_name
                }]
            }]

        search_request = {
            "filterGroups": filter_groups,
            "properties": ["name", "domain"]
        }

        results = sdk_call_with_retry(
            lambda: client.crm.companies.search_api.do_search(public_object_search_request=search_request),
            label="HubSpot company-search"
        )

        if results.total > 0:
            # Company exists - update it
            company_id = results.results[0].id
            print(f"    🏢 Company exists: {company_name}")
            return company_id

        # Create new company
        company_properties = {
            "name": company_name,
            "domain": domain,
            "city": lead.get('Ville', ''),
            "address": lead.get('Adresse', ''),
            "zip": lead.get('Code_Postal', ''),
            "country": lead.get('Pays', ''),
            "phone": lead.get('Tel_Standard', ''),
            "description": f"Industrie: {lead.get('Industrie', '')}" if lead.get('Industrie') else '',
        }

        # Remove empty values
        company_properties = {k: v for k, v in company_properties.items() if v and str(v).strip()}

        company_input = CompanyInput(properties=company_properties)
        company = sdk_call_with_retry(
            lambda: client.crm.companies.basic_api.create(simple_public_object_input_for_create=company_input),
            label="HubSpot company-create"
        )

        print(f"    🏢 Created company: {company_name}")
        return company.id

    except Exception as e:
        error_msg = str(e)
        print(f"    ⚠️  Company error: {error_msg[:200]}")
        if hasattr(e, 'body'):
            print(f"    📋 Error details: {e.body}")
        return None


def create_contact(client, lead, company_id=None):
    """Create new contact in HubSpot (works with or without email)"""

    email = lead.get('Email_Decideur') or lead.get('Email_Generique')

    # Prepare contact properties - using standard HubSpot properties
    properties = {
        "phone": lead.get('Tel_Standard', ''),
        "company": lead.get('Nom_Entreprise', ''),
        "website": lead.get('Site_Web', ''),
        "address": lead.get('Adresse', ''),
        "city": lead.get('Ville', ''),
        "zip": lead.get('Code_Postal', ''),
        "country": lead.get('Pays', ''),
        "industrie": lead.get('Industrie', ''),
        "hs_linkedin_url": lead.get('LinkedIn_URL', ''),
        "lifecyclestage": "lead",
        "hs_lead_status": "NEW",
    }

    if email:
        properties["email"] = email

    # Add new enrichment fields (custom properties in HubSpot)
    if lead.get('Lead_Score') is not None:
        properties["lead_score_ai"] = str(lead.get('Lead_Score', 0))
    if lead.get('Lead_Priority'):
        properties["lead_priority"] = lead.get('Lead_Priority', '')
    if lead.get('Tech_Stack') and lead.get('Tech_Stack') != 'unknown':
        properties["tech_stack"] = lead.get('Tech_Stack', '')
    if lead.get('Email_Source'):
        properties["email_source"] = lead.get('Email_Source', '')

    # Add name fields if available
    if lead.get('Nom_Decideur'):
        name_parts = lead.get('Nom_Decideur', '').split()
        if name_parts:
            properties["firstname"] = name_parts[0]
            if len(name_parts) > 1:
                properties["lastname"] = ' '.join(name_parts[1:])

    # Add job title if available
    if lead.get('Poste_Decideur'):
        properties["jobtitle"] = lead.get('Poste_Decideur')

    # Remove empty values
    properties = {k: v for k, v in properties.items() if v and v.strip()}

    try:
        contact_input = SimplePublicObjectInputForCreate(properties=properties)
        contact = sdk_call_with_retry(
            lambda: client.crm.contacts.basic_api.create(simple_public_object_input_for_create=contact_input),
            label="HubSpot contact-create"
        )

        # Associate with company if company_id exists
        if company_id:
            try:
                sdk_call_with_retry(
                    lambda: client.crm.contacts.associations_api.create(
                        contact_id=contact.id,
                        to_object_type="companies",
                        to_object_id=company_id,
                        association_type="contact_to_company"
                    ),
                    label="HubSpot contact-company association"
                )
            except Exception as assoc_err:
                status = getattr(assoc_err, 'status', None)
                if status != 409:
                    logging.getLogger(__name__).warning(
                        "Association error (contact %s → company %s): %s",
                        contact.id, company_id, str(assoc_err)[:100]
                    )

        print(f"    ✅ Created contact: {email}")
        return contact.id

    except ApiException as e:
        error_msg = str(e)
        print(f"    ❌ Error creating contact: {error_msg[:200]}")
        if hasattr(e, 'body'):
            print(f"    📋 Error details: {e.body}")
        return None
    except Exception as e:
        print(f"    ❌ Unexpected error: {str(e)[:200]}")
        return None


def update_contact(client, contact_id, lead):
    """Update existing contact with new information"""

    # Prepare update properties (only non-empty values)
    properties = {}

    if lead.get('Tel_Standard'):
        properties['phone'] = lead.get('Tel_Standard')

    if lead.get('Industrie'):
        properties['industrie'] = lead.get('Industrie')  # Custom field created in HubSpot

    if lead.get('LinkedIn_URL'):
        properties['hs_linkedin_url'] = lead.get('LinkedIn_URL')  # HubSpot standard field

    if lead.get('Poste_Decideur'):
        properties['jobtitle'] = lead.get('Poste_Decideur')

    if lead.get('Adresse'):
        properties['address'] = lead.get('Adresse')

    if lead.get('Ville'):
        properties['city'] = lead.get('Ville')

    if lead.get('Code_Postal'):
        properties['zip'] = lead.get('Code_Postal')

    if lead.get('Pays'):
        properties['country'] = lead.get('Pays')

    # New enrichment fields
    if lead.get('Lead_Score') is not None:
        properties['lead_score_ai'] = str(lead.get('Lead_Score', 0))
    if lead.get('Lead_Priority'):
        properties['lead_priority'] = lead.get('Lead_Priority', '')
    if lead.get('Tech_Stack') and lead.get('Tech_Stack') != 'unknown':
        properties['tech_stack'] = lead.get('Tech_Stack', '')

    if not properties:
        print(f"    ⏭️  No new data to update")
        return contact_id

    try:
        sdk_call_with_retry(
            lambda: client.crm.contacts.basic_api.update(
                contact_id=contact_id,
                simple_public_object_input={"properties": properties}
            ),
            label="HubSpot contact-update"
        )
        print(f"    ♻️  Updated contact")
        return contact_id

    except ApiException as e:
        print(f"    ⚠️  Update error: {str(e)[:80]}")
        return contact_id


def sync_lead_to_hubspot(client, lead):
    """
    Sync a single lead to HubSpot with upsert logic
    Respects the Statut_Sync field to avoid re-syncing deleted contacts

    Returns:
        Tuple: (HubSpot contact ID, new_status)
    """

    company_name = lead.get('Nom_Entreprise', 'Unknown')
    email = lead.get('Email_Decideur') or lead.get('Email_Generique')
    sync_status = lead.get('Statut_Sync', 'New')

    print(f"  🔄 Syncing: {company_name}")

    # Check if this contact was previously deleted from HubSpot
    if sync_status == 'Deleted':
        print(f"    🚫 Skipped - Contact marked as Deleted (was removed from HubSpot)")
        return None, 'Deleted'

    # Step 1: Create or get company
    company_id = create_or_update_company(client, lead)

    # Step 2: Check if contact exists (by email if available)
    existing_contact_id = None
    if email:
        existing_contact_id = search_contact_by_email(client, email)

    if existing_contact_id:
        contact_id = update_contact(client, existing_contact_id, lead)
        new_status = 'Synced'
    else:
        contact_id = create_contact(client, lead, company_id)
        new_status = 'Synced' if contact_id else 'Failed'

    return contact_id, new_status


def sync_leads(input_file, write_log=False):
    """Sync all leads to HubSpot

    Args:
        input_file: Path to enriched leads JSON
        write_log: If True, write a structured sync log to .tmp/
    """

    # Initialize HubSpot client
    client = init_hubspot_client()

    # Ensure custom properties exist before syncing
    print("🔧 Checking custom HubSpot properties...")
    ensure_custom_properties(client)

    # Load leads
    with open(input_file, 'r', encoding='utf-8') as f:
        leads = json.load(f)

    print(f"📋 Syncing {len(leads)} leads to HubSpot...\n")

    synced_count = 0
    skipped_count = 0
    failed_count = 0
    results = []

    for i, lead in enumerate(leads, 1):
        print(f"[{i}/{len(leads)}]")

        contact_id, new_status = sync_lead_to_hubspot(client, lead)

        # Update the lead's status
        lead['Statut_Sync'] = new_status

        if contact_id:
            lead['HubSpot_ID'] = str(contact_id)
            synced_count += 1
        elif new_status == 'Deleted':
            skipped_count += 1
        elif new_status in ('Failed', 'No Email'):
            failed_count += 1

        # Collect result for log
        results.append({
            "company": lead.get('Nom_Entreprise', 'Unknown'),
            "email": lead.get('Email_Decideur') or lead.get('Email_Generique', ''),
            "status": new_status,
            "hubspot_id": str(contact_id) if contact_id else None,
        })

        # Rate limiting
        sleep(0.5)

    print(f"\n✅ Sync complete!")
    print(f"  📊 Total: {synced_count}/{len(leads)} contacts synced")
    if failed_count > 0:
        print(f"  ❌ Failed: {failed_count} contacts")
    if skipped_count > 0:
        print(f"  🚫 Skipped: {skipped_count} contacts (marked as Deleted)")

    # Save updated leads with HubSpot IDs
    with open(input_file, 'w', encoding='utf-8') as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)

    # Write structured sync log
    if write_log:
        log_dir = Path(input_file).parent
        log_filename = f"sync_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        log_path = log_dir / log_filename

        log_data = {
            "run_date": datetime.now().isoformat(),
            "total": len(leads),
            "synced": synced_count,
            "failed": failed_count,
            "skipped": skipped_count,
            "results": results
        }

        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)

        print(f"  📝 Sync log: {log_path}")

    return leads


def main():
    parser = argparse.ArgumentParser(description='Sync leads to HubSpot CRM')
    parser.add_argument('--input', required=True, help='Input JSON file with enriched leads')
    parser.add_argument('--write-log', action='store_true', help='Write a structured sync results log to .tmp/')

    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        print(f"❌ Input file not found: {input_path}")
        return

    # Sync to HubSpot
    sync_leads(input_path, write_log=args.write_log)

    print(f"\n✅ HubSpot sync complete!")
    print(f"\n💡 Tip: Check your HubSpot CRM to verify the data")

    save_tracker_snapshot("step4_hubspot")


if __name__ == '__main__':
    main()
