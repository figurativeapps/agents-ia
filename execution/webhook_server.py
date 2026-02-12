"""
Webhook Server - Traitement synchrone des demandes Figurative
Reçoit les demandes des formulaires et les traite immédiatement.
Chaque demande crée un nouveau ticket HubSpot et une nouvelle subtask ClickUp.

Endpoints:
    POST /webhook/request  - Traiter une demande client
    GET  /health           - Vérifier l'état du serveur
"""

import os
import sys
from pathlib import Path

# Add execution directory to path for imports BEFORE other imports
execution_dir = Path(__file__).parent
if str(execution_dir) not in sys.path:
    sys.path.insert(0, str(execution_dir))

import json
import traceback
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Import local modules (execution dir is in path)
from classify_request import classify_request
from upload_files import upload_files
from hubspot_ticket import (
    find_or_create_contact,
    create_ticket,
    create_note,
    update_ticket_property,
    ensure_custom_properties
)
from clickup_subtask import create_subtask

# Notification module disabled by default
# The client email already serves as notification via HubSpot Conversations
# Enable only if you need to notify someone other than the email recipient
NOTIFICATIONS_ENABLED = False
try:
    from send_notification import send_notification
except ImportError:
    pass

# Try to import email-ticket association module (experimental feature)
try:
    from associate_email_ticket import find_and_associate
    EMAIL_ASSOCIATION_ENABLED = True
except ImportError:
    EMAIL_ASSOCIATION_ENABLED = False


# Configuration
app = FastAPI(
    title="Figurative Request Handler",
    description="Traitement automatisé des demandes support et modélisation",
    version="2.2.0"
)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class FileAttachment(BaseModel):
    name: str
    url: Optional[str] = None
    size: Optional[int] = None
    type: Optional[str] = None


class RequestPayload(BaseModel):
    source: str  # "contact" or "modelisation"
    objet: str
    description: str
    user_email: str
    user_name: Optional[str] = None
    fichiers: Optional[List[FileAttachment]] = []


class ProcessingResult(BaseModel):
    status: str  # "created", "updated", "error"
    ticket_id: Optional[str] = None
    ticket_url: Optional[str] = None
    is_new_ticket: bool = True
    classification: Optional[str] = None
    files_uploaded: int = 0
    message: str = ""


