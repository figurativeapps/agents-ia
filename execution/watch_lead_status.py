"""
Watch Lead Status — HubSpot ↔ ClickUp Prospection (two-phase)

Phase 1: Detects contacts with hs_lead_status=OPEN, creates ClickUp subtask
          under Prospection task (86c8cryhk).
Phase 2: Detects completed ClickUp subtasks, downloads snapshot + URL,
          generates prospection PDF (overlay_pdf), uploads to R2,
          creates HubSpot note, sets hs_lead_status to IN_PROGRESS.

Usage:
    python watch_lead_status.py              # continuous polling (default)
    python watch_lead_status.py --mode once  # single pass
"""

import os
import sys
import json
import argparse
import time
import logging
import requests
from pathlib import Path
from typing import List, Dict
from dotenv import load_dotenv

execution_dir = Path(__file__).parent
if str(execution_dir) not in sys.path:
    sys.path.insert(0, str(execution_dir))

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

load_dotenv()

from hubspot import HubSpot
from hubspot.crm.contacts import ApiException
from hubspot.crm.properties.exceptions import NotFoundException as PropertyNotFoundException
from tenacity import retry, stop_after_attempt, wait_exponential

from clickup_subtask import (
    create_prospection_subtask,
    get_task_full,
    get_task_comments,
    find_attachment_url,
    get_custom_field_value,
)
from upload_files import upload_to_r2, download_file
from hubspot_ticket import create_note

HUBSPOT_API_KEY = os.getenv("HUBSPOT_API_KEY")
HUBSPOT_HUB_ID = os.getenv("HUBSPOT_HUB_ID", "147476643")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_hubspot_client() -> HubSpot:
    if not HUBSPOT_API_KEY:
        raise ValueError("HUBSPOT_API_KEY not found in .env")
    return HubSpot(access_token=HUBSPOT_API_KEY)


# =============================================================================
# ENSURE CUSTOM PROPERTY EXISTS
# =============================================================================

PROPERTY_NAME = "clickup_prospection_task_id"

PROSPECT_PROPERTIES = [
    {
        "name": PROPERTY_NAME,
        "label": "ClickUp Prospection Task ID",
        "field_type": "text",
        "description": "ClickUp subtask ID created when lead status changes to OPEN",
    },
    {
        "name": "prospect_objet",
        "label": "Objet à modéliser",
        "field_type": "text",
        "description": "Nom de l'objet à modéliser pour ce prospect",
    },
    {
        "name": "prospect_site_url",
        "label": "Site web client",
        "field_type": "text",
        "description": "URL du site web du client prospect",
    },
    {
        "name": "prospect_description",
        "label": "Description prospect",
        "field_type": "textarea",
        "description": "Description de ce qu'il faut faire pour ce prospect",
    },
]


def ensure_custom_property():
    """Create all prospect-related custom properties if they don't exist."""
    client = get_hubspot_client()
    from hubspot.crm.properties import PropertyCreate

    for prop_def in PROSPECT_PROPERTIES:
        name = prop_def["name"]
        try:
            client.crm.properties.core_api.get_by_name(
                object_type="contacts", property_name=name
            )
        except PropertyNotFoundException:
            logger.info(f"Creating property '{name}'...")
            client.crm.properties.core_api.create(
                object_type="contacts",
                property_create=PropertyCreate(
                    name=name,
                    label=prop_def["label"],
                    type="string",
                    field_type=prop_def["field_type"],
                    group_name="contactinformation",
                    description=prop_def["description"],
                ),
            )
            logger.info(f"✅ Property '{name}' created")

    logger.info("All prospect properties verified")


