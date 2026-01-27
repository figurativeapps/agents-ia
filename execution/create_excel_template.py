"""
Create the initial Excel template for Generate_leads.xlsx
This script sets up the master database with proper columns and formatting.
"""

import pandas as pd
from pathlib import Path

def create_excel_template():
    """Create the Generate_leads.xlsx template with proper columns"""

    # Define the columns for the lead database
    columns = [
        'Industrie',           # Industry/sector (e.g., "Cuisinistes")
        'Nom_Entreprise',      # Company name
        'Adresse',             # Full address
        'Ville',               # City
        'Code_Postal',         # Postal code
        'Site_Web',            # Website URL
        'Tel_Standard',        # Main phone number (from Google Maps)
        'Tel_Direct',          # Direct line (enriched from Apollo)
        'Email_Generique',     # Generic email (from website)
        'Email_Decideur',      # Decision maker email (from Waterfall)
        'Email_Source',        # Email source (reconstructed/hunter_generic/not_found)
        'Nom_Decideur',        # Decision maker name
        'Poste_Decideur',      # Decision maker title
        'LinkedIn_URL',        # LinkedIn profile URL
        'Note_Google',         # Google rating
        'Nombre_Avis',         # Number of reviews
        'Site_Actif',          # Website active (Oui/Non)
        'Ecommerce',           # Has e-commerce (Oui/Non)
        'Date_Ajout',          # Date added
        'Statut',              # Status (Nouveau, Contacté, Qualifié, etc.)
        'HubSpot_ID',          # HubSpot contact ID (for sync tracking)
    ]

    # Create empty DataFrame with these columns
    df = pd.DataFrame(columns=columns)

    # Define the output path (root folder)
    output_path = Path(__file__).parent.parent / 'Generate_leads.xlsx'

    # Save to Excel with formatting
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Leads', index=False)

        # Get the worksheet
        worksheet = writer.sheets['Leads']

        # Set column widths for better readability
        column_widths = {
            'A': 20,  # Industrie
            'B': 30,  # Nom_Entreprise
            'C': 40,  # Adresse
            'D': 20,  # Ville
            'E': 12,  # Code_Postal
            'F': 35,  # Site_Web
            'G': 18,  # Tel_Standard
            'H': 18,  # Tel_Direct
            'I': 30,  # Email_Generique
            'J': 30,  # Email_Decideur
            'K': 25,  # Nom_Decideur
            'L': 25,  # Poste_Decideur
            'M': 35,  # LinkedIn_URL
            'N': 12,  # Note_Google
            'O': 12,  # Nombre_Avis
            'P': 12,  # Site_Actif
            'Q': 12,  # Ecommerce
            'R': 15,  # Date_Ajout
            'S': 15,  # Statut
            'T': 15,  # HubSpot_ID
        }

        for col, width in column_widths.items():
            worksheet.column_dimensions[col].width = width

    print(f"✅ Excel template created successfully at: {output_path}")
    print(f"📊 Columns: {len(columns)}")

    return output_path

if __name__ == '__main__':
    create_excel_template()
