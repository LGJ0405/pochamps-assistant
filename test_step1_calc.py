# -*- coding: utf-8 -*-
"""
test_step1_calc.py
Step 1 계산 엔진 통합 테스트

실행:
    python -m pytest test_step1_calc.py -v
"""

import json
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.schemas import PokemonInput, StatSpread, CalcRequest, FieldInput
from src.calc_bridge import CalcBridge


def test_basic_damage_calc():
    """기본 데미지 계산: 한카리아스(지진) → 메타그로스"""
    attacker = PokemonInput(
        species="Garchomp",
        level=50,
        item="Life Orb",
        ability="Rough Skin",
        nature="Jolly",
        evs=StatSpread(hp=0, atk=252, def_=0, spa=0, spd=0, spe=252),
    )
    defender = PokemonInput(
        species="Metagross",
        level=50,
        ability="Clear Body",
        nature="Adamant",
        evs=StatSpread(hp=252, atk=0, def_=0, spa=0, spd=0, spe=0),
    )
    request = CalcRequest(attacker=attacker, defender=defender, move="Earthquake")

    with CalcBridge() as bridge:
        result = bridge.calculate(request)

    assert result.ok, f"계산 실패: {result.error}"
    assert result.damage is not None, "데미지 결과가 없습니다"
    assert len(result.desc) > 0, "설명이 비어 있습니다"
    print(f"\n✅ 기본 데미지 계산 성공")
    print(f"   {result.desc}")


def test_field_weather_calc():
    """날씨 효과: 리자몽(불대문자, 맑음) → 메타그로스"""
    attacker = PokemonInput(
        species="Charizard",
        level=50,
        ability="Blaze",
        nature="Timid",
        evs=StatSpread(spa=252, spe=252),
    )
    defender = PokemonInput(
        species="Metagross",
        level=50,
        ability="Clear Body",
        nature="Adamant",
        evs=StatSpread(hp=252, def_=128, spd=128),
    )
    field = FieldInput(weather="Sun")
    request = CalcRequest(
        attacker=attacker,
        defender=defender,
        move="Fire Blast",
        field=field,
    )

    with CalcBridge() as bridge:
        result = bridge.calculate(request)

    assert result.ok, f"계산 실패: {result.error}"
    print(f"\n✅ 날씨 효과 데미지 계산 성공")
    print(f"   {result.desc}")


def test_dict_based_calc():
    """딕셔너리 기반 직접 계산"""
    req = {
        "attacker": {
            "species": "Pikachu",
            "level": 50,
            "item": "Light Ball",
            "ability": "Static",
            "nature": "Timid",
            "evs": {"spa": 252, "spe": 252},
        },
        "defender": {
            # "species": "Ninetales-Alola",   # 리전폼은 이렇게
            # "species": "Garchomp-Mega",   # 메진은 이렇게
            # "species": "Lucario-Mega-Z",   # Z루카 특성 테스트
            "species": "Garchomp",
            "level": 50,
            # "ability": "Aura Guard",   # Z루카 특성 테스트
            "ability": "Rough Skin",
            "nature": "Jolly",
            "evs": {"hp":4, "atk": 252, "spe": 252},
        },
        "move": "Thunderbolt",
    }

    with CalcBridge() as bridge:
        result = bridge.calculate_dict(req)

    assert result["ok"], f"계산 실패: {result.get('error')}"
    print(f"\n✅ 딕셔너리 기반 계산 성공")
    print(f"   {result['result']['desc']}")


def test_speed_comparison():
    """스피드 비교: 한카리아스 vs 망나뇽"""
    garchomp = PokemonInput(
        species="Garchomp",
        level=50,
        nature="Jolly",
        evs=StatSpread(spe=252),
    )
    dragonite = PokemonInput(
        species="Dragonite",
        level=50,
        nature="Adamant",
        evs=StatSpread(hp=252, atk=252),
    )

    # 양쪽 다 attacker로 써서 스탯을 뽑아낸다
    request = CalcRequest(
        attacker=garchomp,
        defender=dragonite,
        move="Dragon Claw",  # 아무 기술이나 OK
    )

    with CalcBridge() as bridge:
        result = bridge.calculate(request)

    assert result.ok, f"계산 실패: {result.error}"
    atk_spe = result.attacker_stats.get("spe", 0)
    def_spe = result.defender_stats.get("spe", 0)
    print(f"\n✅ 스피드 비교")
    print(f"   한카리아스 스피드: {atk_spe}")
    print(f"   망나뇽 스피드:    {def_spe}")
    assert atk_spe > def_spe, "한카리아스가 망나뇽보다 빨라야 합니다"
    print(f"   → 한카리아스 선공!")


if __name__ == "__main__":
    # print("=" * 60)
    print("  포챔스 배틀 어시스턴트 - Step 1 계산 엔진 테스트")
    print("=" * 60)
    # test_basic_damage_calc() # 기본 데미지 계산
    # test_field_weather_calc() # 날씨 데미지 계산
    test_dict_based_calc()
    # test_speed_comparison() # 스피드 선공 계산
    # print("\n" + "=" * 60)
    # print("  모든 테스트 통과! 🎉")
    # print("=" * 60)
