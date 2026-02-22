"""
Watch Lead Status — HubSpot → ClickUp Prospection
Polls HubSpot contacts whose hs_lead_status changed to OPEN and creates
a ClickUp subtask under the Prospection task (86c8cryhk).

Tracking: stores the ClickUp subtask ID in a custom HubSpot contact property
`clickup_prospection_task_id` so processed contacts are never duplicated.

Usage:
    python watch_lead_status.py --mode poll --interval 60
    python watch_lead_status.py --mode once
"""

import os
import sys
import json
import argparse
import time
import logging
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
from tenacity import retry, stop_after_attempt, wait_exponential

from clickup_subtask import create_prospection_subtask

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
# FIND OPEN LEADS NOT YET SYNCED TO CLICKUP
# =============================================================================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def find_open_leads() -> List[Dict]:
    """
    Search HubSpot for contacts where:
      - hs_lead_status = OPEN
      - clickup_prospection_task_id is not set (NOT_HAS_PROPERTY)
    """
    client = get_hubspot_client()

    search_request = {
        "filterGroups": [{
            "filters": [
                {
                    "propertyName": "hs_lead_status",
                    "operator": "EQ",
                    "value": "OPEN"
                },
                {
                    "propertyName": "clickup_prospection_task_id",
                    "operator": "NOT_HAS_PROPERTY"
                }
            ]
        }],
        "properties": [
            "firstname", "lastname", "email", "company",
            "clickup_prospection_task_id"
        ],
        "limit": 100
    }

    try:
        results = client.crm.contacts.search_api.do_search(
            public_object_search_request=search_request
        )
    except ApiException as e:
        logger.error(f"HubSpot search error: {e}")
        return []

    leads = []
    for contact in results.results:
        props = contact.properties
        firstname = props.get("firstname", "") or ""
        lastname = props.get("lastname", "") or ""
        contact_name = f"{firstname} {lastname}".strip() or props.get("email", "Sans nom")

        leads.append({
            "contact_id": contact.id,
            "contact_name": contact_name,
            "email": props.get("email", ""),
            "company": props.get("company", ""),
            "contact_url": f"https://app.hubspot.com/contacts/{HUBSPOT_HUB_ID}/contact/{contact.id}"
        })

    logger.info(f"Found {len(leads)} OPEN lead(s) not yet in ClickUp")
    return leads


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
# PROCESS A SINGLE LEAD
# =============================================================================

def process_lead(lead: Dict) -> bool:
    """Create ClickUp subtask and mark contact as processed."""
    logger.info(f"  → Processing: {lead['contact_name']} ({lead['email']})")

    result = create_prospection_subtask(
        contact_name=lead["contact_name"],
        contact_email=lead["email"],
        company=lead["company"],
        contact_url=lead["contact_url"]
    )

    if not result.get("success"):
        logger.error(f"  ❌ ClickUp subtask creation failed: {result.get('error')}")
        return False

    return mark_contact_processed(lead["contact_id"], result["subtask_id"])


# =============================================================================
# MAIN LOOPS
# =============================================================================

def run_once() -> int:
    """Single pass: find OPEN leads and process them. Returns count processed."""
    leads = find_open_leads()
    processed = 0
    for lead in leads:
        if process_lead(lead):
            processed += 1
    if processed:
        logger.info(f"✅ Processed {processed}/{len(leads)} lead(s)")
    return processed


def poll(interval_seconds: int = 60):
    """Continuous polling loop."""
    logger.info(f"Starting lead-status watcher (interval: {interval_seconds}s)")
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

    if args.mode == "poll":
        poll(args.interval)
    else:
        count = run_once()
        print(json.dumps({"processed": count}, indent=2))


if __name__ == "__main__":
    main()
