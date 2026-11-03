# -*- coding: utf-8 -*-
"""
update_ko_to_en.py
data/csv/의 PokeAPI CSV(기술, 특성, 도구)를 파싱하여 data/ko_to_en.json에 동기화합니다.
도구(items)는 @smogon/calc 화이트리스트 및 비배틀 도구 필터를 거쳐 실전 배틀 도구만 자동 반영합니다.

실행:
    python scripts/update_ko_to_en.py
"""

import csv
import json
import re
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CSV_DIR = DATA_DIR / "csv"
JSON_PATH = DATA_DIR / "ko_to_en.json"

# 포획용 볼류 (단, 실전 배틀 도구인 Light Ball, Iron Ball은 제외)
NON_BATTLE_BALLS = {
    "Master Ball", "Ultra Ball", "Great Ball", "Safari Ball", "Net Ball",
    "Dive Ball", "Nest Ball", "Repeat Ball", "Timer Ball", "Luxury Ball",
    "Premier Ball", "Dusk Ball", "Heal Ball", "Quick Ball", "Cherish Ball",
    "Lure Ball", "Level Ball", "Moon Ball", "Heavy Ball", "Fast Ball",
    "Friend Ball", "Love Ball", "Park Ball", "Sport Ball", "Dream Ball",
    "Beast Ball", "Strange Ball", "Poké Ball", "Poke Ball"
}

# 배틀 효과 없는 순수 진화의 돌
EVOLUTION_STONES = {
    "Sun Stone", "Moon Stone", "Fire Stone", "Thunder Stone", "Water Stone",
    "Leaf Stone", "Shiny Stone", "Dusk Stone", "Dawn Stone", "Oval Stone",
    "Ice Stone"
}

# 단순 진화/환금/화석 아이템
NON_BATTLE_MISC = {
    "Cracked Pot", "Chipped Pot", "Galarica Cuff", "Galarica Wreath",
    "Syrupy Apple", "Unremarkable Teacup", "Masterpiece Teacup",
    "Metal Alloy", "Auspicious Armor", "Malicious Armor", "Rare Bone",
    "Old Amber"
}


def to_id(text: str) -> str:
    """쇼다운 toID 규칙 (영문, 숫자 소문자화)"""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def get_smogon_valid_items() -> set[str]:
    """@smogon/calc에서 지원하는 모든 실전 배틀 도구 영문 ID를 추출합니다."""
    node_code = """
const { Generations, ITEMS, MEGA_STONES } = require('@smogon/calc');
const set = new Set();

for (const genItems of ITEMS) {
    if (Array.isArray(genItems)) {
        for (const item of genItems) set.add(item);
    }
}
if (MEGA_STONES) {
    for (const stone of Object.keys(MEGA_STONES)) set.add(stone);
}
for (let g = 0; g <= 9; g++) {
    try {
        const gen = Generations.get(g);
        for (const item of gen.items) set.add(item.name);
    } catch (_) {}
}

process.stdout.write(JSON.stringify(Array.from(set)));
"""
    res = subprocess.run(
        ["node", "-e", node_code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(PROJECT_ROOT),
        check=True,
    )
    raw_list = json.loads(res.stdout)
    return {to_id(item) for item in raw_list}


def is_blacklisted(ko_name: str, en_name: str) -> bool:
    """구세대 스모곤 레거시 중 비배틀 아이템인지 판별"""
    # 1. 포획용 볼류
    if en_name in NON_BATTLE_BALLS:
        return True
    if en_name.endswith(" Ball") and en_name not in ("Light Ball", "Iron Ball", "Smoke Ball"):
        return True

    # 2. 기술머신 / 기술레코드 (TM / TR)
    if re.match(r"^T[MR]\d+$", en_name, re.IGNORECASE):
        return True
    if "기술머신" in ko_name or "기술레코드" in ko_name:
        return True

    # 3. 진화의 돌
    if en_name in EVOLUTION_STONES:
        return True

    # 4. 화석류
    if "Fossil" in en_name or "화석" in ko_name:
        return True

    # 5. 기타 비배틀 잡화
    if en_name in NON_BATTLE_MISC:
        return True

    # 6. 상처약 / 회복약 / 상태이상 치료제
    if any(k in ko_name for k in ("상처약", "해독제", "치료제", "회복약", "기력의", "만병통치제")):
        return True

    return False


def filter_battle_items(items: dict[str, str]) -> dict[str, str]:
    """도구 목록에서 실전 배틀 도구만 필터링합니다."""
    valid_ids = get_smogon_valid_items()
    filtered: dict[str, str] = {}
    for ko, en in items.items():
        if to_id(en) not in valid_ids:
            continue
        if is_blacklisted(ko, en):
            continue
        filtered[ko] = en
    return filtered


def parse_names(csv_path: Path, id_field: str) -> dict[str, str]:
    """local_language_id가 3(한국어)과 9(영어)인 행을 매핑합니다."""
    ko_dict: dict[str, str] = {}
    en_dict: dict[str, str] = {}

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            item_id = row[id_field]
            lang = row["local_language_id"]
            name = row["name"].strip()
            if not name:
                continue

            if lang == "3":
                ko_dict[item_id] = name
            elif lang == "9":
                en_dict[item_id] = name

    mapping: dict[str, str] = {}
    for item_id, ko_name in ko_dict.items():
        if item_id in en_dict:
            mapping[ko_name] = en_dict[item_id]

    return mapping


def main():
    if not JSON_PATH.exists():
        raise FileNotFoundError(f"{JSON_PATH} 파일이 없습니다.")

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. 기술(moves)
    move_csv = CSV_DIR / "move_names.csv"
    if move_csv.exists():
        new_moves = parse_names(move_csv, "move_id")
        orig_moves = data.get("moves", {})
        merged_moves = {**new_moves, **orig_moves}
        data["moves"] = merged_moves
        print(f"✅ 기술(moves): {len(data['moves'])}개 반영 완료")

    # 2. 특성(abilities)
    ability_csv = CSV_DIR / "ability_names.csv"
    if ability_csv.exists():
        new_abilities = parse_names(ability_csv, "ability_id")
        orig_abilities = data.get("abilities", {})
        merged_abilities = {**new_abilities, **orig_abilities}
        data["abilities"] = merged_abilities
        print(f"✅ 특성(abilities): {len(data['abilities'])}개 반영 완료")

    # 3. 도구(items) - 실전 배틀 도구 자동 필터링
    item_csv = CSV_DIR / "item_names.csv"
    if item_csv.exists():
        new_items = parse_names(item_csv, "item_id")
        orig_items = data.get("items", {})
        merged_items = {**new_items, **orig_items}
        filtered_items = filter_battle_items(merged_items)
        data["items"] = filtered_items
        print(f"✅ 도구(items): 실전 배틀 도구 {len(data['items'])}개 반영 완료 (전체 {len(merged_items)}개 중 상처약/볼/TM 등 비배틀 도구 자동 제외)")

    # UTF-8로 저장
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n🎉 data/ko_to_en.json 업데이트 완료!")


if __name__ == "__main__":
    main()
