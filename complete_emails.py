"""
complete_emails.py
==================
Script para completar emails faltantes en empresas ya registradas en la BD.

Función:
  • Lee empresas sin email de la BD (para uno o varios nichos)
  • Busca email usando la misma lógica avanzada de prospector_ett.py
  • Actualiza la BD automáticamente
  • Checkpoint independiente para no repetir búsquedas
  • Seguro para ejecutar en paralelo con prospector_ett.py

NICHOS POR DEFECTO:
  - Hotelería
  - Retail / Comercio
  - Restaurantes y Bares
  - Industrial / Manufactura
  - Salud y Bienestar

USO:
    python complete_emails.py                           # completa los 5 nichos por defecto
    python complete_emails.py --nicho "Hotelería"      # solo un nicho
    python complete_emails.py --nichos "Hotelería,Retail / Comercio"  # varios nichos
    python complete_emails.py --reset                   # empieza desde cero
    python complete_emails.py --limit 50                # máximo 50 empresas totales
    python complete_emails.py --solo-linkedin           # solo busca en LinkedIn
"""

import sqlite3
import re
import time
import random
import logging
import json
import os
import sys
import socket
import threading
from urllib.parse import urljoin, urlparse, quote_plus, unquote

import requests
import urllib3
from bs4 import BeautifulSoup

try:
    from ddgs import DDGS
    USE_DDG = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        USE_DDG = True
    except ImportError:
        USE_DDG = False
        print("⚠️  ddgs no instalado. Instala con: pip install ddgs")

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
# Detectar BD automáticamente o usar variable de entorno
import os as _os
DB_PATH = _os.environ.get(
    "DB_PATH",
    "/Users/danielaamaya/Downloads/ETL-master/output/base_marketing.db"
)
# Alternativamente, usar BD local si existe
if not _os.path.exists(DB_PATH) and _os.path.exists("base_marketing.db"):
    DB_PATH = "base_marketing.db"
elif not _os.path.exists(DB_PATH) and _os.path.exists("hoteles_colombia.db"):
    DB_PATH = "hoteles_colombia.db"

DB_TABLE = "contactos_marketing" if "base_marketing" in DB_PATH else "contactos_hoteles"
LOG_FILE         = "complete_emails.log"
CHECKPOINT_FILE  = "checkpoint_complete_emails.json"

# Delays
GOOGLE_DELAY_MIN = 15.0
GOOGLE_DELAY_MAX = 25.0
DDG_DELAY_MIN    = 0.5
DDG_DELAY_MAX    = 1.0
LINKEDIN_DELAY_MIN = 0.3
LINKEDIN_DELAY_MAX = 0.7
FB_DELAY_MIN     = 5.0
FB_DELAY_MAX     = 10.0
SITE_DELAY_MIN   = 0.5
SITE_DELAY_MAX   = 1.0
ENTITY_DELAY_MIN = 4.0
ENTITY_DELAY_MAX = 8.0
PAGE_TIMEOUT     = 3
MAX_DDG_RESULTS  = 3
MAX_SUBPAGES     = 1

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
    "hotels.com", "despegar.com", "kayak.com", "trivago.com",
    "google.com", "google.com.co", "maps.google.com",
    "youtube.com", "wikipedia.org", "yelp.com",
    "wa.me", "wa.link", "linktr.ee", "getawayrentals.info",
    "tiktok.com", "twitter.com", "x.com", "instagram.com", "facebook.com",
    "bbva.com", "onthisday.com", "significados.com",
    "apps.apple.com", "play.google.com", "biblegateway.com",
}

SKIP_EMAIL_DOMAINS = {
    "booking.com", "tripadvisor.com", "expedia.com", "hotels.com",
    "google.com", "gmail.com", "rae.es", "bbva.com",
}

LEGAL_SUFFIXES_RE = re.compile(
    r"\s+(s\.?\s*a\.?\s*s\.?|s\.?\s*a\.?|ltda\.?|bic|s\.c\.a\.?|"
    r"y\s+compan[ií]a|y\s+cia\.?|sucursal\s+colombia|e\.u\.)\b.*$",
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
    "empleo", "trabajar", "oportunidad", "vacante", "selección",
]

