# Guide d'intégration - Formulaire Figurative + Webhook

> Instructions pour configurer le formulaire Figurative afin d'appeler le webhook d'automatisation.

## Architecture cible

```
Client soumet formulaire
         │
         ├──► Email à jordane.pellerin@figurative.fr (déjà en place)
         │    └── Arrive dans HubSpot Conversations
         │
         └──► POST /webhook/request (à ajouter)
              └── Automatisation: Classification, R2, Ticket, ClickUp
```

## Endpoint Webhook

**URL Production** : `https://[SERVEUR]:5000/webhook/request`

**Méthode** : `POST`

**Headers** :
```
Content-Type: application/json
```

## Payload JSON

```json
{
  "source": "modelisation",
  "objet": "Titre de la demande",
  "description": "Contenu complet du message du client...",
  "user_email": "client@example.com",
  "user_name": "Prénom Nom",
  "fichiers": [
    {
      "name": "photo.jpg",
      "url": "https://url-temporaire-du-fichier.com/photo.jpg",
      "type": "image/jpeg",
      "size": 245000
    },
    {
      "name": "document.pdf",
      "url": "https://url-temporaire-du-fichier.com/document.pdf",
      "type": "application/pdf",
      "size": 150000
    }
  ]
}
```

## Champs obligatoires

| Champ | Type | Description |
|-------|------|-------------|
| `source` | string | `"contact"` ou `"modelisation"` selon le formulaire |
| `objet` | string | Titre/sujet de la demande |
| `description` | string | Contenu complet du message |
| `user_email` | string | Email du client |

## Champs optionnels

| Champ | Type | Description |
|-------|------|-------------|
| `user_name` | string | Nom complet du client |
| `fichiers` | array | Liste des pièces jointes |

## Format des fichiers

Chaque fichier dans le tableau `fichiers` :

```json
{
  "name": "nom_fichier.ext",
  "url": "https://url-temporaire-accessible/fichier.ext",
  "type": "mime/type",
  "size": 12345
}
```

**Important** : L'URL doit être accessible publiquement (ou temporairement) pour que le webhook puisse télécharger le fichier et l'uploader sur Cloudflare R2.

## Réponse du Webhook

**Succès (200)** :
```json
{
  "status": "created",
  "ticket_id": "375756709069",
  "ticket_url": "https://app.hubspot.com/contacts/147476643/ticket/375756709069",
  "is_new_ticket": true,
  "classification": "MODELISATION",
  "files_uploaded": 2,
  "message": "Nouveau ticket créé: #375756709069"
}
```

**Mise à jour ticket existant (200)** :
```json
{
  "status": "updated",
  "ticket_id": "375756709069",
  "ticket_url": "https://app.hubspot.com/contacts/147476643/ticket/375756709069",
  "is_new_ticket": false,
  "classification": "MODELISATION",
  "files_uploaded": 1,
  "message": "Réponse ajoutée au ticket existant #375756709069"
}
```

**Erreur (500)** :
```json
{
  "detail": "Processing error: [message d'erreur]"
}
```

## Exemple d'implémentation (JavaScript)

```javascript
// Après validation du formulaire, avant ou après l'envoi de l'email

async function submitToWebhook(formData) {
  const payload = {
    source: formData.formType, // "contact" ou "modelisation"
    objet: formData.subject,
    description: formData.message,
    user_email: formData.email,
    user_name: formData.name,
    fichiers: formData.attachments.map(file => ({
      name: file.name,
      url: file.temporaryUrl, // URL temporaire du fichier uploadé
      type: file.mimeType,
      size: file.size
    }))
  };

  try {
    const response = await fetch('https://[SERVEUR]:5000/webhook/request', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    const result = await response.json();
    console.log('Webhook response:', result);
    
    // Le webhook a traité la demande
    // L'email est envoyé en parallèle (indépendamment)
    
  } catch (error) {
    console.error('Webhook error:', error);
    // Ne pas bloquer l'envoi de l'email si le webhook échoue
  }
}
```

## Exemple d'implémentation (PHP)

```php
<?php
function submitToWebhook($formData) {
    $payload = [
        'source' => $formData['form_type'], // "contact" ou "modelisation"
        'objet' => $formData['subject'],
        'description' => $formData['message'],
        'user_email' => $formData['email'],
        'user_name' => $formData['name'],
        'fichiers' => array_map(function($file) {
            return [
                'name' => $file['name'],
                'url' => $file['temporary_url'],
                'type' => $file['mime_type'],
                'size' => $file['size']
            ];
        }, $formData['attachments'] ?? [])
    ];

    $ch = curl_init('https://[SERVEUR]:5000/webhook/request');
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_POST, true);
    curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($payload));
    curl_setopt($ch, CURLOPT_HTTPHEADER, [
        'Content-Type: application/json'
    ]);
    curl_setopt($ch, CURLOPT_TIMEOUT, 30);

    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    if ($httpCode === 200) {
        $result = json_decode($response, true);
        error_log('Webhook success: ' . $result['message']);
    } else {
        error_log('Webhook error: ' . $response);
    }
}
?>
```

## Points importants

1. **Appel asynchrone** : Le webhook peut être appelé de manière asynchrone (fire-and-forget) pour ne pas ralentir la soumission du formulaire.

2. **Gestion des erreurs** : Si le webhook échoue, l'email doit quand même être envoyé. Le webhook est un enrichissement, pas une dépendance critique.

3. **URLs des fichiers** : Les URLs temporaires doivent rester accessibles au moins 5 minutes après la soumission pour permettre le téléchargement par le webhook.

4. **Timeout** : Le webhook traite de manière synchrone et peut prendre jusqu'à 30 secondes en cas de fichiers volumineux.

## Test

Pour tester l'intégration, utilisez curl :

```bash
curl -X POST https://[SERVEUR]:5000/webhook/request \
  -H "Content-Type: application/json" \
  -d '{
    "source": "modelisation",
    "objet": "Test intégration formulaire",
    "description": "Ceci est un test d'\''intégration depuis le formulaire Figurative.",
    "user_email": "test@example.com",
    "user_name": "Test User",
    "fichiers": []
  }'
```

## Vérification santé

```bash
curl https://[SERVEUR]:5000/health
```

Réponse attendue :
```json
{
  "status": "healthy",
  "version": "2.1.0",
  "features": {
    "classification": true,
    "file_upload": true,
    "hubspot": true,
    "clickup": true,
    "notifications": false,
    "conversation_threading": true,
    "email_association": true
  }
}
```

## Fonctionnalité optionnelle : Association Email-Ticket

Le webhook peut automatiquement associer la conversation email HubSpot au ticket créé. Cette fonctionnalité utilise l'API Conversations HubSpot (beta).

### Comment ça fonctionne

1. Quand un ticket est créé, le webhook tente de trouver le thread de conversation email correspondant
2. Si trouvé, le ticket est lié à la conversation dans HubSpot
3. Cela permet de voir le ticket directement depuis la boîte de réception HubSpot

### Association manuelle

Si l'association automatique échoue (timing, API), vous pouvez la relancer manuellement :

```bash
curl -X POST "https://[SERVEUR]:5000/webhook/associate-email?contact_email=client@example.com&ticket_id=375756709069"
```

### Limitations

- L'API Conversations HubSpot est en beta
- Le timing peut être problématique si l'email arrive après le webhook
- Nécessite les scopes `conversations.read` et `conversations.write`
