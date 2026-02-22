"""
ClickUp Subtask Creation and Management
Creates and updates subtasks under a parent task for tracking modeling requests.
Supports conversation threading with description updates.

Usage:
    python clickup_subtask.py --action create --objet "Request title" --email "user@example.com" --ticket-url "https://..." --description "Content" --fichiers-urls '["https://..."]'
    python clickup_subtask.py --action get --subtask-id "abc123"
    python clickup_subtask.py --action update --subtask-id "abc123" --new-message "Follow-up message" --new-fichiers-urls '["https://..."]'
"""

import os
import re
import sys
import json
import argparse
import requests
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Load environment variables
load_dotenv()

CLICKUP_API_KEY = os.getenv("CLICKUP_API_KEY")
CLICKUP_PARENT_TASK_ID = os.getenv("CLICKUP_PARENT_TASK_ID", "86c7r48ha")
CLICKUP_PROSPECTION_TASK_ID = os.getenv("CLICKUP_PROSPECTION_TASK_ID", "86c8cryhk")
CLICKUP_ASSIGNEE_ID = os.getenv("CLICKUP_ASSIGNEE_ID", "100557980")  # Yvanol Fotso by default
CLICKUP_API_BASE = "https://api.clickup.com/api/v2"


def get_headers():
    """Get API headers"""
    if not CLICKUP_API_KEY:
        raise ValueError("CLICKUP_API_KEY not found in .env")
    return {
        "Authorization": CLICKUP_API_KEY,
        "Content-Type": "application/json"
    }


