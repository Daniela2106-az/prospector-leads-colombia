#!/bin/bash

# Terminal 1: Offset 0-400
python enrich_cities.py --offset 0 --limit 400 > /tmp/enrich_terminal_1.log 2>&1 &
PID1=$!

# Terminal 2: Offset 400-800
python enrich_cities.py --offset 400 --limit 400 > /tmp/enrich_terminal_2.log 2>&1 &
PID2=$!

# Terminal 3: Offset 800-1200
python enrich_cities.py --offset 800 --limit 400 > /tmp/enrich_terminal_3.log 2>&1 &
PID3=$!

# Terminal 4: Offset 1200-1600
python enrich_cities.py --offset 1200 --limit 400 > /tmp/enrich_terminal_4.log 2>&1 &
PID4=$!

# Terminal 5: Offset 1600-2000
python enrich_cities.py --offset 1600 --limit 400 > /tmp/enrich_terminal_5.log 2>&1 &
PID5=$!

echo "✅ Ejecutando 5 terminales en paralelo:"
echo "  Terminal 1 (PID $PID1): Offset 0-400"
echo "  Terminal 2 (PID $PID2): Offset 400-800"
echo "  Terminal 3 (PID $PID3): Offset 800-1200"
echo "  Terminal 4 (PID $PID4): Offset 1200-1600"
echo "  Terminal 5 (PID $PID5): Offset 1600-2000"
echo ""
echo "Monitoreando progreso..."

# Monitorear progreso cada 30 segundos
while kill -0 $PID1 $PID2 $PID3 $PID4 $PID5 2>/dev/null; do
  sleep 30
  echo "[$(date '+%H:%M:%S')] Terminales activas..."
  for i in {1..5}; do
    log_file="/tmp/enrich_terminal_${i}.log"
    if [ -f "$log_file" ]; then
      encontradas=$(grep -c "✅" "$log_file" 2>/dev/null || echo "0")
      no_encontradas=$(grep -c "❌ No encontrada" "$log_file" 2>/dev/null || echo "0")
      echo "  Terminal $i: Encontradas=$encontradas, No encontradas=$no_encontradas"
    fi
  done
done

echo ""
echo "✅ TODAS LAS TERMINALES COMPLETADAS"
echo ""
echo "=== RESUMEN FINAL ==="
for i in {1..5}; do
  log_file="/tmp/enrich_terminal_${i}.log"
  if [ -f "$log_file" ]; then
    encontradas=$(grep -c "✅" "$log_file" 2>/dev/null || echo "0")
    no_encontradas=$(grep -c "❌ No encontrada" "$log_file" 2>/dev/null || echo "0")
    echo "Terminal $i: Encontradas=$encontradas, No encontradas=$no_encontradas"
  fi
done
