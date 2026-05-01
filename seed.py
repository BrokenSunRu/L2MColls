import json

# ==============================================================================
# РЕДАКТИРУЕМАЯ ЧАСТЬ
# ==============================================================================
# Добавь сюда все классы и агатионы из игры.
# Формат для классов: (Название, Редкость, Может ли Ascend, Может ли Elevate)
# Формат для агатионов: (Название, Редкость, Может ли Meld, Может ли Elevate, Может ли Spiritualize)

CLASSES_DATA = [
    # Common
    ("Human Warrior", "Common", False, False),
    ("Elven Scout", "Common", False, False),
    # Rare
    ("Sorcerer", "Rare", True, False),
    ("Paladin", "Rare", True, False),
    # Epic
    ("Warlord", "Epic", True, True),
    ("Moonlight Sentinel", "Epic", True, True),
    # Legend
    ("Eva's Templar", "Legend", True, True),
    ("Hell Knight", "Legend", True, True),
    # Mythic
    ("Raoul", "Mythic", True, True),
    ("Ertheia", "Mythic", True, True),
    # Zenith
    ("Zanna", "Zenith", True, True),
]

AGATHIONS_DATA = [
    ("Little Angel", "Common", False, False, False),
    ("Unicorn", "Rare", True, False, False),
    ("Griffin", "Epic", True, True, False),
    ("Baium", "Legend", True, True, True),
    ("Queen Ant", "Mythic", True, True, True),
]

# ==============================================================================
# ЛОГИКА СКРИПТА (не требует изменений)
# ==============================================================================

def main():
    payload = {"version": 1, "classes": [], "agathions": [], "collections": [], "owned": []}

    for name, rarity, can_ascend, can_elevate in CLASSES_DATA:
        payload["classes"].append({
            "name": name, "rarity": rarity,
            "can_ascend": can_ascend, "can_elevate": can_elevate
        })

    for name, rarity, can_meld, can_elevate, can_spiritualize in AGATHIONS_DATA:
        payload["agathions"].append({
            "name": name, "rarity": rarity,
            "can_meld": can_meld, "can_elevate": can_elevate, "can_spiritualize": can_spiritualize
        })

    output_filename = "seed_data.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"✅ Успешно сгенерирован '{output_filename}' с {len(payload['classes'])} классами и {len(payload['agathions'])} агатионами.")
    print("Теперь можно импортировать этот файл через интерфейс приложения.")

if __name__ == "__main__":
    main()