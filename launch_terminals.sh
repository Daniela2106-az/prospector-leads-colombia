#!/bin/bash

cd /Users/danielaamaya/PycharmProjects/PythonProject

# Activar venv y lanzar cada proceso en su propia terminal
osascript -e "tell app \"Terminal\" to do script \"source /Users/danielaamaya/PycharmProjects/PythonProject/.venv/bin/activate && python prospector_ett.py --ciudad='Bogotá'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source /Users/danielaamaya/PycharmProjects/PythonProject/.venv/bin/activate && cd /Users/danielaamaya/PycharmProjects/PythonProject && python prospector_ett.py --ciudad='Medellín'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source /Users/danielaamaya/PycharmProjects/PythonProject/.venv/bin/activate && cd /Users/danielaamaya/PycharmProjects/PythonProject && python prospector_ett.py --ciudad='Cali'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source /Users/danielaamaya/PycharmProjects/PythonProject/.venv/bin/activate && cd /Users/danielaamaya/PycharmProjects/PythonProject && python prospector_ett.py --ciudad='Barranquilla'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source /Users/danielaamaya/PycharmProjects/PythonProject/.venv/bin/activate && cd /Users/danielaamaya/PycharmProjects/PythonProject && python prospector_ett.py --ciudad='Cartagena'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source /Users/danielaamaya/PycharmProjects/PythonProject/.venv/bin/activate && cd /Users/danielaamaya/PycharmProjects/PythonProject && python prospector_ett.py --ciudad='Santa Marta'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source /Users/danielaamaya/PycharmProjects/PythonProject/.venv/bin/activate && cd /Users/danielaamaya/PycharmProjects/PythonProject && python complete_emails.py --nicho='Hotelería'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source /Users/danielaamaya/PycharmProjects/PythonProject/.venv/bin/activate && cd /Users/danielaamaya/PycharmProjects/PythonProject && python complete_emails.py --nicho='Retail / Comercio'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source /Users/danielaamaya/PycharmProjects/PythonProject/.venv/bin/activate && cd /Users/danielaamaya/PycharmProjects/PythonProject && python complete_emails.py --nicho='Restaurantes y Bares'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source /Users/danielaamaya/PycharmProjects/PythonProject/.venv/bin/activate && cd /Users/danielaamaya/PycharmProjects/PythonProject && python complete_emails.py --nicho='Industrial / Manufactura'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source /Users/danielaamaya/PycharmProjects/PythonProject/.venv/bin/activate && cd /Users/danielaamaya/PycharmProjects/PythonProject && python complete_emails.py --nicho='Salud y Bienestar'\"" &

echo "✅ 11 terminales lanzadas con venv activado"
