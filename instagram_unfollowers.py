#!/usr/bin/env python3
"""
Compara CSV de followers y following para encontrar quiénes no te siguen de vuelta
"""

import csv
from pathlib import Path

FOLLOWERS_FILE = "/Users/danielaamaya/Downloads/danielaamayaz_followers_1-484.csv"
FOLLOWING_FILE = "/Users/danielaamaya/Downloads/danielaamayaz_following_1-493.csv"
OUTPUT_FILE = "/Users/danielaamaya/Downloads/unfollowers.txt"

def read_csv_usernames(filepath):
    """Lee un CSV y extrae los usernames"""
    usernames = set()

    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            username = row.get('userName', '').strip()
            if username:
                usernames.add(username.lower())

    return usernames

def main():
    print("\n" + "="*60)
    print("📊 ANALIZANDO FOLLOWERS Y FOLLOWING")
    print("="*60)

    # Leer datos
    print("\n📖 Leyendo followers...")
    followers = read_csv_usernames(FOLLOWERS_FILE)
    print(f"   ✅ {len(followers)} seguidores")

    print("📖 Leyendo following...")
    following = read_csv_usernames(FOLLOWING_FILE)
    print(f"   ✅ {len(following)} seguidos")

    # Calcular no-followers
    unfollowers = following - followers

    print("\n" + "="*60)
    print("📊 RESULTADO")
    print("="*60)
    print(f"Total que sigues        : {len(following)}")
    print(f"Total seguidores        : {len(followers)}")
    print(f"NO te siguen de vuelta  : {len(unfollowers)}")
    print("="*60)

    # Mostrar lista
    if unfollowers:
        print(f"\n👥 USUARIOS QUE NO TE SIGUEN DE VUELTA ({len(unfollowers)}):")
        print("-"*60)
        for i, username in enumerate(sorted(unfollowers), 1):
            print(f"{i:3d}. @{username}")
        print("-"*60)

        # Guardar a archivo
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write("USUARIOS QUE NO TE SIGUEN DE VUELTA\n")
            f.write("="*60 + "\n\n")
            for i, username in enumerate(sorted(unfollowers), 1):
                f.write(f"{i}. @{username}\n")

        print(f"\n💾 Guardado en: {OUTPUT_FILE}")
    else:
        print("\n✅ ¡Todos los que sigues te siguen de vuelta!")

if __name__ == "__main__":
    main()
