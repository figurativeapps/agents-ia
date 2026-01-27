# 📝 Guide : Créer les Champs Personnalisés dans HubSpot

Pour que la synchronisation Excel → HubSpot fonctionne correctement, vous devez créer 3 champs personnalisés dans HubSpot.

## 🎯 Champs à Créer

### 1. Champ "Industrie" pour les **Contacts**

1. Allez dans **Paramètres** (⚙️ en haut à droite)
2. Dans le menu de gauche : **Propriétés** → **Contact properties**
3. Cliquez sur **Create property** (bouton en haut à droite)
4. Remplissez le formulaire :
   - **Object type** : Contact
   - **Group** : Contact information
   - **Label** : `Industrie`
   - **Description** : Secteur d'activité de l'entreprise
   - **Internal name** : `industrie` ⚠️ **IMPORTANT : Respectez exactement cette orthographe en minuscules**
   - **Field type** : Single-line text
5. Cliquez sur **Create**

---

### 2. Champ "Industrie" pour les **Companies**

1. Allez dans **Paramètres** (⚙️ en haut à droite)
2. Dans le menu de gauche : **Propriétés** → **Company properties**
3. Cliquez sur **Create property**
4. Remplissez le formulaire :
   - **Object type** : Company
   - **Group** : Company information
   - **Label** : `Industrie`
   - **Description** : Secteur d'activité de l'entreprise
   - **Internal name** : `industrie` ⚠️ **IMPORTANT : Respectez exactement cette orthographe en minuscules**
   - **Field type** : Single-line text
5. Cliquez sur **Create**

---

### 3. Champ "LinkedIn URL" pour les **Contacts**

1. Allez dans **Paramètres** (⚙️ en haut à droite)
2. Dans le menu de gauche : **Propriétés** → **Contact properties**
3. Cliquez sur **Create property**
4. Remplissez le formulaire :
   - **Object type** : Contact
   - **Group** : Contact information
   - **Label** : `LinkedIn URL`
   - **Description** : URL du profil LinkedIn du contact
   - **Internal name** : `linkedin_url` ⚠️ **IMPORTANT : Respectez exactement cette orthographe avec underscore**
   - **Field type** : Single-line text
5. Cliquez sur **Create**

---

## ✅ Vérification

Une fois les 3 champs créés, vous pouvez vérifier :

1. **Contacts** → Ouvrir un contact → Cliquer sur "View all properties"
   - Cherchez "Industrie" et "LinkedIn URL" dans la liste

2. **Companies** → Ouvrir une company → Cliquer sur "View all properties"
   - Cherchez "Industrie" dans la liste

---

## 🧪 Test de Synchronisation

Après avoir créé les champs, testez la synchronisation :

```bash
python run_pipeline.py --industry "test" --location "Paris" --max_leads 1
```

Vérifiez dans HubSpot que :
- ✅ Le contact a bien les valeurs dans "Industrie" et "LinkedIn URL"
- ✅ La company a bien la valeur dans "Industrie"

---

## ⚠️ Erreurs Courantes

### Erreur : "Property 'industrie' does not exist"

**Cause** : Le champ n'a pas été créé ou le nom interne est incorrect

**Solution** :
1. Vérifiez que le champ existe dans **Paramètres** → **Propriétés**
2. Vérifiez que l'**Internal name** est exactement `industrie` (tout en minuscules, sans accent)

### Erreur : "Property 'linkedin_url' does not exist"

**Cause** : Le champ n'a pas été créé ou le nom interne est incorrect

**Solution** :
1. Vérifiez que le champ existe dans **Paramètres** → **Propriétés** → **Contact properties**
2. Vérifiez que l'**Internal name** est exactement `linkedin_url` (avec underscore)

---

## 💡 Conseils

- Les champs personnalisés sont **gratuits** et **illimités** dans HubSpot
- Vous pouvez modifier le **Label** (nom affiché) à tout moment
- **Ne modifiez JAMAIS l'Internal name** une fois créé, sinon la synchronisation cessera de fonctionner
- Ces champs apparaîtront automatiquement dans tous vos contacts/companies

---

## 📊 Utilisation dans HubSpot

Une fois les données synchronisées, vous pouvez :

1. **Filtrer** les contacts par industrie
2. **Créer des listes** segmentées par secteur d'activité
3. **Personnaliser** vos emails avec la variable `{industrie}`
4. **Analyser** la répartition de vos leads par industrie dans les rapports
