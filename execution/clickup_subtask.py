"""
ClickUp Subtask Creation
Creates subtasks under a parent task for tracking modeling requests.

Usage:
    python clickup_subtask.py --objet "Request title" --email "user@example.com" --ticket-url "https://..."
"""

import os
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
    parent_task_id: str = None
) -> dict:
    """
    Create a subtask under the parent modeling task.
    
    Args:
        objet: Request title
        user_email: Client email
        ticket_url: HubSpot ticket URL
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
    
    description = f"""**Demande de modélisation**

- **Client** : {user_email}
- **Objet** : {objet}
- **Ticket HubSpot** : {ticket_url}

---
Créé automatiquement par l'agent DOE."""

    # API payload - create task with parent to make it a subtask
    payload = {
        "name": name,
        "description": description,
        "parent": parent_id,  # This makes it a subtask
        "status": "to do",
        "priority": 3  # Normal priority
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


def main():
    parser = argparse.ArgumentParser(description="Create ClickUp subtask")
    parser.add_argument("--objet", required=True, help="Request title")
    parser.add_argument("--email", required=True, help="User email")
    parser.add_argument("--ticket-url", required=True, help="HubSpot ticket URL")
    parser.add_argument("--parent-id", help="Override parent task ID")
    parser.add_argument("--output", help="Output JSON file path")
    
    args = parser.parse_args()
    
    print(f"📋 Creating ClickUp subtask for: {args.email}")
    
    result = create_subtask(
        objet=args.objet,
        user_email=args.email,
        ticket_url=args.ticket_url,
        parent_task_id=args.parent_id
    )
    
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"💾 Result saved to {args.output}")
    
    return result


if __name__ == "__main__":
    main()
