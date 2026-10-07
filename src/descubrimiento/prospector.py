"""
prospector.py
=============
Script unificado: Google Maps scraping + búsqueda de emails.

FASES:
  1. MAPS   — Busca negocios en Google Maps, extrae info y guarda en la BD.
  2. EMAIL  — Para cada negocio sin email, prueba todas las técnicas en orden:
              (a) Scraping profundo del sitio web conocido
              (b) DuckDuckGo: 3 queries → email en snippet o visita sitio oficial
              (c) LinkedIn via DDG
              (d) Google Search via Selenium (fallback automático a DDG si hay 403)
              (e) Facebook (m.facebook.com con requests → Selenium como fallback)

USO:
    python prospector.py                  # continúa desde checkpoint
    python prospector.py --reset          # empieza desde cero
    python prospector.py --solo-email     # salta la fase Maps, solo busca emails
    python prospector.py --syncrono       # modo integrado: toma el job pendiente
                                          # de Syncrono, ejecuta y sube resultados
                                          # automáticamente al CRM.
                                          # Requiere SYNCRONO_URL y SYNCRONO_TOKEN
                                          # en el archivo .env o como variables de entorno.
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
from urllib.parse import urljoin, urlparse, quote_plus

import requests
import urllib3
from bs4 import BeautifulSoup

try:
    from duckduckgo_search import DDGS
    USE_DDG = True
except ImportError:
    USE_DDG = False
    print("⚠️  duckduckgo-search no instalado. Instala con: pip install duckduckgo-search")

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
DB_PATH          = ruta_datos("hoteles_colombia.db")
LOG_FILE         = ruta_datos("prospector.log")
CHECKPOINT_FILE  = ruta_datos("checkpoint_prospector.json")

# Delays Maps
MAPS_SCROLL_WAIT = 3.0
MAPS_DETAIL_WAIT = 12

# Delays Email
GOOGLE_DELAY_MIN = 15.0
GOOGLE_DELAY_MAX = 25.0
DDG_DELAY_MIN    = 2.0
DDG_DELAY_MAX    = 4.5
FB_DELAY_MIN     = 5.0
FB_DELAY_MAX     = 10.0
SITE_DELAY_MIN   = 1.0
SITE_DELAY_MAX   = 2.5
HOTEL_DELAY_MIN  = 4.0
HOTEL_DELAY_MAX  = 8.0
PAGE_TIMEOUT     = 15
MAX_DDG_RESULTS  = 6
MAX_SUBPAGES     = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

FB_MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; SM-S908B) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/112.0.0.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "es-CO,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


SKIP_DOMAINS = {
    "booking.com", "tripadvisor.com", "tripadvisor.co", "airbnb.com",
    "airbnb.es", "airbnb.mx", "airbnb.co", "expedia.com",
    "hotels.com", "despegar.com", "kayak.com", "trivago.com", "trivago.es",
    "google.com", "google.com.co", "maps.google.com",
    "youtube.com", "wikipedia.org", "yelp.com", "cotelco.org",
    "ayenda.com", "decameron.com", "lobbypms.com",
    "wa.me", "wa.link", "linktr.ee", "getawayrentals.info",
    "tiktok.com", "choicehotels.com", "twitter.com", "x.com",
    "instagram.com", "facebook.com", "linkedin.com",
    "centraldereservas.com", "atrapalo.com", "atrapalo.com.co",
    "momondo.com", "momondo.com.co", "hoteles.com", "hoteles.com.co",
    "hotel.com.co", "viajes.com", "hotusa.com", "venere.com",
    "hrs.com", "muchosol.com", "rumbo.com", "edreams.com",
    "lastminute.com", "caribetraveltours.com", "revistalabarra.com",
    "decolar.com", "almundo.com", "viajala.com",
    "computrabajo.com", "fincaraiz.com.co", "ccviva.com", "dle.rae.es",
    "properati.com.co", "bbva.com", "onthisday.com", "significados.com",
    "gen.com.py", "quito.gob.ec", "sixelmusical.es", "promperu.gob.pe",
    "metrocuadrado.com", "codycrossanswers.com", "apps.apple.com",
    "play.google.com", "biblegateway.com", "plix.gg", "avaldigitallabs.com",
    "eldorado.aero", "mastravel.ec", "grandstorespr.com",
    "alcaldiabogota.gov.co", "barranquilla.gov.co",
}

SKIP_EMAIL_DOMAINS = {
    "pricetravel.com", "despegar.com", "booking.com", "tripadvisor.com",
    "expedia.com", "hotels.com", "trivago.com", "kayak.com", "agoda.com",
    "orbitz.com", "priceline.com", "hoteles.com", "hoteles.com.co",
    "viajes.com", "centraldereservas.com", "atrapalo.com", "atrapalo.com.co",
    "momondo.com", "momondo.com.co", "hotusa.com", "edreams.com",
    "caribetraveltours.com", "revistalabarra.com", "decolar.com",
    "almundo.com", "viajala.com", "cotelco.org", "cotelcoatlantico.org",
    "cotelcobogota.org", "google.com", "gmail.com",
    "rae.es", "bbva.com", "gameleap.com", "trivago.es",
}

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
    r"soporte@|support@|admin@|webmaster@|gstatic|googleapis)",
    re.IGNORECASE,
)

CONTACT_KEYWORDS = [
    "contacto", "contact", "contactenos", "contáctenos",
    "nosotros", "about", "info", "informacion", "escribenos",
]

COMMON_CONTACT_PATHS = [
    "/contacto", "/contact", "/contactenos",
    "/nosotros", "/about", "/informacion",
    "/contacto.html", "/contact.html",
]

# ─── LOGGING ──────────────────────────────────────────────────────────────────
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
            data["maps_links_procesados"] = set(data.get("maps_links_procesados", []))
            data["emails_procesados"]     = set(data.get("emails_procesados", []))
            data["ids_para_email"]        = list(data.get("ids_para_email", []))
            log.info(
                f"♻️  Checkpoint: {len(data['maps_links_procesados'])} fichas Maps "
                f"| {len(data['emails_procesados'])} hoteles email procesados"
            )
            return data
        except Exception as e:
            log.warning(f"Error leyendo checkpoint, empezando desde cero: {e}")
    return {
        "maps_links_procesados": set(),
        "emails_procesados": set(),
        "ids_para_email": [],       # IDs encontrados en Maps esta sesión
        "stats": {"nuevos": 0, "emails": 0, "nada": 0},
    }


def save_checkpoint(cp: dict):
    data = dict(cp)
    data["maps_links_procesados"] = list(cp["maps_links_procesados"])
    data["emails_procesados"]     = list(cp["emails_procesados"])
    data["ids_para_email"]        = list(cp["ids_para_email"])
    try:
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"No se pudo guardar checkpoint: {e}")


_cp_ref = None


def handle_interrupt(sig, frame):
    log.info("\n⚠️  Interrupción. Guardando checkpoint...")
    if _cp_ref:
        save_checkpoint(_cp_ref)
    log.info(f"✅ Guardado en {CHECKPOINT_FILE}. Vuelve a correr para retomar.")
    sys.exit(0)


signal.signal(signal.SIGINT, handle_interrupt)
signal.signal(signal.SIGTERM, handle_interrupt)


# ─── BASE DE DATOS ────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contactos_hoteles (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_empresa  TEXT NOT NULL,
            nicho           TEXT,
            nombre_contacto TEXT,
            email           TEXT,
            telefono        TEXT,
            sitio_web       TEXT,
            ciudad          TEXT,
            pais            TEXT,
            direccion       TEXT,
            maps_link       TEXT,
            UNIQUE(nombre_empresa, sitio_web)
        )
    """)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_maps_link
        ON contactos_hoteles(maps_link)
    """)

    # Columnas extra en caso de que la tabla ya existiera sin ellas
    existing = {row[1] for row in cur.execute("PRAGMA table_info(contactos_hoteles)")}
    for col, typedef in [("direccion", "TEXT"), ("maps_link", "TEXT")]:
        if col not in existing:
            cur.execute(f"ALTER TABLE contactos_hoteles ADD COLUMN {col} {typedef}")

    conn.commit()
    conn.close()


def upsert_negocio(nombre, nicho, direccion, telefono, sitio_web, ciudad, maps_link) -> int:
    """
    Inserta o actualiza un negocio.
    Retorna el id del registro (nuevo o existente).
    """
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    web_domain = get_domain(sitio_web) if sitio_web and sitio_web not in ("No disponible", "") else None

    # Buscar por maps_link primero (más preciso)
    if maps_link:
        cur.execute("SELECT id FROM contactos_hoteles WHERE maps_link = ?", (maps_link,))
        row = cur.fetchone()
        if row:
            conn.close()
            return row[0]

    # Buscar por nombre o dominio web
    if web_domain:
        cur.execute(
            "SELECT id FROM contactos_hoteles WHERE LOWER(nombre_empresa) = ? "
            "OR (sitio_web IS NOT NULL AND LOWER(sitio_web) LIKE ?)",
            (nombre.lower(), f"%{web_domain}%"),
        )
    else:
        cur.execute(
            "SELECT id FROM contactos_hoteles WHERE LOWER(nombre_empresa) = ?",
            (nombre.lower(),),
        )
    row = cur.fetchone()

    if row:
        hotel_id = row[0]
        cur.execute("""
            UPDATE contactos_hoteles SET
                telefono  = CASE WHEN telefono  IS NULL OR telefono  = 'No disponible' THEN ? ELSE telefono  END,
                sitio_web = CASE WHEN sitio_web IS NULL OR sitio_web = 'No disponible' THEN ? ELSE sitio_web END,
                direccion = ?,
                maps_link = COALESCE(maps_link, ?)
            WHERE id = ?
        """, (telefono, sitio_web, direccion, maps_link, hotel_id))
        log.info(f"  🔄 Existente actualizado: {nombre}")
    else:
        cur.execute("""
            INSERT OR IGNORE INTO contactos_hoteles
                (nombre_empresa, nicho, telefono, sitio_web, ciudad, pais, direccion, maps_link)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (nombre, nicho, telefono, sitio_web, ciudad, "Colombia", direccion, maps_link))
        hotel_id = cur.lastrowid
        log.info(f"  ✨ Nuevo: {nombre}")

    conn.commit()
    conn.close()
    return hotel_id


