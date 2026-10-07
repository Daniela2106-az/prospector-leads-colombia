#!/usr/bin/env python3
from src.config import ruta_datos
import json
import sqlite3
import time
from datetime import datetime

CHECKPOINT_FILE = ruta_datos("checkpoint_complete_emails.json")
DB_FILE = ruta_datos("base_marketing.db")

def get_retail_status():
    with open(CHECKPOINT_FILE, 'r') as f:
        checkpoint = json.load(f)

    completados = set(checkpoint.get('completados', []))

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("SELECT id FROM contactos_marketing WHERE nicho = 'Retail / Comercio' AND (email IS NULL OR email = '')")
    retail_ids = set(row[0] for row in cur.fetchall())
    retail_comp = retail_ids & completados

    conn.close()

    return {
        'total': len(retail_ids),
        'completados': len(retail_comp),
        'pendientes': len(retail_ids) - len(retail_comp),
        'porcentaje': round(100 * len(retail_comp) / len(retail_ids), 1),
        'timestamp': datetime.now()
    }

# Estado anterior
prev_status = get_retail_status()
prev_time = prev_status['timestamp']

print("🚀 MONITOR RETAIL - Presiona Ctrl+C para detener\n")
print(f"Inicio: {prev_status['timestamp'].strftime('%H:%M:%S')}")
print("="*80)

while True:
    time.sleep(30)  # Actualiza cada 30 segundos

    curr_status = get_retail_status()
    curr_time = curr_status['timestamp']

    # Cálculos
    elapsed_seconds = (curr_time - prev_time).total_seconds()
    registros_avance = curr_status['completados'] - prev_status['completados']
    vel_por_minuto = registros_avance / (elapsed_seconds / 60) if elapsed_seconds > 0 else 0
    vel_por_hora = vel_por_minuto * 60

    falta = curr_status['pendientes']
    if vel_por_hora > 0:
        horas_restantes = falta / vel_por_hora
        horas = int(horas_restantes)
        minutos = int((horas_restantes % 1) * 60)
    else:
        horas = minutos = 0

    # Mostrar
    timestamp = curr_time.strftime('%H:%M:%S')
    print(f"\n[{timestamp}] Completados: {curr_status['completados']:4}/{curr_status['total']:4} ({curr_status['porcentaje']:5.1f}%)")
    print(f"             Pendientes: {falta:,}")
    print(f"             Avance últimos 30s: +{registros_avance} registros")
    print(f"             Velocidad: {vel_por_hora:.1f} reg/hora ({vel_por_minuto:.2f} reg/min)")

    if vel_por_hora > 0:
        print(f"             ⏱️  Tiempo faltante: {horas}h {minutos}m")

    # Actualizar para próxima iteración
    prev_status = curr_status
    prev_time = curr_time
