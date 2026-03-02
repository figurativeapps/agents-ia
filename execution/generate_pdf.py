"""
PDF Generation Tool
Creates customized proposal PDFs from Jinja2 templates.

Usage:
    python generate_pdf.py --company "Acme Corp" --industry "Restaurants"
"""

import argparse
import sys
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
from datetime import datetime
import json

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


def load_company_data(company_name, excel_path=None):
    """
    Load company data from Excel or return empty template

    Args:
        company_name: Name of the company
        excel_path: Path to Generate_leads.xlsx (optional)

    Returns:
        Dictionary with company data
    """

    # Try to load from Excel if available
    if excel_path and excel_path.exists():
        try:
            import pandas as pd
            df = pd.read_excel(excel_path, sheet_name='Leads')

            # Find company
            company_row = df[df['Nom_Entreprise'].str.contains(company_name, case=False, na=False)]

            if not company_row.empty:
                company_data = company_row.iloc[0].to_dict()
                print(f"✅ Found company data in Excel")
                return company_data
        except Exception as e:
            print(f"⚠️  Could not read Excel: {e}")

    # Return empty template if not found
    print(f"⚠️  Company not found in Excel - using manual input")
    return {}


def generate_pdf(company_data, template_name='plaquette_base.html', output_dir=None):
    """
    Generate PDF from Jinja2 template

    Args:
        company_data: Dictionary with company information
        template_name: Name of the template file
        output_dir: Output directory for PDF

    Returns:
        Path to generated PDF
    """

    # Set up paths
    project_root = Path(__file__).parent.parent
    templates_dir = project_root / 'templates'
    output_dir = output_dir or project_root / 'output'
    output_dir.mkdir(exist_ok=True)

    # Set up Jinja2 environment
    env = Environment(loader=FileSystemLoader(str(templates_dir)))

    try:
        template = env.get_template(template_name)
    except Exception as e:
        print(f"❌ Template not found: {template_name}")
        print(f"Creating basic template...")
        create_basic_template(templates_dir / template_name)
        template = env.get_template(template_name)

    # Prepare template variables
    template_vars = {
        'company_name': company_data.get('Nom_Entreprise', 'Votre Entreprise'),
        'contact_name': company_data.get('Nom_Decideur', 'Cher Client'),
        'industry': company_data.get('Industrie', ''),
        'city': company_data.get('Pays', ''),
        'phone': company_data.get('Tel_Standard', ''),
        'website': company_data.get('Site_Web', ''),
        'generation_date': datetime.now().strftime('%d/%m/%Y'),

        # Your company info (customize these)
        'our_company': 'Votre Société',
        'our_tagline': 'Solutions digitales pour votre croissance',
        'our_email': 'contact@votresociete.fr',
        'our_phone': '+33 X XX XX XX XX',

        # Value proposition (customize per industry)
        'value_proposition': get_value_proposition(company_data.get('Industrie', '')),
        'services': get_services_list(company_data.get('Industrie', '')),
        'cta': 'Réservez votre consultation gratuite',
    }

    # Render HTML
    html_content = template.render(**template_vars)

    # Generate PDF
    company_slug = company_data.get('Nom_Entreprise', 'proposal').replace(' ', '_').replace('/', '-')
    pdf_filename = f"{company_slug}_proposal_{datetime.now().strftime('%Y%m%d')}.pdf"
    pdf_path = output_dir / pdf_filename

    print(f"📄 Generating PDF...")

    # Convert HTML to PDF
    HTML(string=html_content, base_url=str(templates_dir)).write_pdf(str(pdf_path))

    print(f"✅ PDF generated successfully!")
    print(f"📁 Location: {pdf_path}")

    return pdf_path


def get_value_proposition(industry):
    """Get industry-specific value proposition"""
    propositions = {
        'Restaurants': 'Augmentez votre fréquentation et optimisez vos commandes en ligne',
        'Cuisinistes': 'Générez plus de demandes de devis qualifiées',
        'E-commerce': 'Maximisez vos conversions et votre panier moyen',
        'Services': 'Automatisez votre génération de leads',
    }
    return propositions.get(industry, 'Développez votre activité avec le digital')


