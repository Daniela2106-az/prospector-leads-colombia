# 🤖 Scripts de Scraping: Prospector ETT + Complete Emails

## 📋 Descripción

Dos scripts complementarios para gestionar empresas en la BD:

1. **`src/descubrimiento/prospector_ett.py`** — Descubre nuevas empresas de servicios temporales en Google Maps y busca sus emails
2. **`src/emails/completar_emails.py`** — Completa emails faltantes en empresas ya existentes (múltiples nichos)

## 🔄 Funcionamiento en Paralelo

### ✅ ¿Es seguro ejecutarlos al mismo tiempo?

**SÍ**, totalmente seguro. Razones:

- **SQLite maneja concurrencia automáticamente**
  - Timeout de escritura: 5 segundos
  - Operaciones rápidas (milisegundos)
  - Sin riesgo de corrupción de datos

- **Checkpoints independientes**
  - `src/descubrimiento/prospector_ett.py` → `checkpoint_ett.json`
  - `src/emails/completar_emails.py` → `checkpoint_complete_emails.json`
  - No interfieren uno con otro

- **Operaciones en diferentes tablas/filas**
  - `src/descubrimiento/prospector_ett.py`: **INSERT** nuevas empresas (nicho: "Empresa de Servicios Temporales")
  - `src/emails/completar_emails.py`: **UPDATE** emails en empresas existentes (otros nichos)

### ⚙️ Protecciones Adicionales

1. **Pequeños delays aleatorios** antes de escribir en BD
2. **Reintentos automáticos** si hay lock temporal
3. **Transacciones ACID** (garantizado por SQLite)

---

## 🚀 Cómo Usar

### Terminal 1: Descubrir ETTs nuevas

```bash
# Empieza a buscar nuevas ETTs en Bogotá
python -m src.descubrimiento.prospector_ett

# Continúa desde última sesión
python -m src.descubrimiento.prospector_ett

# Empieza desde cero (elimina checkpoint)
python -m src.descubrimiento.prospector_ett --reset

# Solo busca emails (sin Maps)
python -m src.descubrimiento.prospector_ett --solo-email
```

**Output esperado:**
```
🗺️  FASE 1 — GOOGLE MAPS
  ✨ Nuevo: ETT Soluciones RH S.A.S.
  ✨ Nuevo: Personal Temporal Colombia

📊 FASE 2 — BÚSQUEDA DE EMAILS
  ✅ Email encontrado: contacto@ettsoluciones.co
  ❌ Sin resultado: Personal Temporal Colombia
```

---

### Terminal 2: Completar Emails Faltantes

```bash
# Completa emails en los 5 nichos por defecto
python -m src.emails.completar_emails

# Solo completa Hotelería
python -m src.emails.completar_emails --nicho="Hotelería"

# Completa varios nichos específicos
python -m src.emails.completar_emails --nichos="Hotelería,Restaurantes y Bares"

# Solo los primeros 30
python -m src.emails.completar_emails --limit=30

# Solo LinkedIn (más rápido, menos preciso)
python -m src.emails.completar_emails --solo-linkedin

# Empieza desde cero
python -m src.emails.completar_emails --reset
```

**Nichos disponibles (por defecto):**
- Hotelería
- Retail / Comercio
- Restaurantes y Bares
- Industrial / Manufactura
- Salud y Bienestar

**Output esperado:**
```
[1/150] Hotel Bogotá Plaza (Bogotá) | Hotelería
  🌐 (a) Web: https://hotelbogota.com
  ✅ Email encontrado en web

[2/150] Tienda Centro (Bogotá) | Retail / Comercio
  📘 (c) LinkedIn
  ✅ Email en LinkedIn: info@tiendacentro.co
```

---

## 📊 Flujo de Trabajo Recomendado

### Scenario 1: Operación Continua

