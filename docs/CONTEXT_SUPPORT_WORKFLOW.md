# Contexte Complet : Workflow Support Figurative

> Document de contexte pour reprise de conversation. Dernière mise à jour : 29 janvier 2026.

---

## 1. Objectif Principal

Automatiser à 100% le traitement des demandes clients de la plateforme **Figurative** (visualisation d'objets en réalité augmentée) sans utiliser n8n, en restant dans le **framework DOE** existant.

### Problématique initiale
- Les emails clients arrivent à `jordane.pellerin@figurative.fr` (connecté à HubSpot)
- HubSpot (comptes récents) ne permet plus de créer automatiquement des tickets
- Création manuelle chronophage
- Pas de synchronisation avec ClickUp
- Pas de classification automatique

### Solution implémentée
Un workflow automatisé qui :
1. Classifie les demandes (SUPPORT vs MODELISATION) via IA + règles
2. Crée des tickets HubSpot Help Desk
3. Crée des subtasks ClickUp (pour modélisation)
4. Upload les fichiers 3D vers Cloudflare R2
5. Notifie l'équipe (à configurer)

---

## 2. Architecture DOE (3 Layers)

```
LAYER 1: DIRECTIVES (directives/)
├── workflow_request_handler.md   # SOP principal
├── classify_request.md           # Règles classification
├── create_hubspot_ticket.md      # Procédure HubSpot
├── create_clickup_subtask.md     # Procédure ClickUp
└── notify_admin.md               # Procédure notification

LAYER 2: ORCHESTRATION
└── Agent IA (Mode C - Handler)

LAYER 3: EXECUTION (execution/)
├── classify_request.py           # Classification optimisée
├── hubspot_ticket.py             # API HubSpot
├── clickup_subtask.py            # API ClickUp
├── upload_files.py               # Upload R2
├── send_notification.py          # Notifications
├── webhook_server.py             # Serveur FastAPI
└── test_request_handler.py       # Tests
```

---

## 3. Types de Demandes

| Type | Description | Actions |
|------|-------------|---------|
| **SUPPORT** | Paiement, compte, bugs, questions | HubSpot Ticket + Notification |
| **MODELISATION** | Création objet 3D pour AR | Upload R2 + HubSpot Ticket + ClickUp Subtask + Notification |

---

## 4. Classification Optimisée (Décision Clé)

### Optimisation pour réduire les coûts (~90% d'économie)

**Avant** : Toutes les requêtes → Claude Sonnet 4 (~$0.004/requête)

**Après** : Pré-filtrage par règles + Claude Haiku 4.5 si nécessaire

```python
# Flux de classification
1. Fichiers 3D présents ? → MODELISATION (95% confiance) [RULES]
2. Mots-clés SUPPORT dominants ? → SUPPORT (90% confiance) [RULES]
3. Mots-clés MODELISATION dominants ? → MODELISATION (90% confiance) [RULES]
4. Aucun mot-clé ? → Basé sur source formulaire (75% confiance) [RULES]
5. Cas ambigu → Claude Haiku 4.5 [LLM]
```

### Code clé : `execution/classify_request.py`

```python
# Mots-clés SUPPORT
SUPPORT_KEYWORDS = [
    'paiement', 'payer', 'facture', 'facturation', 'abonnement',
    'bug', 'erreur', 'problème', 'probleme', 'dysfonctionnement',
    'compte', 'connexion', 'connecter', 'mot de passe', 'password',
    'crédit', 'credit', 'remboursement', 'annuler', 'annulation',
    'aide', 'support', 'assistance', 'question'
]

# Mots-clés MODELISATION (éviter les mots courts comme 'ar', 'scan')
MODELISATION_KEYWORDS = [
    'modéliser', 'modeliser', 'modélisation', 'modelisation',
    'créer un objet', 'creer un objet', 'création 3d', 'creation 3d',
    '3d', 'réalité augmentée', 'realite augmentee', 'augmented reality',
    'scanner', 'visualiser en ar', 'rendu 3d', 'render'
]

# Modèle LLM (pour cas ambigus)
model = "claude-haiku-4-5"  # Actuel, non déprécié
```

### Bug corrigé
- Le mot `ar` était détecté dans "n'**ar**rive" → faux positif
- Solution : utiliser des expressions plus longues

---

## 5. Intégrations Configurées

### HubSpot
| Paramètre | Valeur |
|-----------|--------|
| Hub ID | 147476643 |
| Pipeline ID | 0 |
| Stage "Nouveau" | 1 |
| Scopes | contacts, tickets |

### ClickUp
| Paramètre | Valeur |
|-----------|--------|
| Parent Task ID | 86c7r48ha |
| Action | Créer subtask via API v2 |

### Cloudflare R2
| Paramètre | Valeur |
|-----------|--------|
| Bucket | figurative-support |
| Public URL | https://pub-44fb87ee985849b6b4a6899988df6140.r2.dev |
| Account ID | c46afcbabb4183669d66739ce638dd2e |

---

## 6. Variables d'Environnement (.env)

```bash
# Classification IA
ANTHROPIC_API_KEY=sk-ant-...

# HubSpot
HUBSPOT_API_KEY=pat-...
HUBSPOT_HUB_ID=147476643
HUBSPOT_PIPELINE_ID=0
HUBSPOT_STAGE_NEW=1

# ClickUp
CLICKUP_API_KEY=pk_...
CLICKUP_PARENT_TASK_ID=86c7r48ha

# Cloudflare R2
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET_NAME=figurative-support
R2_ENDPOINT_URL=https://c46afcbabb4183669d66739ce638dd2e.r2.cloudflarestorage.com
R2_PUBLIC_URL=https://pub-44fb87ee985849b6b4a6899988df6140.r2.dev

# Notification
NOTIFICATION_EMAIL=yvanol.fotso@valione-services.com
```

---

## 7. Infrastructure

| Élément | Détail |
|---------|--------|
| Serveur | Ubuntu (Hetzner) - `ubuntu-8gb-nbg1-1` |
| Utilisateur | `figurative` |
| Chemin projet | `/home/figurative/agents-ia` |
| Python | 3.12 (venv dans `~/venv`) |
| Repo GitHub | `figurativeapps/agents-ia` |

### Commandes utiles
```bash
# Connexion et activation
ssh figurative@ubuntu-8gb-nbg1-1
source ~/venv/bin/activate
cd ~/agents-ia

# Mise à jour depuis GitHub
git pull

# Tests
python execution/test_request_handler.py --live --payload support_simple
python execution/test_request_handler.py --live --payload modelisation_with_files
```

---

## 8. Flux de Traitement Détaillé (SUPPORT)

```
┌──────────────────────────────────────────────────────────────────┐
│                     DEMANDE SUPPORT                              │
│  Exemple: "Problème de paiement - Je n'arrive pas à payer"       │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│ ÉTAPE 1: Classification (classify_request.py)                    │
│ ─────────────────────────────────────────────────────────────────│
│ • Vérifie fichiers 3D → Non                                      │
│ • Compte mots-clés SUPPORT → 5 (paiement, payer, facture...)     │
│ • Compte mots-clés MODELISATION → 0                              │
│ • Règle 2 déclenche → SUPPORT (90% confiance)                    │
│ • Pas d'appel LLM nécessaire                                     │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│ ÉTAPE 2: Upload fichiers (upload_files.py)                       │
│ ─────────────────────────────────────────────────────────────────│
│ • Type = SUPPORT → SKIP (pas de fichiers à uploader)             │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│ ÉTAPE 3: Contact HubSpot (hubspot_ticket.py)                     │
│ ─────────────────────────────────────────────────────────────────│
│ • Recherche contact par email                                    │
│ • Si existe → Récupère contact_id                                │
│ • Si n'existe pas → Crée nouveau contact                         │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│ ÉTAPE 4: Ticket HubSpot (hubspot_ticket.py)                      │
│ ─────────────────────────────────────────────────────────────────│
│ • Crée ticket dans Pipeline 0, Stage 1                           │
│ • Propriétés: subject, content, priority                         │
│ • Associe ticket au contact (API v4 associations)                │
│ • Retourne: ticket_id, ticket_url                                │
│                                                                  │
│ URL générée:                                                     │
│ https://app.hubspot.com/contacts/147476643/ticket/{TICKET_ID}    │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│ ÉTAPE 5: ClickUp Subtask (clickup_subtask.py)                    │
│ ─────────────────────────────────────────────────────────────────│
│ • Type = SUPPORT → SKIP (uniquement pour MODELISATION)           │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│ ÉTAPE 6: Notification (send_notification.py)                     │
│ ─────────────────────────────────────────────────────────────────│
│ • Destinataire: yvanol.fotso@valione-services.com                │
│ • Contenu: Type, Client, Objet, Lien ticket                      │
│ • Status actuel: NON CONFIGURÉ (SMTP manquant)                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 9. Problèmes Résolus

| Problème | Solution |
|----------|----------|
| HubSpot 403 Forbidden | Ajouter scope `tickets` à la Private App |
| HubSpot 400 Bad Request | Supprimer propriétés custom inexistantes |
| Association ticket/contact échoue | Utiliser API v4 associations |
| Hub ID = UNKNOWN | Hardcoder `HUBSPOT_HUB_ID=147476643` |
| ClickUp 404 subtask | Créer tâche dans liste avec `parent` |
| Modèle LLM déprécié | `claude-haiku-4-5` (actuel) |
| Faux positif "ar" dans "n'arrive" | Utiliser expressions longues |
| R2 URLs non accessibles | Activer Public Development URL |

---

## 10. Problèmes Ouverts / Prochaines Étapes

| Élément | Status | Action requise |
|---------|--------|----------------|
| **Notifications email** | Non configuré | Configurer SMTP dans .env |
| **Webhook production** | Non lancé | Lancer uvicorn en daemon (systemd) |
| **Intégration Figurative** | En attente | Connecter formulaires au webhook |
| **Monitoring** | Non implémenté | Logs et alertes |

---

## 11. Fichiers Clés à Connaître

| Fichier | Description |
|---------|-------------|
| `AGENTS.md` | Instructions agent (Mode A/B/C) |
| `directives/workflow_request_handler.md` | SOP principal du workflow |
| `execution/classify_request.py` | Classification optimisée |
| `execution/hubspot_ticket.py` | Création tickets + contacts |
| `execution/test_request_handler.py` | Script de test complet |
| `docs/RECAP_REQUEST_HANDLER.md` | Documentation complète |
| `.env.template` | Template variables d'environnement |

---

## 12. Commandes de Test Rapide

```bash
# Sur le serveur Ubuntu
source ~/venv/bin/activate
cd ~/agents-ia

# Test complet workflow SUPPORT
python execution/test_request_handler.py --live --payload support_simple

# Test complet workflow MODELISATION
python execution/test_request_handler.py --live --payload modelisation_with_files

# Test classification seule (sans API calls)
python execution/classify_request.py \
  --objet "Problème paiement" \
  --description "Je n'arrive pas à payer" \
  --source contact

# Test upload R2
python -c "
from execution.upload_files import upload_files
result = upload_files([{'name': 'test.txt', 'path': '/tmp/test.txt'}])
print(result)
"
```

---

## 13. Contacts et Identifiants

| Élément | Valeur |
|---------|--------|
| Email plateforme | jordane.pellerin@figurative.fr |
| Email notification | yvanol.fotso@valione-services.com |
| HubSpot Hub ID | 147476643 |
| ClickUp Parent Task | 86c7r48ha |
| GitHub Repo | figurativeapps/agents-ia |

---

*Ce document peut être copié dans un nouveau chat pour reprendre le contexte.*
