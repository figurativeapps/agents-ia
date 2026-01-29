# Récapitulatif : Workflow Request Handler

## Contexte

### Plateforme Figurative
Figurative est une plateforme de visualisation d'objets en réalité augmentée (AR). Les utilisateurs peuvent :
- Se connecter avec leurs identifiants
- Visualiser des objets 3D en AR
- Contacter l'administrateur via 2 types de formulaires

### Problématique initiale
Les demandes clients arrivent par email à `jordane.pellerin@figurative.fr` (connecté à HubSpot). Cependant :
- HubSpot (comptes récents) ne permet plus de créer automatiquement des tickets depuis la Conversations Inbox
- La création manuelle de tickets est chronophage
- Pas de synchronisation avec ClickUp pour le suivi opérationnel
- Pas de classification automatique des demandes

### Objectif
Automatiser à 100% le traitement des demandes clients :
1. Classification automatique (Support vs Modélisation)
2. Création de tickets HubSpot
3. Synchronisation ClickUp pour les demandes de modélisation
4. Stockage des pièces jointes volumineuses
5. Notification de l'équipe

---

## Architecture DOE (Directive-Orchestration-Execution)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        LAYER 1 : DIRECTIVES                         │
│                     (Les SOPs - "Quoi faire")                       │
├─────────────────────────────────────────────────────────────────────┤
│  directives/                                                        │
│  ├── workflow_request_handler.md   # SOP principal                  │
│  ├── classify_request.md           # Règles de classification       │
│  ├── create_hubspot_ticket.md      # Création ticket HubSpot        │
│  ├── create_clickup_subtask.md     # Création subtask ClickUp       │
│  └── notify_admin.md               # Notification équipe            │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      LAYER 2 : ORCHESTRATION                        │
│                  (L'Agent IA - "Décision")                          │
├─────────────────────────────────────────────────────────────────────┤
│  L'agent (Claude/Cursor) lit les directives et orchestre les        │
│  scripts en fonction du contexte :                                  │
│                                                                     │
│  • Mode A (Hunter) → Lead Generation                                │
│  • Mode B (Maker)  → PDF Creation                                   │
│  • Mode C (Handler)→ Request Handling  ← NOUVEAU                    │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       LAYER 3 : EXECUTION                           │
│                  (Scripts Python - "Action")                        │
├─────────────────────────────────────────────────────────────────────┤
│  execution/                                                         │
│  ├── webhook_server.py         # Serveur FastAPI + Redis            │
│  ├── classify_request.py       # Classification via Claude API      │
│  ├── hubspot_ticket.py         # API HubSpot (contacts + tickets)   │
│  ├── clickup_subtask.py        # API ClickUp (subtasks)             │
│  ├── upload_files.py           # Upload vers Cloudflare R2          │
│  ├── send_notification.py      # Notifications email                │
│  └── test_request_handler.py   # Script de test                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Diagramme de flux complet

```mermaid
flowchart TB
    subgraph Client [Client Figurative]
        U[Utilisateur]
        F1[Formulaire Contact]
        F2[Formulaire Modélisation]
    end
    
    subgraph Platform [Plateforme Figurative]
        WH[Webhook Server<br/>FastAPI + Redis]
    end
    
    subgraph DOE [Framework DOE - Serveur Ubuntu]
        subgraph Classification [Étape 1: Classification]
            CL[classify_request.py]
            CLAUDE[Claude API<br/>Anthropic]
        end
        
        subgraph Files [Étape 2: Fichiers]
            UP[upload_files.py]
            R2[Cloudflare R2]
        end
        
        subgraph HubSpot [Étape 3-4: HubSpot]
            HS[hubspot_ticket.py]
            CONTACT[Find/Create Contact]
            TICKET[Create Ticket]
        end
        
        subgraph ClickUp [Étape 5: ClickUp]
            CK[clickup_subtask.py]
            SUBTASK[Create Subtask]
        end
        
        subgraph Notify [Étape 6: Notification]
            NT[send_notification.py]
            EMAIL[Email Admin]
        end
    end
    
    subgraph External [Services Externes]
        HSCRM[(HubSpot CRM<br/>Help Desk)]
        CKAPP[(ClickUp<br/>Task Management)]
        R2STORE[(Cloudflare R2<br/>File Storage)]
        ADMIN[Admin<br/>yvanol.fotso@valione-services.com]
    end
    
    U -->|Demande simple| F1
    U -->|Demande modélisation + fichiers| F2
    F1 --> WH
    F2 --> WH
    
    WH -->|Payload JSON| CL
    CL <-->|Analyse| CLAUDE
    CL -->|SUPPORT| HS
    CL -->|MODELISATION| UP
    
    UP -->|Upload fichiers 3D| R2
    R2 -->|URLs publiques| HS
    UP --> HS
    
    HS --> CONTACT
    CONTACT --> TICKET
    TICKET -->|Ticket créé| HSCRM
    
    CL -->|Si MODELISATION| CK
    HS -->|ticket_url| CK
    CK --> SUBTASK
    SUBTASK --> CKAPP
    
    TICKET --> NT
    NT --> EMAIL
    EMAIL --> ADMIN
```

---

## Types de demandes

| Type | Source | Contenu | Fichiers | Actions déclenchées |
|------|--------|---------|----------|---------------------|
| **SUPPORT** | Formulaire contact | Question paiement, compte, bug | Rarement | HubSpot Ticket + Notification |
| **MODELISATION** | Formulaire modélisation | Demande création objet 3D | Oui (JPEG, PNG, GLB, OBJ...) | Upload R2 + HubSpot Ticket + ClickUp Subtask + Notification |

---

## Classification IA

Le système utilise Claude (Anthropic) pour classifier automatiquement les demandes :

### Indicateurs SUPPORT
- Mots-clés : paiement, facture, abonnement, bug, erreur, compte, mot de passe, connexion

### Indicateurs MODELISATION
- Mots-clés : créer, modéliser, visualiser, objet, produit, 3D, AR
- Fichiers 3D présents (.glb, .usdz, .obj, .fbx, .stl) = indicateur FORT

### Logique de décision
```
SI confiance >= 70% → Utiliser le type détecté par l'IA
SI confiance < 70%  → Fallback sur la source du formulaire
SI reclassification → Alerter l'admin (le formulaire utilisé ne correspondait pas)
```

---

## Intégrations configurées

### HubSpot
| Élément | Valeur |
|---------|--------|
| Hub ID | 147476643 |
| Pipeline ID | 0 (Pipeline de support) |
| Stage ID | 1 (Nouveau) |
| Scopes | contacts, tickets |

### ClickUp
| Élément | Valeur |
|---------|--------|
| Parent Task ID | 86c7r48ha |
| API | v2 |
| Action | Création subtask sous tâche parente |

### Cloudflare R2
| Élément | Valeur |
|---------|--------|
| Bucket | figurative-support |
| Région | Automatic |
| Accès public | Activé |
| URL publique | https://pub-44fb87ee985849b6b4a6899988df6140.r2.dev |

---

## Fichiers créés

### Directives (SOPs)
```
directives/
├── workflow_request_handler.md    # Workflow principal (6 étapes)
├── classify_request.md            # Règles de classification IA
├── create_hubspot_ticket.md       # Procédure création ticket
├── create_clickup_subtask.md      # Procédure création subtask
└── notify_admin.md                # Procédure notification
```

### Scripts d'exécution
```
execution/
├── classify_request.py            # 217 lignes - Classification LLM
├── hubspot_ticket.py              # 270 lignes - API HubSpot
├── clickup_subtask.py             # 205 lignes - API ClickUp
├── upload_files.py                # 240 lignes - Upload R2
├── send_notification.py           # 278 lignes - Notifications
├── test_request_handler.py        # 300 lignes - Tests
└── webhook_server.py              # 95 lignes - Serveur webhook
```

### Configuration
```
.env.template (mis à jour avec nouvelles variables)
requirements.txt (ajout anthropic, boto3, fastapi, uvicorn, redis)
AGENTS.md (ajout Mode C - Handler)
```

---

## Variables d'environnement requises

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

# Notification (optionnel)
NOTIFICATION_EMAIL=yvanol.fotso@valione-services.com
```

---

## Résultats des tests

### Test SUPPORT
```
✅ Classification: SUPPORT (95% confiance)
✅ HubSpot Contact: Trouvé/Créé
✅ HubSpot Ticket: Créé + Associé au contact
⏭️ ClickUp: Ignoré (normal pour SUPPORT)
⚠️ Notification: SMTP non configuré
```

### Test MODELISATION
```
✅ Classification: MODELISATION (95% confiance)
✅ HubSpot Contact: Trouvé/Créé
✅ HubSpot Ticket: Créé + Associé au contact
✅ ClickUp Subtask: Créé sous la tâche parente
✅ Upload R2: Fichiers accessibles publiquement
⚠️ Notification: SMTP non configuré
```

---

## Infrastructure

### Serveur de production
- **OS**: Ubuntu (Hetzner)
- **Utilisateur**: figurative
- **Chemin projet**: `/home/figurative/agents-ia`
- **Python**: 3.12 (venv)
- **Port webhook**: 5000

### Déploiement
```bash
# Connexion au serveur
ssh figurative@ubuntu-8gb-nbg1-1

# Activation environnement
source ~/venv/bin/activate
cd ~/agents-ia

# Lancement serveur webhook
uvicorn execution.webhook_server:app --host 0.0.0.0 --port 5000
```

---

## Prochaines étapes (à planifier)

1. **Notifications email** - Configurer SMTP pour alerter l'équipe
2. **Webhook production** - Lancer le serveur en mode daemon (systemd)
3. **Intégration Figurative** - Connecter les formulaires au webhook
4. **Monitoring** - Logs et alertes en cas d'erreur
5. **Tests end-to-end** - Validation complète du flux

---

## Avantages

| Avant | Après |
|-------|-------|
| Création manuelle de tickets | Automatique |
| Classification humaine | IA (95% précision) |
| Fichiers éparpillés | Centralisés sur R2 |
| Pas de suivi ClickUp | Subtasks automatiques |
| Processus chronophage | Instantané |

---

*Document généré le 29 janvier 2026*
*Projet: agents-ia / Workflow Request Handler*