# ─── SELENIUM DRIVER ──────────────────────────────────────────────────────────
def get_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--disable-notifications")
    opts.add_argument("--start-maximized")
    opts.add_argument("--lang=es-CO")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    service = Service(ChromeDriverManager().install())
    driver  = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(PAGE_TIMEOUT)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )
    return driver


# ─── FASE 1: GOOGLE MAPS ──────────────────────────────────────────────────────
def maps_extract_detail(driver, maps_link: str) -> tuple:
    """Extrae (nombre, direccion, telefono, sitio_web) de una ficha de Maps."""
    try:
        driver.get(maps_link)
        WebDriverWait(driver, MAPS_DETAIL_WAIT).until(
            EC.presence_of_element_located((By.XPATH, '//h1[contains(@class,"DUwDvf")]'))
        )
    except Exception as e:
        log.warning(f"  ⚠️ Error cargando ficha: {e}")
        return "No disponible", "No disponible", "No disponible", "No disponible"

    nombre = direccion = telefono = sitio_web = "No disponible"

    try:
        nombre = driver.find_element(By.XPATH, '//h1[contains(@class,"DUwDvf")]').text.strip()
    except Exception:
        pass

    try:
        el = driver.find_element(By.XPATH, '//button[@data-item-id="address"]')
        direccion = el.find_element(By.CLASS_NAME, "rogA2c").text.strip()
    except Exception:
        pass

    try:
        el  = driver.find_element(By.XPATH, '//button[contains(@data-item-id,"phone:tel:")]')
        raw = el.get_attribute("aria-label").replace("Teléfono:", "").strip()
        digits = "".join(filter(str.isdigit, raw))
        if digits:
            if len(digits) == 7:
                telefono = f"+57601{digits}"
            elif len(digits) == 10 and digits.startswith("3"):
                telefono = f"+57{digits}"
            else:
                telefono = digits
    except Exception:
        pass

    try:
        el = driver.find_element(By.XPATH, '//a[@data-item-id="authority"]')
        sitio_web = el.get_attribute("href").strip()
    except Exception:
        pass

    return nombre, direccion, telefono, sitio_web


