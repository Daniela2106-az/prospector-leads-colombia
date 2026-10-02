#!/bin/bash

echo "═══════════════════════════════════════════════════════════"
echo "📊 MONITOREO DE PROGRESO - $(date '+%H:%M:%S')"
echo "═══════════════════════════════════════════════════════════"
echo ""

for i in {1..5}; do
  offset=$(( (i-1)*400 ))
  log="/tmp/terminal_${i}.log"
  
  if [ -f "$log" ]; then
    # Contar hallazgos
    encontradas=$(grep -c "✅" "$log" 2>/dev/null | grep -v "Completado" || echo "0")
    no_encontradas=$(grep -c "❌ No encontrada" "$log" 2>/dev/null || echo "0")
    
    # Obtener registro actual
    registro_actual=$(grep -o "\[[0-9]*/400\]" "$log" 2>/dev/null | tail -1 | grep -o "[0-9]*" | head -1)
    
    if [ -z "$registro_actual" ]; then
      registro_actual="0"
    fi
    
    # Calcular progreso
    progreso=$(( registro_actual * 100 / 400 ))
    
    # Estimar tiempo restante (18 segundos por registro)
    registros_restantes=$(( 400 - registro_actual ))
    tiempo_restante=$(( registros_restantes * 18 / 60 ))
    
    echo "Terminal $i (offset $offset-$(( offset+400 ))):"
    echo "  📍 Progreso: [$registro_actual/400] - $progreso%"
    echo "  ✅ Encontradas: $encontradas"
    echo "  ❌ No encontradas: $no_encontradas"
    echo "  ⏱️  Tiempo restante estimado: ~${tiempo_restante} minutos"
    
    # Barra de progreso
    filled=$(( progreso / 5 ))
    empty=$(( 20 - filled ))
    printf "  Barra: ["
    printf "%-${filled}s" | tr ' ' '█'
    printf "%-${empty}s" | tr ' ' '░'
    printf "] %3d%%\n" "$progreso"
    echo ""
  fi
done

# Verificar si algún proceso terminó
active_processes=$(ps aux | grep "enrich_cities.py --offset" | grep -v grep | wc -l)
echo "📊 Procesos activos: $active_processes/5"
echo ""

if [ $active_processes -eq 0 ]; then
  echo "✅ TODOS LOS PROCESOS COMPLETADOS"
else
  echo "⏳ Próxima actualización en 15 minutos..."
fi

echo "═══════════════════════════════════════════════════════════"
