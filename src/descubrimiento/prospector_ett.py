"""
prospector_ett.py
================
Script especializado para empresas de servicios temporales (ETT) en Colombia.

Mejoras respecto a prospector.py:
  • Búsqueda en Maps optimizada para ETTs
  • Búsqueda LinkedIn más agresiva (3 queries diferentes)
  • Palabras clave para validar si es realmente una ETT
  • Scrapping de info específica: licencias, especialidades
  • Misma BD "hoteles_colombia.db" pero nicho="Empresa de Servicios Temporales"

FASES:
  1. MAPS   — Busca ETTs en Google Maps
  2. EMAIL  — Búsqueda email con énfasis en LinkedIn
  3. INFO   — Extrae especialidades, licencias, etc.

USO:
    python prospector_ett.py                # continúa desde checkpoint
    python prospector_ett.py --reset        # empieza desde cero
    python prospector_ett.py --solo-email   # salta Maps, solo busca emails
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
from urllib.parse import urljoin, urlparse, quote_plus, unquote

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
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
import os as _os
DB_PATH = _os.environ.get(
    "DB_PATH",
    ruta_datos("base_marketing.db")
)
# Alternativamente, usar BD local si existe
if not _os.path.exists(DB_PATH) and _os.path.exists(ruta_datos("base_marketing.db")):
    DB_PATH = ruta_datos("base_marketing.db")
elif not _os.path.exists(DB_PATH) and _os.path.exists(ruta_datos("hoteles_colombia.db")):
    DB_PATH = ruta_datos("hoteles_colombia.db")

DB_TABLE = "contactos_marketing" if "base_marketing" in DB_PATH else "contactos_hoteles"
LOG_FILE         = ruta_datos("prospector_ett.log")
CHECKPOINT_FILE  = ruta_datos("checkpoint_ett.json")
NICHO            = "Empresa de Servicios Temporales"

# Delays Maps
MAPS_SCROLL_WAIT = 3.0
MAPS_DETAIL_WAIT = 12

# Delays Email
GOOGLE_DELAY_MIN = 15.0
GOOGLE_DELAY_MAX = 25.0
DDG_DELAY_MIN    = 2.0
DDG_DELAY_MAX    = 4.5
LINKEDIN_DELAY_MIN = 3.0
LINKEDIN_DELAY_MAX = 6.0
FB_DELAY_MIN     = 5.0
FB_DELAY_MAX     = 10.0
SITE_DELAY_MIN   = 1.0
SITE_DELAY_MAX   = 2.5
ENTITY_DELAY_MIN = 4.0
ENTITY_DELAY_MAX = 8.0
PAGE_TIMEOUT     = 15
MAX_DDG_RESULTS  = 8
MAX_SUBPAGES     = 6

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

# ─── PALABRAS CLAVE ETT ────────────────────────────────────────────────────────
ETT_KEYWORDS = {
    "empresa de servicios temporales", "empresa de servicios de personal",
    "agencia de empleo", "agencia de reclutamiento", "staffing",
    "recursos humanos", "personal temporal", "contratación temporal",
    "servicios de personal", "colocación de personal", "outsourcing",
    "intermediación laboral", "selección de personal", "reclutamiento",
    "gestión de personal", "empresa de trabajo temporal", "ett",
    "labor contracting", "personnel services", "employment agency",
}

ETT_SPECIALTIES = {
    "administrativo", "almacén", "logística", "operario", "obrero",
    "construcción", "industrial", "manufactura", "aseo", "limpieza",
    "servicios generales", "seguridad", "vigilancia", "call center",
    "telemarketing", "atención al cliente", "ventas", "comercial",
    "agrícola", "minería", "petróleo", "salud", "enfermería",
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


# ─── VERIFICACIÓN DE CONEXIÓN A INTERNET ──────────────────────────────────────
def check_internet(silent=False) -> bool:
    """Verifica conexión a internet intentando conectar a Google DNS."""
    try:
        import socket
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        if not silent:
            log.info("✅ Conexión a internet OK")
        return True
    except Exception as e:
        if not silent:
            log.error(f"❌ SIN CONEXIÓN A INTERNET: {e}")
        return False


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
                f"| {len(data['emails_procesados'])} ETTs email procesados"
            )
            return data
        except Exception as e:
            log.warning(f"Error leyendo checkpoint, empezando desde cero: {e}")
    return {
        "maps_links_procesados": set(),
        "emails_procesados": set(),
        "ids_para_email": [],
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

    # Crear tabla solo si no existe y es BD local
    if "base_marketing" not in DB_PATH:
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
                especialidades  TEXT,
                licencia_dian   TEXT,
                UNIQUE(nombre_empresa, sitio_web)
            )
        """)
        existing = {row[1] for row in cur.execute("PRAGMA table_info(contactos_hoteles)")}
        for col, typedef in [
            ("direccion", "TEXT"),
            ("maps_link", "TEXT"),
            ("especialidades", "TEXT"),
            ("licencia_dian", "TEXT"),
        ]:
            if col not in existing:
                cur.execute(f"ALTER TABLE contactos_hoteles ADD COLUMN {col} {typedef}")
    else:
        # Si es BD compartida, verificar que la tabla exista
        cur.execute("""
            CREATE TABLE IF NOT EXISTS contactos_marketing (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_empresa  TEXT NOT NULL,
                nicho           TEXT,
                email           TEXT,
                telefono        TEXT,
                sitio_web       TEXT,
                ciudad          TEXT,
                pais            TEXT,
                UNIQUE(nombre_empresa, sitio_web)
            )
        """)
        existing = {row[1] for row in cur.execute("PRAGMA table_info(contactos_marketing)")}
        # Agregar columnas que pueden falta
        for col, typedef in [("email", "TEXT"), ("telefono", "TEXT"), ("sitio_web", "TEXT"), ("ciudad", "TEXT")]:
            if col not in existing:
                cur.execute(f"ALTER TABLE contactos_marketing ADD COLUMN {col} {typedef}")

    conn.commit()
    conn.close()


