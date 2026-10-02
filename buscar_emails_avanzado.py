"""
buscar_emails_avanzado.py
=========================
Busca emails para los hoteles que quedaron sin email usando:
  1. Google Search via Selenium → emails en snippets / Knowledge Panel / sitios oficiales
  2. Facebook público → m.facebook.com con requests → fallback Selenium

NOTAS IMPORTANTES:
  - Chrome corre VISIBLE (no headless) para evitar detección de Google
  - 15-25s de delay entre búsquedas de Google para no triggerear CAPTCHA
  - Si Google muestra CAPTCHA → el script pausa y espera que lo resuelvas en el navegador
  - Un solo driver Chrome para toda la sesión (no abre/cierra por hotel)

USO:
    python buscar_emails_avanzado.py           # continúa desde checkpoint
    python buscar_emails_avanzado.py --reset   # empieza desde cero
"""

import sqlite3
import re
import time
import random
import logging
import json
import os
import sys
import signal
from urllib.parse import urlparse, quote_plus, urljoin, unquote

import requests
import urllib3
from bs4 import BeautifulSoup

try:
    from duckduckgo_search import DDGS
    USE_DDG = True
except ImportError:
    USE_DDG = False

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException,
)
from webdriver_manager.chrome import ChromeDriverManager

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
DB_PATH          = "hoteles_colombia.db"
LOG_FILE         = "buscar_emails_avanzado.log"
REPORT_FILE      = "reporte_emails_avanzado.txt"
CHECKPOINT_FILE  = "checkpoint_emails_avanzado.json"

GOOGLE_DELAY_MIN = 15.0   # espera entre búsquedas Google (evitar CAPTCHA)
GOOGLE_DELAY_MAX = 25.0
FB_DELAY_MIN     = 5.0    # espera entre visitas a Facebook
FB_DELAY_MAX     = 10.0
SITE_DELAY_MIN   = 1.5    # espera entre visitas a sitios web
SITE_DELAY_MAX   = 3.0
HOTEL_DELAY_MIN  = 4.0    # espera entre hoteles
HOTEL_DELAY_MAX  = 8.0
PAGE_TIMEOUT     = 15

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
    "booking.com", "tripadvisor.com", "airbnb.com", "expedia.com",
    "hotels.com", "despegar.com", "kayak.com", "trivago.com",
    "google.com", "google.com.co", "maps.google.com",
    "youtube.com", "wikipedia.org", "yelp.com", "cotelco.org",
    "ayenda.com", "decameron.com", "lobbypms.com",
    "wa.me", "wa.link", "linktr.ee", "getawayrentals.info",
    "tiktok.com", "choicehotels.com", "twitter.com", "x.com",
    "instagram.com",
    # Agregadores y agencias de viaje colombianas/latam
    "centraldereservas.com", "atrapalo.com", "atrapalo.com.co",
    "momondo.com", "momondo.com.co", "hoteles.com", "hoteles.com.co",
    "hotel.com.co", "viajes.com", "hotusa.com", "venere.com",
    "hrs.com", "muchosol.com", "rumbo.com", "edreams.com",
    "lastminute.com", "caribetraveltours.com", "revistalabarra.com",
    "decolar.com", "almundo.com", "viajala.com", "atrápalo.com",
}

