"""
scraper_emails_hoteles.py
=========================
Busca emails en los sitios web de los hoteles de la BD y los guarda automáticamente.

INSTALACIÓN (solo la primera vez):
    pip install requests beautifulsoup4 lxml

USO:
    python scraper_emails_hoteles.py

El script modifica directamente tu archivo hoteles_colombia.db.
Genera también un reporte: reporte_emails.txt
"""

import sqlite3
import re
import time
import random
import logging
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────
# CONFIGURACIÓN  (ajusta si quieres)
# ─────────────────────────────────────────────
DB_PATH        = "hoteles_colombia.db"   # ruta a tu base de datos
DELAY_MIN      = 1.5   # segundos mínimos entre requests (no los spamees)
DELAY_MAX      = 3.5   # segundos máximos
TIMEOUT        = 10    # segundos máx por request
MAX_SUBPAGES   = 3     # cuántas subpáginas revisar si no encuentra email en home
LOG_FILE       = "scraper_emails.log"
REPORT_FILE    = "reporte_emails.txt"

# Headers para parecer un navegador real
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Palabras clave que indican páginas de contacto
CONTACT_KEYWORDS = [
    "contacto", "contact", "contactenos", "contáctenos",
    "contactanos", "contactanos", "escribenos", "escríbenos",
    "nosotros", "about", "info", "informacion", "información",
]

# Dominios que NO tienen email público y conviene saltarse
SKIP_DOMAINS = [
    "booking.com", "tripadvisor.com", "airbnb.com",
    "expedia.com", "hotels.com", "despegar.com",
    "google.com", "instagram.com", "facebook.com",
    "wa.me", "wa.link", "ayenda.com", "lobbypms.com",
]

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────
EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

# Emails genéricos/falsos que hay que filtrar
FAKE_EMAIL_PATTERNS = re.compile(
    r"(ejemplo|example|youremail|tuemail|user@|email@email|"
    r"correo@|info@domain|test@|noreply|no-reply|donotreply|"
    r"sentry|wixpress|squarespace|wordpress|@2x\.|\.png|\.jpg|\.gif)",
    re.IGNORECASE,
)


def is_valid_email(email: str) -> bool:
    """Filtra emails falsos, de imágenes o placeholder."""
    if FAKE_EMAIL_PATTERNS.search(email):
        return False
    # Descarta si la extensión del dominio tiene más de 6 chars (raro en email real)
    domain_ext = email.rsplit(".", 1)[-1]
    if len(domain_ext) > 6:
        return False
    return True


def should_skip(url: str) -> bool:
    """Devuelve True si la URL pertenece a un dominio que hay que omitir."""
    if not url or not url.startswith("http"):
        return True
    parsed = urlparse(url)
    netloc = parsed.netloc.lower().replace("www.", "")
    return any(skip in netloc for skip in SKIP_DOMAINS)


def get_page(url: str, session: requests.Session) -> str | None:
    """Descarga una página y devuelve el HTML, o None si falla."""
    try:
        resp = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if resp.status_code == 200:
            return resp.text
        log.debug(f"HTTP {resp.status_code} → {url}")
    except requests.exceptions.SSLError:
        # Reintentar sin verificar SSL (algunos hoteles tienen certs vencidos)
        try:
            resp = session.get(
                url, headers=HEADERS, timeout=TIMEOUT,
                allow_redirects=True, verify=False
            )
            if resp.status_code == 200:
                return resp.text
        except Exception as e:
            log.debug(f"SSL retry falló: {url} → {e}")
    except Exception as e:
        log.debug(f"Error descargando {url}: {e}")
    return None


def extract_emails_from_html(html: str) -> list[str]:
    """Extrae emails del HTML (texto visible + mailto links)."""
    emails = set()

    soup = BeautifulSoup(html, "lxml")

    # 1. Buscar en links mailto:
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        if href.startswith("mailto:"):
            email = href[7:].split("?")[0].strip().lower()
            if EMAIL_RE.match(email) and is_valid_email(email):
                emails.add(email)

    # 2. Buscar en todo el texto visible
    text = soup.get_text(" ")
    for match in EMAIL_RE.findall(text):
        email = match.strip().lower()
        if is_valid_email(email):
            emails.add(email)

    return list(emails)


