# -*- coding: utf-8 -*-
"""
test_step2_data_link.py
Step 2: 한글 <-> 영어 데이터 링크 검증 및 포챔스 샘플 기반 데미지 계산 테스트

포함된 테스트:
1. test_ko_to_en_pokemon: ko_to_en.json 포켓몬 종족명 전체 계산 엔진 전수 검증
2. test_sample_data_link: my_team.json / meta_samples.json 한글 데이터 사전 매핑 검증
3. test_sample_damage_calc: 내 팀 vs 상대 메타 샘플 간의 포챔스 데미지 계산 및 스피드 비교

실행:
    python test_step2_data_link.py
"""

import json
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.schemas import CalcRequest
from src.calc_bridge import CalcBridge
from src.adapter import DataAdapter

_PROJECT_ROOT = Path(__file__).resolve().parent
_DATA_DIR = _PROJECT_ROOT / "data"


def test_ko_to_en_pokemon():
    """1. data/ko_to_en.json 의 pokemon 영문명 전체 계산 엔진 전수 검증"""
    data_path = _DATA_DIR / "ko_to_en.json"
    with open(data_path, "r", encoding="utf-8") as f:
        ko_to_en = json.load(f)

    pokemon_dict = ko_to_en.get("species", {})
    total = len(pokemon_dict)
    print(f"\n============================================================")
    print(f" [검증 1] ko_to_en.json 전체 {total}개 포켓몬 영문명 검증")
    print(f"============================================================")

    success_count = 0
    failed = []

    with CalcBridge() as bridge:
        for idx, (ko_name, en_name) in enumerate(pokemon_dict.items(), 1):
            req = {
                "attacker": {
                    "species": en_name,
                    "level": 50,
                },
                "defender": {
                    "species": "Pikachu",
                    "level": 50,
                },
                "move": "Thunderbolt",
            }
            res = bridge.calculate_dict(req)
            if res.get("ok"):
                success_count += 1
                # 30개 단위로 진행 상황 요약 출력
                if idx % 50 == 0 or idx == total:
                    print(f"   [{idx:3d}/{total}] 진행 중... (최근: {ko_name} ➔ {en_name} 통과)")
            else:
                err_msg = res.get("error", "알 수 없는 오류")
                failed.append((ko_name, en_name, err_msg))
                print(f"   [{idx:3d}/{total}] ❌ {ko_name} ({en_name}): {err_msg}")

    print(f"\n✅ 포켓몬 영문명 검증 완료: 성공 {success_count}/{total}개 (실패 {len(failed)}개)")
    if failed:
        print("\n❌ 실패 목록:")
        for ko, en, err in failed:
            print(f"  - {ko} ({en}): {err}")

    assert len(failed) == 0, f"총 {len(failed)}개의 포켓몬 영문명 검증에 실패했습니다."


def test_sample_data_link():
    """2. my_team.json과 meta_samples.json의 모든 한글 데이터가 사전에 유효한지 검증"""
    print(f"\n============================================================")
    print(f" [검증 2] 샘플 데이터 한글 ↔ 영어 매핑 링크 검증")
    print(f"============================================================")
    adapter = DataAdapter()

    files = [
        ("my_team.json", _DATA_DIR / "my_team.json"),
        ("meta_samples.json", _DATA_DIR / "meta_samples.json"),
    ]

    for fname, fpath in files:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)

        print(f"\n📁 [{fname}] 검증:")
        for poke_name, sample_list in data.items():
            for sample in sample_list:
                s_name = sample["name"]
                item = sample.get("item", "")
                ability = sample.get("ability", "")
                nature = sample.get("nature", "")
                moves = sample.get("moves", [])

                # 메가 정보
                gimmick = sample.get("gimmick", {})
                mega_info = gimmick.get("mega") if gimmick else None
                mega_form = mega_info.get("form") if mega_info else None
                mega_ability = mega_info.get("ability") if mega_info else None

                # 영어 매핑 확인
                species_en = adapter.to_species_en(s_name)
                item_en = adapter.to_item_en(item)
                ability_en = adapter.to_ability_en(ability)
                nature_en = adapter.to_nature_en(nature)
                moves_en = [adapter.to_move_en(m) for m in moves]

                print(f"   포켓몬: {s_name} ➔ {species_en}")
                print(f"      도구: {item} ➔ {item_en}")
                print(f"      특성: {ability} ➔ {ability_en}")
                print(f"      성격: {nature} ➔ {nature_en}")
                print(f"      기술: {moves} ➔ {moves_en}")

                if mega_form:
                    m_form_en = adapter.to_species_en(mega_form)
                    m_ab_en = adapter.to_ability_en(mega_ability)
                    print(f"      메가폼: {mega_form} ➔ {m_form_en} (특성: {mega_ability} ➔ {m_ab_en})")
                    assert m_form_en != mega_form, f"메가폼 [{mega_form}] 매핑 누락"

                # 검증: 한글과 영어가 같으면 사전에 누락된 것
                assert species_en != s_name, f"포켓몬 [{s_name}] 매핑 누락"
                assert item_en != item, f"도구 [{item}] 매핑 누락"
                assert ability_en != ability, f"특성 [{ability}] 매핑 누락"
                assert nature_en != nature, f"성격 [{nature}] 매핑 누락"
                for m_ko, m_en in zip(moves, moves_en):
                    assert m_en != m_ko, f"기술 [{m_ko}] 매핑 누락"

    print(f"\n✅ 샘플 데이터 전체 한영 링크 정상 확인 완료!")


