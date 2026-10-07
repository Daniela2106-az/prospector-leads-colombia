import sqlite3

conn = sqlite3.connect("hoteles_colombia.db")
cursor = conn.cursor()

# Añadimos las columnas necesarias de Maps de manera segura
try:
    cursor.execute("ALTER TABLE contactos_hoteles ADD COLUMN direccion TEXT;")
    cursor.execute(
        "ALTER TABLE contactos_hoteles ADD COLUMN maps_link TEXT UNIQUE;"
    )
    conn.commit()
    print("Base de datos actualizada con éxito para recibir datos de Maps.")
except sqlite3.OperationalError:
    print("Las columnas ya existían, no hay problema.")

conn.close()