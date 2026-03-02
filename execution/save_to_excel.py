"""
STEP 5: Save to Excel (Master Database)
Saves enriched leads to Generate_leads.xlsx with proper formatting.

Usage:
    python save_to_excel.py --input .tmp/enriched_leads.json
"""

import pandas as pd
import argparse
import json
from pathlib import Path
from datetime import datetime
import sys

# Fix Windows console encoding issues
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        # Python < 3.7
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')


def check_excel_locked(excel_path):
    """Check if Excel file is locked (open in another program)"""
    try:
        # Try to open file in write mode
        with open(excel_path, 'a') as f:
            pass
        return False
    except PermissionError:
        return True


def save_to_excel(leads_data, excel_path):
    """
    Save leads to Excel master database

    Args:
        leads_data: List of lead dictionaries
        excel_path: Path to Generate_leads.xlsx
    """

    print(f"📊 Saving {len(leads_data)} leads to Excel...")

    # Check if file is locked
    if excel_path.exists():
        if check_excel_locked(excel_path):
            print("\n⚠️  WARNING: Generate_leads.xlsx is currently open!")
            print("Please close the file and try again.")
            sys.exit(1)

    # Convert to DataFrame
    new_df = pd.DataFrame(leads_data)

    # Replace empty email with "Non renseigné" for clarity
    if 'Email_Generique' in new_df.columns:
        new_df['Email_Generique'] = new_df['Email_Generique'].fillna('').replace('', 'Non renseigné')

    # Ensure all expected columns exist
    expected_columns = [
        'Industrie', 'Nom_Entreprise', 'Adresse', 'Code_Postal', 'Pays',
        'Site_Web', 'Tel_Standard', 'Email_Generique',
        'Nom_Decideur', 'Poste_Decideur', 'LinkedIn_URL',
        'Ecommerce', 'Date_Ajout', 'Statut_Sync'
    ]

    # Migrate old "Ville" column to "Pays" if present
    if 'Ville' in new_df.columns and 'Pays' not in new_df.columns:
        new_df = new_df.rename(columns={'Ville': 'Pays'})

    for col in expected_columns:
        if col not in new_df.columns:
            if col == 'Statut_Sync':
                # New leads get "New" status by default
                new_df[col] = 'New'
            else:
                new_df[col] = ''

    # Reorder columns
    new_df = new_df[expected_columns]

    # Load existing data if file exists
    if excel_path.exists():
        try:
            existing_df = pd.read_excel(excel_path, sheet_name='Leads')

            # Migrate old "Ville" column to "Pays"
            if 'Ville' in existing_df.columns:
                if 'Pays' not in existing_df.columns:
                    existing_df = existing_df.rename(columns={'Ville': 'Pays'})
                else:
                    existing_df = existing_df.drop(columns=['Ville'])

            # Ensure existing data has all columns
            for col in expected_columns:
                if col not in existing_df.columns:
                    existing_df[col] = ''

            # Combine old and new data, but preserve Statut_Sync from existing data
            # First, mark which rows are from existing data
            existing_df['_is_existing'] = True
            new_df['_is_existing'] = False

            combined_df = pd.concat([existing_df, new_df], ignore_index=True)

            # Remove duplicates based on company name and website, keeping the old one's Statut_Sync
            # Group by company to preserve Statut_Sync from existing data
            def merge_duplicates(group):
                if len(group) > 1:
                    # If there's an existing entry, use its Statut_Sync
                    existing = group[group['_is_existing'] == True]
                    if not existing.empty:
                        # Keep the new data but preserve the old Statut_Sync
                        latest = group.iloc[-1].copy()
                        latest['Statut_Sync'] = existing.iloc[-1]['Statut_Sync']
                        return latest
                return group.iloc[-1]

            combined_df = combined_df.groupby(['Nom_Entreprise', 'Site_Web'], as_index=False).apply(merge_duplicates)
            combined_df = combined_df.reset_index(drop=True)

            # Remove the temporary column
            combined_df = combined_df.drop('_is_existing', axis=1)

            print(f"  ✅ Merged with existing data")
            print(f"  📈 Before: {len(existing_df)} | New: {len(new_df)} | After: {len(combined_df)}")

            df_to_save = combined_df

        except Exception as e:
            print(f"  ⚠️  Could not read existing Excel: {e}")
            print(f"  Creating new file...")
            df_to_save = new_df
    else:
        print(f"  📝 Creating new Excel file")
        df_to_save = new_df

    # Save to Excel with formatting
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        df_to_save.to_excel(writer, sheet_name='Leads', index=False)

        # Get worksheet for formatting
        worksheet = writer.sheets['Leads']

        # Set column widths
        column_widths = {
            'A': 20, 'B': 30, 'C': 40, 'D': 12, 'E': 15,
            'F': 35, 'G': 18, 'H': 30, 'I': 25, 'J': 20,
            'K': 35, 'L': 12, 'M': 15, 'N': 15
        }

        for col, width in column_widths.items():
            worksheet.column_dimensions[col].width = width

        # Freeze first row (header)
        worksheet.freeze_panes = 'A2'

    print(f"\n✅ Excel saved successfully!")
    print(f"📄 Location: {excel_path}")
    print(f"📊 Total leads in database: {len(df_to_save)}")

    return excel_path


def main():
    parser = argparse.ArgumentParser(description='Save leads to Excel master database')
    parser.add_argument('--input', required=True, help='Input JSON file with enriched leads')
    parser.add_argument('--backup-mode', action='store_true',
        help='Backup mode: mark all leads as Synced (used after direct HubSpot sync)')

    args = parser.parse_args()

    input_path = Path(args.input)
    excel_path = Path(__file__).parent.parent / 'Generate_leads.xlsx'

    if not input_path.exists():
        print(f"❌ Input file not found: {input_path}")
        return

    # Load leads from JSON
    with open(input_path, 'r', encoding='utf-8') as f:
        leads = json.load(f)

    # In backup mode, mark all leads as already synced
    if args.backup_mode:
        for lead in leads:
            if lead.get('Statut_Sync') not in ('Failed', 'No Email'):
                lead['Statut_Sync'] = 'Synced'

    # Save to Excel
    save_to_excel(leads, excel_path)

    if args.backup_mode:
        print(f"\n📦 Excel backup complete (post-HubSpot sync)")
    else:
        print(f"\n➡️  Next step: Sync to HubSpot with sync_hubspot.py")


if __name__ == '__main__':
    main()