# Dominios cuyos emails NO son del hotel (agencias, directorios, etc.)
SKIP_EMAIL_DOMAINS = {
    "pricetravel.com", "despegar.com", "booking.com", "tripadvisor.com",
    "expedia.com", "hotels.com", "trivago.com", "kayak.com", "agoda.com",
    "orbitz.com", "priceline.com", "hoteles.com", "hoteles.com.co",
    "viajes.com", "centraldereservas.com", "atrapalo.com", "atrapalo.com.co",
    "momondo.com", "momondo.com.co", "hotusa.com", "edreams.com",
    "caribetraveltours.com", "revistalabarra.com", "decolar.com",
    "almundo.com", "viajala.com", "cotelco.org", "cotelcoatlantico.org",
    "cotelcobogota.org", "google.com", "gmail.com",
    # Emails de cadenas internacionales con dominio de otro país (.uy, .ar, .mx)
    # se filtran verificando que no haya mismatch de país obvio
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
            log.info(f"♻️  Checkpoint: {len(data['procesados'])} hoteles ya procesados.")
            return data
        except Exception as e:
            log.warning(f"Error leyendo checkpoint: {e}")
    return {"procesados": set(), "stats": {"emails": 0, "nada": 0}}


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
    log.info("\n⚠️  Interrupción. Guardando checkpoint...")
    if _cp_ref:
        save_checkpoint(_cp_ref)
    log.info(f"✅ Guardado en {CHECKPOINT_FILE}. Vuelve a correr para retomar.")
    sys.exit(0)


signal.signal(signal.SIGINT, handle_interrupt)
signal.signal(signal.SIGTERM, handle_interrupt)


# ─── UTILIDADES ───────────────────────────────────────────────────────────────
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
    # La parte local debe tener al menos 2 caracteres ("n@" no es válido)
    if len(local) < 2:
        return False
    # Rechazar emails de agencias/plataformas de viaje
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
    return (
        "facebook.com" not in domain
        and "linkedin.com" not in domain
        and not any(skip in domain for skip in SKIP_DOMAINS)
    )


def extract_emails_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
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


def extract_emails_from_text(text: str) -> list[str]:
    return [
        e.strip().lower()
        for e in EMAIL_RE.findall(text)
        if is_valid_email(e.strip().lower())
    ]


def get_page(url: str, session: requests.Session, extra_headers: dict | None = None) -> str | None:
    headers = {**HEADERS, **(extra_headers or {})}
    for verify in (True, False):
        try:
            resp = session.get(
                url, headers=headers, timeout=12,
                allow_redirects=True, verify=verify,
            )
            if resp.status_code == 200:
                return resp.text
        except Exception:
            if verify:
                continue
            break
    return None


def find_contact_subpages(html: str, base_url: str) -> list[str]:
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
    return links[:5]


def scrape_site_deep(url: str, session: requests.Session) -> list[str]:
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
    base = f"{parsed.scheme}://{parsed.netloc}"
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


# ─── SELENIUM DRIVER ──────────────────────────────────────────────────────────
def get_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--disable-notifications")
    opts.add_argument("--start-maximized")
    opts.add_argument("--lang=es-CO")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    # NO headless — Google detecta headless más fácilmente
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(PAGE_TIMEOUT)
    # Ocultar que es Selenium vía JS
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )
    return driver


def accept_google_cookies(driver):
    """Acepta el popup de cookies de Google si aparece."""
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


# ─── GOOGLE SEARCH ────────────────────────────────────────────────────────────
def _parse_serp_urls(source: str) -> tuple[list[str], list[str]]:
    """Extrae URLs oficiales y de Facebook del HTML del SERP de Google."""
    soup = BeautifulSoup(source, "lxml")
    official, facebook = [], []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]

        # Limpiar redirecciones de Google /url?q=...
        if href.startswith("/url?") or href.startswith("/search?"):
            m = re.search(r"[?&]q=([^&]+)", href)
            if m:
                href = unquote(m.group(1))

        if not href.startswith("http") or href in seen:
            continue
        seen.add(href)

        domain = get_domain(href)

        if "facebook.com" in domain:
            # Solo páginas de empresa o perfil (no posts, fotos, etc.)
            path = urlparse(href).path
            if path and not re.search(
                r"/(photo|photos|posts|events|watch|groups|hashtag|sharer|share|login|l\.php)",
                path,
            ):
                facebook.append(href)
        elif is_official_site(href):
            official.append(href)

    return official, facebook


def _google_is_blocked(driver) -> str | None:
    """
    Detecta si Google está bloqueando la búsqueda.
    Retorna: 'captcha' | '403' | None
    """
    current_url = driver.current_url
    title       = driver.title.lower()
    preview     = driver.page_source[:3000].lower()

    if "/sorry/" in current_url or "google.com/sorry" in current_url:
        return "captcha"

    if (
        "error 403" in title
        or "403" in title
        or "error 403" in preview
        or ("unusual traffic" in preview and len(driver.page_source) < 8000)
        or "that's an error" in preview
    ):
        return "403"

    return None


def ddg_search_parsed(query: str) -> tuple[list[str], list[str], list[str]]:
    """
    Búsqueda en DuckDuckGo (fallback cuando Google bloquea).
    Retorna: (emails_en_snippets, urls_oficiales, urls_facebook)
    """
    if not USE_DDG:
        return [], [], []
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=6, region="co-es"))
        time.sleep(random.uniform(2.0, 4.0))
    except Exception as e:
        log.warning(f"DDG error: {e}")
        return [], [], []

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


