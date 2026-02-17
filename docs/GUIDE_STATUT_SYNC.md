# Colonne Statut_Sync (Generate_leads.xlsx)

Gère la synchronisation Excel ↔ HubSpot pour éviter de recréer des contacts supprimés.

## Valeurs

| Statut | Description | Comportement sync |
|--------|-------------|-------------------|
| `New` | Nouveau lead | Sera synchronisé |
| `Synced` | Déjà dans HubSpot | Mis à jour si changements |
| `Deleted` | Supprimé de HubSpot | **Ignoré définitivement** |
| `No Email` | Pas d'email | Non synchronisable |
| `Failed` | Erreur de sync | À vérifier manuellement |

## Workflow

1. Nouveaux leads → statut `New` automatique → sync → statut `Synced`
2. Suppression dans HubSpot → changer manuellement `Synced` → `Deleted` dans Excel
3. Pour forcer une re-sync → changer `Deleted` → `New`

Ne pas confondre `Statut` (commercial) avec `Statut_Sync` (technique).
