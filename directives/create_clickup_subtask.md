# SOP: Création Subtask ClickUp

## Objectif
Créer une subtask dans ClickUp pour le suivi opérationnel des demandes de modélisation.

## Script
`execution/clickup_subtask.py`

## Configuration
- **Parent Task ID** : 86c7r48ha
- **API Endpoint** : `POST https://api.clickup.com/api/v2/task/{parent_id}/subtask`

## Condition de Déclenchement
Uniquement si `type_final == MODELISATION`

## Input
- `objet` : Titre de la demande
- `user_email` : Email du client
- `ticket_url` : URL du ticket HubSpot associé

## Format Subtask

### Nom
```
Demande {user_email}
```

### Description
```markdown
**Demande de modélisation**

- **Client** : {user_email}
- **Objet** : {objet}
- **Ticket HubSpot** : {ticket_url}

---
Créé automatiquement par l'agent DOE.
```

## Output
- `subtask_id` : ID de la subtask créée
- `subtask_url` : URL directe vers la subtask

## Gestion des Erreurs
- **401 Unauthorized** : Token ClickUp invalide
- **429 Rate Limit** : Augmenter délai entre requêtes
- **ClickUp indisponible** : Logger l'erreur, ne pas bloquer le workflow
  - Le ticket HubSpot reste la source de vérité

## Notes
- Les subtasks sont regroupées sous une tâche parente fixe pour centraliser le suivi
- L'équipe opérationnelle peut voir toutes les demandes dans une seule vue