def maps_collect_links(driver, query: str) -> set:
    """Carga Google Maps con la query y recolecta todos los links de fichas."""
    url = f"https://www.google.com/maps/search/{quote_plus(query)}"
    log.info(f"🗺️  Navegando a Maps: {url}")
    driver.get(url)

    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, '//a[contains(@href, "/maps/place/")]'))
        )
    except Exception:
        log.warning("  ⚠️ No aparecieron resultados de Maps de inmediato.")

    encontrados: set = set()
    previo        = -1
    sin_nuevos    = 0

    while sin_nuevos < 5:
        for link in driver.find_elements(By.XPATH, '//a[contains(@href, "/maps/place/")]'):
            href = link.get_attribute("href")
            if href:
                encontrados.add(href.split("?")[0])

        try:
            feed = driver.find_element(By.XPATH, '//div[@role="feed"]')
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", feed)
            time.sleep(MAPS_SCROLL_WAIT)
        except Exception:
            time.sleep(2)
            break

        if len(encontrados) == previo:
            sin_nuevos += 1
        else:
            sin_nuevos = 0
        previo = len(encontrados)
        print(f"  📍 Fichas detectadas: {len(encontrados)}", end="\r")

    print()
    log.info(f"  ✅ Total fichas en Maps: {len(encontrados)}")
    return encontrados


def fase_maps(driver, checkpoint: dict, ciudad: str, tipo_negocio: str):
    """Fase 1: recolectar negocios de Google Maps y guardarlos en la BD."""
    nicho = tipo_negocio.capitalize()
    query = f"{tipo_negocio} en {ciudad}, Colombia"

    links = maps_collect_links(driver, query)

    # Excluir los ya procesados en este checkpoint
    pendientes = links - checkpoint["maps_links_procesados"]
    log.info(f"  🆕 Links nuevos a procesar: {len(pendientes)}")

    stats = checkpoint["stats"]
    for idx, link in enumerate(pendientes, 1):
        log.info(f"\n[Maps {idx}/{len(pendientes)}] {link[:80]}")
        nombre, direccion, telefono, sitio_web = maps_extract_detail(driver, link)
        if nombre == "No disponible":
            checkpoint["maps_links_procesados"].add(link)
            save_checkpoint(checkpoint)
            continue

        hotel_id = upsert_negocio(nombre, nicho, direccion, telefono, sitio_web, ciudad, link)
        if hotel_id and hotel_id not in checkpoint["ids_para_email"]:
            checkpoint["ids_para_email"].append(hotel_id)
        stats["nuevos"] += 1
        checkpoint["maps_links_procesados"].add(link)
        save_checkpoint(checkpoint)
        time.sleep(random.uniform(1.5, 3.0))

    log.info(f"\n✅ Fase Maps completada. Nuevos guardados: {stats['nuevos']}")


