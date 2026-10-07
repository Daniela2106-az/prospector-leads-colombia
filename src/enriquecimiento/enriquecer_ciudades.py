"""
enrich_cities.py
================
Script para enriquecer ciudades/país faltantes usando:
1. Nominatim (OpenStreetMap) - busca por nombre empresa
2. Google Maps scraping - fallback

USO:
    python enrich_cities.py                                  # completa los 5 nichos
    python enrich_cities.py --nicho='Retail / Comercio'      # solo un nicho
"""

from src.config import ruta_datos
import sqlite3
import json
import time
import random
import logging
import os
from urllib.parse import quote_plus

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

from playwright.sync_api import sync_playwright, Page
from bs4 import BeautifulSoup

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
DB_PATH = ruta_datos("base_marketing.db")
CHECKPOINT_FILE = ruta_datos("checkpoint_cities.json")
LOG_FILE = ruta_datos("enrich_cities.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─── CIUDADES COLOMBIANAS ─────────────────────────────────────────────────────
CIUDADES_COLOMBIA = [
    "Bogotá", "Medellín", "Cali", "Barranquilla", "Cartagena", "Cúcuta",
    "Bucaramanga", "Manizales", "Pereira", "Armenia", "Ibagué", "Villavicencio",
    "Santa Marta", "Quibdó", "Pasto", "Popayán", "Tunja", "Valledupar",
    "Montería", "Sincelejo", "Neiva", "Palmira", "Floridablanca", "Giradot",
    "Duitama", "Zipaquirá", "Sogamoso", "Envigado", "Sabaneta", "Mosquera",
    "Soacha", "Chía", "Fusagasugá", "Girardot", "Acacías", "Puerto López",
    "San Gil", "Socorro", "Barrancabermeja", "Yopal", "Arauca", "Leticia",
    "Itagüí", "Bello", "Dosquebradas", "Cartago", "Anserma", "Neira"
]

def extract_city_from_address(direccion: str) -> str | None:
    """Extrae ciudad de la dirección buscando en la lista de ciudades colombianas.

    Ejemplo: "Cl. 66, Barrios Unidos, Bogotá" → "Bogotá"
    """
    for ciudad in CIUDADES_COLOMBIA:
        if ciudad.lower() in direccion.lower():
            return ciudad
    return None


def generate_name_variations(nombre_empresa: str) -> list:
    """Genera variaciones del nombre para búsquedas más flexibles en general.

    Maneja automáticamente:
    - Mayúsculas/minúsculas
    - Abreviaturas jurídicas (S.A., S.A.S, LTDA, LIMITADA, CIA, etc)
    - Caracteres especiales (puntos, guiones, "&", etc)
    - Palabras redundantes
    - Combinaciones de palabras

    Usa regex flexible para encontrar empresas aunque el nombre sea ligeramente diferente.
    """
    import re

    variaciones = [nombre_empresa]  # Original

    # 1. Remover abreviaturas jurídicas y palabras comunes redundantes
    abreviaturas = [
        r'\s*S\.A\.S\s*', r'\s*S\.A\.\s*', r'\s*S\.L\.\s*',
        r'\s*LTDA\.?\s*', r'\s*LIMITADA\s*', r'\s*CIA\.?\s*', r'\s*CÍA\.?\s*',
        r'\s*CORP\.?\s*', r'\s*CORPORATION\s*', r'\s*INC\.?\s*', r'\s*LLC\s*',
        r'\s*CO\.?\s*', r'\s*COMPANY\s*',
        r'\s*&\s*', r'\s*Y\s*', r'\s*AND\s*', r'\s*E\s*'
    ]

    nombre_sin_abrev = nombre_empresa
    for abrev in abreviaturas:
        nombre_sin_abrev = re.sub(abrev, ' ', nombre_sin_abrev, flags=re.IGNORECASE)
    nombre_sin_abrev = re.sub(r'\s+', ' ', nombre_sin_abrev).strip()

    if nombre_sin_abrev and nombre_sin_abrev != nombre_empresa:
        variaciones.append(nombre_sin_abrev)

    # 2. Remover caracteres especiales (puntos, guiones, etc)
    nombre_sin_especiales = re.sub(r'[.\-_()]', '', nombre_empresa)
    nombre_sin_especiales = re.sub(r'\s+', ' ', nombre_sin_especiales).strip()
    if nombre_sin_especiales and nombre_sin_especiales != nombre_empresa:
        variaciones.append(nombre_sin_especiales)

    # 3. Extraer palabras principales (4+ caracteres)
    palabras = [p for p in nombre_sin_abrev.split() if len(p.strip()) >= 3]

    if palabras:
        # Última palabra (generalmente el apellido/nombre clave)
        if len(palabras[-1]) > 2:
            variaciones.append(palabras[-1])

        # Últimas 2 palabras
        if len(palabras) >= 2:
            dos_palabras = " ".join(palabras[-2:])
            if dos_palabras != nombre_sin_abrev and len(dos_palabras) > 3:
                variaciones.append(dos_palabras)

        # Últimas 3 palabras
        if len(palabras) >= 3:
            tres_palabras = " ".join(palabras[-3:])
            if tres_palabras != nombre_sin_abrev and len(tres_palabras) > 3:
                variaciones.append(tres_palabras)

    # 4. Minúsculas
    variaciones = [v.lower() for v in variaciones]

    # Remover duplicados manteniendo orden
    vistas = set()
    resultado = []
    for v in variaciones:
        if v.strip() and v.strip() not in vistas:
            vistas.add(v.strip())
            resultado.append(v.strip())

    return resultado

# ─── NOMINATIM (GRATIS) ───────────────────────────────────────────────────────
def get_city_nominatim(nombre_empresa: str, pais: str = "Colombia") -> tuple[str, str, str] | None:
    """Obtiene ciudad, país y dirección usando Nominatim HTTP API.

    Estrategia GENERAL:
    1. UNA búsqueda con el nombre original
    2. Si no hay resultado, UNA búsqueda con nombre sin abreviaturas
    3. Extrae ciudad de la dirección

    Retorna: (ciudad, país, dirección)
    """
    try:
        import requests
        import ssl
        import urllib3

        # Desactivar SSL verification warnings
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # Usar requests con SSL desactivado (Nominatim es confiable)
        for nombre_busqueda in [nombre_empresa]:
            query = f"{nombre_busqueda}, {pais}"
            try:
                response = requests.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": query, "format": "json", "limit": 1},
                    timeout=10,
                    verify=False
                )

                if response.status_code == 200:
                    data = response.json()
                    if data:
                        result = data[0]
                        direccion = result.get("display_name", "")
                        ciudad = extract_city_from_address(direccion)

                        if ciudad:
                            return ciudad, "Colombia", direccion
            except Exception:
                continue

        # Si la primera búsqueda falla, intentar con variaciones
        variaciones = generate_name_variations(nombre_empresa)
        for nombre_busqueda in variaciones:
            if nombre_busqueda == nombre_empresa:
                continue

            query = f"{nombre_busqueda}, {pais}"
            try:
                response = requests.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": query, "format": "json", "limit": 1},
                    timeout=10,
                    verify=False
                )

                if response.status_code == 200:
                    data = response.json()
                    if data:
                        result = data[0]
                        direccion = result.get("display_name", "")
                        ciudad = extract_city_from_address(direccion)

                        if ciudad:
                            return ciudad, "Colombia", direccion
            except Exception:
                continue

        return None
    except Exception as e:
        return None


