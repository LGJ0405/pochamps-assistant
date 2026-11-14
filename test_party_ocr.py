# -*- coding: utf-8 -*-
"""
test_party_ocr.py
한국어 PP-OCRv4 모델 기반 내 파티 스크린샷 6마리(기술 4개, 특성, 지닌물건, 성격, 노력치 분배) OCR 단위 테스트

실행:
    $env:PYTHONIOENCODING="utf-8"
    python test_party_ocr.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.vision import KoreanOCR, PartyParser, imread_safe

SCREENSHOTS_DIR = PROJECT_ROOT / "tests" / "screenshots"
MOVES_ITEMS_PATH = SCREENSHOTS_DIR / "team_moves_items.png"
STATS_EVS_PATH = SCREENSHOTS_DIR / "team_stats_evs.png"
MY_TEAM_JSON_PATH = PROJECT_ROOT / "data" / "my_team.json"


def test_korean_fuzzy_matcher():
    """1. 폰트 왜곡 오타에 대한 공식 DB 기반 Fuzzy Matching 자동 교정 검증"""
    parser = PartyParser(ocr_engine=None)
    test_cases = [
        ("스케일삿", "moves", "스케일샷", "Scale Shot"),
        ("번개편치", "moves", "번개펀치", "Thunder Punch"),
        ("새도볼", "moves", "섀도볼", "Shadow Ball"),
        ("기합의미", "items", "기합의띠", "Focus Sash"),
        ("생명의구술", "items", "생명의구슬", "Life Orb"),
        ("미러아모", "abilities", "미러아머", "Mirror Armor"),
    ]

    for raw, cat, exp_ko, exp_en in test_cases:
        ko, en = parser.fuzzy_match(raw, cat, cutoff=0.45)
        assert ko == exp_ko, f"Fuzzy matching 실패: {raw} -> {ko} (기대: {exp_ko})"
        assert en == exp_en, f"English slug 변환 실패: {raw} -> {en} (기대: {exp_en})"

    print("✅ [테스트 1] Fuzzy Matching 오타 자동 보정 검증 통과")


def test_party_screenshots_ocr():
    """2. 파티 스크린샷 2종으로부터 6마리 전원(기술 4개, 특성, 지닌물건, 성격, 노력치) 파싱 및 my_team.json 저장 검증"""
    assert MOVES_ITEMS_PATH.exists(), f"테스트 스크린샷 부재: {MOVES_ITEMS_PATH}"
    assert STATS_EVS_PATH.exists(), f"테스트 스크린샷 부재: {STATS_EVS_PATH}"

    t0 = time.perf_counter()
    img_moves = imread_safe(MOVES_ITEMS_PATH)
    img_stats = imread_safe(STATS_EVS_PATH)

    ocr = KoreanOCR()
    parser = PartyParser(ocr_engine=ocr)

    team = parser.parse_full_team(img_moves, img_stats)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert len(team) == 6, f"파티 슬롯 수 오류: {len(team)}"

    # 6마리 실제 화면 기대 데이터 정의 (노력치 총합 66 체계)
    expected_team = {
        1: {
            "species": "아머까오",
            "ability": "미러아머",
            "item": "울퉁불퉁멧",
            "moves": ["날개쉬기", "유턴", "바디프레스", "철벽"],
            "nature": "장난꾸러기",
            "evs": {"hp": 32, "atk": 2, "def": 32, "spa": 0, "spd": 0, "spe": 0},
        },
        2: {
            "species": "타부자고",
            "ability": "황금몸",
            "item": "풍선",
            "moves": ["골드러시", "섀도볼", "나쁜음모", "HP회복"],
            "nature": "조심",
            "evs": {"hp": 29, "atk": 0, "def": 0, "spa": 19, "spd": 0, "spe": 18},
        },
        3: {
            "species": "마스카나",
            "ability": "변환자재",
            "item": "생명의구슬",
            "moves": ["트릭플라워", "트리플악셀", "번개펀치", "속임수"],
            "nature": "명랑",
            "evs": {"hp": 0, "atk": 32, "def": 2, "spa": 0, "spd": 0, "spe": 32},
        },
        4: {
            "species": "킬라플로르",
            "ability": "독치장",
            "item": "킬라플로르나이트",
            "moves": ["오물웨이브", "대지의힘", "니들가드", "파워젬"],
            "nature": "겁쟁이",
            "evs": {"hp": 3, "atk": 0, "def": 0, "spa": 31, "spd": 0, "spe": 32},
        },
        5: {
            "species": "한카리아스",
            "ability": "까칠한피부",
            "item": "기합의띠",
            "moves": ["지진", "스케일샷", "암석봉인", "스텔스록"],
            "nature": "고집",
            "evs": {"hp": 2, "atk": 32, "def": 0, "spa": 0, "spd": 0, "spe": 32},
        },
        6: {
            "species": "팬텀",
            "ability": "저주받은바디",
            "item": "팬텀나이트",
            "moves": ["섀도볼", "오물웨이브", "얼어붙은바람", "길동무"],
            "nature": "겁쟁이",
            "evs": {"hp": 12, "atk": 0, "def": 4, "spa": 20, "spd": 0, "spe": 30},
        },
    }

    # 6마리 전원 엄격 검증
    for p in team:
        exp = expected_team[p.slot]
        assert p.species_ko == exp["species"], f"슬롯 {p.slot} 포켓몬 오류: {p.species_ko} != {exp['species']}"
        assert p.ability_ko == exp["ability"], f"슬롯 {p.slot} 특성 오류: {p.ability_ko} != {exp['ability']}"
        assert p.item_ko == exp["item"], f"슬롯 {p.slot} 지닌물건 오류: {p.item_ko} != {exp['item']}"
        assert len(p.moves_ko) == 4, f"슬롯 {p.slot} 기술 개수 부족: {p.moves_ko}"
        assert p.moves_ko == exp["moves"], f"슬롯 {p.slot} 기술배치 불일치: {p.moves_ko} != {exp['moves']}"
        assert p.nature_ko == exp["nature"], f"슬롯 {p.slot} 성격 오류: {p.nature_ko} != {exp['nature']}"
        assert p.evs == exp["evs"], f"슬롯 {p.slot} 노력치 불일치: {p.evs} != {exp['evs']}"
        assert p.total_evs == 66, f"슬롯 {p.slot} 노력치 총합 오류: {p.total_evs} != 66"

    print(f"✅ [테스트 2] 6마리 전원(기술 4개씩 총 24개, 특성, 도구, 성격, 노력치 총합 66) 완전 일치 검증 통과 ({elapsed_ms:.1f}ms)")

    # 3. data/my_team.json 자동 갱신 및 파일 검증 (team1 단위)
    saved_path = PartyParser.save_team_to_json(team, MY_TEAM_JSON_PATH, team_name="team1")
    assert saved_path.exists(), "my_team.json 저장 실패"

    with open(saved_path, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert "team1" in saved_data, "my_team.json에 'team1' 키 누락"
    team1_members = saved_data["team1"]
    assert len(team1_members) == 6, f"team1 포켓몬 개수 불일치: {len(team1_members)}"

    member_names = [m["name"] for m in team1_members]
    for expected_name in ["아머까오", "타부자고", "마스카나", "킬라플로르", "한카리아스", "팬텀"]:
        assert expected_name in member_names, f"team1에 {expected_name} 누락"
    print(f"✅ [테스트 3] data/my_team.json 'team1' 6마리 파티 데이터 자동 갱신 및 무결성 확인 완료")

    # 파티 종합 요약 테이블 출력
    print("\n" + "=" * 98)
    print("  📋 내 파티 6마리 완전 파싱 요약 결과 (포챔스 66 체계)")
    print("=" * 98)
    header = f"{'슬롯':^4} | {'포켓몬':^8} | {'성격':^6} | {'특성':^8} | {'지닌물건':^12} | {'기술배치 (4개)':^32} | {'노력치 분배 (합계 66)':^22}"
    print(header)
    print("-" * 98)
    for p in team:
        moves_str = ", ".join(p.moves_ko)
        ev = p.evs
        evs_str = f"H{ev['hp']} A{ev['atk']} B{ev['def']} C{ev['spa']} D{ev['spd']} S{ev['spe']}"
        print(
            f" #{p.slot}  | {p.species_ko:^8} | {p.nature_ko:^6} | {p.ability_ko:^8} | {p.item_ko:^12} | {moves_str:<32} | {evs_str:^22}"
        )
    print("=" * 98)


if __name__ == "__main__":
    print("=" * 60)
    print("  포챔스 배틀 어시스턴트 - 한국어 PP-OCRv4 파티 OCR 단위 테스트")
    print("=" * 60)

    test_korean_fuzzy_matcher()
    test_party_screenshots_ocr()

    print("\n" + "=" * 60)
    print("  🎉 6마리 전원 모든 정보(기술 4개/특성/도구/성격/노력치) 검증 통과!")
    print("=" * 60)