# ─── UTILIDADES EMAIL ─────────────────────────────────────────────────────────
def clean_name(nombre: str) -> str:
    cleaned = LEGAL_SUFFIXES_RE.sub("", nombre).strip()
    return cleaned if len(cleaned) >= 4 else nombre


def is_valid_email(email: str) -> bool:
    if FAKE_EMAIL_RE.search(email):
        return False
    parts = email.split("@")
    if len(parts) != 2:
        return False
    local, domain = parts
    if len(local) < 2:
        return False
    if any(skip in domain for skip in SKIP_EMAIL_DOMAINS):
        return False
    ext = domain.rsplit(".", 1)[-1]
    return len(ext) <= 6


def get_domain(url: str) -> str:
    return urlparse(url).netloc.lower().replace("www.", "")


def is_official_site(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    domain = get_domain(url)
    return not any(skip in domain for skip in SKIP_DOMAINS)


def extract_emails_from_html(html: str) -> list:
    soup   = BeautifulSoup(html, "lxml")
    emails = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        if href.startswith("mailto:"):
            email = href[7:].split("?")[0].strip().lower()
            if EMAIL_RE.match(email) and is_valid_email(email):
                emails.add(email)
    for match in EMAIL_RE.findall(soup.get_text(" ")):
        email = match.strip().lower()
        if is_valid_email(email):
            emails.add(email)
    return list(emails)


def extract_emails_from_text(text: str) -> list:
    return [
        e.strip().lower()
        for e in EMAIL_RE.findall(text)
        if is_valid_email(e.strip().lower())
    ]


def get_page(url: str, session: requests.Session, extra_headers=None) -> str | None:
    headers = {**HEADERS, **(extra_headers or {})}
    for verify in (True, False):
        try:
            resp = session.get(url, headers=headers, timeout=12,
                               allow_redirects=True, verify=verify)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            if verify:
                continue
            break
    return None


def find_contact_subpages(html: str, base_url: str) -> list:
    soup       = BeautifulSoup(html, "lxml")
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


def scrape_site_deep(url: str, session: requests.Session) -> list:
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

    for subpage in find_contact_subpages(html, url):
        time.sleep(random.uniform(0.4, 1.0))
        sub_html = get_page(subpage, session)
        if sub_html:
            sub_emails = extract_emails_from_html(sub_html)
            if sub_emails:
                return sub_emails

    parsed = urlparse(url)
    base   = f"{parsed.scheme}://{parsed.netloc}"
    for path in COMMON_CONTACT_PATHS:
        candidate = base + path
        if candidate == url:
            continue
        time.sleep(random.uniform(0.3, 0.6))
        page_html = get_page(candidate, session)
        if page_html:
            page_emails = extract_emails_from_html(page_html)
            if page_emails:
                return page_emails

    return []


# ─── DDG ──────────────────────────────────────────────────────────────────────
def ddg_search(query: str) -> list:
    if not USE_DDG:
        return []
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=MAX_DDG_RESULTS, region="co-es"))
        time.sleep(random.uniform(DDG_DELAY_MIN, DDG_DELAY_MAX))
        return results
    except Exception as e:
        log.warning(f"DDG error ('{query[:50]}'): {e}")
        time.sleep(6)
        return []


def ddg_search_parsed(query: str) -> tuple:
    """
    Retorna (emails_en_snippets, urls_oficiales, urls_facebook).
    """
    results  = ddg_search(query)
    emails, official, facebook = [], [], []
    for r in results:
        url  = r.get("href", "")
        text = r.get("body", "") + " " + r.get("title", "")
        for e in extract_emails_from_text(text):
            if e not in emails:
                emails.append(e)
        if not url:
            continue
        if "facebook.com" in url:
            path = urlparse(url).path
            if not re.search(
                r"/(photo|photos|posts|events|watch|groups|hashtag|sharer|share|login|l\.php)",
                path,
            ):
                facebook.append(url)
        elif is_official_site(url):
            official.append(url)
    return emails, official, facebook



# ─── GOOGLE SEARCH (SELENIUM) ─────────────────────────────────────────────────
def _parse_serp_urls(source: str) -> tuple:
    soup             = BeautifulSoup(source, "lxml")
    official, facebook = [], []
    seen             = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/url?") or href.startswith("/search?"):
            m = re.search(r"[?&]q=([^&]+)", href)
            if m:
                href = unquote(m.group(1))
        if not href.startswith("http") or href in seen:
            continue
        seen.add(href)
        domain = get_domain(href)
        if "facebook.com" in domain:
            path = urlparse(href).path
            if not re.search(
                r"/(photo|photos|posts|events|watch|groups|hashtag|sharer|share|login|l\.php)",
                path,
            ):
                facebook.append(href)
        elif is_official_site(href):
            official.append(href)
    return official, facebook