def find_contact_links(html: str, base_url: str) -> list[str]:
    """Encuentra links que probablemente lleven a la página de contacto."""
    soup = BeautifulSoup(html, "lxml")
    contact_links = []
    seen = set()

    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        text = tag.get_text(" ").strip().lower()
        full_url = urljoin(base_url, href)

        # Ignorar anchors, javascript, externos raros
        if not full_url.startswith("http"):
            continue
        if full_url in seen:
            continue
        # Que sea del mismo dominio
        if urlparse(full_url).netloc != urlparse(base_url).netloc:
            continue

        href_lower = href.lower()
        if any(kw in href_lower or kw in text for kw in CONTACT_KEYWORDS):
            seen.add(full_url)
            contact_links.append(full_url)

    return contact_links[:MAX_SUBPAGES]


def scrape_emails_from_site(url: str, session: requests.Session) -> list[str]:
    """
    Estrategia de scraping:
    1. Descarga la página principal.
    2. Busca emails ahí.
    3. Si no encuentra, busca subpáginas de contacto y las revisa también.
    """
    if should_skip(url):
        return []

    # Asegurarse que tenga esquema
    if not url.startswith("http"):
        url = "https://" + url

    # Paso 1: home
    html = get_page(url, session)
    if not html:
        # Intentar con http si https falló
        if url.startswith("https://"):
            html = get_page(url.replace("https://", "http://", 1), session)
    if not html:
        return []

    emails = extract_emails_from_html(html)
    if emails:
        return emails

    # Paso 2: subpáginas de contacto
    contact_links = find_contact_links(html, url)
    for link in contact_links:
        time.sleep(random.uniform(0.5, 1.2))
        sub_html = get_page(link, session)
        if sub_html:
            sub_emails = extract_emails_from_html(sub_html)
            if sub_emails:
                return sub_emails

    return []


# ─────────────────────────────────────────────
# LÓGICA PRINCIPAL
# ─────────────────────────────────────────────
def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Traer todos los registros sin email pero con web real
    cur.execute("""
        SELECT id, nombre_empresa, sitio_web, ciudad
        FROM contactos_hoteles
        WHERE (email IS NULL OR email = '')
          AND sitio_web IS NOT NULL
          AND sitio_web != ''
          AND sitio_web NOT LIKE '%No disponible%'
          AND sitio_web NOT LIKE '%wa.link%'
          AND sitio_web NOT LIKE '%wa.me%'
          AND sitio_web NOT LIKE '%facebook.com%'
          AND sitio_web NOT LIKE '%instagram.com%'
          AND sitio_web NOT LIKE '%google.com%'
        ORDER BY id
    """)
    hoteles = cur.fetchall()
    total = len(hoteles)
    log.info(f"Hoteles a procesar: {total}")

    session = requests.Session()
    session.headers.update(HEADERS)
    # Silenciar advertencias de SSL
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    encontrados = 0
    no_encontrados = []
    errores = []
    reporte_lines = []

    for i, (hotel_id, nombre, url, ciudad) in enumerate(hoteles, 1):
        log.info(f"[{i}/{total}] {nombre} ({ciudad}) → {url}")

        try:
            emails = scrape_emails_from_site(url, session)
        except Exception as e:
            log.warning(f"  ERROR inesperado: {e}")
            errores.append((nombre, url, str(e)))
            emails = []

        if emails:
            # Guardar el primer email (el más relevante suele ser el primero)
            email_principal = emails[0]
            todos = ", ".join(emails)

            cur.execute(
                "UPDATE contactos_hoteles SET email = ? WHERE id = ?",
                (email_principal, hotel_id)
            )
            conn.commit()

            log.info(f"  ✅ Email encontrado: {todos}")
            encontrados += 1
            reporte_lines.append(f"✅ {nombre} | {email_principal} | {url}")
        else:
            log.info("  ❌ No se encontró email")
            no_encontrados.append((nombre, url))
            reporte_lines.append(f"❌ {nombre} | sin email | {url}")

        # Pausa entre requests para no ser bloqueado
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    conn.close()

    # ─── Reporte final ───
    resumen = (
        f"\n{'='*60}\n"
        f"RESUMEN FINAL\n"
        f"{'='*60}\n"
        f"Total procesados : {total}\n"
        f"Emails encontrados: {encontrados}  ({encontrados/total*100:.1f}%)\n"
        f"Sin email         : {len(no_encontrados)}\n"
        f"Con errores       : {len(errores)}\n"
        f"{'='*60}\n"
    )

    log.info(resumen)

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(resumen + "\n")
        f.write("\nDETALLE POR HOTEL:\n")
        f.write("\n".join(reporte_lines))
        if errores:
            f.write("\n\nERRORES:\n")
            for nombre, url, err in errores:
                f.write(f"  {nombre} | {url} | {err}\n")

    print(f"\n✅ Reporte guardado en: {REPORT_FILE}")
    print(f"📋 Log completo en: {LOG_FILE}")


if __name__ == "__main__":
    main()