#!/usr/bin/env python3
"""
instagram_unfollowers_v2.py
===========================
Bot para encontrar no-followers con LOGIN MANUAL via Selenium.

Flujo:
  1. Abre Chrome con Instagram
  2. TÚ inicia sesión manualmente (evita bloqueos)
  3. Script guarda sesión
  4. Hace scraping automático

USO:
    pip install instagrapi selenium webdriver-manager
    python instagram_unfollowers_v2.py
"""

import json
import time
import random
import logging
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

try:
    from instagrapi import Client
except ImportError:
    print("❌ instagrapi no instalado. Instala con: pip install instagrapi")
    exit(1)

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
LOG_FILE = "instagram_unfollowers_v2.log"
REPORT_FILE = "unfollowers_report.json"
COOKIES_FILE = "instagram_cookies.json"

DELAY_BETWEEN_REQUESTS_MIN = 3.0
DELAY_BETWEEN_REQUESTS_MAX = 8.0
DELAY_BETWEEN_BATCHES_MIN = 10.0
DELAY_BETWEEN_BATCHES_MAX = 15.0

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ─── SELENIUM ─────────────────────────────────────────────────────────────────
def get_chrome_driver():
    """Crea driver de Chrome."""
    opts = Options()
    opts.add_argument("--start-maximized")
    opts.add_argument("--lang=es")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    return driver


def manual_login_and_get_cookies(username: str) -> dict:
    """
    Abre Chrome, tú inicia sesión manualmente, guarda cookies.
    """
    print("\n" + "="*60)
    print("🔐 LOGIN MANUAL VIA CHROME")
    print("="*60)
    print("\n📍 Se abrirá Chrome con Instagram.")
    print("✋ INICIA SESIÓN MANUALMENTE en el navegador.")
    print("✋ Cuando estés dentro, cierra el navegador.")
    print("✋ El script guardará tu sesión automáticamente.\n")

    driver = get_chrome_driver()

    try:
        log.info("🌐 Abriendo Instagram...")
        driver.get("https://www.instagram.com/")

        # Esperar a que el usuario inicie sesión manualmente
        print("⏳ Esperando que iniques sesión manualmente...")
        print("   (Cierra el navegador cuando hayas iniciado sesión)\n")

        # Esperar a que aparezca la URL del perfil o la página principal
        input("Presiona ENTER cuando hayas cerrado el navegador: ")

        log.info("📸 Guardando cookies...")
        cookies = driver.get_cookies()

        # Guardar cookies en archivo
        with open(COOKIES_FILE, "w") as f:
            json.dump(cookies, f)

        log.info(f"✅ Cookies guardadas en {COOKIES_FILE}")
        return cookies

    except Exception as e:
        log.error(f"❌ Error: {e}")
        return None

    finally:
        driver.quit()


def get_following_via_web(driver, username: str) -> set:
    """Obtiene lista de seguidos vía web scraping."""
    log.info(f"📋 Obteniendo seguidos para @{username}...")

    try:
        driver.get(f"https://www.instagram.com/{username}/")
        time.sleep(3)

        # Hacer clic en "Seguidos"
        following_button = driver.find_element("xpath", "//a[contains(@href, 'following')]")
        following_button.click()
        time.sleep(3)

        following_usernames = set()
        last_height = driver.execute_script("return document.body.scrollHeight")

        while True:
            usernames = driver.find_elements("xpath", "//a[@title]")
            for user in usernames:
                username_text = user.get_attribute("title")
                if username_text:
                    following_usernames.add(username_text)

            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)

            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        log.info(f"✅ Total seguidos: {len(following_usernames)}")
        return following_usernames

    except Exception as e:
        log.error(f"❌ Error: {e}")
        return set()


def delay_random(min_sec: float, max_sec: float):
    """Espera aleatorio."""
    wait = random.uniform(min_sec, max_sec)
    time.sleep(wait)


def get_user_followers_count(cl: Client, username: str) -> int:
    """Obtiene cantidad de seguidores de un usuario."""
    try:
        user = cl.user_info_by_username(username)
        return user.follower_count
    except Exception as e:
        log.warning(f"⚠️ Error obteniendo info de @{username}: {e}")
        return 999999  # Si no puede obtener, asumir > 2000


def filter_by_followers(cl: Client, unfollowers: set, max_followers: int = 2000) -> dict:
    """Filtra unfollowers por número de seguidores."""
    log.info(f"🔍 Filtrando por < {max_followers} seguidores...")

    filtered = {}
    total = len(unfollowers)

    for i, username in enumerate(unfollowers, 1):
        followers_count = get_user_followers_count(cl, username)

        if followers_count < max_followers:
            filtered[username] = {"followers": followers_count}
            log.info(f"  [{i}/{total}] @{username} - {followers_count} seguidores")

        if i % 5 == 0:
            delay_random(DELAY_BETWEEN_BATCHES_MIN, DELAY_BETWEEN_BATCHES_MAX)
        else:
            delay_random(DELAY_BETWEEN_REQUESTS_MIN, DELAY_BETWEEN_REQUESTS_MAX)

    log.info(f"✅ Encontrados {len(filtered)} que cumplen criterio")
    return filtered


