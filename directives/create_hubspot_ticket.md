# SOP: Création Ticket HubSpot Help Desk

## Objectif
Créer un ticket dans le Help Desk HubSpot et l'associer au contact client.

## Script
`execution/hubspot_ticket.py`

## Configuration
- **Pipeline ID** : 0 (Pipeline de support)
- **Stage ID** : 1 (Nouveau)
- **HUB_ID** : Récupéré via API ou configuré dans .env

## Actions Disponibles

### Action 1: find_or_create_contact
Recherche un contact par email. Si inexistant, le crée.

**Input** :
- `user_email` : Email du client
- `user_name` : Nom du client (optionnel)

**Output** :
- `contact_id` : ID HubSpot du contact

### Action 2: create_ticket
Crée un ticket et l'associe au contact.

**Input** :
- `contact_id` : ID du contact HubSpot
- `type_final` : SUPPORT ou MODELISATION
- `objet` : Titre du ticket
- `description` : Corps du ticket
- `fichiers_urls` : Liste d'URLs des fichiers (optionnel)
- `source_formulaire` : Source originale
- `reclassifie` : Boolean (pour tag spécial si reclassifié)

**Output** :
- `ticket_id` : ID du ticket créé
- `ticket_url` : URL directe vers le ticket

## Propriétés Ticket
```
subject: objet
content: description + fichiers_urls
hs_pipeline: 0
hs_pipeline_stage: 1
hs_ticket_priority: MEDIUM (ou HIGH si reclassifié)
```

## Association
Le ticket est automatiquement associé au contact via l'API Associations.

## URL Format
```
https://app.hubspot.com/contacts/{HUB_ID}/ticket/{TICKET_ID}
```

## Gestion des Erreurs
- **401 Unauthorized** : Token expiré, alerter admin
- **429 Rate Limit** : Retry avec backoff exponentiel (max 3)
- **Création échoue** : Logger et continuer sans ticket