def upsert_negocio(nombre, nicho, direccion, telefono, sitio_web, ciudad, maps_link,
                   especialidades=None, licencia_dian=None) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    web_domain = get_domain(sitio_web) if sitio_web and sitio_web not in ("No disponible", "") else None

    # Búsqueda por maps_link (solo si es BD local)
    if maps_link and DB_TABLE == "contactos_hoteles":
        cur.execute(f"SELECT id FROM {DB_TABLE} WHERE maps_link = ?", (maps_link,))
        row = cur.fetchone()
        if row:
            conn.close()
            return row[0]

    # Búsqueda por nombre o dominio
    if web_domain:
        cur.execute(
            f"SELECT id FROM {DB_TABLE} WHERE LOWER(nombre_empresa) = ? "
            "OR (sitio_web IS NOT NULL AND LOWER(sitio_web) LIKE ?)",
            (nombre.lower(), f"%{web_domain}%"),
        )
    else:
        cur.execute(
            f"SELECT id FROM {DB_TABLE} WHERE LOWER(nombre_empresa) = ?",
            (nombre.lower(),),
        )
    row = cur.fetchone()

    if row:
        hotel_id = row[0]
        # UPDATE dinámico según la tabla
        if DB_TABLE == "contactos_hoteles":
            cur.execute(f"""
                UPDATE {DB_TABLE} SET
                    telefono  = CASE WHEN telefono  IS NULL OR telefono  = 'No disponible' THEN ? ELSE telefono  END,
                    sitio_web = CASE WHEN sitio_web IS NULL OR sitio_web = 'No disponible' THEN ? ELSE sitio_web END,
                    direccion = ?,
                    maps_link = COALESCE(maps_link, ?),
                    especialidades = COALESCE(especialidades, ?),
                    licencia_dian = COALESCE(licencia_dian, ?)
                WHERE id = ?
            """, (telefono, sitio_web, direccion, maps_link, especialidades, licencia_dian, hotel_id))
        else:
            cur.execute(f"""
                UPDATE {DB_TABLE} SET
                    telefono  = CASE WHEN telefono  IS NULL OR telefono  = 'No disponible' THEN ? ELSE telefono  END,
                    sitio_web = CASE WHEN sitio_web IS NULL OR sitio_web = 'No disponible' THEN ? ELSE sitio_web END
                WHERE id = ?
            """, (telefono, sitio_web, hotel_id))
        log.info(f"  🔄 Existente actualizado: {nombre}")
    else:
        # INSERT dinámico según la tabla
        if DB_TABLE == "contactos_hoteles":
            cur.execute(f"""
                INSERT OR IGNORE INTO {DB_TABLE}
                    (nombre_empresa, nicho, telefono, sitio_web, ciudad, pais, direccion, maps_link, especialidades, licencia_dian)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (nombre, nicho, telefono, sitio_web, ciudad, "Colombia", direccion, maps_link, especialidades, licencia_dian))
        else:
            cur.execute(f"""
                INSERT OR IGNORE INTO {DB_TABLE}
                    (nombre_empresa, nicho, telefono, sitio_web, ciudad, pais)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (nombre, nicho, telefono, sitio_web, ciudad, "Colombia"))
        hotel_id = cur.lastrowid
        log.info(f"  ✨ Nuevo: {nombre}")

    conn.commit()
    conn.close()
    return hotel_id


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