COMMON_CONTACT_PATHS = [
    "/contacto", "/contact", "/contactenos", "/nosotros",
    "/about", "/informacion", "/empleo", "/trabaja",
    "/oportunidades", "/seleccion", "/rrhh",
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


# ─── VALIDACIÓN DE INTERNET ───────────────────────────────────────────────────
def check_internet() -> bool:
    """Verifica si hay conexión a internet."""
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except (socket.timeout, socket.error):
        return False


# ─── CHECKPOINT ───────────────────────────────────────────────────────────────
def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["completados"] = set(data.get("completados", []))
            log.info(f"♻️  Checkpoint: {len(data['completados'])} empresas procesadas")
            return data
        except Exception as e:
            log.warning(f"Error leyendo checkpoint: {e}")
    return {
        "completados": set(),
        "stats": {"emails_encontrados": 0, "sin_resultado": 0},
    }


def save_checkpoint(cp: dict):
    data = dict(cp)
    data["completados"] = list(cp["completados"])
    try:
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"No se pudo guardar checkpoint: {e}")


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
        log.warning(f"DDG error: {e}")
        time.sleep(6)
        return []


def ddg_search_parsed(query: str) -> tuple:
    """Retorna (emails_en_snippets, urls_oficiales, urls_linkedin, urls_facebook)."""
    results  = ddg_search(query)
    emails, official, linkedin, facebook = [], [], [], []
    for r in results:
        url  = r.get("href", "")
        text = r.get("body", "") + " " + r.get("title", "")
        for e in extract_emails_from_text(text):
            if e not in emails:
                emails.append(e)
        if not url:
            continue
        if "linkedin.com" in url:
            if "/company/" in url or "/showcase/" in url:
                linkedin.append(url)
        elif "facebook.com" in url:
            path = urlparse(url).path
            if not re.search(
                r"/(photo|photos|posts|events|watch|groups|hashtag|sharer|share|login|l\.php)",
                path,
            ):
                facebook.append(url)
        elif is_official_site(url):
            official.append(url)
    return emails, official, linkedin, facebook


# ─── LINKEDIN ─────────────────────────────────────────────────────────────────
def scrape_linkedin_company(linkedin_url: str, driver) -> tuple:
    """Scrappea página de empresa en LinkedIn."""
    try:
        driver.get(linkedin_url)
        time.sleep(random.uniform(3.0, 5.0))
    except TimeoutException:
        pass
    except Exception as e:
        log.warning(f"  ⚠️ Error accediendo LinkedIn: {e}")
        return [], ""

    for selector in ["button[aria-label='Dismiss']", "button[aria-label='Rechazar']"]:
        try:
            btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            )
            btn.click()
            time.sleep(1)
        except Exception:
            pass

    try:
        about_section = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'About')]"))
        )
        driver.execute_script("arguments[0].scrollIntoView();", about_section)
        time.sleep(2)
    except Exception:
        pass

    source = driver.page_source
    emails = extract_emails_from_html(source)
    soup = BeautifulSoup(source, "lxml")
    text_content = soup.get_text(" ")

    return emails, text_content


def linkedin_search(nombre_empresa: str, driver, session: requests.Session) -> list:
    """Búsqueda RÁPIDA en LinkedIn - solo 1 query, sin scrape."""
    query = f'site:linkedin.com/company "{nombre_empresa}"'

    all_emails = []
    result = ddg_search(query)
    for r in result:
        text = r.get("body", "") + " " + r.get("title", "")
        for e in extract_emails_from_text(text):
            if e not in all_emails:
                all_emails.append(e)

    time.sleep(random.uniform(0.5, 1.0))
    return all_emails