def get_task_list_id(task_id: str) -> str | None:
    """Get the list ID for a given task"""
    url = f"{CLICKUP_API_BASE}/task/{task_id}"
    try:
        response = requests.get(url, headers=get_headers(), timeout=30)
        if response.status_code == 200:
            data = response.json()
            return data.get("list", {}).get("id")
    except Exception:
        pass
    return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def create_subtask(
    objet: str,
    user_email: str,
    ticket_url: str,
    description: str = None,
    fichiers_urls: list = None,
    parent_task_id: str = None
) -> dict:
    """
    Create a subtask under the parent modeling task.
    
    Args:
        objet: Request title
        user_email: Client email
        ticket_url: HubSpot ticket URL
        description: Full description/content of the original request
        fichiers_urls: List of R2 file URLs
        parent_task_id: Override parent task ID (optional)
    
    Returns:
        {
            "subtask_id": str,
            "subtask_url": str,
            "success": bool
        }
    """
    parent_id = parent_task_id or CLICKUP_PARENT_TASK_ID
    
    # First, get the list ID from the parent task
    list_id = get_task_list_id(parent_id)
    if not list_id:
        print(f"❌ Could not find list for parent task {parent_id}")
        return {
            "subtask_id": None,
            "error": f"Could not find list for parent task {parent_id}",
            "success": False
        }
    
    # Build subtask name and description
    name = f"Demande {user_email}"
    
    # Build full task description with all details
    task_description = f"""**Demande de modélisation**

**Client** : {user_email}
**Objet** : {objet}
**Ticket HubSpot** : {ticket_url}

---

## Description de la demande

{description or "(Aucune description fournie)"}

"""
    
    # Add files section if files are present
    if fichiers_urls and len(fichiers_urls) > 0:
        task_description += """---

## Fichiers joints

"""
        for url in fichiers_urls:
            # Extract filename from URL
            filename = url.split("/")[-1] if "/" in url else url
            task_description += f"- [{filename}]({url})\n"
    
    task_description += """
---
*Créé automatiquement par l'agent DOE.*"""

    # API payload - create task with parent to make it a subtask
    payload = {
        "name": name,
        "markdown_description": task_description,  # Use markdown for better formatting
        "parent": parent_id,  # This makes it a subtask
        "status": "to do",
        "priority": 3,  # Normal priority
        "assignees": [int(CLICKUP_ASSIGNEE_ID)] if CLICKUP_ASSIGNEE_ID else []  # Assign to Yvanol
    }
    
    # Create task in the list (with parent = subtask)
    url = f"{CLICKUP_API_BASE}/list/{list_id}/task"
    
    try:
        response = requests.post(
            url,
            headers=get_headers(),
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            subtask_id = data.get("id")
            subtask_url = data.get("url", f"https://app.clickup.com/t/{subtask_id}")
            
            print(f"✅ Created subtask: {subtask_id}")
            print(f"🔗 URL: {subtask_url}")
            
            return {
                "subtask_id": subtask_id,
                "subtask_url": subtask_url,
                "success": True
            }
        
        elif response.status_code == 401:
            print("❌ ClickUp API: Unauthorized - check your API key")
            return {
                "subtask_id": None,
                "error": "Unauthorized",
                "success": False
            }
        
        elif response.status_code == 429:
            print("⚠️  ClickUp API: Rate limit exceeded")
            raise Exception("Rate limit exceeded")  # Will trigger retry
        
        else:
            error_msg = response.text[:200]
            print(f"❌ ClickUp API error: {response.status_code} - {error_msg}")
            return {
                "subtask_id": None,
                "error": error_msg,
                "success": False
            }
            
    except requests.exceptions.Timeout:
        print("⚠️  ClickUp API: Request timeout")
        return {
            "subtask_id": None,
            "error": "Timeout",
            "success": False
        }
    except requests.exceptions.RequestException as e:
        print(f"❌ ClickUp API error: {str(e)[:200]}")
        return {
            "subtask_id": None,
            "error": str(e),
            "success": False
        }


# =============================================================================
# PROSPECTION SUBTASK
# =============================================================================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def create_prospection_subtask(
    contact_name: str,
    contact_email: str,
    company: str,
    contact_url: str
) -> dict:
    """
    Create a subtask under the Prospection parent task when a lead status
    changes to OPEN in HubSpot.

    Returns:
        {"subtask_id": str, "subtask_url": str, "success": bool}
    """
    parent_id = CLICKUP_PROSPECTION_TASK_ID

    list_id = get_task_list_id(parent_id)
    if not list_id:
        print(f"❌ Could not find list for Prospection task {parent_id}")
        return {
            "subtask_id": None,
            "error": f"Could not find list for parent task {parent_id}",
            "success": False
        }

    task_description = f"""**Entreprise** : {company or "(non renseigné)"}
**Email** : {contact_email}
**Contact HubSpot** : {contact_url}

---
*Créé automatiquement — lead passé en OPEN.*"""

    payload = {
        "name": contact_name,
        "markdown_description": task_description,
        "parent": parent_id,
        "status": "to do",
        "priority": 3,
        "assignees": [int(CLICKUP_ASSIGNEE_ID)] if CLICKUP_ASSIGNEE_ID else []
    }

    url = f"{CLICKUP_API_BASE}/list/{list_id}/task"

    try:
        response = requests.post(url, headers=get_headers(), json=payload, timeout=30)

        if response.status_code == 200:
            data = response.json()
            subtask_id = data.get("id")
            subtask_url = data.get("url", f"https://app.clickup.com/t/{subtask_id}")
            print(f"✅ Created prospection subtask: {subtask_id} — {contact_name}")
            print(f"🔗 URL: {subtask_url}")
            return {"subtask_id": subtask_id, "subtask_url": subtask_url, "success": True}

        elif response.status_code == 429:
            print("⚠️  ClickUp API: Rate limit exceeded")
            raise Exception("Rate limit exceeded")

        else:
            error_msg = response.text[:200]
            print(f"❌ ClickUp API error: {response.status_code} - {error_msg}")
            return {"subtask_id": None, "error": error_msg, "success": False}

    except requests.exceptions.Timeout:
        print("⚠️  ClickUp API: Request timeout")
        return {"subtask_id": None, "error": "Timeout", "success": False}
    except requests.exceptions.RequestException as e:
        print(f"❌ ClickUp API error: {str(e)[:200]}")
        return {"subtask_id": None, "error": str(e), "success": False}