# =============================================================================
# FIND OPEN LEADS NOT YET SYNCED TO CLICKUP
# =============================================================================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def find_all_open_contacts() -> tuple[List[Dict], List[Dict]]:
    """
    Single HubSpot search for all OPEN contacts.
    Returns (new_leads, pending_completion):
      - new_leads: no subtask yet → Phase 1
      - pending_completion: subtask created → Phase 2
    """
    client = get_hubspot_client()

    search_request = {
        "filterGroups": [{
            "filters": [
                {
                    "propertyName": "hs_lead_status",
                    "operator": "EQ",
                    "value": "OPEN"
                }
            ]
        }],
        "properties": [
            "firstname", "lastname", "email", "company",
            "prospect_objet", "prospect_site_url", "prospect_description",
            PROPERTY_NAME
        ],
        "limit": 100
    }

    try:
        results = client.crm.contacts.search_api.do_search(
            public_object_search_request=search_request
        )
    except ApiException as e:
        logger.error(f"HubSpot search error: {e}")
        return [], []

    new_leads = []
    pending_completion = []

    for contact in results.results:
        props = contact.properties
        firstname = props.get("firstname", "") or ""
        lastname = props.get("lastname", "") or ""
        contact_name = f"{firstname} {lastname}".strip() or props.get("email", "Sans nom")
        subtask_id = props.get(PROPERTY_NAME)

        entry = {
            "contact_id": contact.id,
            "contact_name": contact_name,
            "email": props.get("email", ""),
            "company": props.get("company", ""),
            "contact_url": f"https://app-eu1.hubspot.com/contacts/{HUBSPOT_HUB_ID}/contact/{contact.id}",
        }

        if subtask_id:
            entry["subtask_id"] = subtask_id
            pending_completion.append(entry)
        else:
            entry["prospect_info"] = {
                "objet": props.get("prospect_objet", ""),
                "site_url": props.get("prospect_site_url", ""),
                "description": props.get("prospect_description", ""),
            }
            new_leads.append(entry)

    logger.info(f"Found {len(new_leads)} new lead(s), {len(pending_completion)} pending completion")
    return new_leads, pending_completion


# =============================================================================
# MARK CONTACT AS PROCESSED
# =============================================================================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def mark_contact_processed(contact_id: str, subtask_id: str) -> bool:
    """Write clickup_prospection_task_id on the HubSpot contact."""
    client = get_hubspot_client()
    try:
        from hubspot.crm.contacts import SimplePublicObjectInput
        client.crm.contacts.basic_api.update(
            contact_id=contact_id,
            simple_public_object_input=SimplePublicObjectInput(
                properties={"clickup_prospection_task_id": subtask_id}
            )
        )
        logger.info(f"  ✅ Marked contact {contact_id} with subtask {subtask_id}")
        return True
    except Exception as e:
        logger.error(f"  ❌ Failed to mark contact {contact_id}: {e}")
        return False


# =============================================================================
# PARSE PROSPECT INFO FROM HUBSPOT NOTE
# =============================================================================

import re

_IMG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
_HREF_RE = re.compile(r'<a[^>]+href=["\']([^"\']+)["\']', re.IGNORECASE)
_URL_RE = re.compile(r'https?://[^\s<>"\']+')
_TAG_RE = re.compile(r'<[^>]+>')


def _strip_html(html: str) -> str:
    """Strip HTML tags and decode entities."""
    text = _TAG_RE.sub(' ', html)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&nbsp;', ' ').replace('&#x27;', "'")
    return ' '.join(text.split())