# ─── GOOGLE SEARCH ────────────────────────────────────────────────────────────
def _parse_serp_urls(source: str) -> tuple:
    soup             = BeautifulSoup(source, "lxml")
    official, linkedin, facebook = [], [], []
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
        if "linkedin.com" in domain:
            if "/company/" in href:
                linkedin.append(href)
        elif "facebook.com" in domain:
            path = urlparse(href).path
            if not re.search(
                r"/(photo|photos|posts|events|watch|groups|hashtag|sharer|share|login|l\.php)",
                path,
            ):
                facebook.append(href)
        elif is_official_site(href):
            official.append(href)
    return official, linkedin, facebook


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
    """Retorna (emails, official_urls, linkedin_urls, fb_urls)."""
    search_url = f"https://www.google.com/search?q={quote_plus(query)}&hl=es&gl=co&num=10"
    try:
        driver.get(search_url)
        time.sleep(random.uniform(2.5, 4.5))
    except TimeoutException:
        pass
    except Exception as e:
        log.warning(f"Error navegando Google: {e}")
        return None, [], [], []

    block = _google_is_blocked(driver)
    if block == "captcha":
        log.warning("⚠️  Google CAPTCHA detectado. Resuélvelo y presiona Enter.")
        input("   ↳ Presiona Enter cuando hayas resuelto el CAPTCHA: ")
        time.sleep(3)  # Esperar a que Google procese después del CAPTCHA
        if _google_is_blocked(driver) == "403":
            log.warning("⚠️  Google sigue bloqueando. Reintentando en 10 segundos...")
            time.sleep(10)
            if _google_is_blocked(driver) == "403":
                return None, [], [], []
    elif block == "403":
        log.warning("⚠️  Google 403 → usando DuckDuckGo automáticamente.")
        return None, [], [], []

    source    = driver.page_source
    page_text = BeautifulSoup(source, "lxml").get_text(" ")
    emails    = extract_emails_from_text(page_text)
    official, linkedin, facebook = _parse_serp_urls(source)
    return emails, official, linkedin, facebook


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

    source = driver.page_source
    emails = extract_emails_from_html(source)
    return emails


def try_facebook(fb_url: str, driver, session: requests.Session) -> tuple:
    emails = scrape_facebook_requests(fb_url, session)
    if emails:
        return emails, None
    log.info(f"  📘 FB Selenium: {fb_url[:70]}")
    result = scrape_facebook_selenium(fb_url, driver)
    return result, None


