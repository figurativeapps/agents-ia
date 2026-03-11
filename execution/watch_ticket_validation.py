"""
Watch Ticket Validation — HubSpot → ClickUp Modeling Subtask

Polls HubSpot for tickets where validation_status has been changed to
"validated" or "rejected" by the user, then acts accordingly:

- validated → reads last contact note + credits_estimes → creates ClickUp subtask
- rejected  → closes the ticket

Usage:
    python watch_ticket_validation.py              # continuous polling (default)
    python watch_ticket_validation.py --mode once  # single pass
"""

import os
import sys
import re
import json
import argparse
import time
import logging
from pathlib import Path
from typing import List, Dict, Optional
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
from tenacity import retry, stop_after_attempt, wait_exponential

from hubspot_ticket import (
    get_hubspot_client,
    update_ticket_property,
    ensure_custom_properties,
)
from clickup_subtask import create_subtask, get_task_full

HUBSPOT_HUB_ID = os.getenv("HUBSPOT_HUB_ID", "147476643")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r'<[^>]+>')


def _strip_html(html: str) -> str:
    """Strip HTML tags and decode entities."""
    text = _TAG_RE.sub(' ', html)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&nbsp;', ' ').replace('&#x27;', "'")
    return ' '.join(text.split())


# =============================================================================
# FIND TICKETS BY VALIDATION STATUS
# =============================================================================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def find_tickets_by_validation_status(status: str) -> List[Dict]:
    """
    Search HubSpot for tickets with a given validation_status.
    Returns list of ticket dicts with properties and associated contact_id.
    """
    client = get_hubspot_client()

    search_request = {
        "filterGroups": [{
            "filters": [{
                "propertyName": "validation_status",
                "operator": "EQ",
                "value": status
            }]
        }],
        "properties": [
            "subject", "content", "validation_status", "credits_estimes",
            "clickup_subtask_id", "hs_pipeline_stage", "hs_lastmodifieddate",
            "fichiers_urls",
        ],
        "limit": 50
    }

    results = client.crm.tickets.search_api.do_search(
        public_object_search_request=search_request
    )

    tickets = []
    for ticket in results.results:
        # Get associated contact
        contact_id = None
        try:
            assoc = client.crm.associations.v4.basic_api.get_page(
                object_type="tickets",
                object_id=ticket.id,
                to_object_type="contacts",
                limit=1
            )
            if assoc.results:
                contact_id = assoc.results[0].to_object_id
        except Exception:
            pass

        tickets.append({
            "ticket_id": ticket.id,
            "subject": ticket.properties.get("subject", ""),
            "content": ticket.properties.get("content", ""),
            "validation_status": ticket.properties.get("validation_status", ""),
            "credits_estimes": ticket.properties.get("credits_estimes"),
            "clickup_subtask_id": ticket.properties.get("clickup_subtask_id"),
            "hs_pipeline_stage": ticket.properties.get("hs_pipeline_stage"),
            "fichiers_urls": ticket.properties.get("fichiers_urls", ""),
            "contact_id": contact_id,
        })

    return tickets


def find_validated_tickets() -> List[Dict]:
    """Find tickets with validation_status=validated that don't yet have a ClickUp subtask."""
    tickets = find_tickets_by_validation_status("validated")
    return [t for t in tickets if not t.get("clickup_subtask_id")]


def find_rejected_tickets() -> List[Dict]:
    """Find tickets with validation_status=rejected that are still open."""
    tickets = find_tickets_by_validation_status("rejected")
    # Stage "4" = closed in HubSpot default pipeline
    return [t for t in tickets if t.get("hs_pipeline_stage") != "4"]


# =============================================================================
# READ LAST NOTE FROM CONTACT
# =============================================================================

