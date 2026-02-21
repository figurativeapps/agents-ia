"""
PDF Overlay Tool
Superpose titre + image + QR code + lien cliquable sur un PDF template (Canva).

Usage:
    python overlay_pdf.py --image photo.jpg --url "https://example.com" --title "Pinocchio" --company "Acme"
    python overlay_pdf.py --preview  # Affiche les dimensions pour positionner
"""

import argparse
import io
import sys
from pathlib import Path
from datetime import datetime

import fitz  # PyMuPDF
import qrcode

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass


def parse_rect(rect_str):
    """Parse 'x0,y0,x1,y1' string into fitz.Rect (values in points)."""
    parts = [float(x.strip()) for x in rect_str.split(',')]
    if len(parts) != 4:
        raise ValueError(f"Rectangle must have 4 values (x0,y0,x1,y1), got {len(parts)}")
    return fitz.Rect(*parts)


def generate_qr_bytes(url, box_size=10, border=1):
    """Generate a QR code PNG as bytes from a URL."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def preview_pdf(template_path):
    """Show PDF page dimensions to help with positioning."""
    doc = fitz.open(template_path)
    print(f"📄 Template: {template_path}")
    print(f"   Pages: {len(doc)}")
    for i, page in enumerate(doc):
        r = page.rect
        print(f"\n   Page {i}:")
        print(f"   Dimensions: {r.width:.1f} x {r.height:.1f} points")
        print(f"   Dimensions: {r.width/72:.1f} x {r.height/72:.1f} inches")
        print(f"   Dimensions: {r.width/72*25.4:.0f} x {r.height/72*25.4:.0f} mm")
        print(f"\n   Repères utiles:")
        print(f"   Centre:         ({r.width/2:.0f}, {r.height/2:.0f})")
        print(f"   Bas-droite:     ({r.width:.0f}, {r.height:.0f})")
        print(f"   Bas-gauche:     (0, {r.height:.0f})")
        print(f"   Haut-droite:    ({r.width:.0f}, 0)")
    doc.close()


def overlay_pdf(template_path, image_path, url, company, title,
                image_rect, qr_rect, title_rect, link_rect, page_num, output_path):
    """
    Overlay title + image + QR code + clickable link on a PDF template.

    Validated positions for template_plaquette_co.pdf (930x1316 pts):
        title_rect:  388,318,538,345  (centered in phone screen, under dynamic island)
        image_rect:  385,370,541,526  (centered in phone screen)
        qr_rect:     671,350,776,455  (white square above "SCANNEZ OU CLIQUEZ")
    """
    doc = fitz.open(template_path)

    if page_num >= len(doc):
        print(f"❌ Page {page_num} n'existe pas (le PDF a {len(doc)} page(s))")
        doc.close()
        return None

    page = doc[page_num]
    print(f"📄 Page {page_num}: {page.rect.width:.0f} x {page.rect.height:.0f} points")

    # Insert title (centered in phone screen, under dynamic island)
    if title:
        page.insert_textbox(title_rect, title, fontsize=11, fontname='helv',
                            color=(0, 0, 0), align=fitz.TEXT_ALIGN_CENTER)
        print(f"📝 Titre inséré: \"{title}\" → {title_rect}")

    # Insert image
    if image_path:
        image_path = Path(image_path)
        if not image_path.exists():
            print(f"❌ Image introuvable: {image_path}")
            doc.close()
            return None
        page.insert_image(image_rect, filename=str(image_path))
        print(f"🖼️  Image insérée: {image_rect}")

    # Generate and insert QR code
    qr_bytes = generate_qr_bytes(url)
    page.insert_image(qr_rect, stream=qr_bytes)
    print(f"📱 QR code inséré: {qr_rect} → {url}")

    # Add clickable link over QR code area
    effective_link_rect = link_rect if link_rect else qr_rect
    link = {
        "kind": fitz.LINK_URI,
        "uri": url,
        "from": effective_link_rect,
    }
    page.insert_link(link)
    print(f"🔗 Lien cliquable ajouté: {effective_link_rect}")

    # Save
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    doc.close()

    print(f"\n✅ PDF généré: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description='Overlay image + QR code sur un PDF template Canva'
    )
    parser.add_argument('--template', default=None,
                        help='PDF template (défaut: template_plaquette_co.pdf)')
    parser.add_argument('--image', default=None,
                        help='Image à insérer')
    parser.add_argument('--url', default=None,
                        help='URL pour le QR code et le lien cliquable')
    parser.add_argument('--company', default='output',
                        help='Nom entreprise (pour le fichier output)')
    parser.add_argument('--title', default=None,
                        help='Titre objet affiché dans l\'écran du téléphone')
    parser.add_argument('--image-rect', default='385,370,541,526',
                        help='Position image "x0,y0,x1,y1" en points (défaut: 385,370,541,526)')
    parser.add_argument('--qr-rect', default='671,350,776,455',
                        help='Position QR code "x0,y0,x1,y1" en points (défaut: 671,350,776,455)')
    parser.add_argument('--title-rect', default='388,318,538,345',
                        help='Position titre "x0,y0,x1,y1" en points (défaut: 388,318,538,345)')
    parser.add_argument('--link-rect', default=None,
                        help='Zone cliquable "x0,y0,x1,y1" (défaut: même que qr-rect)')
    parser.add_argument('--page', type=int, default=0,
                        help='Page cible (0 = première)')
    parser.add_argument('--output', default=None,
                        help='Chemin output (défaut: output/{company}_plaquette_{date}.pdf)')
    parser.add_argument('--preview', action='store_true',
                        help='Afficher les dimensions du PDF sans générer')

    args = parser.parse_args()

    # Resolve template path
    project_root = Path(__file__).parent.parent
    template_path = Path(args.template) if args.template else project_root / 'template_plaquette_co.pdf'
    if not template_path.is_absolute():
        template_path = project_root / template_path

    if not template_path.exists():
        print(f"❌ Template introuvable: {template_path}")
        sys.exit(1)

    # Preview mode
    if args.preview:
        preview_pdf(template_path)
        return

    # Validate required args
    if not args.url:
        print("❌ --url est requis")
        sys.exit(1)

    # Parse rectangles
    image_rect = parse_rect(args.image_rect)
    qr_rect = parse_rect(args.qr_rect)
    title_rect = parse_rect(args.title_rect)
    link_rect = parse_rect(args.link_rect) if args.link_rect else None

    # Output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_dir = project_root / 'output'
        company_slug = args.company.replace(' ', '_').replace('/', '-')
        date_str = datetime.now().strftime('%Y%m%d')
        output_path = output_dir / f"{company_slug}_plaquette_{date_str}.pdf"

    # Run overlay
    overlay_pdf(
        template_path=str(template_path),
        image_path=args.image,
        url=args.url,
        company=args.company,
        title=args.title,
        image_rect=image_rect,
        qr_rect=qr_rect,
        title_rect=title_rect,
        link_rect=link_rect,
        page_num=args.page,
        output_path=output_path,
    )


if __name__ == '__main__':
    main()
