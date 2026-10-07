"""Rutas compartidas del proyecto. Los datos locales viven en data/ (ignorada por git)."""
import os

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(RAIZ, "data"))
os.makedirs(DATA_DIR, exist_ok=True)


def ruta_datos(nombre):
    """Ruta absoluta de un archivo dentro de la carpeta de datos."""
    return os.path.join(DATA_DIR, nombre)
