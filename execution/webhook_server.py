"""
Webhook Server - Reçoit les demandes des formulaires Figurative
et les ajoute à la queue Redis pour traitement par l'agent DOE.
"""

from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional, List
import json
import uuid
from datetime import datetime
import redis
import logging

# Configuration
app = FastAPI(title="Figurative Request Handler")
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
QUEUE_NAME = "request_queue"

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Modèles de données
class FileAttachment(BaseModel):
    name: str
    url: Optional[str] = None
    size: Optional[int] = None
    type: Optional[str] = None

class RequestPayload(BaseModel):
    source: str
    objet: str
    description: str
    user_email: str
    user_name: Optional[str] = None
    fichiers: Optional[List[FileAttachment]] = []

@app.post("/webhook/request")
async def receive_request(payload: RequestPayload):
    task_id = str(uuid.uuid4())
    task = {
        "id": task_id,
        "timestamp": datetime.now().isoformat(),
        "status": "pending",
        "payload": payload.dict()
    }
    
    redis_client.rpush(QUEUE_NAME, json.dumps(task))
    logger.info(f"Task {task_id} added - Source: {payload.source} - Email: {payload.user_email}")
    
    return {
        "status": "received",
        "task_id": task_id,
        "message": "Votre demande a été enregistrée."
    }

@app.get("/health")
async def health_check():
    try:
        redis_client.ping()
        redis_ok = True
    except:
        redis_ok = False
    
    queue_length = redis_client.llen(QUEUE_NAME) if redis_ok else -1
    
    return {
        "status": "healthy" if redis_ok else "degraded",
        "redis": "connected" if redis_ok else "disconnected",
        "queue_length": queue_length,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/queue/status")
async def queue_status():
    total = redis_client.llen(QUEUE_NAME)
    tasks = []
    for i in range(min(10, total)):
        task_data = redis_client.lindex(QUEUE_NAME, i)
        if task_data:
            tasks.append(json.loads(task_data))
    
    return {
        "total_pending": total,
        "recent_tasks": tasks
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
EOF