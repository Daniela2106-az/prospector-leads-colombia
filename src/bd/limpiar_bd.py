from src.config import ruta_datos
import sqlite3
import os

DB_FILE = ruta_datos("hoteles_colombia.db")


def limpiar_base_de_datos():
    if not os.path.exists(DB_FILE):
        print(f"❌ Error: No se encontró la base de datos '{DB_FILE}'.")
        return

    # 1. Conectar a la base de datos
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 2. Traer todos los registros actuales para analizarlos en Python
    cursor.execute("SELECT id, nombre_empresa FROM contactos_hoteles")
    registros = cursor.fetchall()

    total_inicial = len(registros)
    print(f"📊 Total de registros actuales en la base de datos: {total_inicial}")
    print("⏳ Analizando nombres y aplicando filtros estrictos...")

    # 3. Definir tus palabras clave y cadenas de cadenas famosas en Colombia
    palabras_clave = [
        "hotel", "hoteles", "hosped", "alojamiento", "suites", "apartahotel",
        "hostal", "hostel", "resort", "posada", "lodge", "motel", "cabaña", "inn"
    ]

    cadenas_famosas = [
        "decameron", "tequendama", "estelar", "dann", "movich", "selina",
        "ghl", "hilton", "marriott", "ibis", "hyatt", "radisson", "sofitel",
        "eurobuilding", "nh", "intercontinental", "plaza", "boutique"
    ]

    ids_a_borrar = []

    for id_registro, nombre in registros:
        n = nombre.lower()

        # Validar si cumple con tus palabras clave o con algún hotel famoso
        tiene_palabra_clave = any(raiz in n for raiz in palabras_clave)
        es_cadena_famosa = any(cadena in n for cadena in cadenas_famosas)

        # Filtro de exclusión por si quedó algún restaurante o bar fantasma en el nombre
        es_comida_o_evento = (
                "restaurante" in n or "gourmet" in n or "bar" in n or "cafe" in n or
                "pizzeria" in n or "asadero" in n or "panaderia" in n or "catering" in n or
                "discoteca" in n or "grill" in n or "comidas" in n or "eventos" in n
        )

        # Si NO cumple ninguna regla de hotel, O SI se detecta que es de comida pura, lo marcamos para borrar
        if not (tiene_palabra_clave or es_cadena_famosa) or es_comida_o_evento:
            # Excepción especial: Si se llama "Hotel Restaurante X", la palabra hotel pesa más,
            # pero si solo dice "Restaurante X", se va.
            if "hotel" in n or "hosped" in n:
                continue
            ids_a_borrar.append(id_registro)

    # 4. Ejecutar la purga en SQLite si hay elementos para borrar
    if ids_a_borrar:
        print(f"🔥 Detectados {len(ids_a_borrar)} registros que no corresponden a hotelería.")

        # SQLite no procesa listas gigantes en un solo DELETE de golpe de forma óptima, lo hacemos en bloques
        cursor.execute(f"DELETE FROM contactos_hoteles WHERE id IN ({','.join(map(str, ids_a_borrar))})")
        conn.commit()

        # Vaciar el espacio en disco sobrante del archivo .db
        cursor.execute("VACUUM")
        conn.commit()

        print(f"✨ ¡Purga completada exitosamente!")
    else:
        print("✅ ¡Perfecto! Tu base de datos ya estaba 100% limpia y pulcra.")

    # 5. Mostrar balance final
    cursor.execute("SELECT COUNT(*) FROM contactos_hoteles")
    total_final = cursor.fetchone()[0]
    conn.close()

    print("\n=========================================")
    print(f"🏢 Hoteles puros remanentes: {total_final}")
    print(f"🗑️ Registros eliminados: {total_inicial - total_final}")
    print("=========================================\n")


if __name__ == "__main__":
    limpiar_base_de_datos()