def crear_driver_con_reintentos(intentos: int = 3):
    """Crea un driver de Chrome, reintentando si falla. Devuelve None si no lo logra."""
    for intento in range(intentos):
        try:
            return get_driver()
        except Exception as e:
            log.warning(f"⚠️ Intento {intento + 1} fallido para crear driver: {e}")
            time.sleep(3)
    return None


# ─── FASE 1: GOOGLE MAPS (ETT OPTIMIZADO) ────────────────────────────────────
def maps_extract_detail(driver, maps_link: str) -> tuple:
    """Extrae (nombre, direccion, telefono, sitio_web) de una ficha de Maps."""
    try:
        driver.get(maps_link)
        WebDriverWait(driver, MAPS_DETAIL_WAIT).until(
            EC.presence_of_element_located((By.XPATH, '//h1[contains(@class,"DUwDvf")]'))
        )
    except TimeoutException as e:
        log.warning(f"  ⚠️ Ficha sin datos (timeout de elemento): {e}")
        return "No disponible", "No disponible", "No disponible", "No disponible"
    except WebDriverException as e:
        log.warning(f"  💥 Driver inestable (tab/renderer caído): {e}")
        return None, None, None, None

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
    """Carga Google Maps con la query y recolecta TODOS los links scrolleando agresivamente."""
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
    max_sin_nuevos = 20  # ← Scrollea mucho más agresivamente (antes era 10)
    iteracion     = 0

    while sin_nuevos < max_sin_nuevos:
        iteracion += 1
        for link in driver.find_elements(By.XPATH, '//a[contains(@href, "/maps/place/")]'):
            href = link.get_attribute("href")
            if href:
                encontrados.add(href.split("?")[0])

        # Scroll más agresivo: varias veces por iteración
        try:
            feed = driver.find_element(By.XPATH, '//div[@role="feed"]')
            # Triple scroll para ser más agresivo
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", feed)
            time.sleep(1.5)
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", feed)
            time.sleep(1.5)
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", feed)
            time.sleep(MAPS_SCROLL_WAIT)
        except Exception:
            time.sleep(2)
            break

        nuevos_en_iteracion = len(encontrados) - previo

        if nuevos_en_iteracion == 0:
            sin_nuevos += 1
            log.debug(f"  ⚠️ Iteración {iteracion}: SIN NUEVOS (intent {sin_nuevos}/{max_sin_nuevos})")
        else:
            sin_nuevos = 0
            log.info(f"  ✅ Iteración {iteracion}: +{nuevos_en_iteracion} nuevos → Total: {len(encontrados)}")

        previo = len(encontrados)
        print(f"  📍 Fichas detectadas: {len(encontrados)} (intent sin nuevos: {sin_nuevos}/{max_sin_nuevos})", end="\r")

    print()
    log.info(f"  ✅ SCRAPING COMPLETADO: {len(encontrados)} fichas en Maps")
    return encontrados


