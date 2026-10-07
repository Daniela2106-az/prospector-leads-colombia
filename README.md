# prospector-leads-colombia

Prospección de empresas y extracción de emails en Colombia.

Colección de scripts en Python para **descubrir empresas en Google Maps, encontrar sus datos de contacto (sobre todo emails) y guardarlos en una base de datos SQLite**. Se usó principalmente para armar bases de prospección comercial de hoteles y otros nichos (retail, restaurantes, industria, salud) y empresas de servicios temporales (ETT) en ciudades de Colombia.

## Qué hace el proyecto

1. **Descubre negocios** en Google Maps (Selenium) y extrae nombre, teléfono, dirección, sitio web y enlace de Maps.
2. **Busca emails** de cada negocio con varias estrategias en cascada: scraping profundo del sitio web → DuckDuckGo → LinkedIn → Google → Facebook.
3. **Guarda todo en SQLite** (`hoteles_colombia.db`, tabla `contactos_hoteles`) y permite limpiar, migrar, exportar y monitorear los datos.
4. **Reanuda el trabajo** gracias a checkpoints JSON si el proceso se interrumpe.
5. **Se puede ejecutar en paralelo** (varias ciudades/nichos a la vez en distintas terminales) aprovechando la concurrencia de SQLite.

## Características

- Scraping con Selenium (Chrome) y Playwright, con `webdriver_manager` para gestionar el driver.
- Cascada de búsqueda de emails con validación de correos.
- Checkpoints automáticos (`checkpoint_*.json`) y opción `--reset`.
- Argumentos de línea de comandos (`--ciudad`, `--nicho`, `--nichos`, `--limit`, `--solo-email`, `--solo-linkedin`, `--reset`).
- Geocodificación de direcciones/ciudades con Nominatim (OpenStreetMap) y respaldo con Google Maps.
- Scripts de monitoreo del avance (`monitor_bd.py`, `monitor_progress.sh`).
- Exportación a Excel (`.xlsx`), JSON y reportes de texto.
- Lanzadores para abrir varias terminales en macOS (`scripts/`).
- Envío opcional de prospectos a una API externa (`SYNCRONO_URL` / `SYNCRONO_TOKEN`) desde `prospector.py`.

## Estructura de carpetas

Organizado por etapa del flujo de datos:

```
prospector-leads-colombia/
├── README.md
├── requirements.txt
├── .env.example
├── docs/
│   ├── guia_scripts.md            # guía de prospector_ett y completar_emails
│   └── configuracion_bd.md        # notas de la BD compartida
├── src/
│   ├── config.py                  # rutas compartidas (carpeta data/)
│   ├── descubrimiento/            # encontrar empresas en Google Maps
│   │   ├── prospector.py          # Maps + emails (genérico por nicho)
│   │   ├── prospector_ett.py      # empresas de servicios temporales (ETT)
│   │   ├── bot_maps_hoteles.py
│   │   └── scraper_informa.py
│   ├── emails/                    # encontrar emails de empresas ya guardadas
│   │   ├── completar_emails.py
│   │   ├── buscar_emails_faltantes.py
│   │   ├── buscar_emails_avanzado.py   # Google + Facebook
│   │   ├── scraper_emails_web.py
│   │   └── buscar_por_nombre.py        # registros con solo nombre
│   ├── enriquecimiento/           # completar ciudad y dirección
│   │   ├── enriquecer_ciudades.py
│   │   └── obtener_direcciones.py
│   ├── bd/                        # gestión de la base de datos
│   │   ├── actualizar_bd.py
│   │   ├── limpiar_bd.py
│   │   ├── migrar_datos.py
│   │   └── filtrar_datos.py
│   ├── exportacion/
│   │   ├── exportar_json.py
│   │   └── exportar_reporte.py    # Excel
│   └── monitoreo/
│       ├── monitor_bd.py
│       └── monitor_retail.py
├── scripts/                       # lanzadores en shell (macOS)
│   ├── lanzar_paralelo.sh
│   ├── lanzar_terminales.sh
│   ├── ejecutar_paralelo.sh
│   └── monitor_progreso.sh
└── data/                          # local, ignorada por git: BD, logs, checkpoints, reportes
```

## Base de datos

SQLite, tabla `contactos_hoteles`: `id`, `nombre_empresa`, `nicho`, `email`, `telefono`, `sitio_web`, `ciudad`, `pais`, `direccion`, `maps_link`, `especialidades`, `licencia_dian`.

## Requisitos y dependencias

- Python 3.10 o superior (el código usa sintaxis `str | None`).
- Google Chrome instalado (Selenium).
- macOS para los scripts `scripts/*.sh` (usan `osascript` y Terminal).

Paquetes de Python:

```bash
pip install -r requirements.txt
playwright install chromium   # solo si usas los scripts con Playwright
```

## Configuración

Crea un archivo `.env` (puedes partir de `.env.example`):

```
SYNCRONO_URL=
SYNCRONO_TOKEN=
```

Solo es necesario si vas a enviar prospectos a la API externa desde `prospector.py`.

> Los datos (BD, logs, checkpoints, reportes) se guardan en `data/`. Puedes cambiar la carpeta con la variable de entorno `DATA_DIR`. Los scripts que usan `base_marketing.db` (la BD grande de origen) esperan encontrarla en `data/`.

## Cómo usarlo

Los módulos se ejecutan desde la raíz del proyecto con `python -m`:

```bash
# 1. Descubrir empresas de servicios temporales y buscar sus emails
python -m src.descubrimiento.prospector_ett                       # continúa desde el último checkpoint
python -m src.descubrimiento.prospector_ett --ciudad="Medellín"   # una ciudad concreta
python -m src.descubrimiento.prospector_ett --solo-email          # solo la fase de emails
python -m src.descubrimiento.prospector_ett --reset               # empezar de cero

# 2. Completar emails faltantes de otros nichos
python -m src.emails.completar_emails                             # los 5 nichos por defecto
python -m src.emails.completar_emails --nicho="Hotelería" --limit=100
python -m src.emails.completar_emails --nichos="Hotelería,Retail / Comercio"
python -m src.emails.completar_emails --solo-linkedin

# 3. Monitorear el avance
python -m src.monitoreo.monitor_bd --watch=10

# 4. Exportar resultados
python -m src.exportacion.exportar_reporte   # Excel
python -m src.exportacion.exportar_json      # JSON

# 5. Varios procesos en paralelo (macOS)
./scripts/lanzar_paralelo.sh
```

Puedes pausar con `Ctrl+C`; el progreso queda guardado en el checkpoint y se retoma en la siguiente ejecución. Más detalle en `docs/guia_scripts.md` y `docs/configuracion_bd.md`.

## Aviso de uso responsable

El scraping puede incumplir los términos de servicio de Google, LinkedIn, Facebook o Instagram, y los datos de contacto están sujetos a la normativa de protección de datos (en Colombia, Ley 1581 de 2012). Úsalo con cuidado y solo para fines legítimos.
