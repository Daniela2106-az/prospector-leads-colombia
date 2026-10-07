from src.config import ruta_datos
import sqlite3
import pandas as pd
import os

DB_FILE = ruta_datos("hoteles_colombia.db")
ARCHIVO_EXCEL = ruta_datos("reporte_final_hoteles.xlsx")


def generar_reporte():
    if not os.path.exists(DB_FILE):
        print(f"❌ Error: No se encontró la base de datos '{DB_FILE}' en este proyecto.")
        return

    # 1. Conectar a la base de datos
    conn = sqlite3.connect(DB_FILE)

    # 2. Leer toda la tabla usando Pandas
    query = "SELECT * FROM contactos_hoteles"
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        print("⚠️ La tabla 'contactos_hoteles' está vacía.")
        return

    # 3. Exportar a un archivo Excel limpio
    df.to_excel(ARCHIVO_EXCEL, index=False)

    print("\n📊 --- REPORTE DE CONSOLIDACIÓN GENERADO ---")
    print(f"✅ Archivo guardado con éxito como: '{ARCHIVO_EXCEL}'")
    print(f"🏢 Total de hoteles registrados en la BD: {len(df)}")
    print("-------------------------------------------\n")

    # 4. Mostrar una pequeña muestra en la consola para auditar rápido
    print("🔍 Vista previa de las ciudades recolectadas:")
    print(df['ciudad'].value_counts())

    print("\n📌 Conteo de registros con Teléfono y Sitio Web:")
    print(f"📞 Con teléfono: {df['telefono'].notna().sum()} / {len(df)}")
    print(f"🌐 Con sitio web: {df['sitio_web'].notna().sum()} / {len(df)}")


if __name__ == "__main__":
    generar_reporte()