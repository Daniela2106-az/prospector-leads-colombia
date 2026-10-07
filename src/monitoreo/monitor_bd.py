#!/usr/bin/env python3
"""
monitor_bd.py
=============
Script para monitorear el progreso de ambos scripts en tiempo real.

USO:
    python monitor_bd.py              # muestra estado actual
    python monitor_bd.py --watch 5    # actualiza cada 5 segundos
    python monitor_bd.py --export     # exporta datos a CSV
"""

from src.config import ruta_datos
import sqlite3
import sys
import time
import json
import os
from datetime import datetime

# Detectar BD automáticamente (misma lógica que los otros scripts)
DB_PATH = os.environ.get(
    "DB_PATH",
    ruta_datos("base_marketing.db")
)
# Alternativamente, usar BD local si existe
if not os.path.exists(DB_PATH) and os.path.exists(ruta_datos("base_marketing.db")):
    DB_PATH = ruta_datos("base_marketing.db")
elif not os.path.exists(DB_PATH) and os.path.exists(ruta_datos("hoteles_colombia.db")):
    DB_PATH = ruta_datos("hoteles_colombia.db")

DB_TABLE = "contactos_marketing" if "base_marketing" in DB_PATH else "contactos_hoteles"
CHECKPOINT_ETT = ruta_datos("checkpoint_ett.json")
CHECKPOINT_EMAILS = ruta_datos("checkpoint_complete_emails.json")


def load_checkpoint(file):
    if os.path.exists(file):
        try:
            with open(file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}


def get_bd_stats():
    """Obtiene estadísticas de la BD."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        # Por nicho
        cur.execute(f"""
            SELECT nicho,
                   COUNT(*) as total,
                   SUM(CASE WHEN email IS NOT NULL AND email != '' THEN 1 ELSE 0 END) as con_email,
                   SUM(CASE WHEN email IS NULL OR email = '' THEN 1 ELSE 0 END) as sin_email
            FROM {DB_TABLE}
            GROUP BY nicho
            ORDER BY total DESC
        """)
        nichos = cur.fetchall()

        # Total general
        cur.execute(f"""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN email IS NOT NULL AND email != '' THEN 1 ELSE 0 END) as con_email
            FROM {DB_TABLE}
        """)
        total = cur.fetchone()

        conn.close()
        return nichos, total

    except Exception as e:
        print(f"❌ Error accediendo BD: {e}")
        return None, None


def show_status():
    """Muestra estado actual."""
    nichos, total = get_bd_stats()

    if not nichos:
        print("❌ No hay datos en la BD")
        return

    print("\n" + "="*80)
    print(f"📊 ESTADO GENERAL — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📁 BD: {DB_PATH}")
    print(f"📊 Tabla: {DB_TABLE}")
    print("="*80)

    print(f"\n{'NICHO':<40} {'TOTAL':>8} {'CON EMAIL':>12} {'SIN EMAIL':>12} {'%':>6}")
    print("-"*80)

    for nicho, total_n, con_email, sin_email in nichos:
        con_email = con_email or 0
        sin_email = sin_email or 0
        pct = (con_email / total_n * 100) if total_n > 0 else 0
        print(
            f"{nicho:<40} {total_n:>8} {con_email:>12} {sin_email:>12} {pct:>5.1f}%"
        )

    print("-"*80)
    total_all, con_email_all = total
    con_email_all = con_email_all or 0
    pct_all = (con_email_all / total_all * 100) if total_all > 0 else 0
    print(
        f"{'TOTAL':<40} {total_all:>8} {con_email_all:>12} {total_all - con_email_all:>12} {pct_all:>5.1f}%"
    )
    print("="*80)

    # Checkpoints
    print("\n📋 CHECKPOINTS:")
    print("-"*80)

    cp_ett = load_checkpoint(CHECKPOINT_ETT)
    if cp_ett:
        stats_ett = cp_ett.get("stats", {})
        completados_ett = len(cp_ett.get("maps_links_procesados", []))
        print(
            f"✓ {CHECKPOINT_ETT:<30} "
            f"| Maps: {completados_ett:>4} | "
            f"Emails: {stats_ett.get('emails', 0):>4} | "
            f"Sin resultado: {stats_ett.get('nada', 0):>4}"
        )
    else:
        print(f"⊘ {CHECKPOINT_ETT:<30} (sin iniciar)")

    cp_emails = load_checkpoint(CHECKPOINT_EMAILS)
    if cp_emails:
        stats_emails = cp_emails.get("stats", {})
        completados_emails = len(cp_emails.get("completados", []))
        print(
            f"✓ {CHECKPOINT_EMAILS:<30} "
            f"| Procesados: {completados_emails:>4} | "
            f"Emails: {stats_emails.get('emails_encontrados', 0):>4} | "
            f"Sin resultado: {stats_emails.get('sin_resultado', 0):>4}"
        )
    else:
        print(f"⊘ {CHECKPOINT_EMAILS:<30} (sin iniciar)")

    print("-"*80)


def export_csv():
    """Exporta empresas sin email a CSV."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        cur.execute(f"""
            SELECT id, nombre_empresa, nicho, ciudad, sitio_web, telefono
            FROM {DB_TABLE}
            WHERE email IS NULL OR email = ''
            ORDER BY nicho, nombre_empresa
        """)

        empresas = cur.fetchall()
        conn.close()

        filename = f"empresas_sin_email_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        with open(filename, "w", encoding="utf-8") as f:
            f.write("ID,Empresa,Nicho,Ciudad,Sitio Web,Teléfono\n")
            for row in empresas:
                f.write(
                    f'{row[0]},"{row[1]}","{row[2]}","{row[3] or ""}","{row[4] or ""}","{row[5] or ""}"\n'
                )

        print(f"✅ Exportado: {filename}")
        print(f"   Total empresas: {len(empresas)}")

    except Exception as e:
        print(f"❌ Error exportando: {e}")


def main():
    if "--export" in sys.argv:
        export_csv()
        return

    watch_interval = None
    for arg in sys.argv[1:]:
        if arg.startswith("--watch="):
            watch_interval = int(arg.split("=")[1])
        elif arg == "--watch":
            watch_interval = 5

    if watch_interval:
        print(f"🔄 Monitoreando cada {watch_interval} segundos (Ctrl+C para salir)\n")
        try:
            while True:
                show_status()
                time.sleep(watch_interval)
        except KeyboardInterrupt:
            print("\n\n👋 Monitor detenido")
    else:
        show_status()


if __name__ == "__main__":
    main()
