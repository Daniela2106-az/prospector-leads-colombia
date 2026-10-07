from src.config import ruta_datos
import os
import sqlite3
import time
from urllib.parse import quote_plus
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# ----------------------------------------------------
#               VARIABLES DE CONFIGURACIÓN MODULAR
# ----------------------------------------------------
DB_FILE = ruta_datos("hoteles_colombia.db")


def verificar_y_actualizar_esquema():
    """Asegura de forma estricta que existan las columnas de Google Maps."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(contactos_hoteles);")
    columnas = [info[1] for info in cursor.fetchall()]

    if "direccion" not in columnas:
        print("🔧 Agregando columna 'direccion' a la base de datos...")
        cursor.execute("ALTER TABLE contactos_hoteles ADD COLUMN direccion TEXT;")
        conn.commit()

    if "maps_link" not in columnas:
        print("🔧 Agregando columna 'maps_link' a la base de datos...")
        cursor.execute("ALTER TABLE contactos_hoteles ADD COLUMN maps_link TEXT;")
        conn.commit()

    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_maps_link 
        ON contactos_hoteles(maps_link);
    """
    )
    conn.commit()
    conn.close()


def get_driver():
    """Configura y devuelve un driver de Chrome optimizado."""
    chrome_options = Options()
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--start-maximized")

    # Idioma en español para que los selectores y labels no cambien
    chrome_options.add_argument("--lang=es")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


def extraer_datos_negocio(driver, maps_link):
    """Extrae la información detallada desde la ficha de Google Maps."""
    try:
        driver.get(maps_link)
        # Esperamos que cargue el nombre del hotel para asegurar la página
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.XPATH, '//h1[contains(@class,"DUwDvf")]'))
        )
    except Exception as e:
        print(f"⚠️ Error al cargar ficha {maps_link}: {e}")
        return "No disponible", "No disponible", "No disponible", "No disponible"

    nombre = direccion = telefono = pagina_web = "No disponible"

    try:
        nombre = driver.find_element(By.XPATH, '//h1[contains(@class,"DUwDvf")]').text.strip()
    except:
        pass

    try:
        direccion_el = driver.find_element(By.XPATH, '//button[@data-item-id="address"]')
        direccion = direccion_el.find_element(By.CLASS_NAME, "rogA2c").text.strip()
    except:
        pass

    try:
        telefono_el = driver.find_element(By.XPATH, '//button[contains(@data-item-id,"phone:tel:")]')
        tel_raw = telefono_el.get_attribute("aria-label").replace("Teléfono: ", "").strip()
        telefono = ''.join(filter(str.isdigit, tel_raw))
        if telefono:
            if len(telefono) == 7:
                telefono = f"+57601{telefono}"
            elif len(telefono) == 10 and telefono.startswith("3"):
                telefono = f"+57{telefono}"
    except:
        pass

    try:
        web_el = driver.find_element(By.XPATH, '//a[@data-item-id="authority"]')
        pagina_web = web_el.get_attribute("href").strip()
    except:
        pass

    return nombre, direccion, telefono, pagina_web


