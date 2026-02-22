---
name: PDF_gen
description: "Génère des propositions commerciales PDF avec WeasyPrint et Jinja2 à partir de templates HTML et données entreprise. USE WHEN: l'utilisateur demande un PDF, une proposition commerciale, une plaquette, un document de présentation, ou un devis."
---

# Skill: PDF_gen — PDF Proposal Generator

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

---

## Pipeline B : Overlay sur template Canva

### Inputs requis
- `image` — Chemin vers l'image snapshot à insérer (différente par lead)
- `url` — URL dynamique pour le QR code et lien cliquable
- `title` — Titre affiché au-dessus du snapshot (provient du custom field ClickUp "Titre snapshot")
- `company` (optionnel) — Nom entreprise pour le fichier output

### Etape 1 : Preview (positionnement)
```bash
python execution/overlay_pdf.py --preview
```
Affiche les dimensions du PDF et les repères pour positionner image/QR.

### Etape 2 : Génération avec overlay
```bash
python execution/overlay_pdf.py \
  --image photo.jpg \
  --url "https://example.com/lead" \
  --company "Acme Corp" \
  --image-rect "x0,y0,x1,y1" \
  --qr-rect "x0,y0,x1,y1"
```

### Template Canva
- **Fichier :** `template_plaquette_co.pdf` (racine du projet)
- **Dimensions :** 930 x 1316 points (328 x 464 mm)
- **Moteur :** PyMuPDF (fitz) + qrcode

### Options
| Argument | Description | Défaut |
|----------|-------------|--------|
| `--template` | PDF template | `template_plaquette_co.pdf` |
| `--image` | Image à insérer | requis |
| `--url` | URL QR code + lien | requis |
| `--image-rect` | Position image (x0,y0,x1,y1 pts) | `50,50,250,200` |
| `--qr-rect` | Position QR code (x0,y0,x1,y1 pts) | `450,650,550,750` |
| `--page` | Page cible (0-indexed) | `0` |
| `--preview` | Mode aperçu dimensions | — |

---

## Contrôle qualité
- Vérifier que tous les placeholders sont remplis (pas de `{{ }}` vides)
- Vérifier le rendu PDF (pas de texte coupé)
- Taille fichier < 5 MB
- QR code lisible (scanner avec téléphone)
- Lien URL cliquable dans le PDF
- Prêt pour envoi email ou rattachement au contact HubSpot