# =============================================================================
# TASK INSPECTION (attachments, comments, status)
# =============================================================================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def get_task_full(task_id: str) -> dict | None:
    """
    Get full task data including status and attachments.

    Returns dict with keys: id, name, status, status_type, attachments, url — or None.
    """
    url = f"{CLICKUP_API_BASE}/task/{task_id}?include_subtasks=false"
    try:
        response = requests.get(url, headers=get_headers(), timeout=30)
        if response.status_code == 200:
            data = response.json()
            status_obj = data.get("status", {})
            status_name = status_obj.get("status", "").lower() if isinstance(status_obj, dict) else str(status_obj).lower()
            status_type = status_obj.get("type", "").lower() if isinstance(status_obj, dict) else ""
            return {
                "id": data.get("id"),
                "name": data.get("name"),
                "status": status_name,
                "status_type": status_type,
                "attachments": data.get("attachments", []),
                "url": data.get("url", f"https://app.clickup.com/t/{task_id}"),
            }
        elif response.status_code == 404:
            return None
        else:
            print(f"⚠️  get_task_full error: {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ get_task_full error: {str(e)[:200]}")
        return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def get_task_comments(task_id: str) -> list:
    """Return the list of comments for a task (newest first)."""
    url = f"{CLICKUP_API_BASE}/task/{task_id}/comment"
    try:
        response = requests.get(url, headers=get_headers(), timeout=30)
        if response.status_code == 200:
            return response.json().get("comments", [])
    except Exception as e:
        print(f"❌ get_task_comments error: {str(e)[:200]}")
    return []


_URL_RE = re.compile(r'https?://[^\s<>"\')\]]+')


def extract_url_from_comments(comments: list) -> str | None:
    """Parse comments (newest-first) and return the first http(s) URL found."""
    for comment in comments:
        text = comment.get("comment_text", "")
        match = _URL_RE.search(text)
        if match:
            return match.group(0)
    return None


def find_attachment_url(attachments: list, filename: str) -> str | None:
    """Find the download URL of an attachment by filename (case-insensitive)."""
    target = filename.lower()
    for att in attachments:
        att_title = (att.get("title") or att.get("name") or "").lower()
        if att_title == target or att_title.startswith(target.rsplit(".", 1)[0]):
            return att.get("url")
    return None


