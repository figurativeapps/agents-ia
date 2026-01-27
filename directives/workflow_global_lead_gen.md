# WORKFLOW : GLOBAL LEAD GENERATION (Excel + HubSpot)

## 1. OBJECTIFS
- Générer des leads qualifiés avec téléphones et emails.
- Centraliser dans `Generate_leads.xlsx` avec la colonne "Industrie".
- Synchroniser vers HubSpot CRM (Upsert : Création ou Mise à jour sans doublon).

## 2. INPUTS REQUIS
- `industry` (ex: "Cuisinistes")
- `location` (ex: "Bordeaux")
- `max_leads` (ex: 50)

## 3. PROCESSUS SÉQUENTIEL

### ÉTAPE 1 : SCRAPING (Google Maps)
- **Script :** `execution/scrape_google_maps.py`
- **Output :** Liste brute avec Téléphone Standard et Site Web.

### ÉTAPE 2 : QUALIFICATION (Firecrawl)
- **Script :** `execution/2_qualify_site.py`
- **Action :** Vérifie si le site est actif et cherche des emails génériques.

### ÉTAPE 3 : ENRICHISSEMENT (Apollo/LinkedIn)
- **Script :** `execution/5_enrich.py`
- **Action :** Trouve l'email nominatif du dirigeant.

### ÉTAPE 4 : SAUVEGARDE EXCEL (Source de Vérité)
- **Script :** `execution/save_to_excel.py`
- **Arguments :**
  - `leads_data` (Liste des objets leads)
  - `industry_name` (La valeur de l'input, ex: "Cuisinistes")
- **Action :** Ajoute les leads dans `Generate_leads.xlsx`.
- **Règle :** Ajoute une colonne "Industrie" remplie avec la valeur `industry_name`.

### ÉTAPE 5 : SYNC HUBSPOT (CRM)
- **Script :** `execution/sync_hubspot.py`
- **Entrée :** La liste des leads validés à l'étape 4.
- **Logique de Dédoublonnage :**
  1. Chercher le contact par Email.
  2. SI existe -> Mettre à jour les champs manquants (Tel, Industrie).
  3. SI n'existe pas -> Créer le contact + Créer l'entreprise associée.