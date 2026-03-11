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

### Step 5b : Communication client (manuelle)
Selon le résultat de l'analyse :

| Statut | Action | Template |
|--------|--------|----------|
| `pending_info` | Demande incomplète → Email demande d'infos | Template 1 |
| `pending_credits` | Demande complète → Devis envoyé au client | Template 2 ou 3 selon crédits |
| `pending_admin` | Cas complexe → Notification admin | Template 4 |

**Envoi email** : L'email est consigné dans HubSpot via API Engagements, puis **envoyé manuellement** au client (SMTP non configuré).

### Step 6 : Validation manuelle → Watcher automatique
- L'utilisateur lit la réponse du client et change `validation_status` dans l'UI HubSpot :
  - **"Validé"** (`validated`) → Le watcher crée automatiquement une subtask ClickUp
  - **"Refusé"** (`rejected`) → Le watcher ferme automatiquement le ticket
- **Script watcher :** `execution/watch_ticket_validation.py`
- **Contenu de la subtask :** Dernière note du contact + `credits_estimes`
- **Parent Task ClickUp :** `86c7r48ha`
- **Anti-doublon :** Un ticket avec `clickup_subtask_id` déjà rempli est ignoré

### Step 7 : Notification admin
- **Script :** `execution/send_notification.py`
- **Destinataire :** yvanol.fotso@valione-services.com
- **Alerte spéciale si** `reclassifie == true`

---

## Ticket Validation Watcher (`watch_ticket_validation.py`)

Script de polling qui surveille les changements de `validation_status` sur les tickets HubSpot.

**Flux :**
1. Ticket créé avec `validation_status = "pending_info"` (En attente d'infos)
2. L'utilisateur envoie manuellement le devis au client
3. Le client répond → l'utilisateur passe `validation_status` à **"Validé"** ou **"Refusé"** dans HubSpot
4. Le watcher détecte et agit :

| validation_status | Action du watcher |
|-------------------|-------------------|
| `validated` (+ pas de `clickup_subtask_id`) | Lit dernière note du contact → Crée subtask ClickUp → Stocke `clickup_subtask_id` |
| `rejected` (+ ticket encore ouvert) | Ferme le ticket (stage "4") |

**Anti-doublons :**
- Validé : ignoré si `clickup_subtask_id` déjà rempli
- Refusé : ignoré si ticket déjà fermé (stage "4")

---

## Commandes

```bash
# Lancer le serveur webhook
uvicorn execution.webhook_server:app --host 0.0.0.0 --port 5000

# Tester le webhook
python tests/test_webhook_http.py

# Lancer le watcher de validation tickets (polling continu)
python execution/watch_ticket_validation.py --mode poll --interval 60

# Un seul passage (test)
python execution/watch_ticket_validation.py --mode once
```

---

## Edge Cases
- Classification échoue → Défaut sur source formulaire
- Contact création échoue → Logger, notifier admin
- Upload fichier échoue → Créer ticket sans fichiers, ajouter note
- HubSpot rate limit → Retry backoff exponentiel (max 3)
- ClickUp indisponible → Logger, ticket HubSpot reste source de vérité
- Pas de note sur le contact quand validé → Skip, retry au prochain cycle
- Pas de contact associé au ticket → Skip avec warning

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
| `execution/watch_ticket_validation.py` | Watch validation_status changes, create ClickUp subtasks | Ticket validated/rejected → ClickUp/Close |
| `execution/validation_workflow.py` | (Legacy) Poll pending tickets via email detection | Tickets → Validation |
| `execution/send_notification.py` | Email admin notification via SMTP | Data → SMTP |
| `execution/diagnose_hubspot_properties.py` | Debug HubSpot fields | — |

---

## Propriétés HubSpot
- `validation_status` : pending_info | pending_credits | pending_admin | validated | rejected
- `credits_estimes` : 1 ou 2
- `clickup_subtask_id` : ID de la subtask liée
- `fichiers_urls` : URLs R2 des fichiers uploadés
