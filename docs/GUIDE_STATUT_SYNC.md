# Guide d'utilisation : Colonne Statut_Sync

## Vue d'ensemble

La colonne `Statut_Sync` dans le fichier **Generate_leads.xlsx** permet de gérer la synchronisation avec HubSpot et d'éviter que des contacts supprimés soient automatiquement recréés.

## Valeurs possibles

| Statut | Description | Action du système |
|--------|-------------|-------------------|
| **New** | Nouveau lead pas encore synchronisé | Sera synchronisé au prochain run |
| **Synced** | Contact synchronisé avec HubSpot | Sera mis à jour si des données changent |
| **Deleted** | Contact supprimé de HubSpot | **Ne sera JAMAIS re-synchronisé** |
| **No Email** | Lead sans email | Ne peut pas être synchronisé |
| **Failed** | Échec de synchronisation | À vérifier manuellement |

## Workflow recommandé

### 1. Lors d'un nouveau pipeline
- Tous les nouveaux leads reçoivent automatiquement le statut **"New"**
- Le système les synchronise automatiquement avec HubSpot
- Le statut passe à **"Synced"** après succès

### 2. Si vous supprimez un contact dans HubSpot

**IMPORTANT** : Pour éviter qu'il soit recréé automatiquement :

1. Ouvrez **Generate_leads.xlsx**
2. Trouvez le contact supprimé
3. Changez manuellement `Statut_Sync` de **"Synced"** à **"Deleted"**
4. Sauvegardez le fichier

Le système ne synchronisera plus jamais ce contact !

### 3. Lors des prochains pipelines

- Les leads avec statut **"Deleted"** seront automatiquement ignorés
- Un message apparaîtra : `🚫 Skipped - Contact marked as Deleted`
- Vous gardez l'historique dans Excel sans risque de re-synchronisation

## Exemple pratique

```
Scénario : Vous avez supprimé "Restaurant Cheminée" de HubSpot

1. Ouvrir Generate_leads.xlsx
2. Trouver la ligne "Restaurant Cheminée"
3. Dans la colonne Statut_Sync, changer "Synced" → "Deleted"
4. Sauvegarder

✅ Lors du prochain run du pipeline :
   - Si le système trouve à nouveau ce restaurant
   - Il l'ajoutera dans Excel avec statut "New"
   - Lors de la sync HubSpot, il verra le statut "Deleted"
   - Il sera ignoré automatiquement
```

## Vérification des statuts

Pour voir un résumé de vos statuts dans Excel, vous pouvez :
1. Utiliser un filtre sur la colonne `Statut_Sync`
2. Compter les différentes valeurs

## Notes importantes

⚠️ **Ne pas confondre** :
- `Statut` = Statut commercial du lead (Nouveau, En cours, Converti, etc.)
- `Statut_Sync` = Statut technique de synchronisation HubSpot

💡 **Conseil** : Mettez à jour le `Statut_Sync` en "Deleted" immédiatement après avoir supprimé un contact dans HubSpot pour éviter toute confusion.

## Dépannage

### Le contact a été recréé malgré le statut "Deleted"
- Vérifiez que vous avez bien sauvegardé le fichier Excel
- Vérifiez l'orthographe exacte : "Deleted" (avec majuscule)

### Je veux forcer la re-synchronisation d'un contact "Deleted"
- Changez simplement le statut de "Deleted" à "New"
- Le prochain run le synchronisera à nouveau

### Comment voir les contacts ignorés ?
- Pendant le run du pipeline, les messages `🚫 Skipped` apparaissent dans la console
- À la fin, un résumé affiche : `🚫 Skipped: X contacts (marked as Deleted)`
