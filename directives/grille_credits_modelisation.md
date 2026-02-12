# Grille Tarifaire - Estimation des Crédits Modélisation 3D

> Ce document sert de référence à l'IA pour estimer le coût en crédits d'une demande de modélisation.

## Règles d'Estimation

### 1 Crédit - Modélisation Simple

Une demande coûte **1 crédit** si l'une des conditions suivantes est remplie :

- **Le client fournit déjà un modèle 3D** (fichier .glb, .usdz, .obj, .fbx, .stl, .gltf) avec texture
  - Travail requis : ajustements mineurs, optimisation, conversion de format
  
- **Objet simple à modéliser** :
  - Forme géométrique basique (cube, cylindre, sphère avec modifications mineures)
  - Peu de détails (surface lisse, peu d'éléments décoratifs)
  - Texture simple ou unie
  - Exemples : boîte de rangement, cadre photo, vase simple, tabouret basique

### 2 Crédits - Modélisation Complète

Une demande coûte **2 crédits** si :

- **Création complète requise** (modélisation + texture)
- **Objet de complexité moyenne** :
  - Plusieurs éléments à assembler
  - Détails décoratifs (moulures, gravures, motifs)
  - Textures multiples ou réalistes (bois, métal, tissu)
  - Exemples : chaise avec dossier travaillé, table avec pieds sculptés, lampe design

### Cas Incertain - Validation Admin Requise

Demander l'avis de l'administrateur **AVANT** de répondre au client si :

- **Objet très complexe** à créer entièrement :
  - Nombreux détails fins (sculptures, ornements complexes)
  - Mécanismes ou parties mobiles
  - Textures très élaborées (motifs répétitifs complexes, matériaux multiples)
  - Exemples : meuble ancien avec marqueterie, lustre à multiples branches, cheminée ornementée

- **Doute sur la faisabilité** :
  - Description ambiguë
  - Références visuelles contradictoires
  - Demande inhabituelle

## Éléments à Vérifier pour l'Estimation

### Informations Obligatoires (demande complète)

Pour qu'une demande soit considérée **complète**, elle doit contenir :

1. **Au moins 1 fichier visuel** :
   - Image de référence (photo, croquis, inspiration)
   - OU fichier 3D existant à modifier
   - OU PDF avec plans/dimensions

2. **Description suffisante** :
   - Type d'objet clairement identifié
   - Usage prévu (optionnel mais utile)

### Informations Recommandées (améliore l'estimation)

- Dimensions souhaitées (L x H x P)
- Matériaux/finitions désirés
- Couleurs ou textures spécifiques
- Photos sous plusieurs angles
- Niveau de détail attendu

## Processus de Décision

```
1. Le client a-t-il fourni un fichier 3D avec texture ?
   └─ OUI → 1 crédit (ajustements)
   └─ NON → continuer

2. La demande est-elle complète (fichier visuel + description) ?
   └─ NON → Demander les éléments manquants au client
   └─ OUI → continuer

3. L'objet est-il simple (forme basique, peu de détails) ?
   └─ OUI → 1 crédit
   └─ NON → continuer

4. L'objet est-il de complexité moyenne ?
   └─ OUI → 2 crédits
   └─ NON → continuer

5. L'objet est très complexe ou cas incertain
   └─ Demander validation admin AVANT de répondre au client
```

## Exemples Concrets

| Demande | Crédits | Raison |
|---------|---------|--------|
| "Voici mon fichier .glb, pouvez-vous l'optimiser pour AR ?" | 1 | Fichier 3D fourni |
| "Modéliser une boîte carrée en bois" + photo | 1 | Objet simple |
| "Créer une table de chevet avec 2 tiroirs" + croquis | 2 | Modélisation complète moyenne |
| "Bibliothèque murale 4m avec éclairage LED intégré" + photos | 2 | Modélisation complète moyenne |
| "Cheminée style Louis XV avec ornements sculptés" + inspiration | Admin | Très complexe, validation requise |
| "Reproduire ce meuble ancien avec marqueterie" + photo | Admin | Très complexe, validation requise |

## Format de Réponse au Client

### Si 1 crédit :
> Votre demande de modélisation pour [OBJET] a été analysée. Le coût estimé est de **1 crédit**.
> Merci de confirmer pour que nous puissions démarrer la modélisation.

### Si 2 crédits :
> Votre demande de modélisation pour [OBJET] a été analysée. Le coût estimé est de **2 crédits** (modélisation complète avec textures).
> Merci de confirmer pour que nous puissions démarrer la modélisation.

### Si validation admin requise :
> [Message interne à l'admin, pas au client]
> Demande complexe nécessitant validation : [OBJET]
> Description : [RÉSUMÉ]
> Suggestion IA : [X crédits ou incertain]
> Merci de valider le nombre de crédits avant réponse au client.
