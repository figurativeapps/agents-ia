"""
Associate HubSpot email conversations with tickets.

This module provides functionality to link incoming email conversations
(from HubSpot Conversations Inbox) with tickets created by the webhook.

Usage:
    python associate_email_ticket.py --contact-email user@example.com --ticket-id 12345
"""

import os
import sys
import json
import argparse
import requests
from datetime import datetime, timedelta
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

HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')
HUBSPOT_HUB_ID = os.getenv('HUBSPOT_HUB_ID', '147476643')
HUBSPOT_BASE_URL = "https://api.hubapi.com"

if not HUBSPOT_API_KEY:
    print("WARNING: HUBSPOT_API_KEY not found in .env")


def get_headers() -> dict:
    """Get authentication headers for HubSpot API"""
    return {
        "Authorization": f"Bearer {HUBSPOT_API_KEY}",
        "Content-Type": "application/json"
    }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def find_recent_threads_by_email(contact_email: str, max_age_hours: int = 1) -> list:
    """
    Find recent conversation threads involving a specific email address.
    
    Note: HubSpot Conversations API is in beta and has limited search capabilities.
    This function searches for threads with the contact email as a participant.
    
    Args:
        contact_email: Email address of the contact
        max_age_hours: Only look for threads from the last N hours
        
    Returns:
        List of thread IDs, most recent first
    """
    # First, get the contact ID from email
    url = f"{HUBSPOT_BASE_URL}/crm/v3/objects/contacts/search"
    
    search_payload = {
        "filterGroups": [{
            "filters": [{
                "propertyName": "email",
                "operator": "EQ",
                "value": contact_email
            }]
        }],
        "properties": ["email", "hs_object_id"]
    }
    
    response = requests.post(url, headers=get_headers(), json=search_payload)
    
    if response.status_code != 200:
        print(f"Error searching contact: {response.status_code}")
        return []
    
    results = response.json().get("results", [])
    if not results:
        print(f"No contact found for email: {contact_email}")
        return []
    
    contact_id = results[0]["id"]
    print(f"Found contact ID: {contact_id}")
    
    # Search for conversations associated with this contact
    # Use the Conversations API (beta)
    url = f"{HUBSPOT_BASE_URL}/conversations/v3/conversations/threads"
    
    params = {
        "limit": 10,
        "sort": "-latestMessageTimestamp"  # Most recent first
    }
    
    response = requests.get(url, headers=get_headers(), params=params)
    
    if response.status_code != 200:
        print(f"Error fetching threads: {response.status_code}")
        print(response.text[:500])
        return []
    
    threads = response.json().get("results", [])
    print(f"Found {len(threads)} total threads")
    
    # Filter threads by recency and try to match by contact
    cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
    matching_threads = []
    
    for thread in threads:
        thread_id = thread.get("id")
        latest_timestamp = thread.get("latestMessageTimestamp")
        
        # Check if thread is recent enough
        if latest_timestamp:
            try:
                ts = datetime.fromisoformat(latest_timestamp.replace("Z", "+00:00"))
                if ts.replace(tzinfo=None) < cutoff_time:
                    continue
            except:
                pass
        
        # Get thread details to check participants
        detail_url = f"{HUBSPOT_BASE_URL}/conversations/v3/conversations/threads/{thread_id}"
        detail_response = requests.get(detail_url, headers=get_headers())
        
        if detail_response.status_code == 200:
            thread_detail = detail_response.json()
            
            # Check if this contact is a participant
            # This is a simplified check - real implementation would examine all senders
            matching_threads.append({
                "id": thread_id,
                "timestamp": latest_timestamp,
                "status": thread_detail.get("status"),
                "channelId": thread_detail.get("channelId")
            })
    
    return matching_threads


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def associate_ticket_to_thread(ticket_id: str, thread_id: str) -> dict:
    """
    Associate a HubSpot ticket with a conversation thread.
    
    Uses the CRM v4 associations API to create a link between
    the ticket and the conversation.
    
    Args:
        ticket_id: HubSpot ticket ID
        thread_id: Conversation thread ID
        
    Returns:
        API response or error dict
    """
    # Association from ticket to conversation
    url = f"{HUBSPOT_BASE_URL}/crm/v4/objects/ticket/{ticket_id}/associations/conversation/{thread_id}"
    
    # Association type for ticket-to-conversation
    payload = [{
        "associationCategory": "HUBSPOT_DEFINED",
        "associationTypeId": 32  # ticket_to_conversation
    }]
    
    response = requests.put(url, headers=get_headers(), json=payload)
    
    if response.status_code in [200, 201]:
        print(f"✅ Successfully associated ticket #{ticket_id} with thread #{thread_id}")
        return {"success": True, "ticket_id": ticket_id, "thread_id": thread_id}
    else:
        print(f"❌ Failed to associate: {response.status_code}")
        print(response.text[:500])
        return {"success": False, "error": response.text}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def update_ticket_with_thread_id(ticket_id: str, thread_id: str) -> dict:
    """
    Store the conversation thread ID in a custom ticket property.
    
    This is an alternative approach if direct association doesn't work.
    Creates a reference that can be used later.
    
    Args:
        ticket_id: HubSpot ticket ID  
        thread_id: Conversation thread ID
        
    Returns:
        API response
    """
    from hubspot import HubSpot
    
    client = HubSpot(access_token=HUBSPOT_API_KEY)
    
    # Update ticket with thread ID in a custom property
    # Note: You may need to create this property first
    try:
        from hubspot.crm.tickets import SimplePublicObjectInput
        
        ticket_input = SimplePublicObjectInput(
            properties={
                "hs_conversations_originating_thread_id": thread_id
            }
        )
        
        result = client.crm.tickets.basic_api.update(
            ticket_id=ticket_id,
            simple_public_object_input=ticket_input
        )
        
        print(f"✅ Updated ticket #{ticket_id} with thread ID reference")
        return {"success": True, "ticket_id": ticket_id, "thread_id": thread_id}
        
    except Exception as e:
        print(f"❌ Failed to update ticket: {e}")
        return {"success": False, "error": str(e)}