def google_search(
    query: str, driver
) -> tuple[list[str] | None, list[str], list[str]]:
    """
    Búsqueda en Google via Selenium.
    Retorna: (emails_en_serp, urls_oficiales, urls_facebook)
      - emails = None  →  Google está bloqueando (403); usar DDG como fallback
      - emails = []    →  Google respondió bien pero no encontró emails
    CAPTCHA (/sorry/): pausa y espera que lo resuelvas.
    403: retorna None inmediatamente para que el caller use DDG.
    """
    search_url = (
        f"https://www.google.com/search"
        f"?q={quote_plus(query)}&hl=es&gl=co&num=10"
    )

    try:
        driver.get(search_url)
        time.sleep(random.uniform(2.5, 4.5))
    except TimeoutException:
        pass
    except Exception as e:
        log.warning(f"Error navegando a Google: {e}")
        return None, [], []

    block_type = _google_is_blocked(driver)

    if block_type == "captcha":
        log.warning("⚠️  Google pidió verificación (CAPTCHA). Resuélvela en el navegador.")
        print("\n⚠️  Google pidió verificación. Resuélvela y presiona Enter para continuar.")
        input("   ↳ Presiona Enter cuando termines: ")
        # Re-chequear tras resolverlo
        if _google_is_blocked(driver) == "403":
            log.warning("  Sigue bloqueado después del CAPTCHA → usando DDG")
            return None, [], []

    elif block_type == "403":
        log.warning("⚠️  Google devolvió 403 → cambiando a DuckDuckGo automáticamente.")
        return None, [], []

    source    = driver.page_source
    soup      = BeautifulSoup(source, "lxml")
    page_text = soup.get_text(" ")

    emails        = extract_emails_from_text(page_text)
    official_urls, fb_urls = _parse_serp_urls(source)

    return emails, official_urls, fb_urls


# ─── FACEBOOK ─────────────────────────────────────────────────────────────────
def _fb_about_url(fb_url: str) -> str:
    """Construye la URL de la sección About de Facebook."""
    parsed = urlparse(fb_url)
    # Quitar query params y fragmentos
    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
    if "/about" not in clean:
        clean += "/about"
    return clean


def scrape_facebook_requests(fb_url: str, session: requests.Session) -> list[str]:
    """
    Intenta extraer emails de la página pública de Facebook
    usando el sitio móvil (m.facebook.com), que a veces sirve
    info sin requerir login.
    """
    mobile_url = _fb_about_url(
        fb_url.replace("www.facebook.com", "m.facebook.com")
             .replace("//facebook.com", "//m.facebook.com")
    )

    try:
        resp = session.get(
            mobile_url, headers=FB_MOBILE_HEADERS,
            timeout=12, allow_redirects=True,
        )
        if resp.status_code != 200:
            return []
        # Si redirigió al login, no sirve
        if "login" in resp.url.lower() or "id='loginform'" in resp.text:
            return []
        return extract_emails_from_html(resp.text)
    except Exception as e:
        log.debug(f"FB requests error: {e}")
        return []