def fase_maps(driver, checkpoint: dict, ciudad: str):
    """Fase 1: recolectar ETTs de Google Maps."""
    links = maps_collect_links(driver, f"servicios temporales en {ciudad}, Colombia")

    # Excluir los ya procesados
    pendientes = links - checkpoint["maps_links_procesados"]
    log.info(f"  🆕 Links nuevos a procesar: {len(pendientes)}")

    stats = checkpoint["stats"]
    for idx, link in enumerate(pendientes, 1):
        log.info(f"\n[Maps {idx}/{len(pendientes)}] {link[:80]}")
        nombre, direccion, telefono, sitio_web = maps_extract_detail(driver, link)

        if nombre is None:
            # Driver inestable (crash/renderer caído): NO se marca como procesado,
            # se reintenta en la próxima corrida en vez de perderse para siempre.
            raise WebDriverException("Driver caído durante fase_maps")

        if nombre == "No disponible":
            checkpoint["maps_links_procesados"].add(link)
            save_checkpoint(checkpoint)
            continue

        hotel_id = upsert_negocio(nombre, NICHO, direccion, telefono, sitio_web, ciudad, link)
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


def is_ett(text: str) -> bool:
    """Detecta si el texto menciona características de ETT."""
    text_lower = text.lower()
    count = sum(1 for kw in ETT_KEYWORDS if kw in text_lower)
    return count >= 2


