"""
buscar_emails_faltantes.py
==========================
Encuentra emails para todos los hoteles sin email en la BD.

Estrategias por orden (hasta encontrar email):
  1. Sitio web ya conocido → scraping profundo (home + subpáginas + rutas comunes)
  2. DuckDuckGo con 3 queries → email en snippet o visita sitio oficial
  3. LinkedIn via DDG → extrae website de la página pública → scraping
  4. DDG con "@" forzado → intenta encontrar el email directamente

Checkpoint automático: retoma desde donde quedó si se interrumpe (Ctrl+C).

USO:
    python buscar_emails_faltantes.py           # continúa desde checkpoint
    python buscar_emails_faltantes.py --reset   # empieza desde cero
"""

from src.config import ruta_datos
import sqlite3
import re
import time
import random
import logging
import json
import os
import sys
import signal
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup

try:
    from duckduckgo_search import DDGS
    USE_DDG = True
except ImportError:
    USE_DDG = False

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
DB_PATH         = ruta_datos("hoteles_colombia.db")
LOG_FILE        = ruta_datos("buscar_emails.log")
REPORT_FILE     = ruta_datos("reporte_buscar_emails.txt")
CHECKPOINT_FILE = ruta_datos("checkpoint_buscar_emails.json")
DELAY_MIN       = 4.0   # pausa entre hoteles
DELAY_MAX       = 8.0
DDG_DELAY_MIN   = 2.0   # pausa entre búsquedas DDG
DDG_DELAY_MAX   = 4.5
TIMEOUT         = 12
MAX_DDG_RESULTS = 6
MAX_SUBPAGES    = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

