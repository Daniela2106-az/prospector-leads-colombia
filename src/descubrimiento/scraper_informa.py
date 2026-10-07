from src.config import ruta_datos
import os
import sqlite3
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ----------------------------------------------------
#               VARIABLES DE CONFIGURACIÓN
# ----------------------------------------------------
DB_FILE = ruta_datos("hoteles_colombia.db")
URL_RAIZ = "https://www.informacolombia.com/directorio-empresas/"


def get_driver():
    """Configura y devuelve un driver de Chrome optimizado."""
    chrome_options = Options()
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--lang=es")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


def guardar_o_actualizar_informa(nombre, telefono, ciudad):
    """Lógica Upsert: Inserta si es nuevo, actualiza teléfono si ya existía."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, telefono FROM contactos_hoteles WHERE LOWER(nombre_empresa) = ?",
        (nombre.lower(),),
    )
    existe = cursor.fetchone()

    if existe:
        hotel_id = existe[0]
        tel_actual = existe[1]
        if tel_actual is None or tel_actual in ["No disponible", "", "0"]:
            print(f"🔄 [Upsert] Agregando teléfono a '{nombre}' -> {telefono}")
            cursor.execute(
                "UPDATE contactos_hoteles SET telefono = ? WHERE id = ?",
                (telefono, hotel_id),
            )
    else:
        print(f"✨ [Nuevo Informa] Registrando: {nombre} ({ciudad})")
        cursor.execute(
            """
            INSERT OR IGNORE INTO contactos_hoteles 
            (nombre_empresa, nicho, telefono, ciudad, pais)
            VALUES (?, ?, ?, ?, ?)
        """,
            (nombre, "Hotelería (Informa)", telefono, ciudad, "Colombia"),
        )

    conn.commit()
    conn.close()


def es_hotel_real(nombre):
    """Filtro amplio para capturar cualquier variación de hospedaje u hotel."""
    n = nombre.lower()
    palabras_clave = ["hotel", "hosped", "alojamiento", "suites", "apartahotel", "hostal", "hostel", "resort", "posada",
                      "lodge", "motel", "cabaña", "inn"]
    es_hospedaje = any(raiz in n for raiz in palabras_clave)

    es_comida_o_evento = (
            "restaurante" in n or "gourmet" in n or "bar" in n or "cafe" in n or
            "pizzeria" in n or "asadero" in n or "panaderia" in n or "catering" in n or
            "discoteca" in n or "grill" in n or "comidas" in n or "eventos" in n
    )
    return es_hospedaje and not es_comida_o_evento


def extraer_hoteles_desde_tabla(driver):
    """Recorre las filas de la tabla extrayendo cada columna por separado."""
    conteo_pagina = 0

    # Buscamos todas las filas (tr) que estén dentro de la tabla de resultados
    filas = driver.find_elements(By.XPATH, "//table//tr")

    for fila in filas:
        try:
            # Buscamos las celdas (td) de esta fila en específico
            celdas = fila.find_elements(By.XPATH, "./td")

            # Si la fila no tiene al menos 4 columnas (Empresa, Localidad, Departamento, Teléfono), la saltamos
            if len(celdas) < 4:
                continue

            nombre_raw = celdas[0].text.strip()
            ciudad_raw = celdas[1].text.strip().title()
            telefono_raw = celdas[3].text.strip()

            # Limpiar el teléfono dejando solo los números
            telefono = "".join(filter(str.isdigit, telefono_raw))

            # Si la primera fila es el encabezado ("Empresa", "Localidad", etc.), la saltamos
            if "empresa" in nombre_raw.lower() or len(nombre_raw) < 3:
                continue

            if es_hotel_real(nombre_raw):
                # Formatear si es celular
                if len(telefono) == 10 and telefono.startswith("3"):
                    telefono = f"+57{telefono}"

                guardar_o_actualizar_informa(nombre_raw, telefono, ciudad_raw)
                conteo_pagina += 1
        except Exception as e:
            continue

    return conteo_pagina


def main():
    if not os.path.exists(DB_FILE):
        print(f"❌ Error: No se encuentra '{DB_FILE}' en la raíz.")
        return

    print("🚀 Iniciando Bot Table-Parser para InformaColombia...")
    driver = get_driver()

    print(f"🌐 Navegando a la portada principal: {URL_RAIZ}")
    driver.get(URL_RAIZ)
    time.sleep(3)

    try:
        print("🔎 Localizando la sección 'I - ALOJAMIENTO Y SERVICIOS DE COMIDA'...")
        categoria_i = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(text(), 'ALOJAMIENTO') or contains(@href, 'I_ALOJAMIENTO')]"))
        )
        driver.execute_script("arguments[0].click();", categoria_i)
        print("🎯 Categoría I seleccionada con éxito.")
        time.sleep(4)
    except Exception as e:
        print(f"❌ Error crítico: No se pudo ingresar a la categoría. {e}")
        driver.quit()
        return

    PAGINAS_A_PROCESAR = 40

    for pagina in range(1, PAGINAS_A_PROCESAR + 1):
        print(
            f"\n========================================="
            f"\n📄 PROCESANDO PÁGINA {pagina} DE {PAGINAS_A_PROCESAR}"
            f"\n========================================="
        )

        # Analizar por celdas independientes
        hoteles_encontrados = extraer_hoteles_desde_tabla(driver)
        print(f"✅ Fin de página {pagina}. Se integraron {hoteles_encontrados} hoteles válidos.")

        if pagina == PAGINAS_A_PROCESAR:
            break

        # Avanzar usando la paginación inferior
        try:
            print("箱 Buscando botón para avanzar de página...")
            siguiente_boton = driver.find_elements(
                By.XPATH,
                f"//a[text()='»' or text()='{pagina + 1}' or contains(@aria-label, 'Next')]",
            )

            if siguiente_boton:
                driver.execute_script("arguments[0].click();", siguiente_boton[0])
                time.sleep(4)  # Espera para que cargue la nueva tabla
            else:
                print("⚠️ No se localizó enlace para avanzar de página. Deteniendo.")
                break
        except Exception as e:
            print(f"❌ Error al avanzar de página: {e}")
            break

    driver.quit()
    print("\n🏁 ¡Módulo de InformaColombia finalizado con éxito analizando celdas!")


if __name__ == "__main__":
    main()