def _google_is_blocked(driver) -> str | None:
    current_url = driver.current_url
    title       = driver.title.lower()
    preview     = driver.page_source[:3000].lower()
    if "/sorry/" in current_url or "google.com/sorry" in current_url:
        return "captcha"
    if (
        "error 403" in title or "403" in title
        or "error 403" in preview
        or ("unusual traffic" in preview and len(driver.page_source) < 8000)
        or "that's an error" in preview
    ):
        return "403"
    return None


def accept_google_cookies(driver):
    for selector in [
        "button#L2AGLb",
        "button[aria-label='Aceptar todo']",
        "button[aria-label='Accept all']",
        "[id*='accept']",
    ]:
        try:
            btn = WebDriverWait(driver, 4).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            )
            btn.click()
            time.sleep(1)
            return
        except Exception:
            pass


def google_search(query: str, driver) -> tuple:
    """
    Retorna (emails, official_urls, fb_urls).
    emails = None → Google bloqueado (403); caller debe usar DDG.
    """
    search_url = f"https://www.google.com/search?q={quote_plus(query)}&hl=es&gl=co&num=10"
    try:
        driver.get(search_url)
        time.sleep(random.uniform(2.5, 4.5))
    except TimeoutException:
        pass
    except Exception as e:
        log.warning(f"Error navegando Google: {e}")
        return None, [], []

    block = _google_is_blocked(driver)
    if block == "captcha":
        log.warning("⚠️  Google CAPTCHA detectado. Resuélvelo en el navegador y presiona Enter.")
        input("   ↳ Presiona Enter cuando hayas resuelto el CAPTCHA: ")
        if _google_is_blocked(driver) == "403":
            return None, [], []
    elif block == "403":
        log.warning("⚠️  Google 403 → usando DuckDuckGo automáticamente.")
        return None, [], []

    source    = driver.page_source
    page_text = BeautifulSoup(source, "lxml").get_text(" ")
    emails    = extract_emails_from_text(page_text)
    official, facebook = _parse_serp_urls(source)
    return emails, official, facebook


# ─── FACEBOOK ─────────────────────────────────────────────────────────────────
def _fb_about_url(fb_url: str) -> str:
    parsed = urlparse(fb_url)
    clean  = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
    if "/about" not in clean:
        clean += "/about"
    return clean


def scrape_facebook_requests(fb_url: str, session: requests.Session) -> list:
    mobile_url = _fb_about_url(
        fb_url.replace("www.facebook.com", "m.facebook.com")
              .replace("//facebook.com", "//m.facebook.com")
    )
    try:
        resp = session.get(mobile_url, headers=FB_MOBILE_HEADERS, timeout=12,
                           allow_redirects=True)
        if resp.status_code != 200:
            return []
        if "login" in resp.url.lower() or "id='loginform'" in resp.text:
            return []
        return extract_emails_from_html(resp.text)
    except Exception:
        return []