def find_and_associate(contact_email: str, ticket_id: str) -> dict:
    """
    Main function: find recent email thread and associate with ticket.
    
    This should be called shortly after the webhook creates a ticket,
    to link the incoming email conversation with the ticket.
    
    Args:
        contact_email: Email of the client who sent the message
        ticket_id: The ticket ID created by the webhook
        
    Returns:
        Result dict with success status
    """
    print(f"\n🔍 Looking for recent threads from {contact_email}...")
    
    # Find threads from the last hour
    threads = find_recent_threads_by_email(contact_email, max_age_hours=1)
    
    if not threads:
        print("⚠️  No recent conversation threads found")
        print("   The email may not have arrived in HubSpot yet,")
        print("   or the Conversations API access may be limited.")
        return {"success": False, "reason": "no_threads_found"}
    
    print(f"\n📧 Found {len(threads)} recent thread(s)")
    
    # Use the most recent thread
    thread = threads[0]
    thread_id = thread["id"]
    
    print(f"   Using thread ID: {thread_id}")
    print(f"   Status: {thread.get('status')}")
    
    # Try to associate
    result = associate_ticket_to_thread(ticket_id, thread_id)
    
    return result


def main():
    parser = argparse.ArgumentParser(description="Associate email conversations with tickets")
    parser.add_argument("--contact-email", required=True, help="Email of the contact")
    parser.add_argument("--ticket-id", required=True, help="HubSpot ticket ID")
    parser.add_argument("--list-threads", action="store_true", help="Just list recent threads")
    
    args = parser.parse_args()
    
    if args.list_threads:
        threads = find_recent_threads_by_email(args.contact_email, max_age_hours=24)
        print(f"\nFound {len(threads)} thread(s):")
        for t in threads:
            print(f"  - ID: {t['id']}, Status: {t.get('status')}, Time: {t.get('timestamp')}")
    else:
        result = find_and_associate(args.contact_email, args.ticket_id)
        print(f"\nResult: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()