# ─── BUSCAR EMAIL PARA UNA EMPRESA ────────────────────────────────────────────
def find_email_for_company(empresa_id: int, nombre: str, ciudad: str | None,
                          sitio_web: str | None, driver, session: requests.Session,
                          cur, conn, solo_linkedin: bool = False) -> str | None:
    """
    Busca email para una empresa específica.
    Retorna el email encontrado o None.
    """
    nombre_limpio = clean_name(nombre)
    ciudad_str    = ciudad or "Colombia"

    def save_email(email: str):
        # Pequeño delay aleatorio para evitar collisiones de escritura en BD concurrente
        time.sleep(random.uniform(0.1, 0.3))
        try:
            cur.execute(
                f"UPDATE {DB_TABLE} SET email = ? WHERE id = ?",
                (email, empresa_id),
            )
            conn.commit()
        except Exception as e:
            log.warning(f"  ⚠️ Reintentando escritura en BD: {e}")
            time.sleep(0.5)
            cur.execute(
                f"UPDATE {DB_TABLE} SET email = ? WHERE id = ?",
                (email, empresa_id),
            )
            conn.commit()
        return email

    # ── (a) Web conocida ──────────────────────────────────────────────────────
    if not solo_linkedin and sitio_web and is_official_site(sitio_web):
        log.info(f"  🌐 (a) Web: {sitio_web}")
        emails = scrape_site_deep(sitio_web, session)
        if emails:
            log.info(f"  ✅ Email encontrado en web")
            return save_email(emails[0])
        time.sleep(random.uniform(SITE_DELAY_MIN, SITE_DELAY_MAX))

    # ── (b) DDG ──────────────────────────────────────────────────────────────
    if not solo_linkedin:
        query = f'"{nombre_limpio}" {ciudad_str} email contacto'
        log.info(f"  🔍 (b) DDG: {query[:60]}")
        ddg_results = ddg_search(query)

        for r in ddg_results:
            url  = r.get("href", "")
            text = r.get("body", "") + " " + r.get("title", "")
            for e in extract_emails_from_text(text):
                log.info(f"  ✅ Email en snippet DDG")
                return save_email(e)

        # Visitar sitios oficiales de DDG
        for r in ddg_results:
            url = r.get("href", "")
            if url and is_official_site(url):
                log.info(f"  🌐 (b) Visitando: {url[:70]}")
                emails = scrape_site_deep(url, session)
                if emails:
                    log.info(f"  ✅ Email en sitio DDG")
                    return save_email(emails[0])
                time.sleep(random.uniform(SITE_DELAY_MIN, SITE_DELAY_MAX))
                break

    # ── (c) LINKEDIN ──────────────────────────────────────────────────────────
    log.info(f"  📘 (c) LinkedIn")
    li_emails = linkedin_search(nombre_limpio, driver, session)
    if li_emails:
        log.info(f"  ✅ Email en LinkedIn")
        return save_email(li_emails[0])

    # ── (d) Google Search ─ DESHABILITADO (usar solo DDG) ─────────────────────
    # Google causa "invalid session id" errors. Usando solo DDG para mayor estabilidad.
    if False:  # Google deshabilitado
        pass

        # Sitios oficiales
        for url in g_official[:2]:
            if sitio_web and get_domain(url) == get_domain(sitio_web):
                continue
            log.info(f"  🌐 Visitando: {url[:70]}")
            emails = scrape_site_deep(url, session)
            if emails:
                log.info(f"  ✅ Email en sitio")
                return save_email(emails[0])
            time.sleep(random.uniform(SITE_DELAY_MIN, SITE_DELAY_MAX))

        # Facebook
        for fb_url in g_fb[:2]:
            log.info(f"  📘 Facebook: {fb_url[:70]}")
            fb_emails, _ = try_facebook(fb_url, driver, session)
            if fb_emails:
                log.info(f"  ✅ Email en Facebook")
                return save_email(fb_emails[0])
            time.sleep(random.uniform(FB_DELAY_MIN, FB_DELAY_MAX))

    log.info(f"  ❌ Sin resultado")
    return None


# ─── SELENIUM DRIVER ──────────────────────────────────────────────────────────
def get_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--disable-notifications")
    opts.add_argument("--lang=es-CO")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
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


# ─── MAIN ─────────────────────────────────────────────────────────────────────
# Nichos por defecto para completar
DEFAULT_NICHOS = [
    "Hotelería",
    "Retail / Comercio",
    "Restaurantes y Bares",
    "Industrial / Manufactura",
    "Salud y Bienestar",
]