def scrape_facebook_selenium(fb_url: str, driver) -> list[str]:
    """
    Visita la página de Facebook con Selenium, cierra el popup
    de login si aparece y lee el contenido público disponible.
    """
    about_url = _fb_about_url(fb_url)

    try:
        driver.get(about_url)
        time.sleep(random.uniform(3.5, 5.5))
    except TimeoutException:
        pass
    except Exception as e:
        log.debug(f"FB Selenium nav error: {e}")
        return []

    # Cerrar popup de login (varias estrategias)
    for selector in [
        "[aria-label='Cerrar']",
        "[aria-label='Close']",
        "[aria-label='Cierra']",
        "div[role='dialog'] [role='button']",
        "div[data-testid='dialog'] [role='button']",
    ]:
        try:
            driver.find_element(By.CSS_SELECTOR, selector).click()
            time.sleep(1.5)
            break
        except NoSuchElementException:
            pass

    # También Escape
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(1)
    except Exception:
        pass

    # Buscar en el snippet del SERP de Google también (ya estará en page_text de arriba)
    # Leer el contenido visible
    source = driver.page_source
    emails = extract_emails_from_html(source)

    # Si no hay email, buscar el website del negocio para scrapearlo
    if not emails:
        soup = BeautifulSoup(source, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if is_official_site(href) and "facebook" not in href:
                log.info(f"  🌐 Website extraído de Facebook: {href}")
                return [f"__WEBSITE__{href}"]  # señal especial: encontramos web, no email

    return emails


def try_facebook(
    fb_url: str, driver, session: requests.Session
) -> tuple[list[str], str | None]:
    """
    Combina requests y Selenium para extraer email de una página de Facebook.
    Retorna: (emails, website_encontrado_o_None)
    """
    # 1. Requests en m.facebook.com (rápido, sin usar el driver)
    emails = scrape_facebook_requests(fb_url, session)
    if emails:
        return emails, None

    # 2. Selenium fallback
    log.info(f"  📘 Selenium → Facebook: {fb_url[:70]}")
    result = scrape_facebook_selenium(fb_url, driver)

    # Distinguir email vs señal de website
    if result and result[0].startswith("__WEBSITE__"):
        return [], result[0][len("__WEBSITE__"):]

    return result, None


# ─── PROCESAR UN HOTEL ────────────────────────────────────────────────────────
def process_hotel(
    hotel_id: int,
    nombre: str,
    ciudad: str | None,
    sitio_web: str | None,
    driver,
    session: requests.Session,
    cur,
    conn,
) -> dict:
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

    # ── BÚSQUEDA PRINCIPAL (Google → fallback DDG si Google da 403) ───────────
    query = f'"{nombre_limpio}" {ciudad_str} email contacto'
    log.info(f"  🔍 Google: {query}")
    serp_emails, official_urls, fb_urls = google_search(query, driver)

    if serp_emails is None:
        # Google bloqueó → DDG automático, sin interrumpir el script
        log.info(f"  🔄 DDG fallback: {query}")
        serp_emails, official_urls, fb_urls = ddg_search_parsed(query)
        search_via = "ddg"
    else:
        search_via = "google"
        time.sleep(random.uniform(GOOGLE_DELAY_MIN, GOOGLE_DELAY_MAX))

    # Email directo en snippet
    if serp_emails:
        log.info(f"  ✅ Email en SERP ({search_via}): {serp_emails[0]}")
        save_email(serp_emails[0])
        return {"found": "email", "value": serp_emails[0], "via": f"{search_via}_serp"}

    # Visitar sitios oficiales encontrados (máx 3)
    for url in official_urls[:3]:
        if sitio_web and get_domain(url) == get_domain(sitio_web):
            continue  # ya scrapeado anteriormente
        log.info(f"  🌐 Visitando ({search_via}): {url[:70]}")
        emails = scrape_site_deep(url, session)
        if emails:
            log.info(f"  ✅ Email en sitio: {emails[0]}")
            save_email(emails[0], url if not sitio_web else None)
            return {"found": "email", "value": emails[0], "via": f"{search_via}_site"}
        time.sleep(random.uniform(SITE_DELAY_MIN, SITE_DELAY_MAX))

    # ── FACEBOOK desde el SERP ────────────────────────────────────────────────
    for fb_url in fb_urls[:2]:
        log.info(f"  📘 Facebook (SERP {search_via}): {fb_url[:70]}")
        fb_emails, fb_web = try_facebook(fb_url, driver, session)
        if fb_emails:
            log.info(f"  ✅ Email en Facebook: {fb_emails[0]}")
            save_email(fb_emails[0])
            return {"found": "email", "value": fb_emails[0], "via": "facebook_serp"}
        if fb_web:
            emails = scrape_site_deep(fb_web, session)
            if emails:
                log.info(f"  ✅ Email via Facebook→web: {emails[0]}")
                save_email(emails[0], fb_web)
                return {"found": "email", "value": emails[0], "via": "facebook_web"}
            if not sitio_web:
                save_web(fb_web)
        time.sleep(random.uniform(FB_DELAY_MIN, FB_DELAY_MAX))

    # ── BÚSQUEDA #2: Facebook específico (si no apareció en SERP #1) ─────────
    if not fb_urls:
        fb_query = f'"{nombre_limpio}" {ciudad_str} site:facebook.com'

        if search_via == "google":
            log.info(f"  🔍 Google→Facebook: {fb_query}")
            fb_serp_emails, _, fb_urls_2 = google_search(fb_query, driver)
            if fb_serp_emails is None:
                log.info(f"  🔄 DDG fallback Facebook: {fb_query}")
                fb_serp_emails, _, fb_urls_2 = ddg_search_parsed(fb_query)
            else:
                time.sleep(random.uniform(GOOGLE_DELAY_MIN, GOOGLE_DELAY_MAX))
        else:
            log.info(f"  🔍 DDG→Facebook: {fb_query}")
            fb_serp_emails, _, fb_urls_2 = ddg_search_parsed(fb_query)

        if fb_serp_emails:
            log.info(f"  ✅ Email en snippet Facebook: {fb_serp_emails[0]}")
            save_email(fb_serp_emails[0])
            return {"found": "email", "value": fb_serp_emails[0], "via": "facebook_snippet"}

        if search_via == "google":
            time.sleep(random.uniform(GOOGLE_DELAY_MIN, GOOGLE_DELAY_MAX))

        for fb_url in fb_urls_2[:2]:
            log.info(f"  📘 Facebook (búsqueda directa): {fb_url[:70]}")
            fb_emails, fb_web = try_facebook(fb_url, driver, session)
            if fb_emails:
                log.info(f"  ✅ Email en Facebook: {fb_emails[0]}")
                save_email(fb_emails[0])
                return {"found": "email", "value": fb_emails[0], "via": "facebook_direct"}
            if fb_web:
                emails = scrape_site_deep(fb_web, session)
                if emails:
                    log.info(f"  ✅ Email via Facebook→web: {emails[0]}")
                    save_email(emails[0], fb_web)
                    return {"found": "email", "value": emails[0], "via": "facebook_web2"}
            time.sleep(random.uniform(FB_DELAY_MIN, FB_DELAY_MAX))

    log.info(f"  ❌ Sin resultado: {nombre}")
    return {"found": "nothing"}


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    global _cp_ref

    if "--reset" in sys.argv:
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
            log.info("🗑️  Checkpoint eliminado. Empezando desde cero.")

    checkpoint = load_checkpoint()
    _cp_ref    = checkpoint

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    cur.execute("""
        SELECT id, nombre_empresa, ciudad, sitio_web
        FROM contactos_hoteles
        WHERE email IS NULL OR email = ''
        ORDER BY
            -- Primero los que tienen web real (más probable encontrar email)
            CASE
                WHEN sitio_web IS NOT NULL AND sitio_web != ''
                     AND sitio_web NOT LIKE '%No disponible%'
                     AND sitio_web NOT LIKE '%wa.%'
                     AND sitio_web NOT LIKE '%facebook%'
                     AND sitio_web NOT LIKE '%instagram%'
                THEN 0 ELSE 1
            END,
            id
    """)
    hoteles    = cur.fetchall()
    total      = len(hoteles)
    pendientes = [row for row in hoteles if row[0] not in checkpoint["procesados"]]
    ya_hechos  = total - len(pendientes)

    log.info(f"Total sin email : {total}")
    log.info(f"Ya procesados   : {ya_hechos}")
    log.info(f"Pendientes      : {len(pendientes)}")

    if not pendientes:
        log.info("✅ Todos los hoteles ya fueron procesados.")
        conn.close()
        return

    session = requests.Session()
    driver  = get_driver()

    # Ir a Google para establecer sesión y aceptar cookies
    log.info("🌐 Iniciando sesión en Google...")
    try:
        driver.get("https://www.google.com/?hl=es")
        time.sleep(random.uniform(2, 4))
        accept_google_cookies(driver)
    except Exception:
        pass

    stats  = checkpoint["stats"]
    report = []

    try:
        for i, (hotel_id, nombre, ciudad, sitio_web) in enumerate(pendientes, 1):
            num = ya_hechos + i
            log.info(f"\n[{num}/{total}] {nombre} ({ciudad or 'sin ciudad'})")

            try:
                result = process_hotel(
                    hotel_id, nombre, ciudad, sitio_web,
                    driver, session, cur, conn,
                )
            except Exception as e:
                log.error(f"  ERROR inesperado: {e}")
                result = {"found": "nothing"}

            if result["found"] == "email":
                stats["emails"] += 1
                report.append(
                    f"✅ EMAIL [{result.get('via', '?')}] | {nombre} | {result['value']}"
                )
            else:
                stats["nada"] += 1
                report.append(f"❌ NADA | {nombre} | {ciudad or ''}")

            checkpoint["procesados"].add(hotel_id)
            save_checkpoint(checkpoint)

            if i % 5 == 0:
                log.info(
                    f"  📊 Progreso {num}/{total} | "
                    f"Emails: {stats['emails']} | "
                    f"Sin resultado: {stats['nada']}"
                )

            time.sleep(random.uniform(HOTEL_DELAY_MIN, HOTEL_DELAY_MAX))

    finally:
        driver.quit()
        conn.close()

    resumen = (
        f"\n{'='*60}\n"
        f"RESUMEN FINAL - GOOGLE + FACEBOOK\n"
        f"{'='*60}\n"
        f"Total procesados   : {total}\n"
        f"Emails encontrados : {stats['emails']}\n"
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
    print(f"📋 Log: {LOG_FILE}")


if __name__ == "__main__":
    main()