def test_sample_damage_calc():
    """3. 내 파티 vs 상대 메타 샘플 간의 포챔스(Gen 0, 실수치 66) 데미지 계산 테스트"""
    print(f"\n============================================================")
    print(f" [검증 3] 내 팀 vs 상대 메타 샘플 포챔스 데미지 계산 테스트")
    print(f"============================================================")
    adapter = DataAdapter()

    # 1. 내 팀(캥카) 로드
    with open(_DATA_DIR / "my_team.json", "r", encoding="utf-8") as f:
        my_team = json.load(f)
    kangaskhan_sample = my_team["캥카"][0]
    attacker_input = adapter.sample_to_pokemon_input(kangaskhan_sample, use_mega=True)

    # 2. 상대 메타(보만다, 리자몽) 로드
    with open(_DATA_DIR / "meta_samples.json", "r", encoding="utf-8") as f:
        meta_samples = json.load(f)

    with CalcBridge() as bridge:
        # 캥카 vs 보만다
        salamence_sample = meta_samples["보만다"][0]
        defender_salamence = adapter.sample_to_pokemon_input(salamence_sample, use_mega=True)

        print(f"\n⚔️ [대진 1] {attacker_input.species} vs {defender_salamence.species}")
        for move_ko in kangaskhan_sample["moves"]:
            move_en = adapter.to_move_en(move_ko)
            req = CalcRequest(
                attacker=attacker_input,
                defender=defender_salamence,
                move=move_en,
                gen=0,  # 포챔스 규격
            )
            res = bridge.calculate(req)
            assert res.ok, f"계산 실패: {res.error}"
            print(f"   - {move_ko} ({move_en}): {res.desc}")

        # 캥카 vs 리자몽X
        charizard_sample = meta_samples["리자몽"][0]
        defender_charizard = adapter.sample_to_pokemon_input(charizard_sample, use_mega=True)

        print(f"\n⚔️ [대진 2] {attacker_input.species} vs {defender_charizard.species}")
        for move_ko in kangaskhan_sample["moves"]:
            move_en = adapter.to_move_en(move_ko)
            req = CalcRequest(
                attacker=attacker_input,
                defender=defender_charizard,
                move=move_en,
                gen=0,  # 포챔스 규격
            )
            res = bridge.calculate(req)
            assert res.ok, f"계산 실패: {res.error}"
            print(f"   - {move_ko} ({move_en}): {res.desc}")

    print(f"\n✅ 포챔스 샘플 기반 데미지 계산 전체 성공!")


if __name__ == "__main__":
    print("=" * 60)
    print("  포챔스 배틀 어시스턴트 - Step 2 데이터 링크 및 계산 테스트")
    print("=" * 60)
    test_ko_to_en_pokemon()
    test_sample_data_link()
    test_sample_damage_calc()
    print("\n" + "=" * 60)
    print("  🎉 Step 2 모든 테스트 통과!")
    print("=" * 60)