def scrape_facebook_selenium(fb_url: str, driver) -> list:
    about_url = _fb_about_url(fb_url)
    try:
        driver.get(about_url)
        time.sleep(random.uniform(3.5, 5.5))
    except TimeoutException:
        pass
    except Exception:
        return []

    for selector in [
        "[aria-label='Cerrar']", "[aria-label='Close']",
        "div[role='dialog'] [role='button']",
    ]:
        try:
            driver.find_element(By.CSS_SELECTOR, selector).click()
            time.sleep(1.5)
            break
        except NoSuchElementException:
            pass
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(1)
    except Exception:
        pass

    source = driver.page_source
    emails = extract_emails_from_html(source)
    if not emails:
        soup = BeautifulSoup(source, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if is_official_site(href) and "facebook" not in href:
                return [f"__WEBSITE__{href}"]
    return emails


def try_facebook(fb_url: str, driver, session: requests.Session) -> tuple:
    emails = scrape_facebook_requests(fb_url, session)
    if emails:
        return emails, None
    log.info(f"  📘 FB Selenium: {fb_url[:70]}")
    result = scrape_facebook_selenium(fb_url, driver)
    if result and result[0].startswith("__WEBSITE__"):
        return [], result[0][len("__WEBSITE__"):]
    return result, None


# ─── PIPELINE EMAIL PARA UN NEGOCIO ──────────────────────────────────────────
def _url_relevante(url: str, nombre_limpio: str) -> bool:
    """Descarta URLs que claramente no tienen nada que ver con el negocio."""
    domain = get_domain(url)
    # Dominios de gobierno, puzzles, apps stores, etc. son siempre ruido
    RUIDO = (".gov.co", ".gov", "apple.com", "play.google", "answerscross",
             "cody", "significados", "wikipedia", "eldorado.aero")
    if any(r in domain for r in RUIDO):
        return False
    # Si al menos una palabra del nombre aparece en el dominio, es más probable
    palabras = [p for p in nombre_limpio.lower().split() if len(p) > 3]
    if any(p in domain for p in palabras):
        return True
    # Dominios .co o .com.co tienen más probabilidad de ser el hotel colombiano
    if domain.endswith(".co") or ".com.co" in domain:
        return True
    return True   # dejar pasar si no hay señal clara de ruido


def find_email(hotel_id: int, nombre: str, ciudad: str | None,
               sitio_web: str | None, driver, session: requests.Session,
               cur, conn) -> dict:
    nombre_limpio = clean_name(nombre)
    ciudad_str    = ciudad or "Colombia"
    web_guardada  = False

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

    # ── (a) Scraping del sitio web ya conocido ────────────────────────────────
    if sitio_web and is_official_site(sitio_web):
        log.info(f"  🌐 (a) Web conocida: {sitio_web}")
        emails = scrape_site_deep(sitio_web, session)
        if emails:
            log.info(f"  ✅ Email en web: {emails[0]}")
            save_email(emails[0])
            return {"found": "email", "value": emails[0], "via": "web"}

    # ── (b) DuckDuckGo — 1 sola query, máx 1 sitio visitado ─────────────────
    ddg_query = f'"{nombre_limpio}" {ciudad_str} email contacto'
    log.info(f"  🔍 (b) DDG: {ddg_query}")
    ddg_results = ddg_search(ddg_query)

    ddg_web_candidato = None
    for r in ddg_results:
        url  = r.get("href", "")
        text = r.get("body", "") + " " + r.get("title", "")
        # Email directo en snippet
        for e in extract_emails_from_text(text):
            log.info(f"  ✅ Email snippet DDG: {e}")
            save_email(e)
            return {"found": "email", "value": e, "via": "ddg_snippet"}
        # Guardar el primer sitio oficial relevante para visitar después
        if not ddg_web_candidato and url and is_official_site(url):
            if _url_relevante(url, nombre_limpio):
                ddg_web_candidato = url

    if ddg_web_candidato and (not sitio_web or get_domain(ddg_web_candidato) != get_domain(sitio_web)):
        log.info(f"  🌐 (b) Visitando DDG: {ddg_web_candidato[:70]}")
        emails = scrape_site_deep(ddg_web_candidato, session)
        if emails:
            log.info(f"  ✅ Email en web DDG: {emails[0]}")
            save_email(emails[0], ddg_web_candidato if not sitio_web else None)
            return {"found": "email", "value": emails[0], "via": "ddg_web"}
        if not sitio_web:
            save_web(ddg_web_candidato)
            web_guardada = True
        time.sleep(random.uniform(SITE_DELAY_MIN, SITE_DELAY_MAX))

    # ── (c) Google Search Selenium (fallback DDG si hay 403) ─────────────────
    google_query = f'"{nombre_limpio}" {ciudad_str} email contacto'
    log.info(f"  🔍 (c) Google: {google_query}")
    g_emails, g_official, g_fb = google_search(google_query, driver)

    if g_emails is None:
        log.info(f"  🔄 Google bloqueado → DDG fallback")
        g_emails, g_official, g_fb = ddg_search_parsed(google_query)
        search_via = "ddg"
    else:
        search_via = "google"
        time.sleep(random.uniform(GOOGLE_DELAY_MIN, GOOGLE_DELAY_MAX))

    if g_emails:
        log.info(f"  ✅ Email en SERP ({search_via}): {g_emails[0]}")
        save_email(g_emails[0])
        return {"found": "email", "value": g_emails[0], "via": f"{search_via}_serp"}

    # Visitar hasta 2 sitios oficiales del SERP (solo los relevantes)
    visitados = 0
    for url in g_official:
        if visitados >= 2:
            break
        if sitio_web and get_domain(url) == get_domain(sitio_web):
            continue
        if not _url_relevante(url, nombre_limpio):
            continue
        log.info(f"  🌐 ({search_via}) Visitando: {url[:70]}")
        emails = scrape_site_deep(url, session)
        if emails:
            log.info(f"  ✅ Email en sitio: {emails[0]}")
            save_email(emails[0], url if not sitio_web else None)
            return {"found": "email", "value": emails[0], "via": f"{search_via}_site"}
        time.sleep(random.uniform(SITE_DELAY_MIN, SITE_DELAY_MAX))
        visitados += 1

    # ── (d) Facebook — solo si apareció en el SERP de Google ─────────────────
    for fb_url in g_fb[:2]:
        log.info(f"  📘 (d) Facebook: {fb_url[:70]}")
        fb_emails, fb_web = try_facebook(fb_url, driver, session)
        if fb_emails:
            log.info(f"  ✅ Email en Facebook: {fb_emails[0]}")
            save_email(fb_emails[0])
            return {"found": "email", "value": fb_emails[0], "via": "facebook"}
        if fb_web:
            emails = scrape_site_deep(fb_web, session)
            if emails:
                log.info(f"  ✅ Email via FB→web: {emails[0]}")
                save_email(emails[0], fb_web)
                return {"found": "email", "value": emails[0], "via": "fb_web"}
            if not sitio_web and not web_guardada:
                save_web(fb_web)
        time.sleep(random.uniform(FB_DELAY_MIN, FB_DELAY_MAX))

    log.info(f"  ❌ Sin resultado: {nombre}")
    return {"found": "website_only" if web_guardada else "nothing"}


# ─── FASE 2: BUSCAR EMAILS ────────────────────────────────────────────────────
def fase_email(driver, checkpoint: dict):
    """Fase 2: buscar emails solo para los negocios encontrados en Maps esta sesión."""
    ids_sesion = checkpoint.get("ids_para_email", [])
    if not ids_sesion:
        log.info("ℹ️  No hay IDs nuevos de Maps para buscar emails. Saltando fase Email.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    placeholders = ",".join("?" * len(ids_sesion))
    cur.execute(f"""
        SELECT id, nombre_empresa, ciudad, sitio_web
        FROM contactos_hoteles
        WHERE id IN ({placeholders})
          AND (email IS NULL OR email = '')
        ORDER BY
            CASE WHEN sitio_web IS NOT NULL AND sitio_web != ''
                      AND sitio_web NOT LIKE '%No disponible%'
                      AND sitio_web NOT LIKE '%wa.%'
                      AND sitio_web NOT LIKE '%facebook%'
                      AND sitio_web NOT LIKE '%instagram%'
                 THEN 0 ELSE 1 END,
            id
    """, ids_sesion)
    hoteles    = cur.fetchall()
    pendientes = [row for row in hoteles if row[0] not in checkpoint["emails_procesados"]]
    total      = len(hoteles)
    ya_hechos  = total - len(pendientes)

    log.info(f"\n{'='*60}")
    log.info(f"FASE EMAIL")
    log.info(f"Sin email en BD   : {total}")
    log.info(f"Ya procesados     : {ya_hechos}")
    log.info(f"Pendientes        : {len(pendientes)}")
    log.info(f"{'='*60}")

    if not pendientes:
        log.info("✅ Todos los negocios ya fueron procesados para email.")
        conn.close()
        return

    # Iniciar sesión en Google para reducir detección inmediata
    log.info("🌐 Cargando Google para establecer sesión...")
    try:
        driver.get("https://www.google.com/?hl=es")
        time.sleep(random.uniform(2, 4))
        accept_google_cookies(driver)
    except Exception:
        pass

    session = requests.Session()
    stats   = checkpoint["stats"]

    for i, (hotel_id, nombre, ciudad, sitio_web) in enumerate(pendientes, 1):
        num = ya_hechos + i
        log.info(f"\n[Email {num}/{total}] {nombre} ({ciudad or 'sin ciudad'})")

        try:
            result = find_email(
                hotel_id, nombre, ciudad, sitio_web,
                driver, session, cur, conn,
            )
        except Exception as e:
            log.error(f"  ERROR inesperado: {e}")
            result = {"found": "nothing"}

        if result["found"] == "email":
            stats["emails"] += 1
        else:
            stats["nada"] += 1

        checkpoint["emails_procesados"].add(hotel_id)
        save_checkpoint(checkpoint)

        if i % 10 == 0:
            log.info(
                f"  📊 Progreso {num}/{total} | "
                f"Emails: {stats['emails']} | Sin resultado: {stats['nada']}"
            )

        time.sleep(random.uniform(HOTEL_DELAY_MIN, HOTEL_DELAY_MAX))

    conn.close()
    log.info(
        f"\n✅ Fase Email completada. "
        f"Emails: {stats['emails']} | Sin resultado: {stats['nada']}"
    )


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    global _cp_ref

    if "--reset" in sys.argv:
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
            log.info("🗑️  Checkpoint eliminado. Empezando desde cero.")

    solo_email = "--solo-email" in sys.argv

    init_db()
    checkpoint = load_checkpoint()
    _cp_ref    = checkpoint

    # ── Preguntar parámetros (solo si no es solo-email) ───────────────────────
    ciudad = tipo_negocio = None
    if not solo_email:
        print("\n" + "="*60)
        print("  PROSPECTOR — Google Maps + Buscador de Emails")
        print("="*60)
        ciudad       = input("\n¿Ciudad o lugar a buscar? (ej: Cartagena): ").strip()
        tipo_negocio = input("¿Tipo de negocio? (ej: hoteles, hostales, resorts): ").strip()
        if not ciudad or not tipo_negocio:
            print("❌ Ciudad y tipo de negocio son obligatorios.")
            return
        log.info(f"🎯 Buscando: '{tipo_negocio}' en '{ciudad}, Colombia'")

    driver = get_driver()

    try:
        if not solo_email:
            log.info("\n" + "="*60)
            log.info("FASE 1 — GOOGLE MAPS")
            log.info("="*60)
            fase_maps(driver, checkpoint, ciudad, tipo_negocio)

        log.info("\n" + "="*60)
        log.info("FASE 2 — BÚSQUEDA DE EMAILS")
        log.info("="*60)
        fase_email(driver, checkpoint)

    finally:
        driver.quit()
        log.info("\n🏁 Proceso finalizado.")

    s = checkpoint["stats"]
    print(f"\n{'='*60}")
    print(f"RESUMEN FINAL")
    print(f"{'='*60}")
    if not solo_email:
        print(f"Negocios nuevos   : {s['nuevos']}")
    print(f"Emails encontrados: {s['emails']}")
    print(f"Sin resultado     : {s['nada']}")
    print(f"{'='*60}")
    print(f"📋 Log completo: {LOG_FILE}")


# ─── MODO SYNCRONO (integración con el CRM) ──────────────────────────────────
def syncrono_main():
    """
    Modo integrado con Syncrono:
      1. Consulta el próximo job pendiente en el CRM.
      2. Ejecuta Maps + email scraping con ese nicho y ciudad.
      3. Sube los contactos encontrados al CRM vía /api/crm/prospectos/importar.
      4. Marca el job como completado.

    Variables de entorno necesarias (créalas en un archivo .env en esta carpeta):
      SYNCRONO_URL   = https://syncronotenantversion.management-aa9.workers.dev
      SYNCRONO_TOKEN = <tu JWT — cópialo de la pestaña Network en el panel de admin>
    """
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # sin python-dotenv, usa las variables del sistema

    api_url = os.environ.get("SYNCRONO_URL", "").rstrip("/")
    token   = os.environ.get("SYNCRONO_TOKEN", "")

    if not api_url or not token:
        print("❌ Faltan variables de entorno: SYNCRONO_URL y SYNCRONO_TOKEN")
        print("   Crea un archivo .env con esas dos variables.")
        return

    headers_api = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # 1. Tomar el próximo job pendiente
    log.info("🔍 Consultando job pendiente en Syncrono…")
    try:
        resp = requests.get(f"{api_url}/api/crm/prospector/jobs/next", headers=headers_api, timeout=15)
        data = resp.json()
    except Exception as e:
        log.error(f"❌ No se pudo conectar al API: {e}")
        return

    if not data.get("ok") or not data.get("job"):
        log.info("✅ No hay búsquedas pendientes en este momento.")
        return

    job     = data["job"]
    job_id  = job["id"]
    nicho   = job["nicho"]
    ciudad  = job["ciudad"]
    log.info(f"📋 Job #{job_id}: {nicho} en {ciudad}")

    # 2. Ejecutar el scraping
    global _cp_ref
    init_db()
    checkpoint = load_checkpoint()
    _cp_ref    = checkpoint

    driver = get_driver()
    error_msg  = None
    total_nuevos = 0

    try:
        ids_antes = set()
        conn_tmp = sqlite3.connect(DB_PATH)
        ids_antes = {r[0] for r in conn_tmp.execute("SELECT id FROM contactos_hoteles").fetchall()}
        conn_tmp.close()

        fase_maps(driver, checkpoint, ciudad, nicho)
        fase_email(driver, checkpoint)

        # IDs nuevos encontrados en esta sesión
        conn_tmp = sqlite3.connect(DB_PATH)
        cur_tmp  = conn_tmp.cursor()
        nuevos_ids = [i for i in checkpoint["ids_para_email"] if i not in ids_antes]
        if nuevos_ids:
            placeholders = ",".join("?" * len(nuevos_ids))
            cur_tmp.execute(
                f"SELECT nombre_empresa, email, telefono, sitio_web, ciudad, pais, direccion, maps_link FROM contactos_hoteles WHERE id IN ({placeholders})",
                nuevos_ids,
            )
            filas = cur_tmp.fetchall()
            contactos = [
                {
                    "nombre_empresa": f[0],
                    "nicho":          nicho,
                    "email":          f[1],
                    "telefono":       f[2],
                    "sitio_web":      f[3],
                    "ciudad":         f[4],
                    "pais":           f[5] or "Colombia",
                    "direccion":      f[6],
                    "maps_link":      f[7],
                    "fuente":         "maps",
                    "estado":         "sin_contactar",
                }
                for f in filas
            ]
            conn_tmp.close()

            # 3. Subir contactos al CRM
            if contactos:
                log.info(f"📤 Subiendo {len(contactos)} contactos nuevos a Syncrono…")
                r_imp = requests.post(
                    f"{api_url}/api/crm/prospectos/importar",
                    json=contactos,
                    headers=headers_api,
                    timeout=60,
                )
                d_imp = r_imp.json()
                total_nuevos = d_imp.get("insertados", 0)
                log.info(f"✅ Insertados: {total_nuevos} | Omitidos (ya existían): {d_imp.get('omitidos', 0)}")
        else:
            conn_tmp.close()
            log.info("ℹ️  No se encontraron contactos nuevos.")

    except Exception as e:
        error_msg = str(e)
        log.error(f"❌ Error durante el scraping: {e}")
    finally:
        driver.quit()

    # 4. Marcar job como completado
    try:
        requests.post(
            f"{api_url}/api/crm/prospector/jobs/{job_id}/completar",
            json={"total_nuevos": total_nuevos, "error_msg": error_msg},
            headers=headers_api,
            timeout=15,
        )
        if error_msg:
            log.info(f"⚠️  Job #{job_id} marcado como error.")
        else:
            log.info(f"✅ Job #{job_id} completado — {total_nuevos} contactos nuevos en Syncrono.")
    except Exception as e:
        log.warning(f"No se pudo marcar el job como completado: {e}")

    save_checkpoint(checkpoint)


if __name__ == "__main__":
    if "--syncrono" in sys.argv:
        syncrono_main()
    else:
        main()