# ─── GOOGLE MAPS SCRAPING ─────────────────────────────────────────────────────
def normalize_name(nombre: str) -> str:
    """Normaliza nombre: minúsculas, quita caracteres especiales, mantiene espacios.

    "AGENCIA CAUCHO SOL DE LA COSTA LIMITADA" → "agencia caucho sol de la costa limitada"
    Separa palabras para comparación más robusta.
    """
    import re
    # Minúsculas
    normalizado = nombre.lower()
    # Quita caracteres especiales (puntos, dashes, etc) pero mantiene espacios
    normalizado = re.sub(r'[^a-záéíóúñ0-9\s]', '', normalizado)
    # Normaliza espacios múltiples
    normalizado = ' '.join(normalizado.split())
    return normalizado


def find_matching_result(nombre_empresa: str, resultados: list) -> tuple[str, str, str] | None:
    """Busca un resultado que coincida con el nombre de la empresa.

    Estrategia GENERAL (no casos específicos):
    Compara usando Levenshtein distance (fuzzy matching).
    Si el nombre está PARCIALMENTE presente o es similar (>70% coincidencia),
    es un match.

    Retorna: (ciudad, país, dirección) o None
    """
    from difflib import SequenceMatcher

    # Normalizar nombre empresa (minúsculas, sin caracteres especiales)
    nombre_norm = normalize_name(nombre_empresa)

    for resultado in resultados:
        resultado_norm = normalize_name(resultado)

        # Calcular similitud usando SequenceMatcher
        # Esto maneja "CAUCHO SOL" vs "CAUCHOSOL" automáticamente
        # porque ambos después de normalizar contienen los mismos caracteres
        similitud = SequenceMatcher(None, nombre_norm, resultado_norm).ratio()

        # Si >60% de similitud (flexible para variaciones), es probable match
        if similitud > 0.6:
            ciudad = extract_city_from_address(resultado)
            if ciudad:
                return ciudad, "Colombia", resultado

    return None