def parse_prospect_note(contact_id: str) -> Dict | None:
    """
    Read the most recent non-empty note on a contact and extract:
      - site_url: first URL that isn't a HubSpot/image URL
      - description: plain text (excluding URLs)
      - image_urls: list of all image src URLs
    Returns dict or None if no usable note found.
    """
    client = get_hubspot_client()
    try:
        assoc = client.crm.associations.v4.basic_api.get_page(
            object_type="contacts",
            object_id=contact_id,
            to_object_type="notes",
            limit=5,
        )
    except Exception as e:
        logger.debug(f"Could not read note associations for {contact_id}: {e}")
        return None

    for result in assoc.results:
        note_id = result.to_object_id
        try:
            note = client.crm.objects.notes.basic_api.get_by_id(
                note_id=note_id,
                properties=["hs_note_body", "hs_timestamp"],
            )
            body = note.properties.get("hs_note_body", "") or ""
            if not body.strip():
                continue

            logger.debug(f"Note {note_id} raw HTML: {body[:500]}")

            # --- Extract from raw HTML before stripping tags ---
            image_urls = _IMG_RE.findall(body)
            href_urls = _HREF_RE.findall(body)

            # Plain text + URLs visible after stripping
            plain = _strip_html(body)
            plain_urls = _URL_RE.findall(plain)

            # Merge all discovered URLs (href first, then plain-text), deduplicated
            all_urls = list(dict.fromkeys(href_urls + plain_urls))

            image_url_set = set(image_urls)
            skip_domains = ("hubspot.com", "hubspotusercontent", "hsforms.com")

            # Site URL = first URL that isn't HubSpot infra or an image src
            site_url = None
            for u in all_urls:
                if u in image_url_set:
                    continue
                if any(d in u for d in skip_domains):
                    continue
                site_url = u
                break

            # Description = plain text with ALL discovered URLs removed
            desc_text = plain
            for u in all_urls:
                desc_text = desc_text.replace(u, '')
            for u in image_urls:
                desc_text = desc_text.replace(u, '')
            description = ' '.join(desc_text.split()).strip()

            logger.debug(f"Note {note_id} parsed → site_url={site_url}, "
                         f"description={description[:80]!r}, images={len(image_urls)}")

            if site_url or description or image_urls:
                return {
                    "site_url": site_url or "",
                    "description": description or "",
                    "image_urls": image_urls,
                }
        except Exception as exc:
            logger.debug(f"Error parsing note {note_id}: {exc}")
            continue

    return None


# =============================================================================
# PROCESS A SINGLE LEAD
# =============================================================================

def process_lead(lead: Dict) -> bool:
    """Create ClickUp subtask with prospect info and mark contact as processed."""
    logger.info(f"  → Processing: {lead['contact_name']} ({lead['email']})")

    # Primary source: parse the HubSpot note for all prospect info
    note_data = parse_prospect_note(lead["contact_id"])

    # Fallback to HubSpot properties if note is missing a field
    props = lead.get("prospect_info", {})
    prospect_info = {
        "site_url": (note_data or {}).get("site_url") or props.get("site_url", ""),
        "description": (note_data or {}).get("description") or props.get("description", ""),
        "image_urls": (note_data or {}).get("image_urls", []),
        "objet": props.get("objet", ""),
    }

    if prospect_info.get("image_urls"):
        logger.info(f"  📷 Found {len(prospect_info['image_urls'])} image(s) in note")
    if prospect_info.get("site_url"):
        logger.info(f"  🔗 Site client: {prospect_info['site_url']}")
    if prospect_info.get("description"):
        logger.info(f"  📝 Description: {prospect_info['description'][:80]}")

    result = create_prospection_subtask(
        contact_name=lead["contact_name"],
        contact_email=lead["email"],
        company=lead["company"],
        contact_url=lead["contact_url"],
        prospect_info=prospect_info if any(prospect_info.values()) else None,
    )

    if not result.get("success"):
        logger.error(f"  ❌ ClickUp subtask creation failed: {result.get('error')}")
        return False

    return mark_contact_processed(lead["contact_id"], result["subtask_id"])


# =============================================================================
# PHASE 2 — COMPLETED SUBTASKS → PDF + HUBSPOT NOTE
# =============================================================================

def _download_clickup_attachment(att_url: str, dest: Path) -> bool:
    """Download a ClickUp attachment (requires auth header)."""
    from clickup_subtask import get_headers as clickup_headers
    try:
        resp = requests.get(att_url, headers=clickup_headers(), timeout=60, stream=True)
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return True
    except Exception as e:
        logger.error(f"Download failed {att_url}: {e}")
        return False


