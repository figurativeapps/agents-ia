# Processus Support Figurative

> Workflow automatisé pour traiter les demandes clients (Support / Modélisation)
> **Version 2.0** - Avec threading des conversations (1 ticket par conversation)

## Types de demandes

| Type | Déclencheur | Actions |
|------|-------------|---------|
| **SUPPORT** | Mots-clés: paiement, bug, compte... | Contact → Ticket → Notification |
| **MODELISATION** | Fichiers 3D ou mots-clés: modéliser, 3D, AR | Upload R2 → Contact → Ticket → Note → ClickUp → Notification |

---

## Threading des conversations

**Principe** : 1 ticket par conversation, pas 1 ticket par email.

| Scenario | Action |
|----------|--------|
| Premier email | Créer nouveau ticket |
| Email de suivi (ticket ouvert < 14j) | Ajouter au ticket existant |
| Email après 14j d'inactivité | Créer nouveau ticket |
| Email après fermeture ticket | Créer nouveau ticket |

**Statuts "ticket ouvert"** : Nouveau (1) ou En cours (2)

**Propriétés custom HubSpot** (créées automatiquement) :
- `clickup_subtask_id` : ID de la subtask ClickUp associée
- `fichiers_urls` : URLs des fichiers R2 (concaténées)

---

## Scripts disponibles

| Script | Fonction | Fonctions clés |
|--------|----------|----------------|
| `webhook_server.py` | Endpoint + traitement synchrone | `POST /webhook/request` |
| `classify_request.py` | Classification SUPPORT/MODELISATION | `classify_request()` |
| `upload_files.py` | Upload fichiers vers R2 | `upload_files()` |
| `hubspot_ticket.py` | Gestion contacts, tickets, notes | `find_or_create_contact()`, `find_open_ticket()`, `create_ticket()`, `create_note()`, `append_fichiers_urls()` |
| `clickup_subtask.py` | Gestion subtasks ClickUp | `create_subtask()`, `update_subtask_description()` |
| `send_notification.py` | Email admin | `send_notification()` |

---

## Flux complet (webhook_server.py)

```
1. Recevoir payload (source, objet, description, user_email, fichiers)
2. Classifier la demande (règles + LLM si ambigu)
3. Upload fichiers vers R2 (si présents)
4. Trouver/créer contact HubSpot
5. Chercher ticket ouvert pour ce contact (< 14 jours)

   SI ticket ouvert trouvé:
   ├── Ajouter Note au ticket
   ├── Concaténer fichiers_urls
   ├── Mettre à jour subtask ClickUp (si existe)
   └── Notifier admin

   SINON:
   ├── Créer nouveau ticket
   ├── Stocker fichiers_urls
   ├── Créer subtask ClickUp (si MODELISATION)
   ├── Stocker clickup_subtask_id dans ticket
   ├── Créer Note sur contact (si fichiers)
   └── Notifier admin
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

# ClickUp
CLICKUP_API_KEY=pk_...
CLICKUP_PARENT_TASK_ID=86c7r48ha

# Cloudflare R2
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET_NAME=figurative-support
R2_ENDPOINT_URL=https://c46afcbabb4183669d66739ce638dd2e.r2.cloudflarestorage.com
R2_PUBLIC_URL=https://pub-44fb87ee985849b6b4a6899988df6140.r2.dev

# Notification SMTP (Outlook)
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
NOTIFICATION_EMAIL=yvanol.fotso@valione-services.com
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
```

---

## Endpoint webhook

**POST** `/webhook/request`

```json
{
  "source": "modelisation",
  "objet": "Demande de modélisation",
  "description": "Je souhaite modéliser ce produit...",
  "user_email": "client@example.com",
  "user_name": "Jean Dupont",
  "fichiers": [
    {"name": "photo.jpg", "url": "https://temp-url.com/photo.jpg"}
  ]
}
```

**Réponse** :
```json
{
  "status": "created",
  "ticket_id": "12345",
  "ticket_url": "https://app.hubspot.com/contacts/.../ticket/12345",
  "is_new_ticket": true,
  "classification": "MODELISATION",
  "files_uploaded": 1,
  "message": "Nouveau ticket créé: #12345"
}
```

---

## Prochaines étapes

- [x] Threading des conversations (1 ticket par sujet)
- [x] Concaténation des fichiers (HubSpot + ClickUp)
- [ ] Configurer SMTP Outlook pour notifications
- [ ] Déployer webhook en daemon (systemd)
- [ ] Connecter formulaires Figurative au webhook
