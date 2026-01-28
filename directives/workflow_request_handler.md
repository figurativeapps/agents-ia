# Workflow: Request Handler (Support & Modélisation)

## Goal
Traiter automatiquement les demandes clients reçues via les formulaires de la plateforme Figurative, les classifier, créer les tickets appropriés dans HubSpot, et synchroniser avec ClickUp.

## Trigger
Webhook reçu depuis la plateforme Figurative contenant :
- `source` : "contact" ou "modelisation"
- `objet` : Titre de la demande
- `description` : Contenu du message
- `user_email` : Email de l'utilisateur
- `user_name` : Nom de l'utilisateur
- `fichiers` : Liste des fichiers joints (optionnel)

## Process

### Step 1: Classification
- Lire `directives/classify_request.md`
- Exécuter `execution/classify_request.py`
- Input: objet, description, fichiers, source
- Output: type_final (SUPPORT | MODELISATION), confiance, reclassifie (bool)

### Step 2: Gestion des fichiers (si modélisation)
- Si type_final == MODELISATION ET fichiers présents:
  - Exécuter `execution/upload_files.py`
  - Upload vers stockage externe (S3/Cloudflare R2)
  - Output: liste d'URLs des fichiers

### Step 3: Recherche/Création contact HubSpot
- Exécuter `execution/hubspot_ticket.py` avec action="find_or_create_contact"
- Input: user_email, user_name
- Output: contact_id

### Step 4: Création ticket HubSpot
- Exécuter `execution/hubspot_ticket.py` avec action="create_ticket"
- Input: 
  - contact_id
  - type_final
  - objet
  - description
  - fichiers_urls (si applicable)
  - source_formulaire
  - reclassifie
- Output: ticket_id, ticket_url

### Step 5: Subtask ClickUp (si modélisation)
- Si type_final == MODELISATION:
  - Lire `directives/create_clickup_subtask.md`
  - Exécuter `execution/clickup_subtask.py`
  - Parent task ID: 86c7r48ha
  - Input: objet, user_email, ticket_url
  - Output: subtask_id

### Step 6: Notification admin
- Exécuter `execution/send_notification.py`
- Destinataire: yvanol.fotso@valione-services.com
- Contenu: ticket_url, type_final, objet, reclassifie (alerte si true)

## Edge Cases
- Si classification échoue → Défaut sur source formulaire
- Si contact non trouvé et création échoue → Logger erreur, notifier admin
- Si upload fichier échoue → Créer ticket sans fichiers, ajouter note "fichiers en attente"
- Si HubSpot API rate limit → Retry avec backoff exponentiel (max 3)
- Si ClickUp indisponible → Logger, créer ticket HubSpot quand même

## Self-Annealing Notes
- Si erreur API HubSpot 401 → Vérifier token dans .env, alerter si expiré
- Si erreur API ClickUp 429 → Augmenter délai entre requêtes dans le script
- Si classification incohérente répétée → Ajuster le prompt dans classify_request.py
