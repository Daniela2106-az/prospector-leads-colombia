# ⚙️ Setup Base de Datos Compartida

## 📁 BD Configurada

```
Path: /Users/danielaamaya/Downloads/ETL-master/output/base_marketing.db
Tabla: contactos_marketing
```

## ✅ Scripts Actualizados

Ambos scripts ahora apuntan **automáticamente** a la BD correcta:

### 1️⃣ `prospector_ett.py`
- ✅ Busca nuevas ETTs en Google Maps
- ✅ Guarda en `contactos_marketing` con nicho "Empresa de Servicios Temporales"
- ✅ Busca emails y actualiza en la misma tabla

### 2️⃣ `complete_emails.py`
- ✅ Completa emails de empresas existentes
- ✅ Lee de `contactos_marketing`
- ✅ Busca en 5 nichos: Hotelería, Retail, Restaurantes, Industrial, Salud

---

## 🚀 Ejecutar en Paralelo

### Terminal 1: Descubrir nuevas ETTs

```bash
python prospector_ett.py
```

**¿Qué hace?**
- Busca en Google Maps: "servicios temporales en [ciudad]"
- Extrae: nombre, teléfono, dirección, sitio web
- Busca emails usando: web → DDG → LinkedIn → Google → Facebook
- Guarda TODO en `contactos_marketing`

**Output:**
```
📁 Usando BD: /Users/danielaamaya/Downloads/ETL-master/output/base_marketing.db
📊 Tabla: contactos_marketing
🗺️  FASE 1 — GOOGLE MAPS
  ✨ Nuevo: ETT Soluciones RH
  ✨ Nuevo: Personal Temporal Colombia

📊 FASE 2 — BÚSQUEDA DE EMAILS
  ✅ Email encontrado: contacto@ett.co
  ❌ Sin resultado: Personal Temporal Colombia
```

---

### Terminal 2: Completar Emails

```bash
python complete_emails.py
```

**¿Qué hace?**
- Lee empresas SIN email de los 5 nichos por defecto
- Busca emails para cada una
- Actualiza automáticamente en `contactos_marketing`

**Opciones:**
```bash
# Todos los 5 nichos (defecto)
python complete_emails.py

# Solo un nicho
python complete_emails.py --nicho="Hotelería"

# Varios nichos específicos
python complete_emails.py --nichos="Hotelería,Retail / Comercio"

# Solo primeros N registros
python complete_emails.py --limit=100

# Solo busca en LinkedIn (más rápido)
python complete_emails.py --solo-linkedin

# Reiniciar desde cero
python complete_emails.py --reset
```

**Output:**
```
📁 Usando BD: /Users/danielaamaya/Downloads/ETL-master/output/base_marketing.db
📊 Tabla: contactos_marketing
============================================================
COMPLETAR EMAILS
Total sin email   : 6471
Ya procesados     : 0
Pendientes        : 6471
Nichos            : Hotelería, Retail / Comercio, Restaurantes y Bares, Industrial / Manufactura, Salud y Bienestar
⚠️  Safe para ejecutar en paralelo (SQLite maneja concurrencia)

[1/6471] Hotel Bogotá Plaza (Bogotá) | Hotelería
  🌐 (a) Web: https://hotelbogota.com
  ✅ Email encontrado en web: info@hotelbogota.com
```

---

### Terminal 3 (Opcional): Monitorear Progreso

```bash
python monitor_bd.py --watch=10
```

Muestra en tiempo real:
```
NICHO                                    TOTAL  CON EMAIL  SIN EMAIL     %
Hotelería                                  921        840           81  91.2%
Industrial / Manufactura                  1834       1143          691  62.3%
Retail / Comercio                         4552       2353         2199  51.7%
...
TOTAL                                    13188       8087         5101  61.4%
```

---

## 📊 Estado Inicial de `base_marketing.db`

```
Agricultura y Recursos            │ 156 │  72 │  84 │ 46.2%
Construcción e Infraestructura     │ 865 │ 398 │ 467 │ 46.0%
Educación                          │ 187 │ 142 │  45 │ 75.9%
Gobierno y Servicios Públicos      │ 176 │ 122 │  54 │ 69.3%
Hotelería                          │ 921 │ 840 │  81 │ 91.2%
Industrial / Manufactura           │1834 │1143 │ 691 │ 62.3%
Restaurantes y Bares              │ 876 │ 678 │ 198 │ 77.4%
Retail / Comercio                 │4552 │2353 │2199 │ 51.7%
Salud y Bienestar                 │ 856 │ 579 │ 277 │ 67.7%
Servicios Profesionales           │3146 │2517 │ 629 │ 80.0%
Tecnología / Software             │ 560 │ 425 │ 135 │ 75.9%
─────────────────────────────────────────────────────────────
TOTAL                             │13164│8127 │5037 │ 61.7%
```

**Oportunidad:**
- ✅ 5,037 empresas **SIN EMAIL** esperando ser completadas
- ✅ `complete_emails.py` puede llenar estos datos automáticamente

---

## 🔄 Flujo Recomendado

**Día 1: Llenar Hotelería**
```bash
# Terminal 1: Descubrir ETTs (background)
python prospector_ett.py &

# Terminal 2: Completar Hotelería (primer nicho)
python complete_emails.py --nicho="Hotelería" --limit=200
```

**Día 2: Llenar Retail**
```bash
python complete_emails.py --nicho="Retail / Comercio" --limit=500
```

**Día 3+: Paralelo masivo**
```bash
# Terminal 1: ETT continuo
python prospector_ett.py

# Terminal 2: Retail
python complete_emails.py --nicho="Retail / Comercio" --limit=300

# Terminal 3: Restaurantes
python complete_emails.py --nicho="Restaurantes y Bares" --limit=200

# Terminal 4: Monitor
python monitor_bd.py --watch=10
```

---

## 🛡️ Seguridad de Concurrencia

✅ **Totalmente seguro ejecutar en paralelo:**
- SQLite maneja múltiples lecturas simultáneas
- Escrituras se serializan automáticamente
- Timeout: 5 segundos si hay lock
- Checkpoints independientes: sin duplicación

---

## 📝 Logs

```
prospector_ett.log          # Descubrimiento de ETTs
complete_emails.log         # Completación de emails
```

Ambos logs se escriben simultáneamente sin conflictos.

---

## 🆘 Troubleshooting

### "database is locked"
```
✅ Normal — SQLite está escribiendo
✅ Se reintenta automáticamente
```

### No encuentra empresas sin email
```
✅ Verifica que la BD sea: /Users/danielaamaya/Downloads/ETL-master/output/base_marketing.db
✅ Verifica tabla: contactos_marketing
✅ Verifica que el nicho coincida exactamente (case-sensitive)
```

### Quiero cambiar la BD
```bash
# Opción 1: Variable de entorno
export DB_PATH="/ruta/a/mi/base.db"
python complete_emails.py

# Opción 2: Editar en el script
# Cambiar DB_PATH en complete_emails.py línea ~53
```

---

## 📞 Próximas Funciones (TODO)

- [ ] Exportar resultados a CSV
- [ ] Sincronizar con CRM externo
- [ ] API REST para automatizar
- [ ] Agregar más nichos
- [ ] Dashboard web en tiempo real
