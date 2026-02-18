"""
Webhook Server - Traitement des demandes Figurative avec validation crédits
Reçoit les demandes des formulaires et les traite selon le type:
- SUPPORT: Création immédiate du ticket
- MODELISATION: Workflow de validation (analyse → devis → validation client → subtask)

Endpoints:
    POST /webhook/request       - Traiter une demande client
    POST /webhook/validate      - Valider manuellement une demande (admin)
    POST /webhook/associate-email - Associer email à ticket
    GET  /health                - Vérifier l'état du serveur

Version: 3.0.0 - Ajout workflow validation crédits
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
from analyze_request import (
    analyze_request as analyze_modelisation,
    generate_missing_info_message,
    generate_credit_quote_message,
    generate_admin_message
)
from hubspot_conversation import (
    send_email_to_contact,
    get_contact_by_email
)

# Notification module disabled by default
NOTIFICATIONS_ENABLED = False
try:
    from send_notification import send_notification
except ImportError:
    pass

# Email-ticket association (experimental)
try:
    from associate_email_ticket import find_and_associate
    EMAIL_ASSOCIATION_ENABLED = True
except ImportError:
    EMAIL_ASSOCIATION_ENABLED = False

# Admin email for complex cases
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "jordane.pellerin@figurative.fr")

# HubSpot Pipeline Stages
STAGE_NEW = "1"                    # Nouveau
STAGE_WAITING_ON_CONTACT = "2"     # En attente de contact (client doit répondre)
STAGE_WAITING_ON_US = "3"          # En attente de nous
STAGE_CLOSED = "4"                 # Fermé


# Configuration
app = FastAPI(
    title="Figurative Request Handler",
    description="Traitement automatisé des demandes support et modélisation avec validation crédits",
    version="3.0.0"
)

# New je add pour le CORS middleware pour autoriser les requêtes depuis le domaine du formulaire (arview.figurative.fr) afin que les formulaires puissent communiquer avec ce serveur sans problème de CORS.
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://arview.figurative.fr"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    status: str  # "created", "pending_validation", "error"
    ticket_id: Optional[str] = None
    ticket_url: Optional[str] = None
    is_new_ticket: bool = True
    classification: Optional[str] = None
    files_uploaded: int = 0
    validation_status: Optional[str] = None
    credits_estimes: Optional[int] = None
    message: str = ""


class ValidationPayload(BaseModel):
    ticket_id: str
    credits: int
    admin_notes: Optional[str] = None


# =============================================================================
# STARTUP EVENT
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Ensure HubSpot custom properties exist on startup."""
    logger.info("🚀 Starting Figurative Request Handler v3.0 (with credit validation)")
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
    Process incoming request with credit validation workflow.
    
    Flow for SUPPORT:
    1. Classify → 2. Upload files → 3. Create contact → 4. Create ticket → Done
    
    Flow for MODELISATION:
    1. Classify → 2. Upload files → 3. Create contact → 4. Create ticket (pending)
    5. Analyze completeness → 6a. If incomplete: send info request email
                            → 6b. If complete: estimate credits
    7a. If needs admin: notify admin, wait
    7b. If 1-2 credits: send quote to client, wait for validation
    8. (Later via /webhook/validate or response detection): Create ClickUp subtask
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
        # STEP 4: Create ticket
        # =================================================================
        logger.info("🎫 Step 4: Creating ticket...")
        
        ticket_result = create_ticket(
            contact_id=contact_id,
            type_final=type_final,
            objet=payload.objet,
            description=payload.description,
            fichiers_urls=new_urls,
            source_formulaire=payload.source,
            reclassifie=classification.get("reclassifie", False),
            user_email=payload.user_email
        )
        
        ticket_id = ticket_result.get("ticket_id")
        ticket_url = ticket_result.get("ticket_url")
        
        if not ticket_id:
            raise HTTPException(status_code=500, detail="Failed to create ticket")
        
        logger.info(f"✅ Ticket created: {ticket_id}")
        
        # Store fichiers_urls in custom property
        if new_urls:
            update_ticket_property(ticket_id, "fichiers_urls", "\n".join(new_urls))
        
        # Create note on contact (for file history)
        if new_urls:
            create_note(
                contact_id=contact_id,
                objet=payload.objet,
                fichiers_urls=new_urls,
                ticket_id=ticket_id,
                type_demande=type_final
            )
        
        # =================================================================
        # BRANCH: SUPPORT vs MODELISATION
        # =================================================================
        
        if type_final == "SUPPORT":
            # ---------------------------------------------------------
            # SUPPORT: Simple flow - ticket created, done
            # ---------------------------------------------------------
            logger.info("📋 SUPPORT request - ticket created, workflow complete")
            
            return ProcessingResult(
                status="created",
                ticket_id=ticket_id,
                ticket_url=ticket_url,
                is_new_ticket=True,
                classification=type_final,
                files_uploaded=len(new_urls),
                validation_status="n/a",
                message=f"Ticket support créé: #{ticket_id}"
            )
        
        else:
            # ---------------------------------------------------------
            # MODELISATION: Validation workflow
            # ---------------------------------------------------------
            logger.info("🎨 MODELISATION request - starting validation workflow...")
            
            # Step 5: Analyze completeness and estimate credits
            logger.info("🔍 Step 5: Analyzing request completeness...")
            
            analysis = analyze_modelisation(
                objet=payload.objet,
                description=payload.description,
                fichiers=fichiers_list,
                use_llm=True
            )
            
            logger.info(f"   Complete: {analysis['complete']}")
            logger.info(f"   Credits: {analysis.get('credits')}")
            logger.info(f"   Needs admin: {analysis.get('needs_admin')}")
            logger.info(f"   Recommendation: {analysis['recommendation']}")
            
            # Determine validation status and action
            validation_status = None
            credits_estimes = analysis.get("credits")
            email_sent = False
            
            if not analysis["complete"]:
                # ---------------------------------------------------------
                # Case A: Incomplete - request more info
                # ---------------------------------------------------------
                validation_status = "pending_info"
                logger.info("📧 Step 6a: Sending info request email...")
                
                message_html = generate_missing_info_message(analysis, payload.objet)
                
                email_result = send_email_to_contact(
                    contact_id=contact_id,
                    subject=f"Re: {payload.objet} - Informations complémentaires requises",
                    body_html=message_html,
                    ticket_id=ticket_id
                )
                
                if email_result.get("success"):
                    logger.info(f"✅ Info request email sent")
                    email_sent = True
                else:
                    logger.warning(f"⚠️  Failed to send email: {email_result.get('error')}")
            
            elif analysis.get("needs_admin"):
                # ---------------------------------------------------------
                # Case B: Complex - notify admin
                # ---------------------------------------------------------
                validation_status = "pending_admin"
                logger.info("📧 Step 6b: Notifying admin for complex case...")
                
                # Get admin contact
                admin_contact = get_contact_by_email(ADMIN_EMAIL)
                
                if admin_contact:
                    message_html = generate_admin_message(
                        analysis, payload.objet, payload.description, payload.user_email
                    )
                    
                    email_result = send_email_to_contact(
                        contact_id=admin_contact["contact_id"],
                        subject=f"[VALIDATION REQUISE] Demande modélisation: {payload.objet}",
                        body_html=message_html,
                        ticket_id=ticket_id
                    )
                    
                    if email_result.get("success"):
                        logger.info(f"✅ Admin notification sent")
                        email_sent = True
                    else:
                        logger.warning(f"⚠️  Failed to notify admin: {email_result.get('error')}")
                else:
                    logger.warning(f"⚠️  Admin contact not found: {ADMIN_EMAIL}")
            
            else:
                # ---------------------------------------------------------
                # Case C: Complete - send credit quote
                # ---------------------------------------------------------
                validation_status = "pending_credits"
                logger.info(f"📧 Step 6c: Sending credit quote ({credits_estimes} credits)...")
                
                message_html = generate_credit_quote_message(analysis, payload.objet)
                
                email_result = send_email_to_contact(
                    contact_id=contact_id,
                    subject=f"Re: {payload.objet} - Devis modélisation",
                    body_html=message_html,
                    ticket_id=ticket_id
                )
                
                if email_result.get("success"):
                    logger.info(f"✅ Credit quote email sent")
                    email_sent = True
                else:
                    logger.warning(f"⚠️  Failed to send quote: {email_result.get('error')}")
            
            # Update ticket with validation status
            update_ticket_property(ticket_id, "validation_status", validation_status)
            if credits_estimes:
                update_ticket_property(ticket_id, "credits_estimes", str(credits_estimes))
            
            # Change ticket stage based on validation status
            if email_sent and validation_status in ["pending_info", "pending_credits"]:
                # Email sent to client → "En attente de contact"
                update_ticket_property(ticket_id, "hs_pipeline_stage", STAGE_WAITING_ON_CONTACT)
                logger.info(f"📋 Ticket stage changed to 'Waiting on contact'")
            elif validation_status == "pending_admin":
                # Waiting for admin → "En attente de nous"
                update_ticket_property(ticket_id, "hs_pipeline_stage", STAGE_WAITING_ON_US)
                logger.info(f"📋 Ticket stage changed to 'Waiting on us'")
            
            return ProcessingResult(
                status="pending_validation",
                ticket_id=ticket_id,
                ticket_url=ticket_url,
                is_new_ticket=True,
                classification=type_final,
                files_uploaded=len(new_urls),
                validation_status=validation_status,
                credits_estimes=credits_estimes,
                message=f"Ticket modélisation créé, en attente de validation ({validation_status})"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Processing error: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")


# =============================================================================
# ADMIN VALIDATION ENDPOINT
# =============================================================================

@app.post("/webhook/validate")
async def validate_request(payload: ValidationPayload):
    """
    Manually validate a modeling request and create the ClickUp subtask.
    
    Called by admin after reviewing a complex case or by the validation workflow
    after detecting client approval.
    
    Args:
        ticket_id: HubSpot ticket ID
        credits: Validated number of credits
        admin_notes: Optional notes from admin
    
    Returns:
        Validation result with subtask info
    """
    logger.info(f"✅ Validating ticket {payload.ticket_id} for {payload.credits} credits")
    
    try:
        from hubspot_ticket import get_hubspot_client
        from hubspot_conversation import get_ticket_details
        
        # Get ticket details
        ticket = get_ticket_details(payload.ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        ticket_url = f"https://app.hubspot.com/contacts/147476643/ticket/{payload.ticket_id}"
        
        # Get contact email from ticket
        contact_id = ticket.get("contact_id")
        if not contact_id:
            raise HTTPException(status_code=400, detail="No contact associated with ticket")
        
        # Get contact details
        client = get_hubspot_client()
        contact_response = client.crm.contacts.basic_api.get_by_id(
            contact_id=contact_id,
            properties=["email", "firstname", "lastname"]
        )
        user_email = contact_response.properties.get("email", "unknown")
        
        # Create ClickUp subtask
        logger.info("📋 Creating ClickUp subtask...")
        
        subtask_result = create_subtask(
            objet=ticket.get("subject", "Demande modélisation"),
            user_email=user_email,
            ticket_url=ticket_url,
            description=f"{ticket.get('content', '')}\n\n[Crédits validés: {payload.credits}]",
            fichiers_urls=[]  # URLs are already in ticket
        )
        
        subtask_id = subtask_result.get("subtask_id")
        
        if subtask_id:
            logger.info(f"✅ Subtask created: {subtask_id}")
            
            # Update ticket properties
            update_ticket_property(payload.ticket_id, "validation_status", "validated")
            update_ticket_property(payload.ticket_id, "credits_estimes", str(payload.credits))
            update_ticket_property(payload.ticket_id, "clickup_subtask_id", subtask_id)
            
            # Send confirmation email to client
            confirmation_html = f"""
            <p>Bonjour,</p>
            <p>Votre demande de modélisation a été validée.</p>
            <p><strong>Crédits débités : {payload.credits}</strong></p>
            <p>Notre équipe va maintenant commencer la modélisation. Vous serez notifié dès qu'elle sera terminée.</p>
            <p>Cordialement,<br>L'équipe Figurative</p>
            """
            
            send_email_to_contact(
                contact_id=contact_id,
                subject=f"Re: {ticket.get('subject', 'Votre demande')} - Modélisation confirmée",
                body_html=confirmation_html,
                ticket_id=payload.ticket_id
            )
            
            return {
                "success": True,
                "ticket_id": payload.ticket_id,
                "subtask_id": subtask_id,
                "subtask_url": subtask_result.get("subtask_url"),
                "credits": payload.credits,
                "message": "Demande validée, subtask ClickUp créée"
            }
        else:
            logger.error(f"❌ Subtask creation failed: {subtask_result.get('error')}")
            return {
                "success": False,
                "ticket_id": payload.ticket_id,
                "error": subtask_result.get("error", "Unknown error")
            }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Validation error: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Validation error: {str(e)}")


# =============================================================================
# EMAIL ASSOCIATION ENDPOINT (Optional)
# =============================================================================

@app.post("/webhook/associate-email")
async def associate_email_endpoint(contact_email: str, ticket_id: str):
    """Manually associate an email conversation with a ticket."""
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
        "version": "3.0.0",
        "features": {
            "classification": True,
            "file_upload": True,
            "hubspot": True,
            "clickup": True,
            "credit_validation": True,
            "notifications": NOTIFICATIONS_ENABLED,
            "email_association": EMAIL_ASSOCIATION_ENABLED
        },
        "workflow": {
            "support": "immediate_ticket",
            "modelisation": "validation_required"
        }
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