# =============================================================================
# STARTUP EVENT
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Ensure HubSpot custom properties exist on startup."""
    logger.info("🚀 Starting Figurative Request Handler v2.0")
    try:
        result = ensure_custom_properties()
        logger.info(f"✅ HubSpot properties checked: {result['properties']}")
    except Exception as e:
        logger.warning(f"⚠️  Could not verify HubSpot properties: {e}")


# =============================================================================
# MAIN WEBHOOK ENDPOINT
# =============================================================================

@app.post("/webhook/request", response_model=ProcessingResult)
async def receive_request(payload: RequestPayload):
    """
    Process incoming request with conversation threading.
    
    Flow:
    1. Classify request (SUPPORT/MODELISATION)
    2. Upload files to R2 (if any)
    3. Find or create contact
    4. Check for existing open ticket
    5a. If open ticket exists: add note, update subtask
    5b. If no open ticket: create ticket, create subtask (if MODELISATION)
    6. Send notification
    """
    logger.info(f"📨 Received request from {payload.user_email} - Source: {payload.source}")
    
    try:
        # =================================================================
        # STEP 1: Classify the request
        # =================================================================
        logger.info("🔍 Step 1: Classifying request...")
        
        fichiers_list = [f.dict() for f in payload.fichiers] if payload.fichiers else []
        
        classification = classify_request(
            objet=payload.objet,
            description=payload.description,
            fichiers=fichiers_list,
            source=payload.source
        )
        
        type_final = classification["type_final"]
        logger.info(f"✅ Classification: {type_final} (confidence: {classification['confiance']}%)")
        
        # =================================================================
        # STEP 2: Upload files to R2 (if any)
        # =================================================================
        new_urls = []
        if fichiers_list:
            logger.info(f"📤 Step 2: Uploading {len(fichiers_list)} files to R2...")
            
            upload_result = upload_files(fichiers_list)
            new_urls = [f["url"] for f in upload_result.get("uploaded", [])]
            
            if upload_result.get("failed"):
                logger.warning(f"⚠️  Some files failed to upload: {upload_result['failed']}")
            
            logger.info(f"✅ Uploaded {len(new_urls)} files")
        else:
            logger.info("📭 Step 2: No files to upload")
        
        # =================================================================
        # STEP 3: Find or create contact
        # =================================================================
        logger.info(f"👤 Step 3: Finding/creating contact for {payload.user_email}...")
        
        contact_result = find_or_create_contact(payload.user_email, payload.user_name)
        contact_id = contact_result.get("contact_id")
        
        if not contact_id:
            raise HTTPException(status_code=500, detail="Failed to find or create contact")
        
        logger.info(f"✅ Contact ID: {contact_id} (new: {contact_result.get('created', False)})")
        
        # =================================================================
        # STEP 4: Create new ticket (one ticket per request)
        # =================================================================
        # Note: Threading disabled - each request creates a new ticket
        # This is simpler and avoids confusion when same user sends multiple requests
        
        if True:  # Always create new ticket
            # ---------------------------------------------------------
            # NEW TICKET - Create full workflow
            # ---------------------------------------------------------
            logger.info("🆕 Step 5b: Creating new ticket...")
            
            # Create ticket
            ticket_result = create_ticket(
                contact_id=contact_id,
                type_final=type_final,
                objet=payload.objet,
                description=payload.description,
                fichiers_urls=new_urls,
                source_formulaire=payload.source,
                reclassifie=classification.get("reclassifie", False),
                user_email=payload.user_email  # Email du contact (identifiant plateforme)
            )
            
            ticket_id = ticket_result.get("ticket_id")
            ticket_url = ticket_result.get("ticket_url")
            
            if not ticket_id:
                raise HTTPException(status_code=500, detail="Failed to create ticket")
            
            logger.info(f"✅ Ticket created: {ticket_id}")
            
            # Store fichiers_urls in custom property
            if new_urls:
                update_ticket_property(ticket_id, "fichiers_urls", "\n".join(new_urls))
            
            # Create ClickUp subtask if MODELISATION
            subtask_id = None
            if type_final == "MODELISATION":
                logger.info("📋 Creating ClickUp subtask...")
                
                subtask_result = create_subtask(
                    objet=payload.objet,
                    user_email=payload.user_email,
                    ticket_url=ticket_url,
                    description=payload.description,
                    fichiers_urls=new_urls
                )
                
                subtask_id = subtask_result.get("subtask_id")
                
                if subtask_id:
                    logger.info(f"✅ Subtask created: {subtask_id}")
                    # Store subtask ID in ticket
                    update_ticket_property(ticket_id, "clickup_subtask_id", subtask_id)
                else:
                    logger.warning(f"⚠️  Subtask creation failed: {subtask_result.get('error')}")
            
            # Create note on contact (for file history)
            if new_urls:
                create_note(
                    contact_id=contact_id,
                    objet=payload.objet,
                    fichiers_urls=new_urls,
                    ticket_id=ticket_id,
                    type_demande=type_final
                )
            
            # Send notification
            if NOTIFICATIONS_ENABLED:
                try:
                    send_notification(
                        ticket_url=ticket_url,
                        type_final=type_final,
                        objet=payload.objet,
                        user_email=payload.user_email,
                        reclassifie=classification.get("reclassifie", False)
                    )
                except Exception as e:
                    logger.warning(f"⚠️  Notification failed: {e}")
            
            # Try to associate email conversation with ticket (experimental)
            # This is non-blocking - if it fails, the ticket is still created
            if EMAIL_ASSOCIATION_ENABLED:
                try:
                    logger.info("🔗 Attempting email-ticket association...")
                    assoc_result = find_and_associate(payload.user_email, ticket_id)
                    if assoc_result.get("success"):
                        logger.info(f"✅ Email thread associated with ticket")
                    else:
                        logger.info(f"ℹ️  Email association skipped: {assoc_result.get('reason', 'unknown')}")
                except Exception as e:
                    logger.warning(f"⚠️  Email association failed (non-critical): {e}")
            
            return ProcessingResult(
                status="created",
                ticket_id=ticket_id,
                ticket_url=ticket_url,
                is_new_ticket=True,
                classification=type_final,
                files_uploaded=len(new_urls),
                message=f"Nouveau ticket créé: #{ticket_id}"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Processing error: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")


# =============================================================================
# EMAIL ASSOCIATION ENDPOINT (Optional)
# =============================================================================

@app.post("/webhook/associate-email")
async def associate_email_endpoint(contact_email: str, ticket_id: str):
    """
    Manually associate an email conversation with a ticket.
    
    This endpoint can be called after ticket creation to link
    the HubSpot email conversation with the ticket, especially
    if the automatic association failed due to timing issues.
    
    Args:
        contact_email: Email of the contact
        ticket_id: HubSpot ticket ID to associate
        
    Returns:
        Association result
    """
    if not EMAIL_ASSOCIATION_ENABLED:
        raise HTTPException(
            status_code=501, 
            detail="Email association feature not available"
        )
    
    try:
        result = find_and_associate(contact_email, ticket_id)
        return result
    except Exception as e:
        logger.error(f"Email association error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.get("/health")
async def health_check():
    """Check server health and dependencies."""
    status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "2.2.0",
        "features": {
            "classification": True,
            "file_upload": True,
            "hubspot": True,
            "clickup": True,
            "notifications": NOTIFICATIONS_ENABLED,
            "email_association": EMAIL_ASSOCIATION_ENABLED
        },
        "mode": "one_ticket_per_request"  # No threading - each request = new ticket
    }
    
    return status


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("WEBHOOK_PORT", "5000"))
    host = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    
    logger.info(f"🚀 Starting webhook server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
