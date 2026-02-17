# HubSpot Setup & Mapping

## Champs personnalisés à créer

Créer ces 3 champs dans **Paramètres > Propriétés** :

| Objet | Label | Internal name | Type |
|-------|-------|---------------|------|
| Contact | Industrie | `industrie` | Single-line text |
| Company | Industrie | `industrie` | Single-line text |
| Contact | LinkedIn URL | `linkedin_url` | Single-line text |

Ne jamais modifier l'`internal name` après création.

---

## Mapping Excel → HubSpot

### Contacts

| Colonne Excel | Propriété HubSpot | Type |
|---|---|---|
| `Email_Decideur` / `Email_Generique` | `email` | Standard |
| `Nom_Decideur` (prénom) | `firstname` | Standard |
| `Nom_Decideur` (nom) | `lastname` | Standard |
| `Poste_Decideur` | `jobtitle` | Standard |
| `Tel_Standard` | `phone` | Standard |
| `Site_Web` | `website` | Standard |
| `Adresse` | `address` | Standard |
| `Ville` | `city` | Standard |
| `Code_Postal` | `zip` | Standard |
| `Pays` | `country` | Standard |
| `Industrie` | `industrie` | Custom |
| `LinkedIn_URL` | `linkedin_url` | Custom |
| `Nom_Entreprise` | `company` | Standard |

### Companies

| Colonne Excel | Propriété HubSpot | Type |
|---|---|---|
| `Nom_Entreprise` | `name` | Standard |
| `Site_Web` | `domain` | Standard |
| `Adresse` | `address` | Standard |
| `Ville` | `city` | Standard |
| `Code_Postal` | `zip` | Standard |
| `Pays` | `country` | Standard |
| `Tel_Standard` | `phone` | Standard |
| `Industrie` | `industrie` | Custom |

### Colonnes non synchronisées (Excel uniquement)
- `Date_Ajout`, `Ecommerce`, `Statut_Sync`

---

## Déduplication

- **Contacts** : recherche par email
- **Companies** : recherche par domaine ou nom
- Chaque contact est auto-associé à sa company via l'API

---

## Sync bidirectionnelle

```bash
# Excel → HubSpot
python execution/sync_hubspot.py --input .tmp/enriched_leads.json

# HubSpot → Excel (supprime les contacts supprimés dans HubSpot)
python execution/sync_from_hubspot.py
```

---

## Troubleshooting

| Erreur | Cause | Solution |
|--------|-------|----------|
| `Property 'industrie' does not exist` | Champ non créé ou mauvais internal name | Vérifier dans Paramètres > Propriétés |
| `Property 'linkedin_url' does not exist` | Idem | Internal name = `linkedin_url` (avec underscore) |