def get_services_list(industry):
    """Get industry-specific services list"""
    base_services = [
        'Audit digital complet',
        'Stratégie de visibilité en ligne',
        'Mise en place d\'outils d\'acquisition',
        'Accompagnement et formation',
    ]
    return base_services


def create_basic_template(template_path):
    """Create a basic HTML template if none exists"""

    html_template = """<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Proposition Commerciale - {{ company_name }}</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div class="container">
        <header>
            <h1>{{ our_company }}</h1>
            <p class="tagline">{{ our_tagline }}</p>
        </header>

        <section class="intro">
            <h2>Proposition pour {{ company_name }}</h2>
            <p>Cher {{ contact_name }},</p>
            <p>Nous avons analysé votre activité dans le secteur <strong>{{ industry }}</strong> à {{ city }}.</p>
        </section>

        <section class="value-prop">
            <h3>Notre Solution</h3>
            <p class="highlight">{{ value_proposition }}</p>
        </section>

        <section class="services">
            <h3>Ce que nous proposons</h3>
            <ul>
                {% for service in services %}
                <li>{{ service }}</li>
                {% endfor %}
            </ul>
        </section>

        <section class="cta">
            <h3>{{ cta }}</h3>
            <p>Contactez-nous :</p>
            <p>📧 {{ our_email }}</p>
            <p>📞 {{ our_phone }}</p>
        </section>

        <footer>
            <p>Document généré le {{ generation_date }}</p>
        </footer>
    </div>
</body>
</html>"""

    template_path.parent.mkdir(exist_ok=True)
    with open(template_path, 'w', encoding='utf-8') as f:
        f.write(html_template)

    print(f"📝 Created basic template: {template_path}")

    # Create basic CSS
    css_path = template_path.parent / 'style.css'
    if not css_path.exists():
        css_content = """
body {
    font-family: Arial, sans-serif;
    line-height: 1.6;
    color: #333;
    margin: 0;
    padding: 0;
}

.container {
    max-width: 800px;
    margin: 0 auto;
    padding: 40px;
}

header {
    text-align: center;
    border-bottom: 3px solid #007bff;
    padding-bottom: 20px;
    margin-bottom: 40px;
}

h1 {
    color: #007bff;
    font-size: 2.5em;
    margin: 0;
}

.tagline {
    font-style: italic;
    color: #666;
}

section {
    margin-bottom: 30px;
}

h2, h3 {
    color: #007bff;
}

.highlight {
    background: #f0f8ff;
    padding: 15px;
    border-left: 4px solid #007bff;
    font-size: 1.1em;
}

ul {
    list-style-type: none;
    padding: 0;
}

li {
    padding: 10px 0;
    border-bottom: 1px solid #eee;
}

li:before {
    content: "✓ ";
    color: #28a745;
    font-weight: bold;
}

.cta {
    background: #007bff;
    color: white;
    padding: 30px;
    text-align: center;
    border-radius: 5px;
}

.cta h3 {
    color: white;
    margin-top: 0;
}

footer {
    text-align: center;
    color: #999;
    font-size: 0.9em;
    margin-top: 60px;
}
"""
        with open(css_path, 'w', encoding='utf-8') as f:
            f.write(css_content)
        print(f"🎨 Created basic CSS: {css_path}")


def main():
    parser = argparse.ArgumentParser(description='Generate PDF proposal')
    parser.add_argument('--company', required=True, help='Company name')
    parser.add_argument('--industry', help='Industry sector (optional if in Excel)')
    parser.add_argument('--contact', help='Contact name (optional)')
    parser.add_argument('--template', default='plaquette_base.html', help='Template filename')

    args = parser.parse_args()

    # Paths
    excel_path = Path(__file__).parent.parent / 'Generate_leads.xlsx'

    # Load company data
    company_data = load_company_data(args.company, excel_path)

    # Override with CLI arguments if provided
    if args.industry:
        company_data['Industrie'] = args.industry
    if args.contact:
        company_data['Nom_Decideur'] = args.contact
    if not company_data.get('Nom_Entreprise'):
        company_data['Nom_Entreprise'] = args.company

    # Generate PDF
    pdf_path = generate_pdf(company_data, args.template)

    print(f"\n✅ PDF ready for: {args.company}")


if __name__ == '__main__':
    main()