def extract_ett_info(html: str) -> dict:
    """Extrae especialidades y licencias de una página ETT."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ").lower()

    especialidades = set()
    for spec in ETT_SPECIALTIES:
        if spec in text:
            especialidades.add(spec)

    # Buscar número de DIAN o licencia
    licencia_match = re.search(r"nit[:\s]+(\d{5,})", text)
    dian_match = re.search(r"dian[:\s]+(\d{5,})", text)
    licencia_match_general = re.search(r"licencia.*?(\d{5,})", text)

    licencia = None
    if licencia_match:
        licencia = licencia_match.group(1)
    elif dian_match:
        licencia = dian_match.group(1)
    elif licencia_match_general:
        licencia = licencia_match_general.group(1)

    return {
        "especialidades": ", ".join(sorted(especialidades)) if especialidades else None,
        "licencia_dian": licencia,
    }


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


# ─── LINKEDIN (MEJORADO PARA ETT) ────────────────────────────────────────────
def scrape_linkedin_company(linkedin_url: str, driver) -> tuple:
    """
    Scrappea página de empresa en LinkedIn buscando:
    - Emails en sección "About"
    - Información de la empresa
    Retorna (emails, company_info_text)
    """
    try:
        driver.get(linkedin_url)
        time.sleep(random.uniform(3.0, 5.0))
    except TimeoutException:
        pass
    except Exception as e:
        log.warning(f"  ⚠️ Error accediendo LinkedIn: {e}")
        return [], ""

    # Rechazar cookies/popups
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
        # Scroll hasta sección "About"
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


def linkedin_search_ett(nombre_empresa: str, ciudad: str, driver, session: requests.Session) -> tuple:
    """
    Búsqueda agresiva en LinkedIn para encontrar la ETT.
    Prueba 3 queries diferentes:
    1. "empresa de servicios temporales 'nombre'"
    2. "'nombre' linkedin staffing"
    3. "ETT 'nombre' Colombia"

    Retorna (emails, urls_linkedin)
    """
    queries = [
        f'site:linkedin.com/company "{nombre_empresa}"',
        f'site:linkedin.com "{nombre_empresa}" staffing recursos humanos',
        f'site:linkedin.com "{nombre_empresa}" servicios temporales',
    ]

    all_emails = []
    all_linkedin_urls = []

    for q in queries:
        log.info(f"  🔍 LinkedIn DDG: {q[:60]}")
        result = ddg_search(q)

        for r in result:
            url = r.get("href", "")
            text = r.get("body", "") + " " + r.get("title", "")

            # Emails en snippet
            for e in extract_emails_from_text(text):
                if e not in all_emails:
                    all_emails.append(e)

            # URLs LinkedIn
            if url and "linkedin.com/company" in url:
                all_linkedin_urls.append(url)

        time.sleep(random.uniform(LINKEDIN_DELAY_MIN, LINKEDIN_DELAY_MAX))

    # Visitar LinkedIn URLs y scrappear
    for li_url in all_linkedin_urls[:2]:
        log.info(f"  📘 Visitando LinkedIn: {li_url[:70]}")
        li_emails, li_text = scrape_linkedin_company(li_url, driver)
        if li_emails:
            for e in li_emails:
                if e not in all_emails:
                    all_emails.append(e)

        # Detectar si es realmente ETT
        if is_ett(li_text):
            log.info(f"  ✅ Validado como ETT por LinkedIn")

        time.sleep(random.uniform(LINKEDIN_DELAY_MIN, LINKEDIN_DELAY_MAX))

    return all_emails, all_linkedin_urls


# ─── GOOGLE SEARCH (SELENIUM) ─────────────────────────────────────────────────
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
        log.warning("⚠️  Google CAPTCHA detectado. Resuélvelo en el navegador y presiona Enter.")
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


# ─── PIPELINE EMAIL MEJORADO PARA ETT ─────────────────────────────────────────
def _url_relevante(url: str, nombre_limpio: str) -> bool:
    domain = get_domain(url)
    RUIDO = (".gov.co", ".gov", "apple.com", "play.google", "answerscross",
             "cody", "significados", "wikipedia", "eldorado.aero")
    if any(r in domain for r in RUIDO):
        return False
    palabras = [p for p in nombre_limpio.lower().split() if len(p) > 3]
    if any(p in domain for p in palabras):
        return True
    if domain.endswith(".co") or ".com.co" in domain:
        return True
    return True


def find_email(hotel_id: int, nombre: str, ciudad: str | None,
               sitio_web: str | None, driver, session: requests.Session,
               cur, conn) -> dict:
    nombre_limpio = clean_name(nombre)
    ciudad_str    = ciudad or "Colombia"
    web_guardada  = False

    def save_email(email: str, web: str | None = None):
        if web:
            cur.execute(
                f"UPDATE {DB_TABLE} SET email = ?, sitio_web = ? WHERE id = ?",
                (email, web, hotel_id),
            )
        else:
            cur.execute(
                f"UPDATE {DB_TABLE} SET email = ? WHERE id = ?",
                (email, hotel_id),
            )
        conn.commit()

    def save_web(web: str):
        cur.execute(
            f"UPDATE {DB_TABLE} SET sitio_web = ? WHERE id = ?",
            (web, hotel_id),
        )
        conn.commit()

    def save_ett_info(info: dict):
        # Solo guardar especialidades/licencia si es BD local (contactos_hoteles)
        if DB_TABLE == "contactos_hoteles":
            cur.execute(f"""
                UPDATE {DB_TABLE}
                SET especialidades = ?, licencia_dian = ?
                WHERE id = ?
            """, (info.get("especialidades"), info.get("licencia_dian"), hotel_id))
            conn.commit()

    # ── (a) Scraping del sitio web ya conocido ────────────────────────────────
    if sitio_web and is_official_site(sitio_web):
        log.info(f"  🌐 (a) Web conocida: {sitio_web}")
        emails = scrape_site_deep(sitio_web, session)
        if emails:
            log.info(f"  ✅ Email en web: {emails[0]}")
            save_email(emails[0])
            # Extraer info ETT
            html = get_page(sitio_web, session)
            if html:
                ett_info = extract_ett_info(html)
                if ett_info["especialidades"] or ett_info["licencia_dian"]:
                    save_ett_info(ett_info)
            return {"found": "email", "value": emails[0], "via": "web"}

    # ── (b) DDG + LinkedIn + Google con énfasis en LinkedIn ─────────────────
    ddg_query = f'"{nombre_limpio}" {ciudad_str} email contacto'
    log.info(f"  🔍 (b) DDG: {ddg_query}")
    ddg_results = ddg_search(ddg_query)

    ddg_web_candidato = None
    for r in ddg_results:
        url  = r.get("href", "")
        text = r.get("body", "") + " " + r.get("title", "")
        for e in extract_emails_from_text(text):
            log.info(f"  ✅ Email snippet DDG: {e}")
            save_email(e)
            return {"found": "email", "value": e, "via": "ddg_snippet"}
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

    # ── (c) LINKEDIN — Búsqueda agresiva específica para ETT ─────────────────
    log.info(f"  📘 (c) LinkedIn (ETT optimizado)")
    li_emails, li_urls = linkedin_search_ett(nombre_limpio, ciudad_str, driver, session)

    if li_emails:
        log.info(f"  ✅ Email en LinkedIn: {li_emails[0]}")
        save_email(li_emails[0])
        return {"found": "email", "value": li_emails[0], "via": "linkedin"}

    # ── (d) Google Search Selenium - DESHABILITADO (usar solo DDG) ──────────────
    # Google causa "invalid session id" errors. Usando solo DDG para mayor estabilidad.
    if False:  # Google deshabilitado
        pass
        if emails:
            log.info(f"  ✅ Email en sitio: {emails[0]}")
            save_email(emails[0], url if not sitio_web else None)
            # Extraer info ETT
            html = get_page(url, session)
            if html:
                ett_info = extract_ett_info(html)
                if ett_info["especialidades"] or ett_info["licencia_dian"]:
                    save_ett_info(ett_info)
            return {"found": "email", "value": emails[0], "via": f"{search_via}_site"}
        time.sleep(random.uniform(SITE_DELAY_MIN, SITE_DELAY_MAX))
        visitados += 1

    # ── (e) Facebook ───────────────────────────────────────────────────────────
    for fb_url in g_fb[:2]:
        log.info(f"  📘 (e) Facebook: {fb_url[:70]}")
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
    """Fase 2: buscar emails solo para ETTs encontradas en Maps esta sesión."""
    ids_sesion = checkpoint.get("ids_para_email", [])
    if not ids_sesion:
        log.info("ℹ️  No hay IDs nuevos de Maps para buscar emails. Saltando fase Email.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    placeholders = ",".join("?" * len(ids_sesion))
    cur.execute(f"""
        SELECT id, nombre_empresa, ciudad, sitio_web
        FROM {DB_TABLE}
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
        log.info("✅ Todas las ETTs ya fueron procesadas para email.")
        conn.close()
        return

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
            # Verificar internet cada 10 registros
            if not check_internet(silent=True):
                log.error("❌ ¡CONEXIÓN PERDIDA! Deteniendo...")
                log.error("⚠️  Reconecta a WiFi e ejecuta de nuevo.")
                break

        time.sleep(random.uniform(ENTITY_DELAY_MIN, ENTITY_DELAY_MAX))

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

    # Parsear ciudades desde argumentos de línea de comandos
    ciudades = []
    for arg in sys.argv[1:]:
        if arg.startswith("--ciudad="):
            ciudades = [arg.split("=", 1)[1]]
        elif arg.startswith("--ciudades="):
            ciudades = [c.strip() for c in arg.split("=", 1)[1].split(",")]

    init_db()
    checkpoint = load_checkpoint()
    _cp_ref    = checkpoint

    log.info(f"📁 Usando BD: {DB_PATH}")
    log.info(f"📊 Tabla: {DB_TABLE}")

    # Verificar conexión a internet
    print("\n🌐 Verificando conexión a internet...")
    if not check_internet():
        print("\n❌ ERROR: No hay conexión a internet.")
        print("⚠️  Este script requiere conexión WiFi/Internet para funcionar.")
        print("   Conecta a WiFi e intenta de nuevo.")
        return

    # Si no especifica ciudades desde argumentos y no es solo_email, pedir interactivamente
    if not ciudades and not solo_email:
        print("\n" + "="*60)
        print("  PROSPECTOR ETT — Google Maps + Búsqueda de Emails")
        print("="*60)
        print("\nOpciones:")
        print("  1. Una ciudad específica")
        print("  2. Múltiples ciudades (Bogotá, Medellín, Cali, Barranquilla, Cartagena, Santa Marta)")
        opcion = input("\nElige opción (1 o 2) o escribe ciudades separadas por comas: ").strip()

        if opcion == "2":
            ciudades = ["Bogotá", "Medellín", "Cali", "Barranquilla", "Cartagena", "Santa Marta"]
        elif opcion == "1" or not opcion:
            ciudad_input = input("¿Qué ciudad? ").strip()
            if not ciudad_input:
                print("❌ Ciudad es obligatoria.")
                return
            ciudades = [ciudad_input]
        else:
            ciudades = [c.strip() for c in opcion.split(",") if c.strip()]

        if not ciudades:
            print("❌ No hay ciudades para buscar.")
            return

    stats_ciudades = {}

    driver = crear_driver_con_reintentos()
    if not driver:
        log.error("❌ No se pudo crear el driver después de 3 intentos.")
        return

    try:
        driver_ok = True
        if not solo_email and ciudades:
            log.info("\n" + "="*60)
            log.info("FASE 1 — GOOGLE MAPS")
            log.info("="*60)
            for i, ciudad in enumerate(ciudades, 1):
                if not driver_ok:
                    log.error(f"  ⏭️  Saltando {ciudad}: sin driver disponible.")
                    continue
                print(f"\n📍 [{i}/{len(ciudades)}] Buscando en {ciudad}...")
                stats_antes = checkpoint["stats"]["nuevos"]
                try:
                    fase_maps(driver, checkpoint, ciudad)
                except WebDriverException as e:
                    log.warning(f"  💥 {ciudad}: driver caído ({e}). Recreando sesión de Chrome...")
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = crear_driver_con_reintentos()
                    if not driver:
                        log.error("❌ No se pudo recrear el driver. Se detiene la Fase 1.")
                        driver_ok = False
                    else:
                        try:
                            fase_maps(driver, checkpoint, ciudad)
                        except WebDriverException as e2:
                            log.warning(f"  💥 {ciudad}: falló de nuevo tras recrear driver ({e2}). Se salta esta ciudad.")
                stats_despues = checkpoint["stats"]["nuevos"]
                nuevos_ciudad = stats_despues - stats_antes
                stats_ciudades[ciudad] = nuevos_ciudad
                log.info(f"  ✅ {ciudad}: +{nuevos_ciudad} ETTs nuevas")
                time.sleep(5)  # Pausa entre ciudades

        if driver_ok:
            log.info("\n" + "="*60)
            log.info("FASE 2 — BÚSQUEDA DE EMAILS")
            log.info("="*60)
            try:
                fase_email(driver, checkpoint)
            except WebDriverException as e:
                log.warning(f"  💥 Fase email: driver caído ({e}). Recreando sesión de Chrome...")
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = crear_driver_con_reintentos()
                if driver:
                    try:
                        fase_email(driver, checkpoint)
                    except WebDriverException as e2:
                        log.warning(f"  💥 Fase email falló de nuevo tras recrear driver ({e2}).")
                else:
                    log.error("❌ No se pudo recrear el driver para la Fase 2.")

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        log.info("\n🏁 Proceso finalizado.")

    s = checkpoint["stats"]
    print(f"\n{'='*60}")
    print(f"RESUMEN FINAL")
    print(f"{'='*60}")
    if not solo_email:
        print(f"Total ETTs nuevas : {s['nuevos']}")
        if stats_ciudades:
            print("\nPor ciudad:")
            for ciudad, cantidad in stats_ciudades.items():
                print(f"  • {ciudad}: +{cantidad}")
    print(f"Emails encontrados: {s['emails']}")
    print(f"Sin resultado     : {s['nada']}")
    print(f"{'='*60}")
    print(f"📋 Log completo: {LOG_FILE}")


if __name__ == "__main__":
    main()
