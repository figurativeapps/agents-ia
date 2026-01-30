# Processus Support Figurative

> Workflow automatisé pour traiter les demandes clients (Support / Modélisation)

## Types de demandes

| Type | Déclencheur | Actions |
|------|-------------|---------|
| **SUPPORT** | Mots-clés: paiement, bug, compte... | Contact → Ticket → Notification |
| **MODELISATION** | Fichiers 3D ou mots-clés: modéliser, 3D, AR | Upload R2 → Contact → Ticket → Note → ClickUp → Notification |

---

## Scripts disponibles

| Script | Fonction | Usage |
|--------|----------|-------|
| `classify_request.py` | Classification SUPPORT/MODELISATION | Règles + LLM (Haiku) |
| `upload_files.py` | Upload fichiers vers R2 | Retourne URLs publiques |
| `hubspot_ticket.py` | Contact + Ticket + Note | `find_or_create_contact()`, `create_ticket()`, `create_note()` |
| `clickup_subtask.py` | Subtask avec description + URLs | `create_subtask()` |
| `send_notification.py` | Email admin | ⚠️ SMTP non configuré |
| `test_request_handler.py` | Tests workflow | `--live --payload modelisation_with_files` |

---

## Configuration (.env)

```bash
# Classification
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

## Flux MODELISATION (7 étapes)

```
1. Classification → MODELISATION (fichiers 3D = 95% confiance)
2. Upload R2 → URLs publiques permanentes
3. Contact HubSpot → find_or_create par email
4. Ticket HubSpot → Pipeline 0, Stage 1, contenu + URLs
5. Note HubSpot → Liens cliquables sur fiche contact
6. ClickUp Subtask → Description complète + URLs fichiers
7. Notification → Email admin (SMTP requis)
```

---

## Contenu ClickUp Subtask

```markdown
**Demande de modélisation**

**Client**: user@example.com
**Objet**: Titre de la demande
**Ticket HubSpot**: https://app.hubspot.com/.../ticket/123

## Description de la demande
[Contenu original du mail]

## Fichiers joints
- [photo.jpg](https://pub-xxx.r2.dev/.../photo.jpg)
- [model.glb](https://pub-xxx.r2.dev/.../model.glb)
```

---

## Serveur production

```bash
# Connexion
ssh figurative@ubuntu-8gb-nbg1-1
source ~/venv/bin/activate
cd ~/agents-ia

# Lancement webhook
uvicorn execution.webhook_server:app --host 0.0.0.0 --port 5000
```

---

## Prochaines étapes

- [ ] Configurer SMTP pour notifications
- [ ] Déployer webhook en daemon (systemd)
- [ ] Connecter formulaires Figurative au webhook
