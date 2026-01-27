# 🔗 Mapping HubSpot - Colonnes Excel

Ce document explique comment les colonnes de votre fichier Excel `Generate_leads.xlsx` sont synchronisées avec HubSpot.

## 📊 Mapping des Contacts

| Colonne Excel | Propriété HubSpot | Type | Notes |
|---------------|-------------------|------|-------|
| `Email_Decideur` / `Email_Generique` | `email` | Standard | Email principal du contact |
| `Nom_Decideur` (prénom) | `firstname` | Standard | Premier mot du nom complet |
| `Nom_Decideur` (nom) | `lastname` | Standard | Reste du nom complet |
| `Poste_Decideur` | `jobtitle` | Standard | Titre du poste |
| `Tel_Standard` | `phone` | Standard | Numéro de téléphone |
| `Site_Web` | `website` | Standard | Site web de l'entreprise |
| `Adresse` | `address` | Standard | Adresse complète |
| `Ville` | `city` | Standard | Ville |
| `Code_Postal` | `zip` | Standard | Code postal |
| `Pays` | `country` | Standard | Pays extrait de l'adresse |
| `Industrie` | `industrie` | **Personnalisé** | Champ texte personnalisé créé dans HubSpot |
| `LinkedIn_URL` | `linkedin_url` | **Personnalisé** | Champ texte personnalisé créé dans HubSpot |
| `Nom_Entreprise` | `company` | Standard | Nom de l'entreprise (texte) |

## 🏢 Mapping des Companies (Entreprises)

| Colonne Excel | Propriété HubSpot | Type | Notes |
|---------------|-------------------|------|-------|
| `Nom_Entreprise` | `name` | Standard | Nom de l'entreprise |
| `Site_Web` | `domain` | Standard | Domaine du site web (sans http://) |
| `Adresse` | `address` | Standard | Adresse complète |
| `Ville` | `city` | Standard | Ville |
| `Code_Postal` | `zip` | Standard | Code postal |
| `Pays` | `country` | Standard | Pays extrait de l'adresse |
| `Tel_Standard` | `phone` | Standard | Téléphone principal |
| `Industrie` | `industrie` | **Personnalisé** | Champ texte personnalisé créé dans HubSpot |

## ⚠️ Notes Importantes

### Champs Personnalisés HubSpot

**Deux champs personnalisés ont été créés dans HubSpot :**

1. **`industrie`** (Contacts & Companies)
   - Type : Texte d'une ligne
   - Accepte n'importe quelle valeur : "Cuisinistes", "Spa", "Piscines", "Menuiseries", etc.
   - Pas de limitation aux valeurs prédéfinies

2. **`linkedin_url`** (Contacts)
   - Type : Texte d'une ligne
   - Stocke l'URL complète du profil LinkedIn

**Comment créer ces champs dans HubSpot :**
1. Allez dans **Paramètres** → **Propriétés**
2. Sélectionnez **Contact Properties** ou **Company Properties**
3. Cliquez sur **Create property**
4. Configurez :
   - **Label** : Industrie (ou LinkedIn URL)
   - **Internal name** : `industrie` (ou `linkedin_url`) ⚠️ Important !
   - **Type** : Single-line text

### Association Contact-Company

Chaque contact est automatiquement associé à sa company dans HubSpot via :
- La création de la company en premier
- L'association du contact à la company via l'API

### Déduplication

- **Contacts** : Recherche par email
- **Companies** : Recherche par domaine (site web) ou nom

Si un contact/company existe déjà, il est mis à jour au lieu d'être recréé.

## 📝 Colonnes Non Synchronisées

Ces colonnes restent uniquement dans Excel :

- `Date_Ajout` - Date de création du lead
- `Ecommerce` - Indicateur e-commerce (Oui/Non) - **CRITÈRE DE FILTRAGE** : Seuls les leads avec e-commerce sont conservés
- `Statut_Sync` - Statut de synchronisation HubSpot

## 🔍 Vérification dans HubSpot

Après la synchronisation, vous pouvez vérifier :

1. **Contacts** → Rechercher par email
   - Vérifiez les champs : Adresse, Ville, Industry, LinkedIn

2. **Companies** → Rechercher par nom
   - Vérifiez les champs : Adresse, Ville
   - L'industrie est dans le champ "Description"

## 🔄 Synchronisation Bidirectionnelle

### Excel → HubSpot (Synchronisation normale)

Pour mettre à jour des contacts existants :

```bash
python execution/sync_hubspot.py --input .tmp/enriched_leads.json
```

Les contacts existants seront détectés et mis à jour avec les nouvelles données.

### HubSpot → Excel (Synchronisation inverse)

Pour détecter et supprimer les contacts supprimés dans HubSpot :

```bash
python execution/sync_from_hubspot.py
```

**Ce que fait ce script :**
- Lit tous les contacts dans votre fichier Excel
- Vérifie pour chaque email s'il existe encore dans HubSpot
- **Supprime complètement** les lignes des contacts qui n'existent plus dans HubSpot
- Met à jour le fichier Excel automatiquement

**⚠️ Important :** Fermez le fichier Excel avant d'exécuter ce script.

**💡 Conseil :** Lancez cette synchronisation inverse périodiquement (par exemple, une fois par semaine) pour maintenir votre Excel à jour avec HubSpot.

## 💡 Conseils

1. **Vérifiez d'abord** : Testez avec 1-2 leads avant de synchroniser en masse
2. **Synchronisation inverse** : Lancez `sync_from_hubspot.py` régulièrement pour garder Excel à jour
3. **LinkedIn** : Le champ `hs_linkedin_url` dans HubSpot est un champ standard
4. **Industrie** : Le champ `industrie` pour les contacts est personnalisé, pour les companies il est dans `description`
