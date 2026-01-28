# SOP: Notification Admin

## Objectif
Notifier l'équipe dès qu'une nouvelle demande est traitée.

## Script
`execution/send_notification.py`

## Destinataire
- **Email** : yvanol.fotso@valione-services.com

## Déclencheur
Appelé à la fin de chaque traitement de demande (Step 6).

## Input
- `ticket_url` : URL du ticket HubSpot
- `type_final` : SUPPORT ou MODELISATION
- `objet` : Titre de la demande
- `user_email` : Email du client
- `reclassifie` : Boolean

## Format Email

### Sujet
```
[Figurative] Nouvelle demande {type_final} - {objet}
```

Si `reclassifie == true` :
```
[Figurative] RECLASSIFIE - Nouvelle demande {type_final} - {objet}
```

### Corps
```html
<h2>Nouvelle demande reçue</h2>

<p><strong>Type :</strong> {type_final}</p>
<p><strong>Client :</strong> {user_email}</p>
<p><strong>Objet :</strong> {objet}</p>

{si reclassifie}
<p style="color: orange;"><strong>Attention :</strong> Cette demande a été reclassifiée par l'IA (le formulaire utilisé ne correspondait pas au contenu).</p>
{/si}

<p><a href="{ticket_url}">Voir le ticket dans HubSpot</a></p>

---
<small>Notification automatique - Agent DOE Figurative</small>
```

## Méthode d'Envoi
- **Option 1** : API HubSpot (engagement email loggé)
- **Option 2** : SMTP direct (si HubSpot non disponible)

## Gestion des Erreurs
- Si envoi échoue, logger l'erreur
- Ne pas bloquer le workflow pour une notification échouée
