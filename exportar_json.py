import sqlite3
import json
import os

DB_FILE = "hoteles_colombia.db"
OUTPUT_FILE = "prospectos_export.json"


def determinar_fuente(nicho: str | None) -> str:
    if not nicho:
        return "etl"
    if "Maps" in nicho:
        return "maps"
    if "Informa" in nicho:
        return "informa"
    return "etl"


def exportar():
    if not os.path.exists(DB_FILE):
        print(f"❌ No se encontró '{DB_FILE}'. Ejecuta primero el pipeline de scraping.")
        return

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM contactos_hoteles ORDER BY id")
    rows = cur.fetchall()
    conn.close()

    data = []
    for r in rows:
        data.append({
            "nombre_empresa": r["nombre_empresa"],
            "nicho":          r["nicho"],
            "nombre_contacto":r["nombre_contacto"],
            "email":          r["email"],
            "telefono":       r["telefono"],
            "sitio_web":      r["sitio_web"],
            "ciudad":         r["ciudad"],
            "pais":           r["pais"] or "Colombia",
            "direccion":      r["direccion"],
            "maps_link":      r["maps_link"],
            "fuente":         determinar_fuente(r["nicho"]),
        })

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ Exportados {len(data)} prospectos → '{OUTPUT_FILE}'")
    print("   Sube ese archivo en el panel admin → tab Prospectos → Importar JSON")


if __name__ == "__main__":
    exportar()
