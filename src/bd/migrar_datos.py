import sqlite3
import os
from src.config import DATA_DIR


def migrar_datos(db_origen, db_destino):
    # 1. Validar que la base de datos gigante exista
    if not os.path.exists(db_origen):
        print(f"Error: No se encontró el archivo de origen '{db_origen}'.")
        return

    conn_origen = sqlite3.connect(db_origen)
    cursor_origen = conn_origen.cursor()

    # 2. Inspección automática para encontrar el nombre de la tabla original
    cursor_origen.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tablas = cursor_origen.fetchall()
    nombres_tablas = [t[0] for t in tablas if t[0] != "sqlite_sequence"]

    print("\n🔍 --- INSPECCIÓN DE BASE DE DATOS ---")
    print(f"Tablas encontradas en la base de datos original: {nombres_tablas}")
    print("---------------------------------------\n")

    if not nombres_tablas:
        print(
            "Alerta: No se encontraron tablas en la base de datos de origen."
        )
        conn_origen.close()
        return

    # Usamos la tabla detectada ('contactos_marketing')
    TABLA_REAL = nombres_tablas[0]
    print(f"Intentando extraer datos de la tabla: '{TABLA_REAL}'...")

    # 3. Conectar (o crear) la base de datos de destino limpia
    conn_destino = sqlite3.connect(db_destino)
    cursor_destino = conn_destino.cursor()

    # Estructura optimizada con restricción UNIQUE para blindarnos de duplicados
    cursor_destino.execute(
        """
        CREATE TABLE IF NOT EXISTS contactos_hoteles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_empresa TEXT NOT NULL,
            nicho TEXT,
            nombre_contacto TEXT,
            email TEXT,
            telefono TEXT,
            sitio_web TEXT,
            ciudad TEXT,
            pais TEXT,
            UNIQUE(nombre_empresa, sitio_web) 
        )
    """
    )
    conn_destino.commit()

    # 4. Extracción con FILTRO ESTRICTO (Excluye agencias, turismo, tours, etc.)
    print("Extrayendo datos de la base de datos original...")
    query_extract = f"""
        SELECT nombre_empresa, nicho, nombre_contacto, email, telefono, sitio_web, ciudad, pais
        FROM {TABLA_REAL}
        WHERE LOWER(pais) LIKE '%colombia%' 
          AND (LOWER(nicho) LIKE '%hotel%' OR LOWER(nombre_empresa) LIKE '%hotel%' OR LOWER(nombre_empresa) LIKE '%suites%')
          AND LOWER(nombre_empresa) NOT LIKE '%viaje%'
          AND LOWER(nombre_empresa) NOT LIKE '%turismo%'
          AND LOWER(nombre_empresa) NOT LIKE '%tour%'
          AND LOWER(nombre_empresa) NOT LIKE '%agencia%'
          AND LOWER(nombre_empresa) NOT LIKE '%agency%'
          AND LOWER(nombre_empresa) NOT LIKE '%aviatur%'
          AND LOWER(nombre_empresa) NOT LIKE '%expreso%'
          AND LOWER(nombre_empresa) NOT LIKE '%representaciones%'
    """

    try:
        cursor_origen.execute(query_extract)
        registros = cursor_origen.fetchall()
        print(
            f"Se encontraron {len(registros)} registros que cumplen estrictamente con ser HOTELES."
        )
    except sqlite3.OperationalError as e:
        print(f"Error al leer la tabla '{TABLA_REAL}': {e}")
        conn_origen.close()
        conn_destino.close()
        return

    # 5. Insertar los datos filtrados en la nueva BD
    query_insert = """
        INSERT OR IGNORE INTO contactos_hoteles 
        (nombre_empresa, nicho, nombre_contacto, email, telefono, sitio_web, ciudad, pais)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """

    cursor_destino.executemany(query_insert, registros)
    conn_destino.commit()

    # Verificar el total real guardado
    cursor_destino.execute("SELECT COUNT(*) FROM contactos_hoteles")
    total_nuevos = cursor_destino.fetchone()[0]

    print(
        f"¡Migración completada con éxito! La nueva BD '{db_destino}' tiene {total_nuevos} registros puros de hoteles."
    )

    # Cerrar conexiones de forma segura
    conn_origen.close()
    conn_destino.close()


if __name__ == "__main__":
    # Ruta de origen (donde está tu base de datos gigante)
    RUTA_ORIGEN_CARPETA = os.environ.get("ETL_OUTPUT_DIR", DATA_DIR)
    BASE_ORIGEN = os.path.join(RUTA_ORIGEN_CARPETA, "base_marketing.db")

    # CAMBIO AQUÍ: La nueva BD se creará directamente dentro de tu proyecto en PyCharm
    RUTA_PROYECTO_NUEVO = DATA_DIR
    BASE_DESTINO = os.path.join(RUTA_PROYECTO_NUEVO, "hoteles_colombia.db")

    print(f"Buscando base de datos en: {BASE_ORIGEN}")
    print(f"Creando nueva base de datos EN TU PROYECTO: {BASE_DESTINO}")

    # Ejecutamos la migración
    migrar_datos(BASE_ORIGEN, BASE_DESTINO)