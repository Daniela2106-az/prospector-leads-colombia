#!/bin/bash

cd /Users/danielaamaya/PycharmProjects/PythonProject

# Ciudades para prospector_ett (6 terminales)
ciudades=("Bogotá" "Medellín" "Cali" "Barranquilla" "Cartagena" "Santa Marta")

# Nichos para complete_emails.py (5 terminales)
nichos=("Hotelería" "Retail / Comercio" "Restaurantes y Bares" "Industrial / Manufactura" "Salud y Bienestar")

echo "🚀 Lanzando 6 procesos de prospector_ett (por ciudad)..."
for ciudad in "${ciudades[@]}"; do
  osascript -e "tell app \"Terminal\" to do script \"cd /Users/danielaamaya/PycharmProjects/PythonProject && python prospector_ett.py --ciudad='$ciudad'\""
  sleep 1
done

echo "🚀 Lanzando 5 procesos de complete_emails.py (por nicho)..."
for nicho in "${nichos[@]}"; do
  osascript -e "tell app \"Terminal\" to do script \"cd /Users/danielaamaya/PycharmProjects/PythonProject && python complete_emails.py --nicho='$nicho'\""
  sleep 1
done

echo "✅ Todos los 11 procesos han sido lanzados en terminales separadas"
