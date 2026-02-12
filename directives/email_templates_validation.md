# Templates Email - Workflow Validation Modélisation

> Templates utilisés par l'IA pour communiquer avec les clients et l'admin durant le processus de validation des demandes de modélisation.

## 1. Demande d'informations complémentaires

**Contexte:** La demande est incomplète (fichiers manquants, description insuffisante).

**Sujet:** `Re: [OBJET] - Informations complémentaires requises`

```html
<p>Bonjour,</p>

<p>Merci pour votre demande de modélisation concernant : <strong>[OBJET]</strong>.</p>

<p>Pour pouvoir traiter votre demande et vous fournir un devis précis, nous aurions besoin des éléments suivants :</p>

<ul>
  <!-- Éléments obligatoires manquants -->
  <li><strong>Une image de référence</strong> (photo, croquis, ou inspiration) de l'objet à modéliser</li>
  <li><strong>Une description plus détaillée</strong> de vos attentes</li>
</ul>

<p>Les informations suivantes nous aideraient également :</p>
<ul>
  <!-- Recommandations optionnelles -->
  <li>Les dimensions souhaitées (hauteur, largeur, profondeur)</li>
  <li>Les matériaux ou finitions désirés</li>
  <li>Des photos sous plusieurs angles si possible</li>
</ul>

<p>Dès réception de ces éléments, nous vous enverrons une estimation du coût en crédits.</p>

<p>Cordialement,<br>
L'équipe Figurative</p>
```

---

## 2. Devis - 1 Crédit

**Contexte:** Objet simple ou fichier 3D fourni.

**Sujet:** `Re: [OBJET] - Devis modélisation`

```html
<p>Bonjour,</p>

<p>Nous avons bien reçu votre demande de modélisation pour : <strong>[OBJET]</strong>.</p>

<p>Après analyse, le coût estimé pour cette modélisation est de :</p>

<p style="font-size: 20px; text-align: center; margin: 20px 0;">
  <strong>➤ 1 crédit</strong>
</p>

<p><em>[RAISON : ex. "Objet simple - modélisation basique" ou "Fichier 3D fourni - ajustements uniquement"]</em></p>

<p>Pour confirmer et lancer la modélisation, merci de <strong>répondre à cet email</strong> avec votre validation (ex: "Je valide" ou "OK").</p>

<p>Cordialement,<br>
L'équipe Figurative</p>
```

---

## 3. Devis - 2 Crédits

**Contexte:** Modélisation complète avec textures.

**Sujet:** `Re: [OBJET] - Devis modélisation`

```html
<p>Bonjour,</p>

<p>Nous avons bien reçu votre demande de modélisation pour : <strong>[OBJET]</strong>.</p>

<p>Après analyse, le coût estimé pour cette modélisation est de :</p>

<p style="font-size: 20px; text-align: center; margin: 20px 0;">
  <strong>➤ 2 crédits</strong>
</p>

<p><em>Modélisation complète avec création des textures.</em></p>

<p>Pour confirmer et lancer la modélisation, merci de <strong>répondre à cet email</strong> avec votre validation (ex: "Je valide" ou "OK").</p>

<p>Cordialement,<br>
L'équipe Figurative</p>
```

---

## 4. Notification Admin - Cas Complexe

**Contexte:** Objet très complexe nécessitant validation manuelle.

**Sujet:** `[VALIDATION REQUISE] Demande modélisation: [OBJET]`

**Destinataire:** Admin (jordane.pellerin@figurative.fr)