def get_city_google_maps(nombre_empresa: str, page) -> tuple[str, str, str] | None:
    """Obtiene ciudad, país y dirección scrapeando Google Maps con Playwright.

    Estrategia: Usar Playwright para mejor stealth contra bot detection.

    Retorna: (ciudad, país, dirección)
    """
    try:
        if not page:
            return None

        query = f"{nombre_empresa} Colombia"
        url = f"https://www.google.com/maps/search/{quote_plus(query)}"

        page.goto(url, wait_until="networkidle", timeout=15000)
        time.sleep(15)  # SUPER LENTO: Esperar 15 segundos a que JavaScript renderice

        resultados = []

        # Extraer resultados (Playwright)
        try:
            # Esperar a que aparezcan elementos de resultado
            page.wait_for_selector(".Io6YTe", timeout=15000)

            # Extraer todos los elementos con la clase de resultado
            elementos = page.locator(".Io6YTe").all()

            for elem in elementos:
                text = elem.text_content().strip()
                # FILTRAR: Rechazar UI genérico
                if (text and len(text) > 10
                    and "Arrastra para cambiar" not in text
                    and "haz clic" not in text.lower()):
                    resultados.append(text)
        except Exception:
            pass

        # Si no hay resultados válidos, Google probablemente bloqueó
        if not resultados:
            return None

        # Buscar match dentro de los resultados válidos
        match = find_matching_result(nombre_empresa, resultados)
        if match:
            return match

        return None
    except Exception as e:
        return None


# ─── PLAYWRIGHT BROWSER ───────────────────────────────────────────────────────
def get_page():
    """Crea una página de Playwright con stealth mode."""
    global _browser_context, _browser

    try:
        from playwright.sync_api import sync_playwright

        _pw = sync_playwright().start()
        _browser = _pw.chromium.launch(headless=True)
        _browser_context = _browser.new_context()
        page = _browser_context.new_page()
        page.set_default_timeout(15000)
        return page
    except Exception as e:
        log.error(f"Error creating Playwright page: {e}")
        return None


def close_browser():
    """Cierra el browser de Playwright."""
    global _browser_context, _browser

    try:
        if _browser_context:
            _browser_context.close()
        if _browser:
            _browser.close()
    except:
        pass


_browser = None
_browser_context = None


# ─── CHECKPOINT ───────────────────────────────────────────────────────────────
def load_checkpoint():
    """Carga checkpoint.

    'encontrados': empresas CON INFORMACIÓN GUARDADA (no se reintentan)
    'buscadas': empresas QUE SE INTENTARON BUSCAR pero sin resultado
                (se reintentan cuando el script relanza con lógica mejorada)
    """
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, 'r') as f:
            return json.load(f)
    return {'encontrados': [], 'buscadas': []}


def save_checkpoint(encontrados, buscadas):
    """Guarda checkpoint.

    encontrados: empresas donde SÍ se encontró y guardó información
    buscadas: empresas donde se intentó buscar pero no se encontró
    """
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump({
            'encontrados': list(encontrados),
            'buscadas': list(buscadas)
        }, f, indent=2)


