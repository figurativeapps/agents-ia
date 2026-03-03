"""
STEP 6: Sync to HubSpot CRM (Batch Mode)
Syncs leads to HubSpot with deduplication logic (Upsert).
Uses batch APIs for create/update/associate to minimize API calls.

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

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

logging.basicConfig(level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")

load_dotenv()

from api_utils import sdk_call_with_retry, save_tracker_snapshot

HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')

BATCH_CHUNK_SIZE = 100

CUSTOM_CONTACT_PROPERTIES = [
    {"name": "email_source", "label": "Email Source", "type": "string", "fieldType": "text",
     "groupName": "contactinformation", "description": "Source of the email (hunter, apollo, etc.)"},
]


def init_hubspot_client():
    """Initialize HubSpot API client"""
    if not HUBSPOT_API_KEY:
        raise ValueError("HUBSPOT_API_KEY not found in .env file")
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


# ───────────────────────────────────────────────────────────────
# Phase 1 helpers: Search
# ───────────────────────────────────────────────────────────────

def _search_company(client, lead):
    """Search for existing company by domain or name. Returns company_id or None."""
    company_name = lead.get('Nom_Entreprise', '')
    domain = lead.get('Site_Web', '').replace('https://', '').replace('http://', '').split('/')[0]

    if not company_name and not domain:
        return None

    try:
        if domain:
            filter_groups = [{"filters": [{"propertyName": "domain", "operator": "EQ", "value": domain}]}]
        else:
            filter_groups = [{"filters": [{"propertyName": "name", "operator": "EQ", "value": company_name}]}]

        results = sdk_call_with_retry(
            lambda: client.crm.companies.search_api.do_search(
                public_object_search_request={"filterGroups": filter_groups, "properties": ["name", "domain"]}
            ),
            label="HubSpot company-search"
        )
        if results.total > 0:
            return results.results[0].id
        return None
    except Exception as e:
        print(f"    ⚠️  Company search error: {str(e)[:50]}")
        return None


def _search_contact_by_email(client, email):
    """Search for existing contact by email. Returns contact_id or None."""
    if not email:
        return None
    try:
        search_request = {
            "filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}],
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
        print(f"    ⚠️  Contact search error: {str(e)[:50]}")
        return None


def _search_contact_by_company(client, lead):
    """Fallback: search for existing contact by company name or website domain.

    Used when the lead has no email — prevents creating duplicate contacts
    for the same company.
    Returns contact_id or None.
    """
    company_name = lead.get('Nom_Entreprise', '').strip()
    domain = lead.get('Site_Web', '').replace('https://', '').replace('http://', '').split('/')[0].replace('www.', '')

    if not company_name and not domain:
        return None

    filter_groups = []
    if company_name:
        filter_groups.append(
            {"filters": [{"propertyName": "company", "operator": "EQ", "value": company_name}]}
        )
    if domain:
        filter_groups.append(
            {"filters": [{"propertyName": "website", "operator": "CONTAINS_TOKEN", "value": domain}]}
        )

    if not filter_groups:
        return None

    try:
        search_request = {
            "filterGroups": filter_groups,
            "properties": ["email", "company", "website"]
        }
        results = sdk_call_with_retry(
            lambda: client.crm.contacts.search_api.do_search(public_object_search_request=search_request),
            label="HubSpot contact-search-by-company"
        )
        if results.total > 0:
            return results.results[0].id
        return None
    except Exception as e:
        print(f"    ⚠️  Contact search by company error: {str(e)[:50]}")
        return None


# ───────────────────────────────────────────────────────────────
# Property builders
# ───────────────────────────────────────────────────────────────

def _build_company_properties(lead):
    """Build company properties dict from a lead."""
    domain = lead.get('Site_Web', '').replace('https://', '').replace('http://', '').split('/')[0]
    props = {
        "name": lead.get('Nom_Entreprise', ''),
        "domain": domain,
        "address": lead.get('Adresse', ''),
        "zip": lead.get('Code_Postal', ''),
        "country": lead.get('Pays', ''),
        "phone": lead.get('Tel_Standard', ''),
        "description": f"Industrie: {lead.get('Industrie', '')}" if lead.get('Industrie') else '',
    }
    return {k: v for k, v in props.items() if v and str(v).strip()}


def _build_contact_properties(lead):
    """Build contact properties dict from a lead."""
    email = lead.get('Email_Generique')
    props = {
        "phone": lead.get('Tel_Standard', ''),
        "company": lead.get('Nom_Entreprise', ''),
        "website": lead.get('Site_Web', ''),
        "address": lead.get('Adresse', ''),
        "zip": lead.get('Code_Postal', ''),
        "country": lead.get('Pays', ''),
        "industrie": lead.get('Industrie', ''),
        "hs_linkedin_url": lead.get('LinkedIn_URL', ''),
        "lifecyclestage": "lead",
        "hs_lead_status": "NEW",
    }
    if email:
        props["email"] = email
    if lead.get('Email_Source'):
        props["email_source"] = lead.get('Email_Source', '')
    if lead.get('Nom_Decideur'):
        name_parts = lead.get('Nom_Decideur', '').split()
        if name_parts:
            props["firstname"] = name_parts[0]
            if len(name_parts) > 1:
                props["lastname"] = ' '.join(name_parts[1:])
    if lead.get('Poste_Decideur'):
        props["jobtitle"] = lead.get('Poste_Decideur')
    return {k: v for k, v in props.items() if v and v.strip()}


def _build_update_properties(lead):
    """Build properties for updating an existing contact (only non-empty fields)."""
    props = {}
    field_map = {
        'Tel_Standard': 'phone',
        'Industrie': 'industrie',
        'LinkedIn_URL': 'hs_linkedin_url',
        'Poste_Decideur': 'jobtitle',
        'Adresse': 'address',
        'Code_Postal': 'zip',
        'Pays': 'country',
    }
    for src, dst in field_map.items():
        val = lead.get(src)
        if val and str(val).strip():
            props[dst] = val
    return props


# ───────────────────────────────────────────────────────────────
# Phase 2-5: Batch operations
# ───────────────────────────────────────────────────────────────

def _chunked(items, size):
    """Yield successive chunks of a list."""
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _batch_create_companies(client, plans):
    """Batch create companies for plans that need them. Updates plan['company_id']."""
    for chunk in _chunked(plans, BATCH_CHUNK_SIZE):
        inputs = []
        for plan in chunk:
            props = _build_company_properties(plan['lead'])
            if props.get('name'):
                inputs.append({"properties": props})

        if not inputs:
            continue

        try:
            result = sdk_call_with_retry(
                lambda inp=inputs: client.crm.companies.batch_api.create(
                    batch_input_simple_public_object_batch_input_for_create={"inputs": inp}
                ),
                label="HubSpot batch-company-create"
            )
            created = result.results if hasattr(result, 'results') else []
            created_by_domain = {}
            created_by_name = {}
            for obj in created:
                d = getattr(obj, 'properties', {}).get('domain', '')
                n = getattr(obj, 'properties', {}).get('name', '')
                if d:
                    created_by_domain[d] = obj.id
                if n:
                    created_by_name[n] = obj.id

            for plan in chunk:
                lead = plan['lead']
                domain = lead.get('Site_Web', '').replace('https://', '').replace('http://', '').split('/')[0]
                name = lead.get('Nom_Entreprise', '')
                cid = created_by_domain.get(domain) or created_by_name.get(name)
                if cid:
                    plan['company_id'] = cid

            print(f"    🏢 Batch created {len(created)} companies")

        except Exception as e:
            print(f"    ❌ Batch company create error: {str(e)[:200]}")
            _fallback_create_companies_sequential(client, chunk)


def _fallback_create_companies_sequential(client, plans):
    """Fallback: create companies one by one if batch fails."""
    for plan in plans:
        lead = plan['lead']
        name = lead.get('Nom_Entreprise', '')
        if not name:
            continue
        try:
            props = _build_company_properties(lead)
            company_input = CompanyInput(properties=props)
            company = sdk_call_with_retry(
                lambda ci=company_input: client.crm.companies.basic_api.create(
                    simple_public_object_input_for_create=ci
                ),
                label="HubSpot company-create"
            )
            plan['company_id'] = company.id
        except Exception as e:
            print(f"    ⚠️  Company create failed for {name}: {str(e)[:80]}")


def _batch_create_contacts(client, plans):
    """Batch create contacts. Updates plan['contact_id'] and lead statuses."""
    for chunk in _chunked(plans, BATCH_CHUNK_SIZE):
        inputs = []
        email_to_plan = {}
        idx_to_plan = {}

        for i, plan in enumerate(chunk):
            props = _build_contact_properties(plan['lead'])
            inputs.append({"properties": props})
            email = plan['lead'].get('Email_Generique', '')
            if email:
                email_to_plan[email.lower()] = plan
            idx_to_plan[i] = plan

        if not inputs:
            continue

        try:
            result = sdk_call_with_retry(
                lambda inp=inputs: client.crm.contacts.batch_api.create(
                    batch_input_simple_public_object_batch_input_for_create={"inputs": inp}
                ),
                label="HubSpot batch-contact-create"
            )
            created = result.results if hasattr(result, 'results') else []

            for obj in created:
                email = getattr(obj, 'properties', {}).get('email', '')
                plan = email_to_plan.get(email.lower()) if email else None
                if plan:
                    plan['contact_id'] = obj.id
                    plan['lead']['Statut_Sync'] = 'Synced'
                    plan['lead']['HubSpot_ID'] = str(obj.id)

            # Handle contacts without email — match by index order
            if len(created) == len(inputs):
                for i, obj in enumerate(created):
                    plan = idx_to_plan[i]
                    if not plan.get('contact_id'):
                        plan['contact_id'] = obj.id
                        plan['lead']['Statut_Sync'] = 'Synced'
                        plan['lead']['HubSpot_ID'] = str(obj.id)

            print(f"    ✅ Batch created {len(created)} contacts")

        except Exception as e:
            print(f"    ❌ Batch contact create error: {str(e)[:200]}")
            _fallback_create_contacts_sequential(client, chunk)


def _fallback_create_contacts_sequential(client, plans):
    """Fallback: create contacts one by one if batch fails."""
    for plan in plans:
        lead = plan['lead']
        try:
            props = _build_contact_properties(lead)
            contact_input = SimplePublicObjectInputForCreate(properties=props)
            contact = sdk_call_with_retry(
                lambda ci=contact_input: client.crm.contacts.basic_api.create(
                    simple_public_object_input_for_create=ci
                ),
                label="HubSpot contact-create"
            )
            plan['contact_id'] = contact.id
            lead['Statut_Sync'] = 'Synced'
            lead['HubSpot_ID'] = str(contact.id)
        except Exception as e:
            lead['Statut_Sync'] = 'Failed'
            print(f"    ⚠️  Contact create failed for {lead.get('Nom_Entreprise', '?')}: {str(e)[:80]}")
        sleep(0.3)


def _batch_update_contacts(client, plans):
    """Batch update existing contacts with new data."""
    for chunk in _chunked(plans, BATCH_CHUNK_SIZE):
        inputs = []
        for plan in chunk:
            props = _build_update_properties(plan['lead'])
            if not props:
                plan['lead']['Statut_Sync'] = 'Synced'
                plan['lead']['HubSpot_ID'] = str(plan['contact_id'])
                continue
            inputs.append({"id": str(plan['contact_id']), "properties": props})

        if not inputs:
            for plan in chunk:
                plan['lead']['Statut_Sync'] = 'Synced'
                plan['lead']['HubSpot_ID'] = str(plan['contact_id'])
            continue

        try:
            sdk_call_with_retry(
                lambda inp=inputs: client.crm.contacts.batch_api.update(
                    batch_input_simple_public_object_batch_input={"inputs": inp}
                ),
                label="HubSpot batch-contact-update"
            )
            for plan in chunk:
                plan['lead']['Statut_Sync'] = 'Synced'
                plan['lead']['HubSpot_ID'] = str(plan['contact_id'])

            print(f"    ♻️  Batch updated {len(inputs)} contacts")

        except Exception as e:
            print(f"    ❌ Batch contact update error: {str(e)[:200]}")
            for plan in chunk:
                plan['lead']['Statut_Sync'] = 'Synced'
                plan['lead']['HubSpot_ID'] = str(plan['contact_id'])


def _batch_associate_contacts_to_companies(client, plans):
    """Batch associate contacts with their companies."""
    for chunk in _chunked(plans, BATCH_CHUNK_SIZE):
        try:
            from hubspot.crm.associations.v4 import BatchInputPublicDefaultAssociationMultiPost
            from hubspot.crm.associations.v4.models import PublicDefaultAssociationMultiPost

            inputs = []
            for plan in chunk:
                inputs.append(PublicDefaultAssociationMultiPost(
                    _from={"id": str(plan['contact_id'])},
                    to={"id": str(plan['company_id'])}
                ))

            if not inputs:
                continue

            association_input = BatchInputPublicDefaultAssociationMultiPost(inputs=inputs)
            sdk_call_with_retry(
                lambda ai=association_input: client.crm.associations.v4.batch_api.create_default(
                    from_object_type="contacts",
                    to_object_type="companies",
                    batch_input_public_default_association_multi_post=ai
                ),
                label="HubSpot batch-association"
            )
            print(f"    🔗 Batch associated {len(inputs)} contacts → companies")

        except Exception as e:
            if '409' not in str(e):
                print(f"    ⚠️  Batch association error: {str(e)[:100]}")


# ───────────────────────────────────────────────────────────────
# Single-lead upsert (called from qualify_site.py)
# ───────────────────────────────────────────────────────────────

_hubspot_client = None


def _get_contacts_for_company(client, company_id):
    """Get existing contacts associated with a company. Returns first contact_id or None."""
    if not company_id:
        return None
    try:
        assocs = sdk_call_with_retry(
            lambda cid=company_id: client.crm.companies.associations_api.get_all(
                company_id=cid, to_object_type="contacts"
            ),
            label="HubSpot company-associations"
        )
        results = assocs.results if hasattr(assocs, 'results') else []
        if results:
            return str(results[0].to_object_id)
    except Exception:
        pass
    return None


def upsert_single_lead(lead):
    """Create or update a single lead in HubSpot (company + contact + association).

    Dedup strategy (in order):
      1. Search contact by email (if available)
      2. Search contact by company name / website domain
      3. If company already exists in HubSpot, check its associated contacts
      4. Only create if nothing found

    Returns True on success, False on error.
    """
    global _hubspot_client
    if not HUBSPOT_API_KEY:
        return False

    try:
        if _hubspot_client is None:
            _hubspot_client = init_hubspot_client()
        client = _hubspot_client
    except Exception:
        return False

    company_name = lead.get('Nom_Entreprise', '')
    email = lead.get('Email_Generique', '').strip()

    try:
        company_id = _search_company(client, lead)

        contact_id = None
        if email:
            contact_id = _search_contact_by_email(client, email)
        if not contact_id:
            contact_id = _search_contact_by_company(client, lead)
        if not contact_id and company_id:
            contact_id = _get_contacts_for_company(client, company_id)

        if not company_id and company_name:
            props = _build_company_properties(lead)
            company = sdk_call_with_retry(
                lambda p=props: client.crm.companies.basic_api.create(
                    simple_public_object_input_for_create=CompanyInput(properties=p)
                ),
                label="HubSpot company-create"
            )
            company_id = company.id

        if contact_id:
            update_props = _build_update_properties(lead)
            if update_props:
                sdk_call_with_retry(
                    lambda cid=contact_id, p=update_props: client.crm.contacts.basic_api.update(
                        contact_id=cid,
                        simple_public_object_input={"properties": p}
                    ),
                    label="HubSpot contact-update"
                )
        else:
            props = _build_contact_properties(lead)
            contact = sdk_call_with_retry(
                lambda p=props: client.crm.contacts.basic_api.create(
                    simple_public_object_input_for_create=SimplePublicObjectInputForCreate(properties=p)
                ),
                label="HubSpot contact-create"
            )
            contact_id = contact.id

        if contact_id and company_id:
            try:
                from hubspot.crm.associations.v4.models import PublicDefaultAssociationMultiPost
                from hubspot.crm.associations.v4 import BatchInputPublicDefaultAssociationMultiPost
                assoc_input = BatchInputPublicDefaultAssociationMultiPost(
                    inputs=[PublicDefaultAssociationMultiPost(
                        _from={"id": str(contact_id)}, to={"id": str(company_id)}
                    )]
                )
                sdk_call_with_retry(
                    lambda ai=assoc_input: client.crm.associations.v4.batch_api.create_default(
                        from_object_type="contacts", to_object_type="companies",
                        batch_input_public_default_association_multi_post=ai
                    ),
                    label="HubSpot association"
                )
            except Exception:
                pass

        lead['Statut_Sync'] = 'Synced'
        lead['HubSpot_ID'] = str(contact_id)
        return True

    except Exception as e:
        lead['Statut_Sync'] = 'Failed'
        logging.warning(f"HubSpot upsert failed for {company_name}: {str(e)[:100]}")
        return False


# ───────────────────────────────────────────────────────────────
# Main sync orchestrator
# ───────────────────────────────────────────────────────────────

def sync_leads(input_file, write_log=False):
    """Sync all leads to HubSpot using batch APIs.

    Args:
        input_file: Path to enriched leads JSON
        write_log: If True, write a structured sync log to .tmp/
    """
    client = init_hubspot_client()

    print("🔧 Checking custom HubSpot properties...")
    ensure_custom_properties(client)

    with open(input_file, 'r', encoding='utf-8') as f:
        leads = json.load(f)

    total = len(leads)
    print(f"📋 Syncing {total} leads to HubSpot (batch mode)...\n")

    # ── Phase 1: Search existing records ──
    print("  Phase 1/5: Searching existing records...")
    plans = []
    skipped = 0

    for i, lead in enumerate(leads):
        plan = {'idx': i, 'lead': lead, 'action': None, 'company_id': None, 'contact_id': None}

        if lead.get('Statut_Sync') == 'Deleted':
            plan['action'] = 'skip'
            plans.append(plan)
            skipped += 1
            continue

        plan['company_id'] = _search_company(client, lead)

        email = lead.get('Email_Generique', '').strip()
        plan['contact_id'] = _search_contact_by_email(client, email)

        if not plan['contact_id'] and not email:
            plan['contact_id'] = _search_contact_by_company(client, lead)
            if plan['contact_id']:
                print(f"    🔍 Found existing contact for {lead.get('Nom_Entreprise', '?')} via company name/domain")

        plan['action'] = 'update' if plan['contact_id'] else 'create'
        plans.append(plan)
        sleep(0.2)

    existing_companies = sum(1 for p in plans if p['company_id'] and p['action'] != 'skip')
    existing_contacts = sum(1 for p in plans if p['contact_id'] and p['action'] != 'skip')
    print(f"    Found {existing_companies} existing companies, {existing_contacts} existing contacts, {skipped} skipped")

    # ── Phase 2: Batch create companies ──
    needs_company = [p for p in plans if p['action'] != 'skip' and p['company_id'] is None
                     and p['lead'].get('Nom_Entreprise')]
    if needs_company:
        print(f"  Phase 2/5: Batch creating {len(needs_company)} companies...")
        _batch_create_companies(client, needs_company)
    else:
        print("  Phase 2/5: No companies to create")

    # ── Phase 3: Batch create contacts ──
    to_create = [p for p in plans if p['action'] == 'create']
    if to_create:
        print(f"  Phase 3/5: Batch creating {len(to_create)} contacts...")
        _batch_create_contacts(client, to_create)
    else:
        print("  Phase 3/5: No contacts to create")

    # ── Phase 4: Batch update contacts ──
    to_update = [p for p in plans if p['action'] == 'update']
    if to_update:
        print(f"  Phase 4/5: Batch updating {len(to_update)} contacts...")
        _batch_update_contacts(client, to_update)
    else:
        print("  Phase 4/5: No contacts to update")

    # ── Phase 5: Batch associate ──
    to_associate = [p for p in plans if p['contact_id'] and p['company_id'] and p['action'] != 'skip']
    if to_associate:
        print(f"  Phase 5/5: Batch associating {len(to_associate)} contacts → companies...")
        _batch_associate_contacts_to_companies(client, to_associate)
    else:
        print("  Phase 5/5: No associations to create")

    # ── Results ──
    synced_count = sum(1 for p in plans if p['lead'].get('Statut_Sync') == 'Synced')
    failed_count = sum(1 for p in plans if p['lead'].get('Statut_Sync') == 'Failed')

    print(f"\n✅ Sync complete!")
    print(f"  📊 Total: {synced_count}/{total} contacts synced")
    if failed_count > 0:
        print(f"  ❌ Failed: {failed_count} contacts")
    if skipped > 0:
        print(f"  🚫 Skipped: {skipped} contacts (marked as Deleted)")

    # Save updated leads with HubSpot IDs
    with open(input_file, 'w', encoding='utf-8') as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)

    # Write structured sync log
    if write_log:
        log_dir = Path(input_file).parent
        log_filename = f"sync_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        log_path = log_dir / log_filename

        results = []
        for plan in plans:
            lead = plan['lead']
            results.append({
                "company": lead.get('Nom_Entreprise', 'Unknown'),
                "email": lead.get('Email_Generique', ''),
                "status": lead.get('Statut_Sync', 'Unknown'),
                "hubspot_id": lead.get('HubSpot_ID'),
            })

        log_data = {
            "run_date": datetime.now().isoformat(),
            "mode": "batch",
            "total": total,
            "synced": synced_count,
            "failed": failed_count,
            "skipped": skipped,
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

    sync_leads(input_path, write_log=args.write_log)

    print(f"\n✅ HubSpot sync complete!")
    print(f"\n💡 Tip: Check your HubSpot CRM to verify the data")

    save_tracker_snapshot("step4_hubspot")


if __name__ == '__main__':
    main()