def main():
    if "--reset" in sys.argv:
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
            log.info("🗑️  Checkpoint eliminado. Empezando desde cero.")

    # Parsear argumentos
    nichos = None
    limit = None
    offset = 0
    count = None
    solo_linkedin = False

    for arg in sys.argv[1:]:
        if arg.startswith("--nicho="):
            nichos = [arg.split("=", 1)[1]]
        elif arg.startswith("--nichos="):
            nichos = [n.strip() for n in arg.split("=", 1)[1].split(",")]
        elif arg.startswith("--limit="):
            limit = int(arg.split("=", 1)[1])
        elif arg.startswith("--offset="):
            offset = int(arg.split("=", 1)[1])
        elif arg.startswith("--count="):
            count = int(arg.split("=", 1)[1])
        elif arg == "--solo-linkedin":
            solo_linkedin = True

    # Si no especifica nichos, usar los por defecto
    if not nichos:
        nichos = DEFAULT_NICHOS

    checkpoint = load_checkpoint()

    log.info(f"📁 Usando BD: {DB_PATH}")
    log.info(f"📊 Tabla: {DB_TABLE}")

    conn = sqlite3.connect(DB_PATH)
    # ⚠️  Timeout más alto para evitar "database is locked" en operaciones concurrentes
    conn.execute("PRAGMA busy_timeout = 5000")  # 5 segundos
    cur  = conn.cursor()

    # Obtener empresas sin email para los nichos especificados
    placeholders = ",".join("?" * len(nichos))
    query = f"""
        SELECT id, nombre_empresa, ciudad, sitio_web, nicho
        FROM {DB_TABLE}
        WHERE (email IS NULL OR email = '')
          AND nicho IN ({placeholders})
        ORDER BY nicho, nombre_empresa
    """
    cur.execute(query, nichos)

    empresas = cur.fetchall()
    pendientes = [row for row in empresas if row[0] not in checkpoint["completados"]]

    total = len(empresas)
    ya_hechos = total - len(pendientes)

    # Aplicar offset y count para paralelización
    if offset > 0 or count:
        pendientes = pendientes[offset:]
        if count:
            pendientes = pendientes[:count]
    elif limit:
        pendientes = pendientes[:limit]

    log.info(f"\n{'='*60}")
    log.info(f"COMPLETAR EMAILS")
    log.info(f"Total sin email   : {total}")
    log.info(f"Ya procesados     : {ya_hechos}")
    log.info(f"Pendientes        : {len(pendientes)}")
    log.info(f"Nichos            : {', '.join(nichos)}")
    if solo_linkedin:
        log.info(f"Modo              : Solo LinkedIn")
    log.info(f"⚠️  Safe para ejecutar en paralelo (SQLite maneja concurrencia)")
    log.info(f"{'='*60}\n")

    if not pendientes:
        log.info("✅ No hay empresas sin email.")
        conn.close()
        return

    driver = get_driver()
    session = requests.Session()
    stats = checkpoint["stats"]

    try:
        # Establecer sesión Google
        log.info("🌐 Cargando Google para establecer sesión...")
        try:
            driver.get("https://www.google.com/?hl=es")
            time.sleep(random.uniform(2, 4))
            accept_google_cookies(driver)
        except Exception:
            pass

        driver_cycles = 0
        for i, (empresa_id, nombre, ciudad, sitio_web, nicho_actual) in enumerate(pendientes, 1):
            # Reiniciar driver cada 50 registros para evitar "invalid session id"
            if i % 50 == 0 and i > 0:
                log.info(f"🔄 Reiniciando ChromeDriver (50 registros completados)...")
                try:
                    driver.quit()
                except:
                    pass
                time.sleep(2)
                try:
                    driver = get_driver()
                    log.info("✅ ChromeDriver reiniciado exitosamente")
                except Exception as e:
                    log.error(f"❌ Error reiniciando driver: {e}")
                    log.error("   Intentando continuar con driver actual...")

            # Validar conectividad cada 10 empresas
            if i % 10 == 0:
                if not check_internet():
                    log.error("❌ CONEXIÓN A INTERNET PERDIDA. Deteniendo script.")
                    log.info(f"   Progreso guardado: {i}/{len(pendientes)} empresas procesadas")
                    break

            num = ya_hechos + i
            log.info(f"\n[{num}/{total}] {nombre} ({ciudad or 'sin ciudad'}) | {nicho_actual}")

            try:
                email = find_email_for_company(
                    empresa_id, nombre, ciudad, sitio_web,
                    driver, session, cur, conn, solo_linkedin
                )
                if email:
                    stats["emails_encontrados"] += 1
                else:
                    stats["sin_resultado"] += 1
            except Exception as e:
                log.error(f"  ERROR: {e}")
                stats["sin_resultado"] += 1

            checkpoint["completados"].add(empresa_id)
            save_checkpoint(checkpoint)

            if i % 10 == 0:
                log.info(
                    f"  📊 Progreso {num}/{total} | "
                    f"Emails: {stats['emails_encontrados']} | Sin resultado: {stats['sin_resultado']}"
                )

            time.sleep(random.uniform(ENTITY_DELAY_MIN, ENTITY_DELAY_MAX))

    finally:
        driver.quit()
        conn.close()

    log.info(f"\n{'='*60}")
    log.info(f"RESUMEN")
    log.info(f"Emails encontrados: {stats['emails_encontrados']}")
    log.info(f"Sin resultado     : {stats['sin_resultado']}")
    log.info(f"{'='*60}")


if __name__ == "__main__":
    main()