def read_last_note(contact_id: str) -> Optional[str]:
    """
    Read the most recent non-empty note on a contact.
    Returns plain text body or None.
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
        logger.warning(f"Could not read note associations for contact {contact_id}: {e}")
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

            plain = _strip_html(body)
            if plain.strip():
                return plain.strip()
        except Exception as exc:
            logger.debug(f"Error reading note {note_id}: {exc}")
            continue

    return None


# =============================================================================
# PROCESS VALIDATED TICKET
# =============================================================================

def process_validated_ticket(ticket: Dict) -> bool:
    """
    Process a validated ticket:
    1. Read last note from the contact (modeling request details)
    2. Create ClickUp subtask with note content + credits
    3. Store clickup_subtask_id on the ticket
    """
    ticket_id = ticket["ticket_id"]
    contact_id = ticket.get("contact_id")
    subject = ticket.get("subject", "Demande modelisation")
    credits = int(ticket.get("credits_estimes") or 2)

    logger.info(f"Processing validated ticket #{ticket_id}: {subject}")

    if not contact_id:
        logger.warning(f"Ticket #{ticket_id} has no associated contact — skipping")
        return False

    # Get contact email
    client = get_hubspot_client()
    try:
        contact = client.crm.contacts.basic_api.get_by_id(
            contact_id=contact_id,
            properties=["email", "firstname", "lastname"]
        )
        user_email = contact.properties.get("email", "unknown@email.com")
    except Exception as e:
        logger.warning(f"Could not get contact email: {e}")
        user_email = "unknown@email.com"

    # Read last note from contact
    note_text = read_last_note(contact_id)
    if not note_text:
        logger.warning(f"Ticket #{ticket_id}: no note found on contact {contact_id} — skipping (will retry next cycle)")
        return False

    # Build description with note + credits
    description = f"{note_text}\n\n---\n\n**Credits valides : {credits}**"

    # Parse fichiers_urls if present
    fichiers_urls = []
    raw_urls = ticket.get("fichiers_urls", "")
    if raw_urls:
        fichiers_urls = [u.strip() for u in raw_urls.split("\n") if u.strip()]

    ticket_url = f"https://app-eu1.hubspot.com/contacts/{HUBSPOT_HUB_ID}/ticket/{ticket_id}"

    # Create ClickUp subtask
    subtask_result = create_subtask(
        objet=subject,
        user_email=user_email,
        ticket_url=ticket_url,
        description=description,
        fichiers_urls=fichiers_urls,
    )

    subtask_id = subtask_result.get("subtask_id")
    if subtask_id:
        # Store subtask ID on ticket (marks as processed)
        update_ticket_property(ticket_id, "clickup_subtask_id", subtask_id)
        logger.info(f"Ticket #{ticket_id} → ClickUp subtask {subtask_id} created ({credits} credits)")
        return True
    else:
        logger.error(f"Ticket #{ticket_id}: subtask creation failed — {subtask_result.get('error')}")
        return False


# =============================================================================
# PHASE 2: DETECT COMPLETED CLICKUP SUBTASKS → CLOSE TICKET
# =============================================================================

def find_completed_subtask_tickets() -> List[Dict]:
    """
    Find tickets with validation_status=validated AND a clickup_subtask_id set,
    then check if the ClickUp subtask is complete.
    """
    tickets = find_tickets_by_validation_status("validated")
    completed = []

    for ticket in tickets:
        subtask_id = ticket.get("clickup_subtask_id")
        if not subtask_id:
            continue  # No subtask yet — Phase 1 handles this

        # Already closed? Skip
        if ticket.get("hs_pipeline_stage") == "4":
            continue

        # Check ClickUp subtask status
        task = get_task_full(subtask_id)
        if not task:
            logger.warning(f"Ticket #{ticket['ticket_id']}: subtask {subtask_id} not found in ClickUp")
            continue

        task_status = task.get("status", "")
        task_status_type = task.get("status_type", "")
        is_complete = task_status in ("complete", "closed", "done") or task_status_type == "closed"

        if is_complete:
            ticket["subtask_status"] = task_status
            completed.append(ticket)

    return completed


def process_completed_subtask(ticket: Dict) -> bool:
    """Close a ticket whose ClickUp subtask is complete."""
    ticket_id = ticket["ticket_id"]
    subtask_id = ticket.get("clickup_subtask_id", "")
    subject = ticket.get("subject", "")

    logger.info(f"Subtask {subtask_id} complete → closing ticket #{ticket_id}: {subject}")

    result = update_ticket_property(ticket_id, "hs_pipeline_stage", "4")
    if result.get("success"):
        logger.info(f"Ticket #{ticket_id} closed (modeling complete)")
        return True
    else:
        logger.error(f"Ticket #{ticket_id}: failed to close — {result.get('error')}")
        return False


# =============================================================================
# PROCESS REJECTED TICKET
# =============================================================================

def process_rejected_ticket(ticket: Dict) -> bool:
    """Close a rejected ticket (set pipeline stage to 4 = closed)."""
    ticket_id = ticket["ticket_id"]
    subject = ticket.get("subject", "")

    logger.info(f"Processing rejected ticket #{ticket_id}: {subject}")

    result = update_ticket_property(ticket_id, "hs_pipeline_stage", "4")
    if result.get("success"):
        logger.info(f"Ticket #{ticket_id} closed (rejected)")
        return True
    else:
        logger.error(f"Ticket #{ticket_id}: failed to close — {result.get('error')}")
        return False


# =============================================================================
# MAIN LOOPS
# =============================================================================

def run_once() -> int:
    """Single pass: Phase 1 (validated/rejected) + Phase 2 (subtask complete)."""
    processed = 0

    # Phase 1a: Validated tickets → ClickUp subtask
    validated = find_validated_tickets()
    if validated:
        logger.info(f"Phase 1: {len(validated)} validated ticket(s) to process")
    for ticket in validated:
        if process_validated_ticket(ticket):
            processed += 1

    # Phase 1b: Rejected tickets → close
    rejected = find_rejected_tickets()
    if rejected:
        logger.info(f"Phase 1: {len(rejected)} rejected ticket(s) to close")
    for ticket in rejected:
        if process_rejected_ticket(ticket):
            processed += 1

    # Phase 2: Completed ClickUp subtasks → close ticket
    completed = find_completed_subtask_tickets()
    if completed:
        logger.info(f"Phase 2: {len(completed)} completed subtask(s) → closing tickets")
    for ticket in completed:
        if process_completed_subtask(ticket):
            processed += 1

    return processed


def poll(interval_seconds: int = 60):
    """Continuous polling loop."""
    logger.info(f"Starting ticket-validation watcher (interval: {interval_seconds}s)")
    ensure_custom_properties()
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            logger.info("Polling stopped by user")
            break
        except Exception as e:
            logger.error(f"Polling error: {e}")

        logger.info(f"Sleeping {interval_seconds}s...")
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
        description="Watch HubSpot ticket validation_status and create ClickUp subtasks"
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

    ensure_custom_properties()

    if args.mode == "poll":
        poll(args.interval)
    else:
        count = run_once()
        print(json.dumps({"processed": count}, indent=2))


if __name__ == "__main__":
    main()
