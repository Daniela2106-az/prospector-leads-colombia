#!/bin/bash
PROY="$(cd "$(dirname "$0")/.." && pwd)"

cd $PROY

# Ciudades para prospector_ett (6 terminales)
ciudades=("Bogotá" "Medellín" "Cali" "Barranquilla" "Cartagena" "Santa Marta")

# Nichos para complete_emails.py (5 terminales)
nichos=("Hotelería" "Retail / Comercio" "Restaurantes y Bares" "Industrial / Manufactura" "Salud y Bienestar")

echo "🚀 Lanzando 6 procesos de prospector_ett (por ciudad)..."
for ciudad in "${ciudades[@]}"; do
  osascript -e "tell app \"Terminal\" to do script \"cd $PROY && python -m src.descubrimiento.prospector_ett --ciudad='$ciudad'\""
  sleep 1
done

echo "🚀 Lanzando 5 procesos de complete_emails.py (por nicho)..."
for nicho in "${nichos[@]}"; do
  osascript -e "tell app \"Terminal\" to do script \"cd $PROY && python -m src.emails.completar_emails --nicho='$nicho'\""
  sleep 1
done

echo "✅ Todos los 11 procesos han sido lanzados en terminales separadas"