# =============================================================================
# SUBTASK UPDATE FUNCTIONS (for conversation threading)
# =============================================================================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def get_subtask(subtask_id: str) -> dict | None:
    """
    Get details of a subtask including its current description.
    
    Args:
        subtask_id: ClickUp task/subtask ID
    
    Returns:
        {
            "id": str,
            "name": str,
            "description": str,
            "url": str
        } or None if not found
    """
    url = f"{CLICKUP_API_BASE}/task/{subtask_id}"
    
    try:
        response = requests.get(url, headers=get_headers(), timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            return {
                "id": data.get("id"),
                "name": data.get("name"),
                "description": data.get("description", ""),
                "markdown_description": data.get("markdown_description", ""),
                "url": data.get("url", f"https://app.clickup.com/t/{subtask_id}")
            }
        elif response.status_code == 404:
            print(f"⚠️  Subtask not found: {subtask_id}")
            return None
        else:
            print(f"⚠️  Error getting subtask: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"❌ Error getting subtask: {str(e)[:200]}")
        return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def update_subtask_description(
    subtask_id: str,
    new_message: str,
    new_fichiers_urls: list = None,
    append_mode: bool = True
) -> dict:
    """
    Update a subtask's description with new message and/or files.
    
    When append_mode=True (default), the new content is APPENDED to the existing
    description, preserving the conversation history.
    
    Args:
        subtask_id: ClickUp subtask ID
        new_message: New message/description content to add
        new_fichiers_urls: List of new R2 file URLs to add
        append_mode: If True, append to existing description. If False, replace.
    
    Returns:
        {"success": bool, "subtask_id": str}
    """
    from datetime import datetime
    
    # First, get the current description if we're appending
    current_description = ""
    if append_mode:
        subtask = get_subtask(subtask_id)
        if subtask:
            current_description = subtask.get("markdown_description") or subtask.get("description") or ""
    
    # Build the new content to add
    timestamp = datetime.now().strftime("%d/%m/%Y à %H:%M")
    new_section = f"""

---

## Nouveau message ({timestamp})

{new_message}
"""
    
    # Add new files if provided
    if new_fichiers_urls and len(new_fichiers_urls) > 0:
        new_section += """
### Nouveaux fichiers joints

"""
        for url in new_fichiers_urls:
            filename = url.split("/")[-1] if "/" in url else url
            new_section += f"- [{filename}]({url})\n"
    
    # Combine descriptions
    if append_mode and current_description:
        final_description = current_description + new_section
    else:
        final_description = new_section
    
    # Update the task
    url = f"{CLICKUP_API_BASE}/task/{subtask_id}"
    payload = {
        "markdown_description": final_description
    }
    
    try:
        response = requests.put(
            url,
            headers=get_headers(),
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            print(f"✅ Updated subtask description: {subtask_id}")
            return {
                "success": True,
                "subtask_id": subtask_id,
                "files_added": len(new_fichiers_urls) if new_fichiers_urls else 0
            }
        else:
            error_msg = response.text[:200]
            print(f"❌ Error updating subtask: {response.status_code} - {error_msg}")
            return {
                "success": False,
                "subtask_id": subtask_id,
                "error": error_msg
            }
            
    except Exception as e:
        print(f"❌ Error updating subtask: {str(e)[:200]}")
        return {
            "success": False,
            "subtask_id": subtask_id,
            "error": str(e)
        }


def main():
    parser = argparse.ArgumentParser(description="ClickUp Subtask Management")
    parser.add_argument("--action", default="create", choices=["create", "get", "update"],
                        help="Action to perform (default: create)")
    
    # Create action arguments
    parser.add_argument("--objet", help="Request title (for create)")
    parser.add_argument("--email", help="User email (for create)")
    parser.add_argument("--ticket-url", help="HubSpot ticket URL (for create)")
    parser.add_argument("--description", help="Full request description/content (for create)")
    parser.add_argument("--fichiers-urls", help="JSON array of file URLs")
    parser.add_argument("--parent-id", help="Override parent task ID (for create)")
    
    # Get/Update action arguments
    parser.add_argument("--subtask-id", help="Subtask ID (for get/update)")
    parser.add_argument("--new-message", help="New message to append (for update)")
    parser.add_argument("--new-fichiers-urls", help="JSON array of new file URLs (for update)")
    
    parser.add_argument("--output", help="Output JSON file path")
    
    args = parser.parse_args()
    
    if args.action == "create":
        if not args.objet or not args.email or not args.ticket_url:
            print("❌ --objet, --email, and --ticket-url are required for create")
            sys.exit(1)
        
        fichiers_urls = json.loads(args.fichiers_urls) if args.fichiers_urls else []
        print(f"📋 Creating ClickUp subtask for: {args.email}")
        
        result = create_subtask(
            objet=args.objet,
            user_email=args.email,
            ticket_url=args.ticket_url,
            description=args.description,
            fichiers_urls=fichiers_urls,
            parent_task_id=args.parent_id
        )
    
    elif args.action == "get":
        if not args.subtask_id:
            print("❌ --subtask-id is required for get")
            sys.exit(1)
        
        print(f"🔍 Getting subtask: {args.subtask_id}")
        result = get_subtask(args.subtask_id)
        if result is None:
            result = {"found": False, "error": "Subtask not found"}
        else:
            result["found"] = True
    
    elif args.action == "update":
        if not args.subtask_id:
            print("❌ --subtask-id is required for update")
            sys.exit(1)
        if not args.new_message and not args.new_fichiers_urls:
            print("❌ --new-message or --new-fichiers-urls is required for update")
            sys.exit(1)
        
        new_fichiers_urls = json.loads(args.new_fichiers_urls) if args.new_fichiers_urls else []
        print(f"📝 Updating subtask: {args.subtask_id}")
        
        result = update_subtask_description(
            subtask_id=args.subtask_id,
            new_message=args.new_message or "",
            new_fichiers_urls=new_fichiers_urls
        )
    
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"💾 Result saved to {args.output}")
    
    return result


if __name__ == "__main__":
    main()
