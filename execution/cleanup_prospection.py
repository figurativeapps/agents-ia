"""
One-time cleanup: fix duplicate ClickUp subtasks under Prospection.

1. Lists all subtasks under Prospection parent task
2. Groups by name to detect duplicates
3. For each pair: keeps the one with attachments (original), deletes the empty one
4. Updates HubSpot contacts to point to the correct subtask ID

Usage:
    python execution/cleanup_prospection.py --dry-run   # preview only
    python execution/cleanup_prospection.py              # apply fixes
"""

import os
import sys
import requests
from pathlib import Path
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
from hubspot.crm.contacts import SimplePublicObjectInput

HUBSPOT_API_KEY = os.getenv("HUBSPOT_API_KEY")
CLICKUP_API_KEY = os.getenv("CLICKUP_API_KEY")
CLICKUP_API_BASE = "https://api.clickup.com/api/v2"
CLICKUP_PROSPECTION_TASK_ID = os.getenv("CLICKUP_PROSPECTION_TASK_ID", "86c8cryhk")
PROPERTY_NAME = "clickup_prospection_task_id"


def clickup_headers():
    return {"Authorization": CLICKUP_API_KEY, "Content-Type": "application/json"}


def get_subtasks(parent_id):
    """Get all subtasks of the Prospection parent task."""
    url = f"{CLICKUP_API_BASE}/task/{parent_id}?include_subtasks=true"
    resp = requests.get(url, headers=clickup_headers(), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    subtasks = data.get("subtasks", [])
    result = []
    for st in subtasks:
        status_obj = st.get("status", {})
        result.append({
            "id": st["id"],
            "name": st.get("name", ""),
            "status": status_obj.get("status", "").lower() if isinstance(status_obj, dict) else "",
            "status_type": status_obj.get("type", "").lower() if isinstance(status_obj, dict) else "",
            "has_attachments": len(st.get("attachments", [])) > 0,
            "custom_fields": st.get("custom_fields", []),
        })
    return result


def delete_clickup_task(task_id):
    """Delete a ClickUp task."""
    url = f"{CLICKUP_API_BASE}/task/{task_id}"
    resp = requests.delete(url, headers=clickup_headers(), timeout=30)
    return resp.status_code == 200


def find_hubspot_contact_by_subtask_id(client, subtask_id):
    """Find a HubSpot contact that has this subtask_id."""
    search_request = {
        "filterGroups": [{
            "filters": [{
                "propertyName": PROPERTY_NAME,
                "operator": "EQ",
                "value": subtask_id,
            }]
        }],
        "properties": ["firstname", "lastname", "email", PROPERTY_NAME],
        "limit": 1,
    }
    try:
        results = client.crm.contacts.search_api.do_search(
            public_object_search_request=search_request
        )
        if results.results:
            c = results.results[0]
            return {
                "id": c.id,
                "name": f"{c.properties.get('firstname', '')} {c.properties.get('lastname', '')}".strip(),
                "email": c.properties.get("email", ""),
                "current_subtask_id": c.properties.get(PROPERTY_NAME, ""),
            }
    except Exception as e:
        print(f"  HubSpot search error: {e}")
    return None


def update_contact_subtask_id(client, contact_id, new_subtask_id):
    """Update the clickup_prospection_task_id on a HubSpot contact."""
    client.crm.contacts.basic_api.update(
        contact_id=contact_id,
        simple_public_object_input=SimplePublicObjectInput(
            properties={PROPERTY_NAME: new_subtask_id}
        ),
    )


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Cleanup duplicate prospection subtasks")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    args = parser.parse_args()

    dry = args.dry_run
    if dry:
        print("=== DRY RUN — no changes will be made ===\n")

    client = HubSpot(access_token=HUBSPOT_API_KEY)

    # 1. Get all subtasks under Prospection
    print(f"Fetching subtasks under Prospection ({CLICKUP_PROSPECTION_TASK_ID})...")
    subtasks = get_subtasks(CLICKUP_PROSPECTION_TASK_ID)
    print(f"Found {len(subtasks)} subtask(s)\n")

    # 2. Group by name to detect duplicates
    by_name = {}
    for st in subtasks:
        name = st["name"]
        by_name.setdefault(name, []).append(st)

    for name, group in by_name.items():
        if len(group) < 2:
            print(f"  OK  {name} — no duplicate")
            continue

        print(f"\n  DUPLICATE  {name} ({len(group)} subtasks):")

        # Find the "original" (has attachments or is complete/in_progress) vs "duplicate" (to do, no attachments)
        originals = [s for s in group if s["has_attachments"] or s["status"] not in ("to do",)]
        duplicates = [s for s in group if s not in originals]

        if not originals:
            # If no clear original, keep the first non-to-do one
            originals = [group[0]]
            duplicates = group[1:]

        original = originals[0]
        print(f"    KEEP   {original['id']} (status={original['status']}, attachments={original['has_attachments']})")

        for dup in duplicates:
            print(f"    DELETE {dup['id']} (status={dup['status']}, attachments={dup['has_attachments']})")

            # Check if any HubSpot contact points to this duplicate
            contact = find_hubspot_contact_by_subtask_id(client, dup["id"])
            if contact:
                print(f"      -> HubSpot contact {contact['name']} ({contact['email']}) points to duplicate")
                print(f"         Updating {PROPERTY_NAME}: {dup['id']} -> {original['id']}")
                if not dry:
                    update_contact_subtask_id(client, contact["id"], original["id"])
                    print(f"         Updated!")

            # Delete the duplicate subtask
            print(f"      -> Deleting ClickUp subtask {dup['id']}")
            if not dry:
                if delete_clickup_task(dup["id"]):
                    print(f"         Deleted!")
                else:
                    print(f"         FAILED to delete")

    # 3. Also check if any contact points to NO subtask but should
    print("\n--- Checking OPEN contacts without subtask ID ---")
    search_request = {
        "filterGroups": [{
            "filters": [
                {"propertyName": "hs_lead_status", "operator": "EQ", "value": "OPEN"},
            ]
        }],
        "properties": ["firstname", "lastname", "email", PROPERTY_NAME],
        "limit": 100,
    }
    results = client.crm.contacts.search_api.do_search(
        public_object_search_request=search_request
    )
    for c in results.results:
        subtask_id = c.properties.get(PROPERTY_NAME, "")
        name = f"{c.properties.get('firstname', '')} {c.properties.get('lastname', '')}".strip()
        if not subtask_id:
            print(f"  WARNING: {name} ({c.properties.get('email', '')}) has hs_lead_status=OPEN but no subtask ID")

    print("\nDone!" + (" (dry run — no changes applied)" if dry else ""))


if __name__ == "__main__":
    main()
