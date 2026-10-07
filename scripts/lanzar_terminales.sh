#!/bin/bash
PROY="$(cd "$(dirname "$0")/.." && pwd)"

cd $PROY

# Activar venv y lanzar cada proceso en su propia terminal
osascript -e "tell app \"Terminal\" to do script \"source $PROY/.venv/bin/activate && python -m src.descubrimiento.prospector_ett --ciudad='Bogotá'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source $PROY/.venv/bin/activate && cd $PROY && python -m src.descubrimiento.prospector_ett --ciudad='Medellín'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source $PROY/.venv/bin/activate && cd $PROY && python -m src.descubrimiento.prospector_ett --ciudad='Cali'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source $PROY/.venv/bin/activate && cd $PROY && python -m src.descubrimiento.prospector_ett --ciudad='Barranquilla'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source $PROY/.venv/bin/activate && cd $PROY && python -m src.descubrimiento.prospector_ett --ciudad='Cartagena'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source $PROY/.venv/bin/activate && cd $PROY && python -m src.descubrimiento.prospector_ett --ciudad='Santa Marta'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source $PROY/.venv/bin/activate && cd $PROY && python -m src.emails.completar_emails --nicho='Hotelería'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source $PROY/.venv/bin/activate && cd $PROY && python -m src.emails.completar_emails --nicho='Retail / Comercio'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source $PROY/.venv/bin/activate && cd $PROY && python -m src.emails.completar_emails --nicho='Restaurantes y Bares'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source $PROY/.venv/bin/activate && cd $PROY && python -m src.emails.completar_emails --nicho='Industrial / Manufactura'\"" &
sleep 2

osascript -e "tell app \"Terminal\" to do script \"source $PROY/.venv/bin/activate && cd $PROY && python -m src.emails.completar_emails --nicho='Salud y Bienestar'\"" &

echo "✅ 11 terminales lanzadas con venv activado"
