---
name: maker
description: "Génère des propositions commerciales PDF avec WeasyPrint et Jinja2 à partir de templates HTML et données entreprise. USE WHEN: l'utilisateur demande un PDF, une proposition commerciale, une plaquette, un document de présentation, ou un devis."
---

# Skill: Maker — PDF Proposal Generator

## Inputs requis
- `company_name` (ex: "La Belle Cuisine")
- `contact_name` (optionnel) — Nom du décideur
- `industry` (optionnel) — Secteur d'activité
- `template` (défaut: "plaquette_base.html")

---

## Pipeline

### Etape 1 : Récupération des données
- **Source :** `Generate_leads.xlsx`
- **Action :** Extraire les infos de l'entreprise par nom
- **Fallback :** Si non trouvée dans Excel, demander les infos à l'utilisateur

### Etape 2 : Génération PDF
- **Script :** `execution/generate_pdf.py`
- **Template :** `templates/plaquette_base.html`
- **Style :** `templates/style.css`
- **Moteur :** WeasyPrint + Jinja2
- **Output :** `output/{company_name}_proposal.pdf`

### Variables Jinja2 disponibles
| Variable | Description |
|----------|-------------|
| `{{ company_name }}` | Nom de l'entreprise |
| `{{ contact_name }}` | Nom du décideur |
| `{{ industry }}` | Secteur d'activité |
| `{{ our_company }}` | Nom de notre entreprise |
| `{{ value_proposition }}` | Proposition de valeur |
| `{{ services }}` | Liste des services |
| `{{ cta }}` | Call to action |

---

## Commandes

```bash
# Générer un PDF
python execution/generate_pdf.py --company "La Belle Cuisine"

# Créer un template Excel vierge
python execution/create_excel_template.py
```

---

## Contrôle qualité
- Vérifier que tous les placeholders sont remplis (pas de `{{ }}` vides)
- Vérifier le rendu PDF (pas de texte coupé)
- Taille fichier < 5 MB
- Prêt pour envoi email ou rattachement au contact HubSpot