def process_completed_subtask(contact: Dict) -> bool:
    """
    Handle a completed ClickUp subtask:
    1. Download snapshot.png from attachments
    2. Extract URL from comments
    3. Generate PDF via overlay_pdf
    4. Upload assets to R2
    5. Create HubSpot note
    6. Set hs_lead_status → IN_PROGRESS
    """
    subtask_id = contact["subtask_id"]
    company = contact["company"] or "prospect"

    task = get_task_full(subtask_id)
    if not task:
        logger.warning(f"  ⚠️  Subtask {subtask_id} not found in ClickUp")
        return False

    status = task["status"]
    status_type = task.get("status_type", "")
    is_complete = status in ("complete", "closed", "done") or status_type == "closed"
    if not is_complete:
        logger.debug(f"  Subtask {subtask_id} status='{status}' type='{status_type}' (not complete)")
        return False

    logger.info(f"  ✅ Subtask {subtask_id} is '{status}' — processing {contact['contact_name']}")

    # --- 1. Get attachments (snapshot.png, qrcode.png) ---
    snapshot_url = find_attachment_url(task["attachments"], "snapshot.png")
    qrcode_url = find_attachment_url(task["attachments"], "qrcode.png")

    if not snapshot_url:
        logger.error(f"  ❌ snapshot.png not found in subtask attachments")
        return False

    tmp_dir = Path(__file__).parent.parent / ".tmp"
    tmp_dir.mkdir(exist_ok=True)
    snapshot_path = tmp_dir / f"snapshot_{subtask_id}.png"
    qrcode_path = tmp_dir / f"qrcode_{subtask_id}.png"

    if not _download_clickup_attachment(snapshot_url, snapshot_path):
        return False

    if qrcode_url:
        _download_clickup_attachment(qrcode_url, qrcode_path)

    # --- 2. Get AR link and snapshot title from custom fields ---
    lead_url = get_custom_field_value(task, "lien ra")
    if not lead_url:
        logger.error(f"  ❌ 'lien ra' custom field is empty on subtask {subtask_id}")
        logger.error(f"     Custom fields: {[(f.get('name'), f.get('value')) for f in task.get('custom_fields', [])]}")
        _cleanup(snapshot_path, qrcode_path)
        return False

    snapshot_title = get_custom_field_value(task, "Titre snapshot") or contact["contact_name"]
    logger.info(f"  🔗 Lien RA: {lead_url}")
    logger.info(f"  🏷️  Titre snapshot: {snapshot_title}")

    # --- 3. Generate PDF via overlay_pdf ---
    try:
        from overlay_pdf import overlay_pdf as run_overlay

        project_root = Path(__file__).parent.parent
        template_path = project_root / "template_plaquette_co.pdf"
        if not template_path.exists():
            logger.error(f"  ❌ Template not found: {template_path}")
            _cleanup(snapshot_path, qrcode_path)
            return False

        company_slug = company.replace(" ", "_").replace("/", "-")
        from datetime import datetime as dt
        pdf_filename = f"{company_slug}_plaquette_{dt.now().strftime('%Y%m%d')}.pdf"
        output_dir = project_root / "output"
        output_dir.mkdir(exist_ok=True)
        pdf_path = output_dir / pdf_filename

        import fitz  # noqa: F401 — validate PyMuPDF is importable
        result_path = run_overlay(
            template_path=str(template_path),
            image_path=str(snapshot_path),
            url=lead_url,
            company=company,
            title=snapshot_title,
            image_rect=fitz.Rect(385, 370, 541, 526),
            qr_rect=fitz.Rect(671, 350, 776, 455),
            title_rect=fitz.Rect(388, 318, 538, 345),
            link_rect=None,
            page_num=0,
            output_path=str(pdf_path),
        )
        if not result_path:
            logger.error("  ❌ PDF generation failed")
            _cleanup(snapshot_path, qrcode_path)
            return False

        logger.info(f"  📄 PDF generated: {pdf_path}")
    except Exception as e:
        logger.error(f"  ❌ PDF generation error: {e}")
        _cleanup(snapshot_path, qrcode_path)
        return False

    # --- 4. Upload to R2 ---
    prefix = f"prospection/{company_slug}"
    r2_urls = {}

    r2_snapshot = upload_to_r2(snapshot_path, f"{prefix}/snapshot.png")
    if r2_snapshot:
        r2_urls["snapshot"] = r2_snapshot

    if qrcode_path.exists():
        r2_qr = upload_to_r2(qrcode_path, f"{prefix}/qrcode.png")
        if r2_qr:
            r2_urls["qrcode"] = r2_qr

    r2_pdf = upload_to_r2(Path(pdf_path), f"{prefix}/{pdf_filename}")
    if r2_pdf:
        r2_urls["pdf"] = r2_pdf

    # --- 5. Create HubSpot note ---
    note_body = f"<strong>Prospection — {company}</strong><br><br>"
    if r2_urls.get("snapshot"):
        note_body += f'<strong>Snapshot:</strong> <a href="{r2_urls["snapshot"]}">snapshot.png</a><br>'
    if r2_urls.get("qrcode"):
        note_body += f'<strong>QR Code:</strong> <a href="{r2_urls["qrcode"]}">qrcode.png</a><br>'
    note_body += f'<strong>URL:</strong> <a href="{lead_url}">{lead_url}</a><br>'
    if r2_urls.get("pdf"):
        note_body += f'<strong>Plaquette PDF:</strong> <a href="{r2_urls["pdf"]}">{pdf_filename}</a><br>'

    all_urls = [v for v in r2_urls.values()]
    create_note(
        contact_id=contact["contact_id"],
        objet=f"Prospection — {company}",
        fichiers_urls=all_urls,
        type_demande="PROSPECTION",
    )

    # --- 6. Update lead status → IN_PROGRESS ---
    try:
        from hubspot.crm.contacts import SimplePublicObjectInput
        client = get_hubspot_client()
        client.crm.contacts.basic_api.update(
            contact_id=contact["contact_id"],
            simple_public_object_input=SimplePublicObjectInput(
                properties={"hs_lead_status": "IN_PROGRESS"}
            ),
        )
        logger.info(f"  ✅ Lead status → IN_PROGRESS for contact {contact['contact_id']}")
    except Exception as e:
        logger.error(f"  ❌ Failed to update lead status: {e}")

    _cleanup(snapshot_path, qrcode_path)
    logger.info(f"  🎉 Completed processing for {contact['contact_name']}")
    return True


