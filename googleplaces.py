"""
grupo_b_google_search.py
========================
Para hoteles que SOLO tienen nombre (y a veces teléfono), sin web ni maps_link.
Busca en DuckDuckGo "<nombre hotel> <ciudad> email contacto" y scrappea los
primeros resultados intentando encontrar el sitio web oficial o el email.

CHECKPOINT AUTOMÁTICO:
    Si paras el script (Ctrl+C) o se apaga el PC, al volver a correrlo
    retoma exactamente desde donde quedó. No reprocesa hoteles ya revisados.
    El progreso se guarda en: checkpoint_grupo_b.json

INSTALACIÓN:
    pip install requests beautifulsoup4 lxml duckduckgo-search

USO:
    python grupo_b_google_search.py

    Para reiniciar desde cero (ignorar checkpoint):
    python grupo_b_google_search.py --reset
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

import requests
from bs4 import BeautifulSoup

try:
    from duckduckgo_search import DDGS
    USE_DDG = True
except ImportError:
    USE_DDG = False

# ─────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────
DB_PATH         = "hoteles_colombia.db"
LOG_FILE        = "grupo_b_search.log"
REPORT_FILE     = "reporte_grupo_b.txt"
CHECKPOINT_FILE = "checkpoint_grupo_b.json"
DELAY_MIN       = 3.0
DELAY_MAX       = 6.0
TIMEOUT         = 10
MAX_RESULTS     = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CO,es;q=0.9",
}

SKIP_DOMAINS = [
    "booking.com", "tripadvisor.com", "airbnb.com", "expedia.com",
    "hotels.com", "despegar.com", "kayak.com", "trivago.com",
    "google.com", "maps.google", "facebook.com", "instagram.com",
    "twitter.com", "youtube.com", "wikipedia.org", "linkedin.com",
    "yelp.com", "foursquare.com", "waze.com", "cotelco.org",
    "ayenda.com", "decameron.com",
]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
FAKE_EMAIL_RE = re.compile(
    r"(ejemplo|example|youremail|tuemail|noreply|no-reply|donotreply|"
    r"test@|sentry|wixpress|squarespace|wordpress|@2x\.|\.png|\.jpg)",
    re.IGNORECASE,
)

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
# CHECKPOINT
# ─────────────────────────────────────────────
def load_checkpoint() -> dict:
    """
    Carga el checkpoint del archivo JSON.
    Devuelve un dict con:
        - last_id: último hotel_id procesado exitosamente
        - procesados: set de IDs ya procesados
        - stats: contadores acumulados
    """
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Convertir lista a set (JSON no guarda sets)
            data["procesados"] = set(data.get("procesados", []))
            log.info(
                f"♻️  Checkpoint encontrado: {len(data['procesados'])} hoteles ya procesados. "
                f"Retomando desde donde quedó..."
            )
            return data
        except Exception as e:
            log.warning(f"Error leyendo checkpoint, empezando desde cero: {e}")

    return {
        "last_id": None,
        "procesados": set(),
        "stats": {"emails": 0, "webs": 0, "nada": 0},
    }


def save_checkpoint(checkpoint: dict):
    """Guarda el checkpoint en disco. Se llama después de cada hotel."""
    data = dict(checkpoint)
    data["procesados"] = list(checkpoint["procesados"])  # set → list para JSON
    try:
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"No se pudo guardar checkpoint: {e}")


def clear_checkpoint():
    """Elimina el checkpoint para empezar desde cero."""
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        log.info("🗑️  Checkpoint eliminado. Empezando desde cero.")


# ─────────────────────────────────────────────
# SEÑAL DE INTERRUPCIÓN (Ctrl+C o apagado)
# ─────────────────────────────────────────────
_checkpoint_ref = None  # referencia global para guardar en SIGINT

def handle_interrupt(sig, frame):
    log.info("\n⚠️  Interrupción detectada. Guardando checkpoint...")
    if _checkpoint_ref is not None:
        save_checkpoint(_checkpoint_ref)
    log.info(f"✅ Progreso guardado en {CHECKPOINT_FILE}. Puedes cerrar el PC.")
    log.info("   Al volver a correr el script retomará desde donde quedó.")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_interrupt)
signal.signal(signal.SIGTERM, handle_interrupt)


# ─────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────
def is_valid_email(email: str) -> bool:
    if FAKE_EMAIL_RE.search(email):
        return False
    ext = email.rsplit(".", 1)[-1]
    return len(ext) <= 6


def is_official_site(url: str) -> bool:
    from urllib.parse import urlparse
    netloc = urlparse(url).netloc.lower().replace("www.", "")
    return not any(skip in netloc for skip in SKIP_DOMAINS)


def search_ddg(query: str) -> list:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=MAX_RESULTS, region="co-es"))
            return results
    except Exception as e:
        log.warning(f"DDG search error: {e}")
        return []


def get_page(url: str, session: requests.Session) -> str | None:
    try:
        resp = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if resp.status_code == 200:
            return resp.text
    except Exception:
        try:
            resp = session.get(
                url, headers=HEADERS, timeout=TIMEOUT,
                allow_redirects=True, verify=False
            )
            if resp.status_code == 200:
                return resp.text
        except Exception:
            pass
    return None


def extract_emails_from_html(html: str) -> list:
    soup = BeautifulSoup(html, "lxml")
    emails = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        if href.startswith("mailto:"):
            email = href[7:].split("?")[0].strip().lower()
            if EMAIL_RE.match(email) and is_valid_email(email):
                emails.add(email)
    text = soup.get_text(" ")
    for match in EMAIL_RE.findall(text):
        email = match.strip().lower()
        if is_valid_email(email):
            emails.add(email)
    return list(emails)


def find_email_in_snippet(text: str) -> list:
    found = []
    for match in EMAIL_RE.findall(text):
        email = match.strip().lower()
        if is_valid_email(email):
            found.append(email)
    return found


# ─────────────────────────────────────────────
# PROCESAR UN HOTEL
# ─────────────────────────────────────────────
def process_hotel(hotel_id, nombre, ciudad, telefono, session, cur, conn):
    ciudad_str = ciudad or "Colombia"

    queries = [
        f"{nombre} {ciudad_str} hotel email contacto",
        f"{nombre} {ciudad_str} hotel sitio web",
    ]

    for query in queries:
        log.info(f"  🔍 {query}")
        results = search_ddg(query)
        time.sleep(random.uniform(1.5, 2.5))

        for result in results:
            url   = result.get("href", "")
            body  = result.get("body", "")
            title = result.get("title", "")

            # 1. Email directo en el snippet
            snippet_emails = find_email_in_snippet(body + " " + title)
            if snippet_emails:
                email = snippet_emails[0]
                log.info(f"  ✅ Email en snippet: {email}")
                cur.execute(
                    "UPDATE contactos_hoteles SET email = ? WHERE id = ?",
                    (email, hotel_id)
                )
                conn.commit()
                return {"found": "email", "value": email}

            # 2. Sitio oficial → visitar y buscar email
            if url and is_official_site(url):
                log.info(f"  🌐 Visitando: {url}")
                html = get_page(url, session)
                if html:
                    emails = extract_emails_from_html(html)
                    if emails:
                        email = emails[0]
                        log.info(f"  ✅ Email en web: {email}")
                        cur.execute(
                            "UPDATE contactos_hoteles SET email = ?, sitio_web = ? WHERE id = ?",
                            (email, url, hotel_id)
                        )
                        conn.commit()
                        return {"found": "email", "value": email}

                    # Sin email pero guardar la web
                    cur.execute(
                        "UPDATE contactos_hoteles SET sitio_web = ? WHERE id = ?",
                        (url, hotel_id)
                    )
                    conn.commit()
                    log.info(f"  📋 Web guardada sin email: {url}")
                    return {"found": "website_only", "value": url}

                time.sleep(random.uniform(0.8, 1.5))

    return {"found": "nothing"}


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    global _checkpoint_ref

    if not USE_DDG:
        print("\n❌ Falta instalar: pip install duckduckgo-search")
        return

    # ¿Reinicio forzado?
    if "--reset" in sys.argv:
        clear_checkpoint()

    checkpoint = load_checkpoint()
    _checkpoint_ref = checkpoint  # para que SIGINT lo pueda guardar

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, nombre_empresa, ciudad, telefono
        FROM contactos_hoteles
        WHERE (email IS NULL OR email = '')
          AND (maps_link IS NULL OR maps_link = '')
          AND (
            sitio_web IS NULL OR sitio_web = '' OR
            sitio_web LIKE '%No disponible%'
          )
        ORDER BY id
    """)
    hoteles = cur.fetchall()
    total = len(hoteles)

    # Filtrar los que ya están en el checkpoint
    pendientes = [(hid, n, c, t) for hid, n, c, t in hoteles if hid not in checkpoint["procesados"]]
    ya_hechos  = total - len(pendientes)

    log.info(f"Total hoteles Grupo B : {total}")
    log.info(f"Ya procesados         : {ya_hechos}")
    log.info(f"Pendientes            : {len(pendientes)}")

    if not pendientes:
        log.info("✅ Todos los hoteles del Grupo B ya fueron procesados.")
        conn.close()
        return

    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session = requests.Session()

    reporte_lines = []
    stats = checkpoint["stats"]

    for i, (hotel_id, nombre, ciudad, telefono) in enumerate(pendientes, 1):
        num_global = ya_hechos + i
        log.info(f"\n[{num_global}/{total}] {nombre} ({ciudad or 'sin ciudad'})")

        result = process_hotel(hotel_id, nombre, ciudad, telefono, session, cur, conn)

        # Actualizar stats y checkpoint
        if result["found"] == "email":
            stats["emails"] += 1
            reporte_lines.append(f"✅ EMAIL | {nombre} | {result['value']}")
        elif result["found"] == "website_only":
            stats["webs"] += 1
            reporte_lines.append(f"🌐 WEB   | {nombre} | {result['value']}")
        else:
            stats["nada"] += 1
            reporte_lines.append(f"❌ NADA  | {nombre} | {ciudad or ''}")

        checkpoint["procesados"].add(hotel_id)
        checkpoint["last_id"] = hotel_id
        save_checkpoint(checkpoint)  # ← guarda después de CADA hotel

        # Mostrar progreso cada 10 hoteles
        if i % 10 == 0:
            log.info(
                f"  📊 Progreso: {num_global}/{total} | "
                f"Emails: {stats['emails']} | "
                f"Solo web: {stats['webs']} | "
                f"Sin resultado: {stats['nada']}"
            )

        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    conn.close()

    # Resumen final
    resumen = (
        f"\n{'='*60}\n"
        f"RESUMEN FINAL GRUPO B\n"
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
        f.write("\n".join(reporte_lines))

    # Borrar checkpoint al terminar exitosamente
    clear_checkpoint()
    print(f"\n✅ Completado. Reporte en: {REPORT_FILE}")
    print(f"📋 Log en: {LOG_FILE}")

if __name__ == "__main__":
    main()