```html
<p>⚠️ <strong>VALIDATION REQUISE - Demande complexe</strong></p>

<table style="border-collapse: collapse; width: 100%; margin: 15px 0;">
  <tr>
    <td style="padding: 8px; border: 1px solid #ddd; background: #f5f5f5;"><strong>Client</strong></td>
    <td style="padding: 8px; border: 1px solid #ddd;">[USER_EMAIL]</td>
  </tr>
  <tr>
    <td style="padding: 8px; border: 1px solid #ddd; background: #f5f5f5;"><strong>Objet</strong></td>
    <td style="padding: 8px; border: 1px solid #ddd;">[OBJET]</td>
  </tr>
  <tr>
    <td style="padding: 8px; border: 1px solid #ddd; background: #f5f5f5;"><strong>Fichiers</strong></td>
    <td style="padding: 8px; border: 1px solid #ddd;">[NOMBRE] fichiers joints</td>
  </tr>
</table>

<p><strong>Description:</strong></p>
<blockquote style="border-left: 3px solid #ccc; padding-left: 15px; margin: 10px 0; color: #555;">
[DESCRIPTION - premiers 500 caractères]
</blockquote>

<p><strong>Analyse IA:</strong> [RAISON - ex. "Objet complexe avec ornements sculptés détectés"]</p>

<hr style="margin: 20px 0;">

<p>Merci de valider le nombre de crédits à facturer pour cette demande.</p>

<p><strong>Options:</strong></p>
<ul>
  <li>Répondre <code>1 crédit</code> pour une modélisation simple</li>
  <li>Répondre <code>2 crédits</code> pour une modélisation complète</li>
  <li>Répondre avec un autre montant si nécessaire</li>
</ul>

<p><a href="[TICKET_URL]">Voir le ticket HubSpot</a></p>
```

---

## 5. Confirmation de validation

**Contexte:** Le client a validé le devis, la modélisation démarre.

**Sujet:** `Re: [OBJET] - Modélisation confirmée`

```html
<p>Bonjour,</p>

<p>Votre demande de modélisation a été validée et est maintenant en cours de traitement.</p>

<p style="font-size: 18px; text-align: center; margin: 20px 0; padding: 15px; background: #e8f5e9; border-radius: 5px;">
  <strong>✓ Crédits débités : [CREDITS]</strong>
</p>

<p>Notre équipe va maintenant commencer la modélisation de votre objet. Vous serez notifié dès qu'elle sera terminée.</p>

<p>Cordialement,<br>
L'équipe Figurative</p>
```

---

## 6. Modélisation terminée

**Contexte:** La modélisation est terminée et prête à être livrée.

**Sujet:** `Re: [OBJET] - Votre modélisation est prête !`

```html
<p>Bonjour,</p>

<p>Bonne nouvelle ! La modélisation de votre objet <strong>[OBJET]</strong> est maintenant terminée.</p>

<p>Vous pouvez dès à présent visualiser votre objet en réalité augmentée depuis la plateforme Figurative.</p>

<p style="text-align: center; margin: 25px 0;">
  <a href="[LIEN_PLATEFORME]" style="background: #4CAF50; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; font-weight: bold;">
    Voir ma modélisation
  </a>
</p>

<p>Si vous avez des questions ou souhaitez des ajustements, n'hésitez pas à nous contacter.</p>

<p>Cordialement,<br>
L'équipe Figurative</p>
```

---

## Variables disponibles

| Variable | Description | Exemple |
|----------|-------------|---------|
| `[OBJET]` | Titre de la demande | "Table de chevet en chêne" |
| `[USER_EMAIL]` | Email du client | "client@example.com" |
| `[CREDITS]` | Nombre de crédits | "2" |
| `[RAISON]` | Justification du devis | "Modélisation complète avec textures" |
| `[DESCRIPTION]` | Description de la demande | "Je souhaite..." |
| `[TICKET_URL]` | Lien vers le ticket HubSpot | "https://app.hubspot.com/..." |
| `[NOMBRE]` | Nombre de fichiers | "3" |

---

## Règles de rédaction

1. **Ton professionnel mais accessible** - Pas trop formel, le client doit se sentir accompagné
2. **Clarté** - Les informations importantes (crédits, actions requises) doivent être visibles
3. **Call-to-action clair** - Toujours indiquer ce que le client doit faire
4. **Pas d'emojis excessifs** - Un ou deux maximum pour les points importants
5. **Responsive** - Les emails doivent être lisibles sur mobile

## Détection des réponses client

L'IA détecte automatiquement les réponses suivantes :

**Validation:**
- "Je valide"
- "J'accepte"
- "OK pour X crédits"
- "C'est bon"
- "D'accord"
- "Parfait"
- "On y va"

**Refus:**
- "Je refuse"
- "Trop cher"
- "Non merci"
- "J'annule"
- "Pas d'accord"

**Questions:**
- Présence de "?"
- "Pourquoi", "Comment", "Est-ce que"
- "Je ne comprends pas"