def save_report(unfollowers: dict):
    """Guarda reporte."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "total_unfollowers": len(unfollowers),
        "filtered_max_followers": 2000,
        "data": unfollowers,
    }

    try:
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        log.info(f"✅ Reporte guardado: {REPORT_FILE}")
    except Exception as e:
        log.error(f"❌ Error guardando reporte: {e}")


def main():
    """Ejecuta el bot."""
    print("\n" + "="*60)
    print("  INSTAGRAM UNFOLLOWERS BOT v2 (Manual Login)")
    print("="*60)

    username = input("\n📱 Tu usuario de Instagram: ").strip()

    if not username:
        print("❌ Usuario es obligatorio")
        return

    # Paso 1: Login manual
    print("\n" + "="*60)
    print("PASO 1: LOGIN MANUAL")
    print("="*60)

    cookies = manual_login_and_get_cookies(username)
    if not cookies:
        return

    # Paso 2: Conectar con instagrapi
    print("\n" + "="*60)
    print("PASO 2: CONECTANDO A INSTAGRAM API")
    print("="*60)

    try:
        cl = Client()

        # Cargar cookies guardadas
        with open(COOKIES_FILE, "r") as f:
            cookies_list = json.load(f)

        # Convertir lista de cookies a diccionario
        cookies_dict = {cookie['name']: cookie['value'] for cookie in cookies_list}
        cl.set_cookies(cookies_dict)

        log.info("✅ Sesión cargada exitosamente")
    except Exception as e:
        log.error(f"❌ Error cargando sesión: {e}")
        log.info("💡 Intenta de nuevo. A veces Instagram necesita reintentos.")
        return

    # Paso 3: Obtener datos
    print("\n" + "="*60)
    print("PASO 3: OBTENIENDO DATOS")
    print("="*60)

    try:
        # Obtener info del usuario
        user = cl.user_info_by_username(username)
        following_count = user.following_count
        followers_count = user.follower_count

        log.info(f"👤 @{username}")
        log.info(f"   Seguidos: {following_count}")
        log.info(f"   Seguidores: {followers_count}")

        # Obtener seguidos
        log.info(f"\n📋 Obteniendo lista de {following_count} seguidos...")
        user_id = user.pk
        following = cl.user_following(user_id)
        following_usernames = {u.username for u in following}
        log.info(f"✅ Total seguidos obtenidos: {len(following_usernames)}")

        delay_random(DELAY_BETWEEN_BATCHES_MIN, DELAY_BETWEEN_BATCHES_MAX)

        # Obtener seguidores
        log.info(f"\n👥 Obteniendo lista de {followers_count} seguidores...")
        followers = cl.user_followers(user_id)
        followers_usernames = {u.username for u in followers}
        log.info(f"✅ Total seguidores obtenidos: {len(followers_usernames)}")

        # Paso 4: Comparar
        print("\n" + "="*60)
        print("PASO 4: COMPARANDO")
        print("="*60)

        unfollowers = following_usernames - followers_usernames
        log.info(f"👎 No te siguen de vuelta: {len(unfollowers)}")

        # Paso 5: Filtrar
        print("\n" + "="*60)
        print("PASO 5: FILTRANDO POR SEGUIDORES")
        print("="*60)

        filtered = filter_by_followers(cl, unfollowers, max_followers=2000)

        # Paso 6: Guardar reporte
        print("\n" + "="*60)
        print("PASO 6: GUARDANDO REPORTE")
        print("="*60)

        save_report(filtered)

        # Resumen
        print("\n" + "="*60)
        print("RESUMEN")
        print("="*60)
        print(f"Total seguidos        : {len(following_usernames)}")
        print(f"Total seguidores      : {len(followers_usernames)}")
        print(f"No te siguen de vuelta: {len(unfollowers)}")
        print(f"< 2000 seguidores     : {len(filtered)} 👈")
        print("="*60)

        # Lista
        if filtered:
            print("\n👥 USUARIOS QUE NO TE SIGUEN DE VUELTA (< 2000 seguidores):")
            print("-"*60)
            for i, (user, info) in enumerate(sorted(filtered.items(),
                                                    key=lambda x: x[1]['followers'],
                                                    reverse=True), 1):
                print(f"{i:3d}. @{user:<25} | {info['followers']:>6} seguidores")
            print("-"*60)

        print(f"\n📄 Reporte completo: {REPORT_FILE}")

    except Exception as e:
        log.error(f"❌ Error: {e}")

    finally:
        log.info("\n🏁 Bot finalizado")


if __name__ == "__main__":
    main()
