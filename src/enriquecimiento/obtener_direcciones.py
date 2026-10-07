"""
get_addresses.py
================
Script para obtener direcciones de empresas usando:
1. Nominatim (OpenStreetMap) - GRATIS, sin API key
2. Google Maps scraping - FALLBACK

USO:
    python get_addresses.py                                  # completa los 5 nichos
    python get_addresses.py --nicho='Retail / Comercio'      # solo un nicho
    python get_addresses.py --limit 100                      # máximo 100 empresas
"""

from src.config import ruta_datos
import sqlite3
import json
import time
import random
import logging
import os
from datetime import datetime
from urllib.parse import quote_plus

import requests
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
DB_PATH = ruta_datos("base_marketing.db")
CHECKPOINT_FILE = ruta_datos("checkpoint_addresses.json")
LOG_FILE = ruta_datos("get_addresses.log")

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

def extract_address_without_city(direccion: str, ciudad: str) -> str:
    """Extrae la dirección sin la ciudad.

    Ejemplo: "Cl. 66, Barrios Unidos, Bogotá" + ciudad="Bogotá"
             → "Cl. 66, Barrios Unidos"
    """
    # Quitar ciudad de la dirección
    # Buscar la ciudad en la dirección y quitar la última ocurrencia
    partes = [p.strip() for p in direccion.split(",")]

    # Quitar la parte que coincide con la ciudad
    partes_filtradas = [p for p in partes if p.lower() != ciudad.lower()]

    return ", ".join(partes_filtradas).strip()

# ─── NOMINATIM (GRATIS) ───────────────────────────────────────────────────────
def get_address_nominatim(nombre_empresa: str, ciudad: str, pais: str = "Colombia") -> str | None:
    """Obtiene dirección usando Nominatim (OpenStreetMap).

    Con ciudad podemos ser más precisos en la búsqueda.
    """
    try:
        import ssl
        ssl._create_default_https_context = ssl._create_unverified_context

        geolocator = Nominatim(user_agent="get_addresses_script", timeout=10)
        query = f"{nombre_empresa}, {ciudad}, {pais}"

        location = geolocator.geocode(query)
        if location:
            return location.address
        return None
    except GeocoderTimedOut:
        return None
    except Exception as e:
        return None


# ─── GOOGLE MAPS SCRAPING (FALLBACK) ──────────────────────────────────────────
def get_address_google_maps_scrape(nombre_empresa: str, ciudad: str, driver) -> str | None:
    """Obtiene dirección scrapeando Google Maps.

    Con ciudad la búsqueda es más precisa.
    Retorna: dirección completa (Calle #, Barrio, Ciudad)
    """
    try:
        query = f"{nombre_empresa} {ciudad} Colombia"
        url = f"https://www.google.com/maps/search/{quote_plus(query)}"

        driver.get(url)
        time.sleep(2)

        # Extraer dirección del elemento
        try:
            elementos = driver.find_elements(By.CLASS_NAME, "Io6YTe")
            if elementos:
                direccion_text = elementos[0].text
                # Validar que contenga la ciudad buscada
                if ciudad.lower() in direccion_text.lower():
                    return direccion_text
                else:
                    log.info(f"  ⚠️  Dirección encontrada pero no contiene '{ciudad}'")
                    return None
        except:
            pass

        return None

    except Exception as e:
        return None


# ─── SELENIUM DRIVER ──────────────────────────────────────────────────────────
def get_driver():
    """Crea un ChromeDriver."""
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-plugins")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(15)

    return driver


# ─── CHECKPOINT ───────────────────────────────────────────────────────────────
def load_checkpoint():
    """Carga checkpoint de direcciones encontradas."""
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, 'r') as f:
            return json.load(f)
    return {'direcciones': {}, 'completados': []}


def save_checkpoint(checkpoint):
    """Guarda checkpoint."""
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump(checkpoint, f, indent=2)


# ─── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Obtener direcciones de empresas")
    parser.add_argument("--nicho", type=str, default=None, help="Nicho específico")
    parser.add_argument("--limit", type=int, default=None, help="Máximo registros")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Nichos por defecto
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
    completados = set(checkpoint.get('completados', []))
    direcciones_cache = checkpoint.get('direcciones', {})

    driver = None
    try:
        driver = get_driver()

        for nicho in nichos:
            log.info(f"\n🔹 {nicho}")

            # Obtener empresas CON CIUDAD pero SIN DIRECCIÓN
            # (Con ciudad podemos buscar dirección precisa)
            cur.execute(f"""
                SELECT id, nombre_empresa, ciudad FROM contactos_marketing
                WHERE nicho = ?
                AND email IS NOT NULL AND email != ''
                AND (ciudad IS NOT NULL AND ciudad != '')
                AND (direccion IS NULL OR direccion = '')
                LIMIT ?
            """, (nicho, args.limit or 999999))

            empresas = cur.fetchall()
            log.info(f"   Total sin dirección: {len(empresas)}")

            for i, (empresa_id, nombre, ciudad) in enumerate(empresas, 1):
                if empresa_id in completados:
                    continue

                log.info(f"\n[{i}/{len(empresas)}] {nombre} | {ciudad}")

                # Verificar si ciudad está en lista de colombianas
                es_ciudad_colombia = any(c.lower() == ciudad.lower() for c in CIUDADES_COLOMBIA)

                if es_ciudad_colombia:
                    log.info(f"  ✓ Ciudad '{ciudad}' es de Colombia")
                    # Asignar país si está vacío
                    cur.execute(
                        "UPDATE contactos_marketing SET pais = ? WHERE id = ? AND (pais IS NULL OR pais = '')",
                        ("Colombia", empresa_id)
                    )
                    conn.commit()
                else:
                    log.info(f"  ? Ciudad '{ciudad}' no está en lista (podría ser otro país)")

                # Buscar dirección (sea Colombia u otro país)
                log.info(f"  📍 Buscando dirección en Nominatim...")
                direccion_completa = get_address_nominatim(nombre, ciudad)

                if not direccion_completa:
                    log.info(f"  📍 Nominatim sin resultado, intentando Google Maps...")
                    time.sleep(2)
                    # 2. Fallback: Google Maps scraping
                    direccion_completa = get_address_google_maps_scrape(nombre, ciudad, driver)

                if direccion_completa:
                    # Quitar la ciudad de la dirección
                    direccion_sin_ciudad = extract_address_without_city(direccion_completa, ciudad)

                    log.info(f"  ✅ {direccion_sin_ciudad[:80]}")

                    # Guardar en BD (sin la ciudad, solo calle/barrio)
                    cur.execute(
                        "UPDATE contactos_marketing SET direccion = ? WHERE id = ?",
                        (direccion_sin_ciudad, empresa_id)
                    )
                    conn.commit()
                    direcciones_cache[str(empresa_id)] = direccion_sin_ciudad
                else:
                    log.info(f"  ❌ No encontrada en Nominatim ni Google Maps")

                completados.add(empresa_id)

                # Guardar checkpoint cada 10 registros
                if i % 10 == 0:
                    checkpoint['completados'] = list(completados)
                    checkpoint['direcciones'] = direcciones_cache
                    save_checkpoint(checkpoint)

                # Rate limit
                time.sleep(random.uniform(0.5, 1.5))

    finally:
        if driver:
            driver.quit()

        # Guardar checkpoint final
        checkpoint['completados'] = list(completados)
        checkpoint['direcciones'] = direcciones_cache
        save_checkpoint(checkpoint)

        log.info(f"\n✅ Completado. Checkpoint guardado.")
        conn.close()


if __name__ == "__main__":
    main()