LINKEDIN_HEADERS = {
    **HEADERS,
    "Referer": "https://www.google.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

# Dominios que nunca tienen emails de contacto directo
SKIP_DOMAINS = {
    "booking.com", "tripadvisor.com", "airbnb.com", "expedia.com",
    "hotels.com", "despegar.com", "kayak.com", "trivago.com",
    "google.com", "maps.google.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org",
    "yelp.com", "foursquare.com", "waze.com", "cotelco.org",
    "ayenda.com", "decameron.com", "lobbypms.com", "wa.me", "wa.link",
    "linktr.ee", "getawayrentals.info", "tiktok.com", "choicehotels.com",
    "computrabajo.com", "fincaraiz.com.co", "ccviva.com", "dle.rae.es",
    "properati.com.co", "bbva.com", "onthisday.com", "significados.com",
}

# Sufijos legales que ensucian el nombre al buscar en DDG/LinkedIn
LEGAL_SUFFIXES_RE = re.compile(
    r"\s+(s\.?\s*a\.?\s*s\.?|s\.?\s*a\.?|ltda\.?|bic|s\.c\.a\.?|"
    r"y\s+compan[ií]a|y\s+cia\.?|sucursal\s+colombia)\b.*$",
    re.IGNORECASE,
)

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
FAKE_EMAIL_RE = re.compile(
    r"(ejemplo|example|youremail|tuemail|noreply|no-reply|donotreply|"
    r"test@|sentry@|wixpress|squarespace|wordpress|@2x\.|\.png|\.jpg|\.gif|"
    r"user@|info@domain|correo@domain|@miempresa|email@email|"
    r"soporte@|support@|admin@|webmaster@)",
    re.IGNORECASE,
)

CONTACT_KEYWORDS = [
    "contacto", "contact", "contactenos", "contáctenos",
    "nosotros", "about", "info", "informacion", "información",
    "escribenos", "escríbenos", "comunicacion",
]

COMMON_CONTACT_PATHS = [
    "/contacto", "/contact", "/contactenos", "/contáctenos",
    "/nosotros", "/about", "/informacion", "/informacion-contacto",
    "/contacto.html", "/contact.html",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ─── CHECKPOINT ───────────────────────────────────────────────────────────────
def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["procesados"] = set(data.get("procesados", []))
            log.info(
                f"♻️  Checkpoint encontrado: {len(data['procesados'])} hoteles ya procesados."
            )
            return data
        except Exception as e:
            log.warning(f"Error leyendo checkpoint, empezando desde cero: {e}")
    return {
        "procesados": set(),
        "stats": {"emails": 0, "webs": 0, "nada": 0},
    }


def save_checkpoint(cp: dict):
    data = dict(cp)
    data["procesados"] = list(cp["procesados"])
    try:
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"No se pudo guardar checkpoint: {e}")


_cp_ref = None


def handle_interrupt(sig, frame):
    log.info("\n⚠️  Interrupción detectada. Guardando checkpoint...")
    if _cp_ref:
        save_checkpoint(_cp_ref)
    log.info(f"✅ Progreso guardado en {CHECKPOINT_FILE}.")
    log.info("   Vuelve a correr el script para retomar desde donde quedó.")
    sys.exit(0)


signal.signal(signal.SIGINT, handle_interrupt)
signal.signal(signal.SIGTERM, handle_interrupt)


# ─── UTILIDADES ───────────────────────────────────────────────────────────────
def clean_name(nombre: str) -> str:
    """Elimina sufijos legales (SAS, LTDA, etc.) para mejorar la búsqueda."""
    cleaned = LEGAL_SUFFIXES_RE.sub("", nombre).strip()
    # Si después de limpiar queda muy corto, usar el original
    return cleaned if len(cleaned) >= 4 else nombre


def is_valid_email(email: str) -> bool:
    if FAKE_EMAIL_RE.search(email):
        return False
    ext = email.rsplit(".", 1)[-1]
    return len(ext) <= 6


def get_domain(url: str) -> str:
    return urlparse(url).netloc.lower().replace("www.", "")


def is_official_site(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    domain = get_domain(url)
    return not any(skip in domain for skip in SKIP_DOMAINS)


def get_page(url: str, session: requests.Session, extra_headers: dict | None = None) -> str | None:
    headers = {**HEADERS, **(extra_headers or {})}
    for verify in (True, False):
        try:
            resp = session.get(
                url, headers=headers, timeout=TIMEOUT,
                allow_redirects=True, verify=verify,
            )
            if resp.status_code == 200:
                return resp.text
        except Exception:
            if verify:
                continue
            break
    return None


def extract_emails_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    emails = set()
    # mailto links primero (más confiables)
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        if href.startswith("mailto:"):
            email = href[7:].split("?")[0].strip().lower()
            if EMAIL_RE.match(email) and is_valid_email(email):
                emails.add(email)
    # Texto visible
    for match in EMAIL_RE.findall(soup.get_text(" ")):
        email = match.strip().lower()
        if is_valid_email(email):
            emails.add(email)
    return list(emails)


def extract_emails_from_text(text: str) -> list[str]:
    return [
        e.strip().lower()
        for e in EMAIL_RE.findall(text)
        if is_valid_email(e.strip().lower())
    ]


def find_contact_subpages(html: str, base_url: str) -> list[str]:
    """Detecta links de contacto dentro del mismo dominio."""
    soup = BeautifulSoup(html, "lxml")
    seen, links = set(), []
    base_netloc = urlparse(base_url).netloc
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        text = tag.get_text().strip().lower()
        full = urljoin(base_url, href)
        if not full.startswith("http") or full in seen:
            continue
        if urlparse(full).netloc != base_netloc:
            continue
        if any(kw in href.lower() or kw in text for kw in CONTACT_KEYWORDS):
            seen.add(full)
            links.append(full)
    return links[:MAX_SUBPAGES]


def scrape_site_deep(url: str, session: requests.Session) -> list[str]:
    """
    Scraping profundo de un sitio:
      1. Home page
      2. Subpáginas de contacto detectadas en el HTML
      3. Rutas de contacto comunes hardcodeadas
    """
    if not is_official_site(url):
        return []
    if not url.startswith("http"):
        url = "https://" + url

    html = get_page(url, session)
    if not html and url.startswith("https://"):
        html = get_page(url.replace("https://", "http://", 1), session)
    if not html:
        return []

    emails = extract_emails_from_html(html)
    if emails:
        return emails

    # Subpáginas detectadas en el HTML
    for subpage in find_contact_subpages(html, url):
        time.sleep(random.uniform(0.4, 1.0))
        sub_html = get_page(subpage, session)
        if sub_html:
            sub_emails = extract_emails_from_html(sub_html)
            if sub_emails:
                return sub_emails

    # Rutas de contacto comunes
    parsed  = urlparse(url)
    base    = f"{parsed.scheme}://{parsed.netloc}"
    visited = set()
    for path in COMMON_CONTACT_PATHS:
        candidate = base + path
        if candidate in visited or candidate == url:
            continue
        visited.add(candidate)
        time.sleep(random.uniform(0.3, 0.7))
        page_html = get_page(candidate, session)
        if page_html:
            page_emails = extract_emails_from_html(page_html)
            if page_emails:
                return page_emails

    return []


def ddg_search(query: str) -> list[dict]:
    """Busca en DuckDuckGo y devuelve los resultados."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=MAX_DDG_RESULTS, region="co-es"))
        time.sleep(random.uniform(DDG_DELAY_MIN, DDG_DELAY_MAX))
        return results
    except Exception as e:
        log.warning(f"DDG error ('{query[:50]}...'): {e}")
        time.sleep(6)
        return []


def try_linkedin(nombre_limpio: str, ciudad: str, session: requests.Session) -> tuple[list[str], str | None]:
    """
    Busca la empresa en LinkedIn via DDG:
      1. Revisa el snippet de DDG por emails
      2. Visita la página pública de LinkedIn (sin login)
      3. Extrae el website listado en el perfil → para scraping posterior

    Retorna: (emails_encontrados, website_url_o_None)
    """
    query = f'"{nombre_limpio}" {ciudad} site:linkedin.com/company'
    log.info(f"  🔗 LinkedIn DDG: {query}")
    results = ddg_search(query)

    for r in results:
        url  = r.get("href", "")
        body = r.get("body", "")

        # Email directo en el snippet
        snippet_emails = extract_emails_from_text(body)
        if snippet_emails:
            log.info(f"  📧 Email en snippet LinkedIn: {snippet_emails[0]}")
            return snippet_emails, None

        # Visitar la página de empresa en LinkedIn
        if "linkedin.com/company" not in url:
            continue

        log.info(f"  🔗 Visitando LinkedIn: {url}")
        html = get_page(url, session, extra_headers=LINKEDIN_HEADERS)
        if not html:
            continue

        # Buscar email en la página (raro pero ocurre en descripciones)
        li_emails = extract_emails_from_html(html)
        if li_emails:
            log.info(f"  📧 Email en página LinkedIn: {li_emails[0]}")
            return li_emails, None

        # Buscar website externo: LinkedIn redirige con /redir/ o /redirect/
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Redirección externa de LinkedIn
            if "/redir/" in href or "redirect" in href.lower():
                m = re.search(r"url=([^&\"']+)", href)
                if m:
                    dest = unquote(m.group(1))
                    if dest.startswith("http") and is_official_site(dest):
                        log.info(f"  🌐 Website encontrado en LinkedIn: {dest}")
                        return [], dest
            # Link externo directo (raro en público, pero posible)
            if href.startswith("http") and is_official_site(href):
                if "linkedin.com" not in href:
                    log.info(f"  🌐 Website encontrado en LinkedIn: {href}")
                    return [], href

    return [], None


# ─── PROCESAR UN HOTEL ────────────────────────────────────────────────────────
def process_hotel(
    hotel_id: int,
    nombre: str,
    ciudad: str | None,
    sitio_web: str | None,
    session: requests.Session,
    cur,
    conn,
) -> dict:
    """
    Intenta encontrar el email del hotel usando múltiples estrategias.
    Actualiza la BD en cuanto encuentra algo.
    Retorna dict con 'found' y 'value'.
    """
    nombre_limpio = clean_name(nombre)
    ciudad_str    = ciudad or "Colombia"

    def save_email(email: str, web: str | None = None):
        if web:
            cur.execute(
                "UPDATE contactos_hoteles SET email = ?, sitio_web = ? WHERE id = ?",
                (email, web, hotel_id),
            )
        else:
            cur.execute(
                "UPDATE contactos_hoteles SET email = ? WHERE id = ?",
                (email, hotel_id),
            )
        conn.commit()

    def save_web(web: str):
        cur.execute(
            "UPDATE contactos_hoteles SET sitio_web = ? WHERE id = ?",
            (web, hotel_id),
        )
        conn.commit()

    # ── ESTRATEGIA 1: Sitio web ya conocido → scraping profundo ───────────────
    if sitio_web and is_official_site(sitio_web):
        log.info(f"  🌐 Scraping web conocida: {sitio_web}")
        emails = scrape_site_deep(sitio_web, session)
        if emails:
            log.info(f"  ✅ Email en web conocida: {emails[0]}")
            save_email(emails[0])
            return {"found": "email", "value": emails[0], "via": "web_conocida"}

    # ── ESTRATEGIA 2: DuckDuckGo → email en snippet / sitio oficial ───────────
    queries = [
        f'"{nombre_limpio}" {ciudad_str} email contacto',
        f'"{nombre_limpio}" {ciudad_str} correo reservas',
        f'"{nombre_limpio}" colombia hotel "@"',
    ]

    webs_to_try: list[str] = []

    for query in queries:
        log.info(f"  🔍 DDG: {query}")
        results = ddg_search(query)

        for r in results:
            url   = r.get("href", "")
            body  = r.get("body", "")
            title = r.get("title", "")
            text  = body + " " + title

            # Email directo en snippet
            snippet_emails = extract_emails_from_text(text)
            if snippet_emails:
                log.info(f"  ✅ Email en snippet DDG: {snippet_emails[0]}")
                save_email(snippet_emails[0])
                return {"found": "email", "value": snippet_emails[0], "via": "ddg_snippet"}

            # Acumular sitios oficiales para visitar
            if url and is_official_site(url) and url not in webs_to_try:
                webs_to_try.append(url)

    # Visitar sitios oficiales encontrados en DDG (máx 3)
    web_guardada = False
    for web_url in webs_to_try[:3]:
        log.info(f"  🌐 Visitando (DDG): {web_url}")
        emails = scrape_site_deep(web_url, session)
        if emails:
            log.info(f"  ✅ Email en web DDG: {emails[0]}")
            save_email(emails[0], web_url if not sitio_web else None)
            return {"found": "email", "value": emails[0], "via": "ddg_web"}
        # Guardar la web aunque no haya email (solo si no tenía)
        if not sitio_web and not web_guardada:
            save_web(web_url)
            web_guardada = True
            log.info(f"  📋 Web guardada: {web_url}")
        time.sleep(random.uniform(1.0, 2.0))

    # ── ESTRATEGIA 3: LinkedIn ─────────────────────────────────────────────────
    li_emails, li_web = try_linkedin(nombre_limpio, ciudad_str, session)

    if li_emails:
        log.info(f"  ✅ Email via LinkedIn: {li_emails[0]}")
        save_email(li_emails[0])
        return {"found": "email", "value": li_emails[0], "via": "linkedin"}

    if li_web:
        log.info(f"  🌐 Scraping web de LinkedIn: {li_web}")
        web_emails = scrape_site_deep(li_web, session)
        if web_emails:
            log.info(f"  ✅ Email via LinkedIn→web: {web_emails[0]}")
            save_email(web_emails[0], li_web)
            return {"found": "email", "value": web_emails[0], "via": "linkedin_web"}
        if not sitio_web and not web_guardada:
            save_web(li_web)
        return {"found": "website_only", "value": li_web, "via": "linkedin"}

    # ── Sin resultado ──────────────────────────────────────────────────────────
    log.info(f"  ❌ Sin resultado: {nombre}")
    if web_guardada:
        return {"found": "website_only", "value": webs_to_try[0], "via": "ddg"}
    return {"found": "nothing"}


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    global _cp_ref

    if not USE_DDG:
        print("❌ Falta instalar: pip install duckduckgo-search")
        return

    if "--reset" in sys.argv:
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
            log.info("🗑️  Checkpoint eliminado. Empezando desde cero.")

    checkpoint = load_checkpoint()
    _cp_ref    = checkpoint

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    cur.execute("""
        SELECT id, nombre_empresa, ciudad, sitio_web, maps_link
        FROM contactos_hoteles
        WHERE email IS NULL OR email = ''
        ORDER BY
            -- Prioridad: primero los que tienen web (más fácil encontrar email)
            CASE WHEN sitio_web IS NOT NULL AND sitio_web != ''
                      AND sitio_web NOT LIKE '%No disponible%'
                 THEN 0 ELSE 1 END,
            id
    """)
    hoteles    = cur.fetchall()
    total      = len(hoteles)
    pendientes = [
        row for row in hoteles
        if row[0] not in checkpoint["procesados"]
    ]
    ya_hechos  = total - len(pendientes)

    log.info(f"Total sin email   : {total}")
    log.info(f"Ya procesados     : {ya_hechos}")
    log.info(f"Pendientes        : {len(pendientes)}")

    if not pendientes:
        log.info("✅ Todos los hoteles ya fueron procesados.")
        conn.close()
        return

    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session = requests.Session()

    stats  = checkpoint["stats"]
    report = []

    for i, (hotel_id, nombre, ciudad, sitio_web, maps_link) in enumerate(pendientes, 1):
        num = ya_hechos + i
        log.info(f"\n[{num}/{total}] {nombre} ({ciudad or 'sin ciudad'})")

        try:
            result = process_hotel(
                hotel_id, nombre, ciudad, sitio_web,
                session, cur, conn,
            )
        except Exception as e:
            log.error(f"  ERROR inesperado: {e}")
            result = {"found": "nothing"}

        if result["found"] == "email":
            stats["emails"] += 1
            report.append(
                f"✅ EMAIL [{result.get('via', '?')}] | {nombre} | {result['value']}"
            )
        elif result["found"] == "website_only":
            stats["webs"] += 1
            report.append(
                f"🌐 WEB  [{result.get('via', '?')}] | {nombre} | {result['value']}"
            )
        else:
            stats["nada"] += 1
            report.append(f"❌ NADA | {nombre} | {ciudad or ''}")

        checkpoint["procesados"].add(hotel_id)
        save_checkpoint(checkpoint)

        if i % 10 == 0:
            log.info(
                f"  📊 Progreso {num}/{total} | "
                f"Emails: {stats['emails']} | "
                f"Webs: {stats['webs']} | "
                f"Sin resultado: {stats['nada']}"
            )

        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    conn.close()

    resumen = (
        f"\n{'='*60}\n"
        f"RESUMEN FINAL - BUSCAR EMAILS FALTANTES\n"
        f"{'='*60}\n"
        f"Total procesados   : {total}\n"
        f"Emails encontrados : {stats['emails']}\n"
        f"Solo web guardada  : {stats['webs']}\n"
        f"Sin resultado      : {stats['nada']}\n"
        f"{'='*60}\n"
    )
    log.info(resumen)

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(resumen + "\n\nDETALLE:\n")
        f.write("\n".join(report))

    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)

    print(f"\n✅ Completado. Reporte: {REPORT_FILE}")
    print(f"📋 Log completo: {LOG_FILE}")


if __name__ == "__main__":
    main()