def _cleanup(*paths):
    for p in paths:
        try:
            if p and Path(p).exists():
                Path(p).unlink()
        except Exception:
            pass


# =============================================================================
# MAIN LOOPS
# =============================================================================

def run_once() -> int:
    """Single pass: Phase 1 (OPEN → subtask) + Phase 2 (complete → PDF/note)."""
    new_leads, pending = find_all_open_contacts()

    # Phase 1 — new OPEN leads → create ClickUp subtasks
    created = 0
    for lead in new_leads:
        if process_lead(lead):
            created += 1
    if created:
        logger.info(f"✅ Phase 1: created {created}/{len(new_leads)} subtask(s)")

    # Phase 2 — completed subtasks → PDF + HubSpot note
    completed = 0
    for contact in pending:
        if process_completed_subtask(contact):
            completed += 1
    if completed:
        logger.info(f"✅ Phase 2: processed {completed}/{len(pending)} completed subtask(s)")

    return created + completed


def poll(interval_seconds: int = 60):
    """Continuous polling loop."""
    logger.info(f"Starting lead-status watcher (interval: {interval_seconds}s)")
    ensure_custom_property()
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            logger.info("Polling stopped by user")
            break
        except Exception as e:
            logger.error(f"Polling error: {e}")

        logger.info(f"💤 Sleeping {interval_seconds}s...")
        try:
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            logger.info("Polling stopped by user")
            break


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Watch HubSpot lead status and create ClickUp prospection subtasks"
    )
    parser.add_argument(
        "--mode", default="poll", choices=["poll", "once"],
        help="'poll' for continuous loop (default), 'once' for a single pass"
    )
    parser.add_argument(
        "--interval", type=int, default=60,
        help="Polling interval in seconds (default: 60)"
    )
    args = parser.parse_args()

    ensure_custom_property()

    if args.mode == "poll":
        poll(args.interval)
    else:
        count = run_once()
        print(json.dumps({"processed": count}, indent=2))


if __name__ == "__main__":
    main()
