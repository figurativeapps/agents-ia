---
name: handler
description: |
  Traite les demandes de support et de modélisation 3D reçues par webhook.
  Classifie, estime les crédits, crée tickets HubSpot, et gère le workflow
  de validation avec le client.
  USE WHEN: l'utilisateur parle de tickets, demandes support, modélisation 3D,
  webhook, validation de crédits, ou workflow de traitement de demandes.
allowed-tools: Bash, Read, Write
---

# Skill: Handler — Support & Modélisation Request Processing

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

### Step 5b : Communication client
Selon le résultat de l'analyse :

| Statut | Action | Template |
|--------|--------|----------|
| `pending_info` | Demande incomplète → Email demande d'infos | Template 1 |
| `pending_credits` | Demande complète → Devis envoyé au client | Template 2 ou 3 selon crédits |
| `pending_admin` | Cas complexe → Notification admin | Template 4 |

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
- **Action :** Surveille les tickets en attente de réponse client
- **Détection réponses :**
  - Validation : "Je valide", "OK", "D'accord", "Parfait", "On y va"
  - Refus : "Je refuse", "Trop cher", "Non merci", "J'annule"
  - Questions : présence de "?", "Pourquoi", "Comment"

---

## Commandes

```bash
# Lancer le serveur webhook
uvicorn execution.webhook_server:app --host 0.0.0.0 --port 5000

# Tester le webhook
python tests/test_webhook_http.py

# Lancer le polling de validation
python execution/validation_workflow.py
```

---

## Edge Cases
- Classification échoue → Défaut sur source formulaire
- Contact création échoue → Logger, notifier admin
- Upload fichier échoue → Créer ticket sans fichiers, ajouter note
- HubSpot rate limit → Retry backoff exponentiel (max 3)
- ClickUp indisponible → Logger, ticket HubSpot reste source de vérité

---

## Propriétés HubSpot
- `validation_status` : pending_info | pending_credits | pending_admin | validated | rejected
- `credits_estimes` : 1 ou 2
- `clickup_subtask_id` : ID de la subtask liée
- `fichiers_urls` : URLs R2 des fichiers uploadés