# ─── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Enriquecer ciudades faltantes")
    parser.add_argument("--nicho", type=str, default=None, help="Nicho específico")
    parser.add_argument("--offset", type=int, default=0, help="Offset (registros a saltar)")
    parser.add_argument("--limit", type=int, default=None, help="Máximo registros")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    nichos = [
        'Retail / Comercio',
        'Salud y Bienestar',
        'Industrial / Manufactura',
        'Hotelería',
        'Restaurantes y Bares'
    ]

    if args.nicho:
        nichos = [args.nicho]

    checkpoint = load_checkpoint()
    encontrados = set(checkpoint.get('encontrados', []))  # Con info guardada
    buscadas = set(checkpoint.get('buscadas', []))        # Intentadas sin resultado

    page = None
    try:
        page = get_page()

        for nicho in nichos:
            log.info(f"\n🔹 {nicho}")

            # Obtener empresas SIN CIUDAD (excepto las ya encontradas)
            cur.execute(f"""
                SELECT id, nombre_empresa, ciudad, pais FROM contactos_marketing
                WHERE nicho = ? AND email IS NOT NULL AND email != ''
                AND (ciudad IS NULL OR ciudad = '')
                LIMIT ? OFFSET ?
            """, (nicho, args.limit or 999999, args.offset))

            empresas = cur.fetchall()
            log.info(f"   Total SIN ciudad: {len(empresas)}")

            for i, (empresa_id, nombre, ciudad_actual, pais_actual) in enumerate(empresas, 1):
                # Solo saltar si YA ENCONTRAMOS información (no si solo la buscamos)
                if empresa_id in encontrados:
                    continue

                log.info(f"[{i}/{len(empresas)}] {nombre[:50]}")

                # 1. Intentar con Nominatim
                resultado = get_city_nominatim(nombre)

                if not resultado:
                    log.info(f"  📍 Nominatim sin resultado, intentando Google Maps...")
                    time.sleep(10)  # SUPER LENTO: 10 segundos antes de Google Maps
                    # 2. Fallback: Google Maps scraping con Playwright
                    resultado = get_city_google_maps(nombre, page)

                if resultado:
                    ciudad, pais_encontrado, direccion = resultado

                    # Determinar valores finales
                    ciudad_final = ciudad if (ciudad and ciudad.strip()) else ciudad_actual
                    pais_final = pais_encontrado if (pais_encontrado and pais_encontrado.strip()) else pais_actual

                    # Log detallado
                    log.info(f"  ✅ Ciudad: {ciudad_final}, País: {pais_final}")
                    if direccion:
                        log.info(f"     Dirección: {direccion[:60]}")

                    # Guardar: ciudad, país Y dirección
                    cur.execute(
                        "UPDATE contactos_marketing SET ciudad = ?, pais = ?, direccion = ? WHERE id = ?",
                        (ciudad_final, pais_final, direccion, empresa_id)
                    )
                    conn.commit()

                    # Guardar en "encontrados" (con información)
                    encontrados.add(empresa_id)
                else:
                    log.info(f"  ❌ No encontrada (será reintentada con lógica mejorada)")
                    # Guardar en "buscadas" (intentada sin resultado)
                    buscadas.add(empresa_id)

                # Guardar checkpoint cada 20 registros
                if i % 20 == 0:
                    save_checkpoint(encontrados, buscadas)
                    log.info(f"  💾 Checkpoint guardado")

                # Rate limit SUPER LENTO para evitar detección
                time.sleep(random.uniform(10, 20))

            # ─── SEGUNDA PASADA: CON CIUDAD, SIN PAÍS ──────────────────────────────
            log.info(f"\n   🔄 Segunda pasada: Asignando país a ciudades sin país...")

            cur.execute(f"""
                SELECT id, nombre_empresa, ciudad, pais FROM contactos_marketing
                WHERE nicho = ? AND email IS NOT NULL AND email != ''
                AND (ciudad IS NOT NULL AND ciudad != '')
                AND (pais IS NULL OR pais = '')
                LIMIT ?
            """, (nicho, args.limit or 999999))

            empresas_sin_pais = cur.fetchall()
            log.info(f"   Total CON ciudad, SIN país: {len(empresas_sin_pais)}")

            for i, (empresa_id, nombre, ciudad, pais_actual) in enumerate(empresas_sin_pais, 1):
                if empresa_id in encontrados:
                    continue

                # Verificar si ciudad está en lista de colombianas
                es_ciudad_colombia = any(c.lower() == ciudad.lower() for c in CIUDADES_COLOMBIA)

                if es_ciudad_colombia:
                    log.info(f"[{i}/{len(empresas_sin_pais)}] {nombre[:50]} | {ciudad} → Colombia ✓")

                    # Asignar país = Colombia
                    cur.execute(
                        "UPDATE contactos_marketing SET pais = ? WHERE id = ?",
                        ("Colombia", empresa_id)
                    )
                    conn.commit()
                    encontrados.add(empresa_id)
                else:
                    log.info(f"[{i}/{len(empresas_sin_pais)}] {nombre[:50]} | {ciudad} → País desconocido")
                    # País queda vacío (no es Colombia)
                    encontrados.add(empresa_id)

                # Guardar checkpoint cada 20 registros
                if i % 20 == 0:
                    save_checkpoint(encontrados, buscadas)

                time.sleep(random.uniform(0.2, 0.5))

    finally:
        close_browser()
        save_checkpoint(encontrados, buscadas)
        log.info(f"\n✅ Completado. Checkpoint guardado.")
        conn.close()


if __name__ == "__main__":
    main()
