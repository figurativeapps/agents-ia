# Processus Support Figurative

> Workflow automatisé pour traiter les demandes clients (Support / Modélisation)
> **Version 3.0** - Avec validation des crédits avant création de subtask ClickUp

## Types de demandes

| Type | Déclencheur | Workflow |
|------|-------------|----------|
| **SUPPORT** | Mots-clés: paiement, bug, compte... | Contact → Ticket → Done |
| **MODELISATION** | Fichiers 3D ou mots-clés: modéliser, 3D, AR | Contact → Ticket → **Validation crédits** → ClickUp |

---

## Workflow Modélisation (v3.0)

### Principe : Validation AVANT création de subtask

```
┌─────────────────────────────────────────────────────────────────┐
│                    DEMANDE MODELISATION                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. Classification (SUPPORT/MODELISATION)                        │
│  2. Upload fichiers vers R2                                      │
│  3. Création contact HubSpot                                     │
│  4. Création ticket HubSpot (statut: EN ATTENTE)                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. ANALYSE COMPLETUDE + ESTIMATION CREDITS                      │
│     - Fichiers présents ?                                        │
│     - Description suffisante ?                                   │
│     - Complexité de l'objet ?                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │ INCOMPLET│   │ COMPLEXE │   │ COMPLET  │
        └──────────┘   └──────────┘   └──────────┘
              │               │               │
              ▼               ▼               ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │ Email:   │   │ Email:   │   │ Email:   │
        │ Demande  │   │ Notif    │   │ Devis    │
        │ d'infos  │   │ Admin    │   │ X crédits│
        └──────────┘   └──────────┘   └──────────┘
              │               │               │
              ▼               ▼               ▼
        pending_info   pending_admin   pending_credits
              │               │               │
              └───────────────┴───────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │ CLIENT REPOND    │
                    │ "Je valide" / OK │
                    └──────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │ SUBTASK CLICKUP  │
                    │ CREEE            │
                    └──────────────────┘
                              │
                              ▼
                         validated
```

---

## Grille Tarifaire Crédits

| Crédits | Condition | Exemples |
|---------|-----------|----------|
| **1** | Fichier 3D fourni (ajustements) | Client envoie .glb/.usdz à optimiser |
| **1** | Objet simple | Boîte, cadre, vase simple |
| **2** | Modélisation complète + textures | Chaise, table, meuble standard |
| **Admin** | Objet très complexe | Cheminée ornementée, marqueterie |

Voir `directives/grille_credits_modelisation.md` pour les règles détaillées.

---

## Propriétés HubSpot (Tickets)

| Propriété | Type | Valeurs |
|-----------|------|---------|
| `validation_status` | Enum | `pending_info`, `pending_credits`, `pending_admin`, `validated`, `rejected` |
| `credits_estimes` | Number | 1 ou 2 |
| `clickup_subtask_id` | String | ID de la subtask ClickUp |
| `fichiers_urls` | Textarea | URLs R2 (une par ligne) |

---

## Scripts disponibles

| Script | Fonction | Fonctions clés |
|--------|----------|----------------|
| `webhook_server.py` | Endpoint + traitement (v3.0) | `POST /webhook/request`, `POST /webhook/validate` |
| `classify_request.py` | Classification SUPPORT/MODELISATION | `classify_request()` |
| `analyze_request.py` | Analyse complétude + estimation crédits | `analyze_request()`, `generate_*_message()` |
| `upload_files.py` | Upload fichiers vers R2 | `upload_files()` |
| `hubspot_ticket.py` | Gestion contacts, tickets, notes | `find_or_create_contact()`, `create_ticket()`, `update_ticket_property()` |
| `hubspot_conversation.py` | Lecture/envoi emails HubSpot | `send_email_to_contact()`, `get_messages_for_ticket()` |
| `clickup_subtask.py` | Gestion subtasks ClickUp | `create_subtask()` |
| `validation_workflow.py` | Polling + traitement réponses | `poll_pending_tickets()`, `process_validation()` |

---

## Endpoints API

### POST `/webhook/request`

Reçoit une demande client et démarre le workflow.

**Payload:**
```json
{
  "source": "modelisation",
  "objet": "Modélisation fauteuil vintage",
  "description": "Je souhaite modéliser ce fauteuil...",
  "user_email": "client@example.com",
  "user_name": "Jean Dupont",
  "fichiers": [
    {"name": "photo.jpg", "url": "https://temp-url.com/photo.jpg"}
  ]
}
```

**Réponse (MODELISATION):**
```json
{
  "status": "pending_validation",
  "ticket_id": "12345",
  "ticket_url": "https://app.hubspot.com/contacts/.../ticket/12345",
  "is_new_ticket": true,
  "classification": "MODELISATION",
  "files_uploaded": 1,
  "validation_status": "pending_credits",
  "credits_estimes": 2,
  "message": "Ticket modélisation créé, en attente de validation"
}
```

### POST `/webhook/validate`

Valide manuellement une demande (admin ou après détection réponse client).

**Payload:**
```json
{
  "ticket_id": "12345",
  "credits": 2,
  "admin_notes": "Validation OK"
}
```

**Réponse:**
```json
{
  "success": true,
  "ticket_id": "12345",
  "subtask_id": "86c870m18",
  "credits": 2,
  "message": "Demande validée, subtask ClickUp créée"
}
```

### GET `/health`

Vérifie l'état du serveur.

```json
{
  "status": "healthy",
  "version": "3.0.0",
  "features": {
    "classification": true,
    "file_upload": true,
    "hubspot": true,
    "clickup": true,
    "credit_validation": true
  },
  "workflow": {
    "support": "immediate_ticket",
    "modelisation": "validation_required"
  }
}
```

---

## Configuration (.env)

```bash
# Classification
ANTHROPIC_API_KEY=sk-ant-...

# HubSpot
HUBSPOT_API_KEY=pat-...
HUBSPOT_HUB_ID=147476643
HUBSPOT_PIPELINE_ID=0
HUBSPOT_STAGE_NEW=1

# Admin (pour notifications cas complexes)
ADMIN_EMAIL=jordane.pellerin@figurative.fr

# ClickUp
CLICKUP_API_KEY=pk_...
CLICKUP_PARENT_TASK_ID=86c7r48ha
CLICKUP_ASSIGNEE_ID=100557980  # Yvanol

# Cloudflare R2
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET_NAME=figurative-support
R2_ENDPOINT_URL=https://c46afcbabb4183669d66739ce638dd2e.r2.cloudflarestorage.com
R2_PUBLIC_URL=https://pub-44fb87ee985849b6b4a6899988df6140.r2.dev
```

---

## Serveur production

```bash
# Connexion
ssh figurative@ubuntu-8gb-nbg1-1
source ~/venv/bin/activate
cd ~/agents-ia

# Lancement webhook
uvicorn execution.webhook_server:app --host 0.0.0.0 --port 5000

# Lancement polling validation (optionnel, en background)
python execution/validation_workflow.py --mode poll --interval 60
```

---

## Prochaines étapes

- [x] Threading des conversations (1 ticket par sujet) → Désactivé v2.2
- [x] Validation crédits avant création subtask ClickUp (v3.0)
- [x] Analyse complétude automatique
- [x] Emails automatiques (demande info, devis, confirmation)
- [ ] Configurer polling validation en daemon (systemd)
- [ ] Déployer v3.0 en production
- [ ] Connecter formulaires Figurative au webhook
