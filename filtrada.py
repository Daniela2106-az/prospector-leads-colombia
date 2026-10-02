import os
import sqlite3

# ==========================================
# CONFIGURACIÓN DE RUTAS Y PARÁMETROS
# ==========================================
RUTA_ORIGEN = (
    "/Users/danielaamaya/Downloads/ETL-master/output/base_marketing.db"
)

# Carpeta de destino
CARPETA_DESTINO = "/Users/danielaamaya/Human Valley"
RUTA_DESTINO = os.path.join(CARPETA_DESTINO, "base_marketing_filtrada.db")

NOMBRE_TABLA = "contactos_marketing"
COLUMNA_NICHO = "nicho"

# Nichos exactos a filtrar
NICHOS_A_COPIAR = [
    "Hoteleria",
    "Retail / Comercio",
    "Restaurantes y Bares",
    "Industrial / Manufactura",
    "Salud y Bienestar",
    "Empresa de Servicios Temporales",
]


def exportar_contactos_filtrados():
    if not os.path.exists(RUTA_ORIGEN):
        print(f"Error: No se encontró el archivo de origen en: {RUTA_ORIGEN}")
        return

    # Crear la carpeta de destino si no existe
    if not os.path.exists(CARPETA_DESTINO):
        os.makedirs(CARPETA_DESTINO, exist_ok=True)

    # Conexiones a SQLite
    conn_origen = sqlite3.connect(RUTA_ORIGEN)
    conn_destino = sqlite3.connect(RUTA_DESTINO)

    cursor_origen = conn_origen.cursor()
    cursor_destino = conn_destino.cursor()

    try:
        # 1. Obtener el DDL (CREATE TABLE) de la tabla 'contactos_marketing'
        cursor_origen.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?;",
            (NOMBRE_TABLA,),
        )
        resultado = cursor_origen.fetchone()

        if not resultado or not resultado[0]:
            print(
                f"Error: La tabla '{NOMBRE_TABLA}' no se encuentra en la base de datos."
            )
            return

        schema_sql = resultado[0]

        # 2. Recrear la tabla con la misma estructura en la base de datos destino
        cursor_destino.execute(
            f"DROP TABLE IF EXISTS {NOMBRE_TABLA}"
        )  # Previene errores si la tabla ya existía
        cursor_destino.execute(schema_sql)

        # 3. Consultar los registros que coincidan con la lista de nichos
        placeholders = ",".join(["?"] * len(NICHOS_A_COPIAR))
        query_select = f"SELECT * FROM {NOMBRE_TABLA} WHERE {COLUMNA_NICHO} IN ({placeholders})"

        cursor_origen.execute(query_select, NICHOS_A_COPIAR)
        registros = cursor_origen.fetchall()

        if not registros:
            print(
                "No se encontraron registros que coincidan exactamente con los nichos proporcionados."
            )
            return

        # 4. Insertar los registros filtrados en la nueva base de datos
        num_columnas = len(registros[0])
        insert_placeholders = ",".join(["?"] * num_columnas)
        query_insert = (
            f"INSERT INTO {NOMBRE_TABLA} VALUES ({insert_placeholders})"
        )

        cursor_destino.executemany(query_insert, registros)
        conn_destino.commit()

        print(
            f"¡Proceso completado con éxito! Se copiaron {len(registros)} contactos a:"
        )
        print(f"  --> {RUTA_DESTINO}")

    except sqlite3.Error as e:
        print(f"Ocurrió un error con SQLite: {e}")

    finally:
        conn_origen.close()
        conn_destino.close()


if __name__ == "__main__":
    exportar_contactos_filtrados()