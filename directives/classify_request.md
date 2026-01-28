# SOP: Classification des Demandes

## Objectif
Classifier automatiquement les demandes clients en deux catégories : SUPPORT ou MODELISATION.

## Script
`execution/classify_request.py`

## Logique de Classification

### Catégorie SUPPORT
Demandes relatives à :
- Paiement, facturation, abonnement
- Bugs, erreurs techniques
- Compte utilisateur, mot de passe, connexion
- Questions générales sur la plateforme

**Mots-clés indicateurs** : paiement, facture, abonnement, bug, erreur, compte, mot de passe, connexion, crédit, problème

### Catégorie MODELISATION
Demandes relatives à :
- Création/modélisation d'objets 3D
- Visualisation en réalité augmentée
- Scan d'objets existants

**Mots-clés indicateurs** : créer, modéliser, visualiser, objet, produit, 3D, AR, réalité augmentée, scanner

**Indicateur fort** : Présence de fichiers 3D (.glb, .usdz, .obj, .fbx, .stl)

## Règles de Décision

1. **Confiance >= 70%** : Utiliser le type détecté par le LLM
2. **Confiance < 70%** : Fallback sur la source du formulaire
3. **Reclassification** : Si le type détecté diffère de la source, marquer `reclassifie=true`

## Output Format
```json
{
  "type_detecte": "SUPPORT | MODELISATION",
  "confiance": 0-100,
  "raison": "explication courte",
  "coherent": true/false,
  "type_final": "SUPPORT | MODELISATION",
  "reclassifie": true/false
}
```

## Self-Annealing
- Les erreurs de parsing JSON sont loggées dans `.tmp/error_log.json`
- Si taux d'erreur élevé, ajuster le prompt dans le script