```
HORA 1:
Terminal 1: python -m src.descubrimiento.prospector_ett
  → Descubre 50 nuevas ETTs en Bogotá
  → Busca emails para todas
  → Guarda en BD

Terminal 2: (espera a que terminal 1 agregue datos)
  → python -m src.emails.completar_emails --nicho="Hotelería"
  → Completa 200 hoteles sin email
  → Actualiza BD en paralelo

HORA 2:
Terminal 1: python -m src.descubrimiento.prospector_ett (nueva ciudad: Medellín)
  → Descubre ETTs en Medellín

Terminal 2: python -m src.emails.completar_emails --nichos="Retail / Comercio,Restaurantes y Bares"
  → Completa emails de retail y restaurantes
```

### Scenario 2: Procesamiento Masivo

```bash
# Ventana 1: Prospector ETT
python -m src.descubrimiento.prospector_ett

# Ventana 2: Completar Hotelería
python -m src.emails.completar_emails --nicho="Hotelería" --limit=100

# Ventana 3: Completar Retail
python -m src.emails.completar_emails --nicho="Retail / Comercio" --limit=100

# Ventana 4: Completar Restaurantes
python -m src.emails.completar_emails --nicho="Restaurantes y Bares" --limit=100
```

→ Todos ejecutándose al mismo tiempo sin conflictos

---

## 🗂️ Estructura de Base de Datos

**Tabla: `contactos_hoteles`**

```
id              INTEGER PRIMARY KEY
nombre_empresa  TEXT              ← Nombre de la empresa
nicho           TEXT              ← Categoría (Hotelería, ETT, etc.)
email           TEXT              ← EMAIL (NULL = pendiente)
telefono        TEXT
sitio_web       TEXT
ciudad          TEXT
pais            TEXT = "Colombia"
direccion       TEXT
maps_link       TEXT
especialidades  TEXT              ← Específico para ETT
licencia_dian   TEXT              ← Específico para ETT
```

**Nichos Actuales:**
- `"Hotelería"`
- `"Retail / Comercio"`
- `"Restaurantes y Bares"`
- `"Industrial / Manufactura"`
- `"Salud y Bienestar"`
- `"Empresa de Servicios Temporales"` ← Agregado por `src/descubrimiento/prospector_ett.py`

---

## 📝 Logs

- `prospector_ett.log` — Log de descubrimiento ETT
- `complete_emails.log` — Log de completación de emails

Ambos se escriben al mismo tiempo sin problemas.

---

## ⚠️ Consideraciones

### Si ambos escriben exactamente al mismo tiempo
- SQLite espera automáticamente (~5 seg timeout)
- No hay error, solo pequeña pausa
- Transacciones completadas exitosamente

### Si quieres monitoreo en tiempo real
```bash
# Terminal adicional: ver BD en tiempo real
sqlite3 hoteles_colombia.db "SELECT nicho, COUNT(*) as total, SUM(CASE WHEN email IS NOT NULL THEN 1 ELSE 0 END) as con_email FROM contactos_hoteles GROUP BY nicho;"
```

### Si necesitas pausar
- **Ctrl+C** en cualquier terminal
- Checkpoint se guarda automáticamente
- Próxima ejecución continúa desde donde paró

---

## 🔍 Troubleshooting

### "database is locked"
```
✅ Normal — SQLite está escribiendo desde otro proceso
✅ Se reintenta automáticamente en 5 segundos
```

### Email duplicado / actualizado múltiples veces
```
✅ Imposible — Checkpoints independientes evitan esto
✅ Cada script sabe qué ya procesó
```

### Progreso lento
```
🔧 Reduce delays en el código
🔧 Usa --solo-linkedin (más rápido)
🔧 Usa --limit para procesar menos
```

---

## 📊 Estadísticas

Ejemplo de output final:

```
prospector_ett.py:
  ETTs nuevas       : 45
  Emails encontrados: 38
  Sin resultado     : 7

complete_emails.py (Hotelería):
  Total sin email   : 350
  Ya procesados     : 150
  Pendientes        : 200
  Emails encontrados: 145
  Sin resultado     : 55
```

---

## 🎯 Próximas Mejoras

- [ ] Agregar más nichos
- [ ] Exportar resultados a CSV
- [ ] API para sincronizar con CRM externo
- [ ] Dashboard de progreso en tiempo real
