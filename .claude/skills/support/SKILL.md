---
name: support
description: "Traite les demandes de support et de modélisation 3D reçues par webhook. Classifie, estime les crédits, crée tickets HubSpot, et gère le workflow de validation avec le client. USE WHEN: l'utilisateur parle de tickets, demandes support, modélisation 3D, webhook, validation de crédits, ou workflow de traitement de demandes."
---

# Skill: Support — Support & Modélisation Request Processing

## Trigger
Webhook `POST /webhook/request` avec payload :
- `source` : "contact" ou "modelisation"
- `objet` : Titre de la demande
- `description` : Contenu du message
- `user_email` : Email de l'utilisateur (compte plateforme)
- `user_name` : Nom de l'utilisateur
- `fichiers` : Liste des fichiers joints (optionnel)

---

## Pipeline séquentiel

### Step 1 : Classification
- **Script :** `execution/classify_request.py`
- **Input :** objet, description, fichiers, source
- **Logique :**
  - Pré-filtrage par mots-clés (SUPPORT: paiement, bug, compte... / MODELISATION: créer, 3D, modéliser...)
  - Indicateur fort : fichiers 3D (.glb, .usdz, .obj, .fbx, .stl)
  - Si ambiguë → LLM Claude Haiku (10x moins cher que Sonnet)
  - Confiance >= 70% → type détecté / < 70% → fallback sur source formulaire
- **Output :** `type_final` (SUPPORT | MODELISATION), `confiance`, `reclassifie` (bool)

### Step 2 : Upload fichiers (si modélisation)
- **Condition :** `type_final == MODELISATION` ET fichiers présents
- **Script :** `execution/upload_files.py`
- **Destination :** Cloudflare R2 (S3-compatible)
- **Output :** Liste d'URLs publiques des fichiers

### Step 3 : Contact HubSpot
- **Script :** `execution/hubspot_ticket.py` avec `action="find_or_create_contact"`
- **Input :** user_email, user_name
- **Logique Upsert :** Chercher par email → créer si inexistant
- **Output :** `contact_id`

### Step 4 : Ticket HubSpot
- **Script :** `execution/hubspot_ticket.py` avec `action="create_ticket"`
- **Input :** contact_id, type_final, objet, description, fichiers_urls, source_formulaire, reclassifie
- **Priorité :** MEDIUM (HIGH si reclassifié)
- **Output :** `ticket_id`, `ticket_url`

### Step 5 : Analyse + Estimation crédits (si modélisation)
- **Condition :** `type_final == MODELISATION`
- **Script :** `execution/analyze_request.py`
- **Grille de crédits :** Voir [docs/credit-grid.md](docs/credit-grid.md)
- **Complétude requise :** Au moins 1 fichier visuel + description suffisante
- **Output :** `credits_estimes`, `completeness`, `missing_info`

### Step 5b : Communication client (SMTP + HubSpot)
Selon le résultat de l'analyse :

| Statut | Action | Template |
|--------|--------|----------|
| `pending_info` | Demande incomplète → Email demande d'infos | Template 1 |
| `pending_credits` | Demande complète → Devis envoyé au client | Template 2 ou 3 selon crédits |
| `pending_admin` | Cas complexe → Notification admin | Template 4 |