def guardar_o_actualizar_hotel(nombre, direccion, telefono, pagina_web, ciudad, maps_link):
    """Lógica Upsert modular."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id FROM contactos_hoteles 
        WHERE LOWER(nombre_empresa) = ? OR (sitio_web IS NOT NULL AND LOWER(sitio_web) LIKE ?)
    """, (nombre.lower(), f"%{pagina_web.lower()}%" if pagina_web != "No disponible" else "---NA---"))
    existe = cursor.fetchone()

    if existe:
        hotel_id = existe[0]
        print(f"🔄 [Upsert] '{nombre}' ya existía. Enriqueciendo datos...")
        cursor.execute("""
            UPDATE contactos_hoteles
            SET telefono = CASE WHEN telefono IS NULL OR telefono = 'No disponible' THEN ? ELSE telefono END,
                sitio_web = CASE WHEN sitio_web IS NULL OR sitio_web = 'No disponible' THEN ? ELSE sitio_web END,
                direccion = ?,
                maps_link = ?
            WHERE id = ?
        """, (telefono, pagina_web, direccion, maps_link, hotel_id))
    else:
        print(f"✨ [Nuevo] Guardando: {nombre}")
        cursor.execute("""
            INSERT OR IGNORE INTO contactos_hoteles 
            (nombre_empresa, nicho, telefono, sitio_web, ciudad, pais, direccion, maps_link)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (nombre, "Hotelería (Maps)", telefono, pagina_web, ciudad, "Colombia", direccion, maps_link))

    conn.commit()
    conn.close()


def procesar_ciudad(driver, ciudad):
    """Maneja el ciclo de scroll y recolección cargando la URL directa."""
    termino_busqueda = f"hoteles en {ciudad}, Colombia"

    # Construcción de la URL directa codificada
    url_directa = f"https://www.google.com/maps/search/{quote_plus(termino_busqueda)}"
    print(f"\n🔎 Navegando directo a resultados de: '{termino_busqueda}'...")
    driver.get(url_directa)

    # Esperamos a que aparezca la lista de resultados en la parte izquierda
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, '//a[contains(@href, "/maps/place/")]'))
        )
    except Exception as e:
        print(f"⚠️ Alerta: No se renderizaron resultados iniciales de inmediato. {e}")

    enlaces_encontrados = set()
    enlaces_previos = -1
    intentos_sin_nuevos = 0
    MAX_INTENTOS = 4

    # Bloque de Scroll
    while intentos_sin_nuevos < MAX_INTENTOS:
        links_actuales = driver.find_elements(By.XPATH, '//a[contains(@href, "/maps/place/")]')
        for link in links_actuales:
            href = link.get_attribute("href")
            if href:
                enlaces_encontrados.add(href.split("?")[0])

        try:
            # Buscamos el contenedor lateral de los resultados para hacerle scroll
            scrollable_div = driver.find_element(By.XPATH, '//div[@role="feed"]')
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scrollable_div)
            time.sleep(3)
        except:
            time.sleep(2)
            break

        if len(enlaces_encontrados) == enlaces_previos:
            intentos_sin_nuevos += 1
        else:
            intentos_sin_nuevos = 0

        enlaces_previos = len(enlaces_encontrados)
        print(f"📍 Enlaces detectados en {ciudad}: {len(enlaces_encontrados)}", end="\r")

    print(f"\n✅ Total enlaces listos para procesar en {ciudad}: {len(enlaces_encontrados)}")

    if not enlaces_encontrados:
        return

    # Comprobación segura de enlaces existentes para evitar reprocesar lo que ya se hizo
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT maps_link FROM contactos_hoteles WHERE maps_link IS NOT NULL")
    enlaces_guardados = set(row[0] for row in cursor.fetchall())
    conn.close()

    nuevos_enlaces = enlaces_encontrados - enlaces_guardados
    print(f"🆕 Enlaces nuevos que no estaban en la base de datos: {len(nuevos_enlaces)}")

    for idx, enlace in enumerate(nuevos_enlaces, 1):
        print(f"\n[{idx}/{len(nuevos_enlaces)}] Procesando ficha del hotel...")
        nombre, direccion, telefono, pagina_web = extraer_datos_negocio(driver, enlace)
        if nombre != "No disponible":
            guardar_o_actualizar_hotel(nombre, direccion, telefono, pagina_web, ciudad, enlace)


def main():
    if not os.path.exists(DB_FILE):
        print(f"❌ Error: No se encuentra '{DB_FILE}' en la raíz. Ejecuta la migración del Módulo 1.")
        return

    verificar_y_actualizar_esquema()

    print("🚀 Iniciando Bot Modular de Google Maps para Hoteles...")
    CIUDADES = ["Barranquilla", "Bogota", "Medellin","Cali"]

    driver = get_driver()

    try:
        for ciudad in CIUDADES:
            print(f"\n=========================================")
            print(f"🏢 INICIANDO FASE: {ciudad.upper()}")
            print(f"=========================================")
            procesar_ciudad(driver, ciudad)
    finally:
        driver.quit()
        print("\n🏁 Proceso finalizado por completo.")


if __name__ == "__main__":
    main()