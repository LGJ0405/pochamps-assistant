# -*- coding: utf-8 -*-
"""
test_battle_state.py
배틀 상태 엔진(BattleStateTracker) 단위 테스트:
1. 번치코 가속(Speed Boost) 시계열 턴 경과별 스피드 +1랭크 누적 및 선후공 역전 감지 검증
2. 포켓몬 교체 시 랭크업 초기화 검증
3. 메가진화 도구/특성 자동 확정 (갸라도스나이트, 틀깨기) 검증
4. 기합의띠(Focus Sash) 발동 및 소모 추론 검증
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.battle_advisor import BattleAdvisor


def test_speed_boost_and_speed_reversal():
    """번치코 가속 특성으로 인한 턴 경과별 스피드 랭크업 및 선후공 역전 검증"""
    print("\n============================================================")
    print(" [검증 1] 번치코 가속(Speed Boost) 턴 경과별 스피드 랭크업 & 선후공 역전")
    print("============================================================")

    advisor = BattleAdvisor()
    advisor.reset_session()

    try:
        # Turn 1: 한카리아스 vs 번치코 (첫 턴: 번치코 0랭크, 스피드 145 vs 한카리아스 154)
        brief_t1 = advisor.evaluate_turn(
            ally_species_ko="한카리아스",
            enemy_species_ko="번치코",
            ally_cur_hp=185,
            ally_max_hp=185,
            enemy_hp_percent=100,
            turn_index=1,
            timestamp_sec=71.4,
        )
        print("📌 Turn 1 결과:")
        print(brief_t1.format_console_text())

        assert brief_t1.speed_relation == "ally_faster", f"Turn 1 선공 실패: {brief_t1.speed_relation}"
        assert brief_t1.ally_speed == 154
        assert brief_t1.enemy_speed == 145
        assert len(brief_t1.warning_notes) == 0, "Turn 1에 역전 경고가 없어야 함"

        # Turn 2: 한카리아스 vs 번치코 (2턴째: 1턴 종료 후 가속 +1랭크 발동, 스피드 145 * 1.5 = 217)
        brief_t2 = advisor.evaluate_turn(
            ally_species_ko="한카리아스",
            enemy_species_ko="번치코",
            ally_cur_hp=185,
            ally_max_hp=185,
            enemy_hp_percent=100,
            turn_index=2,
            timestamp_sec=91.3,
        )
        print("\n📌 Turn 2 결과 (가속 +1랭크 발동):")
        print(brief_t2.format_console_text())

        assert brief_t2.speed_relation == "enemy_faster", f"Turn 2 후공 역전 실패: {brief_t2.speed_relation}"
        assert brief_t2.ally_speed == 154
        assert brief_t2.enemy_speed == 217
        assert any("선후공 역전 경고" in w for w in brief_t2.warning_notes), "선후공 역전 경고 누락!"

        # Turn 3: 상대가 갸라도스로 교체 등장 -> 랭크업 리셋 확인
        brief_t3 = advisor.evaluate_turn(
            ally_species_ko="한카리아스",
            enemy_species_ko="갸라도스",
            ally_cur_hp=185,
            ally_max_hp=185,
            enemy_hp_percent=47,
            turn_index=3,
            timestamp_sec=160.7,
        )
        print("\n📌 Turn 3 결과 (상대 갸라도스 교체 등장):")
        print(brief_t3.format_console_text())

        assert brief_t3.speed_relation == "ally_faster", f"Turn 3 선공 실패: {brief_t3.speed_relation}"
        assert brief_t3.enemy_speed == 146
        enemy_mem = advisor.tracker.get_or_create_memory("갸라도스", is_ally=False)
        assert enemy_mem.boosts.spe == 0, "교체된 갸라도스는 스피드 0랭크여야 함"

        print("\n✅ 번치코 가속 시계열 스피드 랭크업 및 선후공 역전 감지 검증 통과!")

    finally:
        advisor.close()


def test_mega_and_focus_sash_deduction():
    """메가진화 도구/특성 확정 및 기합의띠 발동/소모 추론 검증"""
    print("\n============================================================")
    print(" [검증 2] 메가진화 도구/특성 확정 & 기합의띠(Focus Sash) 발동/소모 추론")
    print("============================================================")

    advisor = BattleAdvisor()
    advisor.reset_session()

    try:
        # Turn 4: 메가갸라도스 등장
        brief_t4 = advisor.evaluate_turn(
            ally_species_ko="아머까오",
            enemy_species_ko="메가갸라도스",
            ally_cur_hp=131,
            ally_max_hp=205,
            enemy_hp_percent=31,
            turn_index=4,
            timestamp_sec=200.4,
            is_enemy_mega=True,
        )
        print("📌 Turn 4 결과 (메가갸라도스):")
        print(brief_t4.format_console_text())

        gyarados_mem = advisor.tracker.get_or_create_memory("갸라도스", is_ally=False)
        assert "갸라도스나이트" in gyarados_mem.item_ko
        assert gyarados_mem.item_status == "확정 🔥"
        assert gyarados_mem.ability_ko == "틀깨기"
        assert gyarados_mem.ability_status == "확정 🔥"

        # BATTLE_ACTIVE: 아군 한카리아스가 만피 상태에서 공격을 맞고 HP 1로 생존
        active_warnings = advisor.tracker.on_active_event(
            ally_species_ko="한카리아스",
            enemy_species_ko="갑주무사",
            ally_cur_hp=185,
            ally_max_hp=185,
            enemy_hp_percent=75,
        )
        active_warnings_2 = advisor.tracker.on_active_event(
            ally_species_ko="한카리아스",
            enemy_species_ko="갑주무사",
            ally_cur_hp=1,
            ally_max_hp=185,
            enemy_hp_percent=63,
        )
        print("\n📌 교전 이벤트 (한카리아스 HP 185 ➔ 1):")
        for w in active_warnings_2:
            print(f"   {w}")

        garchomp_mem = advisor.tracker.get_or_create_memory("한카리아스", is_ally=True)
        assert garchomp_mem.item_status == "소모됨 ❌", "기합의띠 소모 상태가 되어야 함"

        # Turn 10: 한카리아스 vs 갑주무사 (기합의띠 소모 확인 브리핑)
        brief_t10 = advisor.evaluate_turn(
            ally_species_ko="한카리아스",
            enemy_species_ko="갑주무사",
            ally_cur_hp=1,
            ally_max_hp=185,
            enemy_hp_percent=40,
            turn_index=10,
            timestamp_sec=351.2,
        )
        print("\n📌 Turn 10 결과 (기합의띠 소모 후):")
        print(brief_t10.format_console_text())

        print("\n✅ 메가진화 도구/특성 확정 및 기합의띠 발동/소모 추론 검증 통과!")

    finally:
        advisor.close()


def test_multi_speed_tier_and_bulk_inference():
    """다중 스피드 티어 비교, 아군 선공 역추론, 스케일샷 랭크업 및 2타 내구 역산 검증"""
    print("\n============================================================")
    print(" [검증 3] 다중 스피드 티어 / 선후공 역추론 / 내구 범위 역산")
    print("============================================================")

    advisor = BattleAdvisor()
    advisor.reset_session()

    try:
        # Turn 1: 아군 준속 한카리아스(154) vs 상대 한카리아스 (미확정 -> 최속 169 / 준속 154 / S0 122)
        b1 = advisor.evaluate_turn(
            ally_species_ko="한카리아스",
            enemy_species_ko="한카리아스",
            ally_cur_hp=185,
            ally_max_hp=185,
            enemy_hp_percent=100,
            turn_index=1,
            timestamp_sec=36.3,
        )
        print("📌 Turn 1 결과 (미확정 동족전):")
        print(b1.format_console_text())

        assert b1.speed_relation == "mixed"
        assert [t.effective_spe for t in b1.speed_tiers] == [169, 154, 122]

        # Turn 1 교전 결과 반영: 아군(154)이 스케일샷 2타 선공 명중 -> 40% 피해 (100% -> 60%), 상대 스텔스록
        order_msg = advisor.tracker.record_turn_order(
            ally_species_ko="한카리아스",
            enemy_species_ko="한카리아스",
            first_actor="ally",
            ally_move_ko="스케일샷",
            enemy_move_ko="스텔스록",
            ally_eff_spe_at_action=b1.ally_speed,
            enemy_spe_rank_at_action=0,
            enemy_max_base_spe=169,
            turn_index=1,
        )
        stat_msgs = advisor.tracker.apply_move_side_effects("한카리아스", is_ally=True, move_ko="스케일샷", turn_index=1)
        bulk_msg = advisor.infer_enemy_bulk(
            ally_species_ko="한카리아스",
            enemy_species_ko="한카리아스",
            move_ko="스케일샷",
            damage_pct=40,
            hit_count=2,
        )

        extra = [m for m in ([order_msg] + stat_msgs + [bulk_msg]) if m]

        # Turn 2: 아군 231 [+1랭크], 상대 최속·스카프 배제(≤154), 상대 내구 H32 B32~H32 B32+ 반영
        b2 = advisor.evaluate_turn(
            ally_species_ko="한카리아스",
            enemy_species_ko="한카리아스",
            ally_cur_hp=185,
            ally_max_hp=185,
            enemy_hp_percent=60,
            turn_index=2,
            timestamp_sec=60.5,
            extra_warnings=extra,
        )
        print("\n📌 Turn 2 결과 (선공 역추론 + +1랭크 + 내구 역산 반영):")
        print(b2.format_console_text())

        assert b2.ally_speed == 231, f"스케일샷 +1랭크 스피드 기대값 231, 실제: {b2.ally_speed}"
        assert b2.speed_relation == "ally_faster"
        assert "최속" in b2.speed_desc and "배제" in b2.speed_desc
        assert "H32 B32" in b2.enemy_bulk_desc
        assert b2.enemy_max_hp_est == 215, f"H32 반영 시 최대 HP 215여야 함, 실제: {b2.enemy_max_hp_est}"

        print("\n✅ 다중 스피드 티어·역추론·내구 역산 통합 검증 통과!")

    finally:
        advisor.close()


if __name__ == "__main__":
    print("=" * 60)
    print("  포챔스 배틀 어시스턴트 - 배틀 상태 엔진(BattleStateTracker) 단위 테스트")
    print("=" * 60)

    test_speed_boost_and_speed_reversal()
    test_mega_and_focus_sash_deduction()
    test_multi_speed_tier_and_bulk_inference()

    print("\n" + "=" * 60)
    print("  🎉 모든 배틀 상태 추적 및 동적 추론 테스트 통과!")
    print("=" * 60)