**Envoi email** : `send_email_to_contact()` dans `hubspot_conversation.py` fait 2 choses :
1. Envoi réel via SMTP (le prospect reçoit l'email dans sa boîte)
2. Consignation via API Engagements HubSpot (tracking CRM)

L'adresse SMTP (`SMTP_USER`) doit être la même que l'email connecté à HubSpot pour que les réponses du prospect soient auto-capturées comme emails INCOMING.

### Step 6 : Subtask ClickUp (après validation client)
- **Condition :** Client a validé le devis
- **Script :** `execution/clickup_subtask.py`
- **Parent Task :** 86c7r48ha
- **Nom :** `Demande {user_email}`
- **Output :** `subtask_id`
- **Propriété HubSpot mise à jour :** `validation_status` → `validated`

### Step 7 : Notification admin
- **Script :** `execution/send_notification.py`
- **Destinataire :** yvanol.fotso@valione-services.com
- **Alerte spéciale si** `reclassifie == true`

---

## Validation Workflow (polling)
- **Script :** `execution/validation_workflow.py`
- **Action :** Surveille les tickets en attente de réponse client (INCOMING emails via HubSpot)
- **Détection réponses :**
  - Validation : "Je valide", "OK", "D'accord", "Parfait", "On y va" → `process_validation()` → Crée subtask ClickUp
  - Refus : "Je refuse", "Trop cher", "Non merci", "J'annule" → `process_rejection()` → Ferme le ticket
  - Questions : présence de "?", "Pourquoi", "Comment" → Log pour traitement manuel
  - Info complémentaire (si `pending_info`) → `process_info_response()` → Renvoie un devis
- **Après validation :** Subtask ClickUp créée + email de confirmation envoyé au prospect

---

## Configuration SMTP (requis pour l'envoi d'emails)

Variables `.env` obligatoires :
- `SMTP_HOST` : Serveur SMTP (ex: `smtp.gmail.com` pour Google Workspace)
- `SMTP_PORT` : Port (587 pour STARTTLS)
- `SMTP_USER` : Adresse email d'envoi (doit être connectée à HubSpot)
- `SMTP_PASSWORD` : Mot de passe d'application (Google Workspace → App passwords)

Sans SMTP configuré, les emails sont uniquement consignés dans HubSpot mais pas envoyés au prospect.

---

## Commandes

```bash
# Lancer le serveur webhook
uvicorn execution.webhook_server:app --host 0.0.0.0 --port 5000

# Tester le webhook
python tests/test_webhook_http.py

# Lancer le polling de validation (surveille les réponses clients)
python execution/validation_workflow.py --mode poll --interval 60

# Vérifier les tickets en attente
python execution/validation_workflow.py --mode list-pending

# Vérifier un ticket spécifique
python execution/validation_workflow.py --mode check --ticket-id 123456
```

---

## Edge Cases
- Classification échoue → Défaut sur source formulaire
- Contact création échoue → Logger, notifier admin
- Upload fichier échoue → Créer ticket sans fichiers, ajouter note
- HubSpot rate limit → Retry backoff exponentiel (max 3)
- ClickUp indisponible → Logger, ticket HubSpot reste source de vérité
- SMTP non configuré → Email consigné dans HubSpot uniquement (warning dans les logs)
- SMTP échoue → Email quand même consigné dans HubSpot, `smtp_sent: false` dans le retour

---

## Scripts utilisés

| Script | Function | Input → Output |
|--------|----------|----------------|
| `execution/webhook_server.py` | Receive requests (FastAPI v3.0) | HTTP → Ticket + Validation |
| `execution/classify_request.py` | Classify SUPPORT/MODELISATION | Text → Type + Confidence |
| `execution/analyze_request.py` | Check completeness + estimate credits | Request → Credits + Missing info |
| `execution/upload_files.py` | Upload files to Cloudflare R2 | Files → Public URLs |
| `execution/hubspot_ticket.py` | Manage contacts, tickets, notes | Data → HubSpot objects |
| `execution/hubspot_conversation.py` | Read/send emails via HubSpot + SMTP | Email ↔ HubSpot |
| `execution/clickup_subtask.py` | Create modeling subtask in ClickUp | Data → ClickUp task |
| `execution/validation_workflow.py` | Poll pending tickets, process client responses | Tickets → Validation |
| `execution/send_notification.py` | Email admin notification via SMTP | Data → SMTP |
| `execution/diagnose_hubspot_properties.py` | Debug HubSpot fields | — |

---

## Propriétés HubSpot
- `validation_status` : pending_info | pending_credits | pending_admin | validated | rejected
- `credits_estimes` : 1 ou 2
- `clickup_subtask_id` : ID de la subtask liée
- `fichiers_urls` : URLs R2 des fichiers uploadés
