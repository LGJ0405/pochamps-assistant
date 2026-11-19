# -*- coding: utf-8 -*-
"""
battle_advisor.py
배틀 커맨드 페이즈(BATTLE_COMMAND) 의사결정 지원 및 실시간 데미지/선후공 브리퍼

주요 역할:
1. my_team.json과 meta_samples.json을 로드하여 현재 필드 대진 포켓몬의 스펙을 구성합니다.
2. 아군 포켓몬의 4개 기술에 대해 상대 포켓몬의 현재 남은 HP 기준 데미지 범위 및 KO 확정/난수타를 계산합니다.
3. 상대 메타 샘플의 공격 기술에 대해 아군 포켓몬의 현재 남은 HP 기준 피격 데미지 및 생존 여부를 계산합니다.
4. 양측의 스피드 실수치를 비교하여 선공/후공/동속 판정을 산출합니다.
5. 터미널 및 GUI 대시보드에서 활용 가능한 구조화된 브리핑 리포트를 생성합니다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .adapter import DataAdapter
from .calc_bridge import CalcBridge
from .schemas import Boosts, CalcRequest, PokemonInput, StatSpread

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MY_TEAM_PATH = DATA_DIR / "my_team.json"

# 선공기(우선도 > 0) 및 후공기(우선도 < 0) 목록 — 순수 스피드 역추론 시 우선도 차이 배제용
_HIGH_PRIORITY_MOVES: Set[str] = {
    "전광석화", "신속", "불릿펀치", "마하펀치", "아쿠아제트", "얼음뭉치",
    "야습", "기습", "속이기", "진공파", "질풍날개", "페인트", "전광석화",
    "방어", "판별", "니들가드", "블로킹", "토치카", "버티기", "퍼스트가드",
    "도우미", "날따름", "분노가루",
}
_LOW_PRIORITY_MOVES: Set[str] = {
    "드래곤테일", "배대뒤치기", "울부짖기", "날려버리기", "리벤지", "눈사태", "트릭룸",
    "미러코트", "카운터", "메탈버스트", "기합펀치",
}

# 확정 자가 스탯 변화 기술 (자막 누락 보완용)
_SELF_MOVE_STAT_EFFECTS: Dict[str, List[Tuple[str, int]]] = {
    "스케일샷": [("spe", 1), ("def_", -1)],
    "용의춤": [("atk", 1), ("spe", 1)],
    "칼춤": [("atk", 2)],
    "나쁜음모": [("spa", 2)],
    "철벽": [("def_", 2)],
    "벌크업": [("atk", 1), ("def_", 1)],
    "명상": [("spa", 1), ("spd", 1)],
    "고속이동": [("spe", 2)],
    "개척하기": [("spe", 1)],
    "니트로차지": [("spe", 1)],
    "아쿠아스텝": [("spe", 1)],
    "인파이트": [("def_", -1), ("spd", -1)],
    "골드러시": [("spa", -1)],
    "오버히트": [("spa", -2)],
    "리프스톰": [("spa", -2)],
    "용성군": [("spa", -2)],
    "엄청난힘": [("atk", -1), ("def_", -1)],
}

# 기술명 한글 -> 랭크 표시 라벨
_STAT_KEY_KO = {
    "atk": "공격",
    "def_": "방어",
    "spa": "특공",
    "spd": "특방",
    "spe": "스피드",
}


@dataclass
class SpeedTier:
    """상대 포켓몬의 단일 스피드 분포 티어"""
    label: str                  # "최속", "준속", "무투자" 등
    base_spe: int               # 0랭크 기본 스피드 실수치
    effective_spe: int          # 현재 랭크 반영 실수치
    relation: str               # "ally_faster", "enemy_faster", "speed_tie"
    is_eliminated: bool = False # 인게임 선후공 역추론으로 배제되었는지 여부
    elim_reason: str = ""


@dataclass
class MoveCalcBrief:
    """단일 기술 계산 브리핑 요약"""
    move_ko: str
    move_en: str
    damage_range: tuple[int, int]  # (min_dmg, max_dmg)
    percent_range_str: str        # e.g. "188.5 - 223.5%"
    ko_desc: str                  # e.g. "확정 1타 (KO)", "난수 2타 (42.5%)"
    full_desc: str                # 쇼다운 전체 계산 결과 문구
    category: str = "Physical"    # "Physical", "Special", "Status"
    is_ko: bool = False           # 최소 데미지만으로 현재 잔여 HP 이상인가


@dataclass
class TurnDecisionBrief:
    """한 턴의 종합 의사결정 브리핑 리포트"""
    turn_index: Optional[int]
    timestamp_sec: float
    # 아군 상태
    ally_species_ko: str
    ally_species_en: str
    ally_cur_hp: int
    ally_max_hp: int
    ally_hp_percent: float
    ally_speed: int
    # 상대 상태
    enemy_species_ko: str
    enemy_species_en: str
    enemy_hp_percent: int
    enemy_cur_hp_est: int
    enemy_max_hp_est: int
    enemy_speed: int
    # 도구 및 특성 추론 정보
    ally_item: str = ""
    ally_ability: str = ""
    enemy_item: str = ""
    enemy_ability: str = ""
    # 아군 랭크업 및 상대 내구 역산 정보
    ally_boost_desc: str = ""
    enemy_bulk_desc: str = ""
    # 선공 판정: 'ally_faster', 'enemy_faster', 'speed_tie', 'mixed'
    speed_relation: str = "speed_tie"
    speed_desc: str = ""
    speed_tiers: List[SpeedTier] = field(default_factory=list)
    scarf_speed_ref: Optional[int] = None
    # 전황 경고 및 특이사항 (선후공 역전, 기합의띠 발동, 내구/스피드 역추론 등)
    warning_notes: List[str] = field(default_factory=list)
    # 데미지 브리핑 (Physical / Special 공격 기술만)
    offense_moves: List[MoveCalcBrief] = field(default_factory=list)
    defense_moves: List[MoveCalcBrief] = field(default_factory=list)
    # 변화기 (Status) 목록 (결정력 계산 제외)
    ally_status_moves: List[str] = field(default_factory=list)
    enemy_status_moves: List[str] = field(default_factory=list)

    def format_console_text(self) -> str:
        """콘솔 출력용 깔끔한 브리핑 문자열 생성"""
        turn_str = f"Turn {self.turn_index:2d}" if self.turn_index is not None else "COMMAND"
        lines = [
            f"⚡ [{turn_str} 브리핑 | {self.timestamp_sec:5.1f}s] "
            f"아군: {self.ally_species_ko} (HP {self.ally_cur_hp}/{self.ally_max_hp}) "
            f"vs 상대: {self.enemy_species_ko} (HP {self.enemy_hp_percent}%) | {self.speed_desc}"
        ]

        # 아군 랭크 상태 표시 (0랭크가 아닌 스탯이 있을 때)
        if self.ally_boost_desc:
            lines.append(f"   📈 [아군 현재 랭크]: {self.ally_boost_desc}")

        # 상대 분석 정보 (인게임 확정/역추론 정보 표시)
        info_parts = []
        if self.enemy_ability and "추정" not in self.enemy_ability:
            info_parts.append(f"특성: {self.enemy_ability}")
        if self.enemy_item and "추정" not in self.enemy_item:
            info_parts.append(f"도구: {self.enemy_item}")
        if self.enemy_bulk_desc:
            info_parts.append(f"내구 역산: {self.enemy_bulk_desc}")
        if info_parts:
            lines.append(f"   🔍 [상대 정보 분석]: {' | '.join(info_parts)}")

        # 특별 전황 경고 (선후공 역전 경고 등)
        for warn in self.warning_notes:
            lines.append(f"   {warn}")

        if self.offense_moves:
            lines.append(f"   🗡️ [내 공격 기술 ({self.ally_species_ko} ➔ {self.enemy_species_ko})]")
            for m in self.offense_moves:
                ko_tag = f" ➔ {m.ko_desc}" if m.ko_desc else ""
                lines.append(
                    f"      - {m.move_ko:12s} ({m.move_en:16s}): "
                    f"{m.damage_range[0]:3d}~{m.damage_range[1]:3d} ({m.percent_range_str}){ko_tag}"
                )

        if self.ally_status_moves:
            status_str = ", ".join(self.ally_status_moves)
            lines.append(f"   🛠️ [내 보유 변화기]: {status_str}")

        return "\n".join(lines)


def get_stat_multiplier(rank: int) -> float:
    """공/방/특공/특방/스피드 랭크 배율 (-6 ~ +6)"""
    rank = max(-6, min(6, rank))
    if rank >= 0:
        return (2.0 + rank) / 2.0
    else:
        return 2.0 / (2.0 - rank)


@dataclass
class PokemonBattleMemory:
    """단일 포켓몬에 대해 배틀 중 누적 추론된 상태 메모리"""
    species_ko: str
    species_en: str
    is_ally: bool
    # 도구 상태
    item_ko: str = ""
    item_en: str = ""
    item_status: str = "추정"  # "확정 🔥", "추정", "소모됨 ❌"
    # 특성 상태
    ability_ko: str = ""
    ability_en: str = ""
    ability_status: str = "추정"  # "확정 🔥", "추정", "발동 ⚡"
    # 필드 상태 및 랭크업
    turns_on_field: int = 0
    boosts: Boosts = field(default_factory=Boosts)
    last_hp: Optional[int] = None
    last_hp_percent: Optional[int] = None
    is_fainted: bool = False
    # 스피드 역추론 제약 (0랭크 기준)
    max_possible_base_spe: Optional[int] = None
    min_possible_base_spe: Optional[int] = None
    scarf_possible: bool = True
    suspected_scarf: bool = False
    speed_inference_note: str = ""
    # 내구 역추론 결과
    inferred_bulk_label: str = ""
    inferred_bulk_candidates: Optional[Set[str]] = None
    inferred_defender_evs: Optional[StatSpread] = None
    inferred_defender_nature: Optional[str] = None
    bulk_inference_note: str = ""
    # 확인된 사용 기술 목록
    used_moves: List[str] = field(default_factory=list)


class BattleStateTracker:
    """실시간 배틀 시계열 상태 및 랭크업/도구/특성/스피드·내구 역추론 엔진"""

    def __init__(self, adapter: Optional[DataAdapter] = None):
        self.adapter = adapter or DataAdapter()
        self.current_turn: int = 0
        self.current_ally_species: Optional[str] = None
        self.current_enemy_species: Optional[str] = None
        self.ally_memories: Dict[str, PokemonBattleMemory] = {}
        self.enemy_memories: Dict[str, PokemonBattleMemory] = {}
        # 턴별 중복 랭크 적용 방지용: (turn_index, is_ally, stat_key)
        self._applied_stat_changes: Set[Tuple[int, bool, str]] = set()

    def reset(self) -> None:
        """배틀 세션 초기화"""
        self.current_turn = 0
        self.current_ally_species = None
        self.current_enemy_species = None
        self.ally_memories.clear()
        self.enemy_memories.clear()
        self._applied_stat_changes.clear()

    def get_or_create_memory(self, species_ko: str, is_ally: bool) -> PokemonBattleMemory:
        mems = self.ally_memories if is_ally else self.enemy_memories
        clean_name = species_ko.replace("메가", "")
        if clean_name not in mems:
            s_en = self.adapter.to_species_en(clean_name)
            mems[clean_name] = PokemonBattleMemory(
                species_ko=clean_name,
                species_en=s_en,
                is_ally=is_ally,
            )
        return mems[clean_name]

    @staticmethod
    def get_move_priority(move_ko: str) -> int:
        """기술명의 대략적 우선도 분류 (+1, 0, -1)"""
        if move_ko in _HIGH_PRIORITY_MOVES:
            return 1
        if move_ko in _LOW_PRIORITY_MOVES:
            return -1
        return 0

    @staticmethod
    def format_boosts(boosts: Boosts) -> str:
        """0이 아닌 랭크 변화만 깔끔하게 문자열로 포맷"""
        parts = []
        for attr, label in _STAT_KEY_KO.items():
            val = getattr(boosts, attr, 0)
            if val > 0:
                parts.append(f"{label} +{val}")
            elif val < 0:
                parts.append(f"{label} {val}")
        return ", ".join(parts)

    def apply_stat_change(
        self,
        species_ko: str,
        is_ally: bool,
        stat_key: str,
        delta: int,
        turn_index: Optional[int] = None,
    ) -> Optional[str]:
        """단일 능력치 랭크 변화(-6~+6 클램프) 적용 및 알림 메시지 반환"""
        if not stat_key or delta == 0:
            return None
        mem = self.get_or_create_memory(species_ko, is_ally=is_ally)
        cur_val = getattr(mem.boosts, stat_key, 0)
        new_val = max(-6, min(6, cur_val + delta))
        setattr(mem.boosts, stat_key, new_val)

        if turn_index is not None:
            self._applied_stat_changes.add((turn_index, is_ally, stat_key))

        side_tag = "아군" if is_ally else "상대"
        stat_label = _STAT_KEY_KO.get(stat_key, stat_key)
        sign = f"+{delta}" if delta > 0 else str(delta)
        return f"📊 [랭크 변화] {side_tag} {mem.species_ko} {stat_label} {sign} (현재 {new_val:+d})"

    def apply_move_side_effects(
        self,
        species_ko: str,
        is_ally: bool,
        move_ko: str,
        turn_index: int,
    ) -> List[str]:
        """
        자막으로 일부 랭크 줄을 놓쳤더라도 확정 자가 랭크 기술(스케일샷, 용의춤 등)의
        부가 효과를 중복 없이 보완 적용합니다.
        """
        mem = self.get_or_create_memory(species_ko, is_ally=is_ally)
        if move_ko and move_ko not in mem.used_moves:
            mem.used_moves.append(move_ko)

        effects = _SELF_MOVE_STAT_EFFECTS.get(move_ko, [])
        msgs: List[str] = []
        for stat_key, delta in effects:
            if (turn_index, is_ally, stat_key) in self._applied_stat_changes:
                continue  # 이미 자막에서 해당 턴 랭크 반영 완료
            msg = self.apply_stat_change(
                species_ko=species_ko,
                is_ally=is_ally,
                stat_key=stat_key,
                delta=delta,
                turn_index=turn_index,
            )
            if msg:
                msgs.append(msg)
        return msgs

    def record_turn_order(
        self,
        ally_species_ko: str,
        enemy_species_ko: str,
        first_actor: str,  # "ally" or "enemy"
        ally_move_ko: str = "",
        enemy_move_ko: str = "",
        ally_eff_spe_at_action: int = 0,
        enemy_spe_rank_at_action: int = 0,
        enemy_max_base_spe: int = 0,
        turn_index: int = 1,
    ) -> Optional[str]:
        """
        실제 교전 행동 순서(누가 먼저 기술 선언을 했는지)를 바탕으로
        상대 0랭크 기본 스피드 상한/하한 및 구애스카프 여부를 역추론합니다.
        """
        if first_actor not in ("ally", "enemy") or ally_eff_spe_at_action <= 0:
            return None

        # 우선도 차이 확인 (한쪽이 선공기/후공기를 쓴 경우 스피드 비교 대상에서 제외)
        a_prio = self.get_move_priority(ally_move_ko) if ally_move_ko else 0
        e_prio = self.get_move_priority(enemy_move_ko) if enemy_move_ko else 0
        if a_prio != e_prio:
            return None
        # 만약 상대 기술을 모르는 상태에서 아군이 선공기/후공기를 쓴 경우 보수적 제외
        if a_prio != 0 and not enemy_move_ko:
            return None

        e_mem = self.get_or_create_memory(enemy_species_ko, is_ally=False)
        e_mult = get_stat_multiplier(enemy_spe_rank_at_action)
        inferred_enemy_base_bound = int(ally_eff_spe_at_action / e_mult) if e_mult > 0 else ally_eff_spe_at_action

        if first_actor == "ally":
            prev_bound = e_mem.max_possible_base_spe
            narrowed = prev_bound is None or inferred_enemy_base_bound < prev_bound
            if narrowed:
                e_mem.max_possible_base_spe = inferred_enemy_base_bound
            # 아군이 0랭크 이하에서 선공했다면 상대가 구애스카프일 가능성 배제 (단, 아군도 스카프 아닌 경우 기준)
            if enemy_max_base_spe > 0 and inferred_enemy_base_bound < int(enemy_max_base_spe * 1.5):
                e_mem.scarf_possible = False

            if narrowed and enemy_max_base_spe > 0 and e_mem.max_possible_base_spe is not None and e_mem.max_possible_base_spe < enemy_max_base_spe:
                e_mem.speed_inference_note = (
                    f"Turn {turn_index} 선공으로 최속({enemy_max_base_spe})·스카프 배제 (≤{e_mem.max_possible_base_spe})"
                )
                return f"⚡ [스피드 역추론] {e_mem.speed_inference_note}"
        else:
            # 상대가 먼저 행동했더라도 아군이 기술을 쓰지 않았으면(교체·행동불능 등) 스피드 대결 아님
            if not ally_move_ko:
                return None
            # 상대 실스피드는 아군 이상
            if e_mem.min_possible_base_spe is None or inferred_enemy_base_bound > e_mem.min_possible_base_spe:
                e_mem.min_possible_base_spe = inferred_enemy_base_bound
            has_other_item = (
                e_mem.item_status in ("확정 🔥", "소모됨 ❌")
                and e_mem.item_ko != "구애스카프"
            )
            if enemy_max_base_spe > 0 and e_mem.scarf_possible and not has_other_item:
                enemy_max_eff = int(enemy_max_base_spe * e_mult)
                if ally_eff_spe_at_action > enemy_max_eff:
                    e_mem.suspected_scarf = True
                    e_mem.speed_inference_note = f"Turn {turn_index} 추월 당함 ➔ 구애스카프 경계!"
                    return f"🚨 [스피드 경고] {e_mem.speed_inference_note}"

        return None

    def on_active_event(
        self,
        ally_species_ko: str,
        enemy_species_ko: str,
        ally_cur_hp: int,
        ally_max_hp: int,
        enemy_hp_percent: int,
    ) -> List[str]:
        """BATTLE_ACTIVE(교전/기절) 발생 시 실시간 체력 변화 기반 도구 소모 추론"""
        warnings = []
        clean_a = ally_species_ko.replace("메가", "")
        clean_e = enemy_species_ko.replace("메가", "")

        a_mem = self.get_or_create_memory(clean_a, is_ally=True)
        e_mem = self.get_or_create_memory(clean_e, is_ally=False)

        # 1. 아군 기합의띠 발동 감지: 이전 만피 상태에서 HP 1(또는 1 이하)로 생존
        if a_mem.last_hp is not None and a_mem.last_hp >= int(ally_max_hp * 0.9):
            if ally_cur_hp == 1 and a_mem.item_status != "소모됨 ❌":
                a_mem.item_ko = "기합의띠"
                a_mem.item_en = "Focus Sash"
                a_mem.item_status = "소모됨 ❌"
                warnings.append(f"🛡️ [도구 발동] 아군 {clean_a} 기합의띠로 1 생존! (도구 소모됨)")

        # 2. 상대 기합의띠 발동 감지: 이전 100%에서 HP 1%로 생존
        if e_mem.last_hp_percent is not None and e_mem.last_hp_percent >= 90:
            if enemy_hp_percent == 1 and e_mem.item_status != "소모됨 ❌":
                e_mem.item_ko = "기합의띠"
                e_mem.item_en = "Focus Sash"
                e_mem.item_status = "소모됨 ❌"
                warnings.append(f"⚠️ [도구 발동] 상대 {clean_e} 기합의띠 발동 확인! (도구 소모됨)")

        a_mem.last_hp = ally_cur_hp
        e_mem.last_hp_percent = enemy_hp_percent
        return warnings

    def on_turn_update(
        self,
        turn_index: int,
        ally_species_ko: str,
        enemy_species_ko: str,
        ally_cur_hp: int,
        ally_max_hp: int,
        enemy_hp_percent: int,
        is_ally_mega: bool = False,
        is_enemy_mega: bool = False,
        ally_sample: Optional[dict] = None,
        enemy_sample: Optional[dict] = None,
    ) -> List[str]:
        """
        새로운 커맨드 턴 시작 시 교체, 턴 수 누적, 가속 랭크업, 도구/특성 상태를 갱신합니다.
        """
        warnings = []
        is_new_turn = (turn_index != self.current_turn)
        self.current_turn = turn_index

        clean_a = ally_species_ko.replace("메가", "")
        clean_e = enemy_species_ko.replace("메가", "")

        ally_mem = self.get_or_create_memory(clean_a, is_ally=True)
        enemy_mem = self.get_or_create_memory(clean_e, is_ally=False)

        # 1. 아군 교체 감지 및 필드 턴 누적
        if self.current_ally_species != clean_a:
            if self.current_ally_species and self.current_ally_species in self.ally_memories:
                prev_mem = self.ally_memories[self.current_ally_species]
                prev_mem.turns_on_field = 0
                prev_mem.boosts = Boosts()
            ally_mem.turns_on_field = 0
            ally_mem.boosts = Boosts()
            self.current_ally_species = clean_a
        elif is_new_turn:
            ally_mem.turns_on_field += 1

        # 2. 상대 교체 감지 및 필드 턴 누적
        if self.current_enemy_species != clean_e:
            if self.current_enemy_species and self.current_enemy_species in self.enemy_memories:
                prev_mem = self.enemy_memories[self.current_enemy_species]
                prev_mem.turns_on_field = 0
                prev_mem.boosts = Boosts()
            enemy_mem.turns_on_field = 0
            enemy_mem.boosts = Boosts()
            self.current_enemy_species = clean_e
        elif is_new_turn:
            enemy_mem.turns_on_field += 1

        # 아군 등록 샘플 기반 도구/특성 로드
        if ally_sample:
            if not ally_mem.ability_ko:
                ally_mem.ability_ko = ally_sample.get("ability", "")
                ally_mem.ability_en = self.adapter.to_ability_en(ally_mem.ability_ko)
                ally_mem.ability_status = "확정"
            if not ally_mem.item_ko:
                ally_mem.item_ko = ally_sample.get("item", "")
                ally_mem.item_en = self.adapter.to_item_en(ally_mem.item_ko)
                ally_mem.item_status = "확정"

        # 3. 메가진화 도구 & 특성 확정
        if is_enemy_mega or "-mega" in enemy_mem.species_en.lower():
            mega_stone_ko = f"{clean_e}나이트" if not clean_e.endswith("나이트") else clean_e
            enemy_mem.item_ko = mega_stone_ko
            enemy_mem.item_en = self.adapter.to_item_en(mega_stone_ko)
            enemy_mem.item_status = "확정 🔥"

            # 메가진화 특성 매핑
            if clean_e == "갸라도스":
                enemy_mem.ability_ko = "틀깨기"
                enemy_mem.ability_en = "Mold Breaker"
                enemy_mem.ability_status = "확정 🔥"
            elif clean_e == "보만다":
                enemy_mem.ability_ko = "스카이스킨"
                enemy_mem.ability_en = "Aerilate"
                enemy_mem.ability_status = "확정 🔥"
            elif clean_e == "리자몽":
                enemy_mem.ability_ko = "단단한발톱"
                enemy_mem.ability_en = "Tough Claws"
                enemy_mem.ability_status = "확정 🔥"

        # 4. 상대 특성 '가속(Speed Boost)' 시계열 랭크업 추적
        enemy_ability = enemy_mem.ability_ko or (enemy_sample.get("ability", "") if enemy_sample else "")
        if enemy_ability == "가속" or clean_e == "번치코":
            enemy_mem.ability_ko = "가속"
            enemy_mem.ability_en = "Speed Boost"
            if enemy_mem.turns_on_field == 0:
                enemy_mem.boosts.spe = 0
                enemy_mem.ability_status = "대기"
            else:
                # 턴 종료마다 스피드 +1랭크 누적 (최대 6랭크)
                enemy_mem.boosts.spe = min(6, enemy_mem.turns_on_field)
                enemy_mem.ability_status = f"발동 (+{enemy_mem.boosts.spe}랭크 ⚡)"

        # 5. 기합의띠 발동/소모 확인
        if enemy_mem.last_hp_percent is not None and enemy_mem.last_hp_percent >= 90:
            if enemy_hp_percent == 1 and enemy_mem.item_status != "소모됨 ❌":
                enemy_mem.item_ko = "기합의띠"
                enemy_mem.item_en = "Focus Sash"
                enemy_mem.item_status = "소모됨 ❌"
                warnings.append(f"⚠️ [도구 발동] 상대 {clean_e} 기합의띠 발동 확인! (도구 소모됨)")

        if ally_mem.last_hp is not None and ally_mem.last_hp >= int(ally_max_hp * 0.8):
            if ally_cur_hp == 1 and ally_mem.item_status != "소모됨 ❌":
                ally_mem.item_status = "소모됨 ❌"
                warnings.append(f"🛡️ [도구 발동] 아군 {clean_a} 기합의띠로 1 생존! (도구 소모됨)")

        enemy_mem.last_hp_percent = enemy_hp_percent
        ally_mem.last_hp = ally_cur_hp

        return warnings


class BattleAdvisor:
    """배틀 의사결정 브릿지 및 실시간 데미지·스피드·내구 역추론 브리퍼"""

    def __init__(
        self,
        bridge: Optional[CalcBridge] = None,
        adapter: Optional[DataAdapter] = None,
        my_team_path: Optional[Union[str, Path]] = None,
        meta_samples_path: Optional[Union[str, Path]] = None,
    ):
        self.bridge = bridge
        self._owns_bridge = False
        self.adapter = adapter or DataAdapter()
        self.my_team_path = Path(my_team_path or MY_TEAM_PATH)
        self.meta_samples_path = Path(meta_samples_path) if meta_samples_path else None

        self.tracker = BattleStateTracker(self.adapter)

        self._my_team: Dict[str, Any] = {}
        self._meta_samples: Dict[str, Any] = {}
        self._neutral_spe_cache: Dict[str, int] = {}
        self.reload_data()

    def reset_session(self) -> None:
        """새 배틀 세션을 위해 상태 추적기를 초기화합니다."""
        self.tracker.reset()

    def reload_data(self) -> None:
        """내 파티 및 선택적 외부 메타 사전을 로드합니다."""
        if self.my_team_path.exists():
            with open(self.my_team_path, "r", encoding="utf-8") as f:
                self._my_team = json.load(f)
        if self.meta_samples_path and self.meta_samples_path.exists():
            with open(self.meta_samples_path, "r", encoding="utf-8") as f:
                self._meta_samples = json.load(f)

    def _get_or_create_bridge(self) -> CalcBridge:
        if self.bridge is not None and self.bridge.is_alive():
            return self.bridge
        if self.bridge is None:
            self.bridge = CalcBridge()
            self._owns_bridge = True
        if not self.bridge.is_alive():
            self.bridge.start()
        return self.bridge

    def close(self) -> None:
        """자체 생성한 브릿지가 있다면 종료합니다."""
        if self._owns_bridge and self.bridge is not None:
            self.bridge.stop()
            self.bridge = None

    def __enter__(self) -> "BattleAdvisor":
        self._get_or_create_bridge()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def find_ally_sample(self, species_ko: str) -> Optional[dict]:
        """내 파티에서 해당 한글 종족명의 샘플을 조회합니다 (팀 단위 'team1' 및 개별 키 모두 지원)."""
        clean_name = species_ko.replace("메가", "")

        # 1. 팀 단위 리스트 구조 (예: {"team1": [ {...}, ... ]}) 탐색
        for key, val in self._my_team.items():
            if isinstance(val, list):
                for member in val:
                    if isinstance(member, dict) and member.get("name") in (species_ko, clean_name):
                        return member
            elif isinstance(val, dict):
                if species_ko in val:
                    return val[species_ko]
                if clean_name in val:
                    return val[clean_name]

        # 2. 기존 개별 종족명 키 구조 호환
        if species_ko in self._my_team and self._my_team[species_ko]:
            entry = self._my_team[species_ko]
            return entry[0] if isinstance(entry, list) else entry
        if clean_name in self._my_team and self._my_team[clean_name]:
            entry = self._my_team[clean_name]
            return entry[0] if isinstance(entry, list) else entry

        return None

    def find_enemy_sample(self, species_ko: str) -> Optional[dict]:
        """상대 메타 샘플에서 해당 한글 종족명의 대표 샘플을 조회합니다."""
        if species_ko in self._meta_samples and self._meta_samples[species_ko]:
            return self._meta_samples[species_ko][0]
        base_name = species_ko.replace("메가", "")
        if base_name in self._meta_samples and self._meta_samples[base_name]:
            return self._meta_samples[base_name][0]
        return None

    def _translate_ko_desc(self, full_desc: str) -> str:
        """쇼다운 KO 문구를 직관적인 한국어 문구로 번역/정제"""
        if "guaranteed OHKO" in full_desc or "100% chance to OHKO" in full_desc:
            return "💥 확정 1타 (KO)"
        if "chance to OHKO" in full_desc:
            return "🎲 난수 1타 (OHKO 가능)"
        if "guaranteed 2HKO" in full_desc:
            return "⚔️ 확정 2타"
        if "chance to 2HKO" in full_desc:
            return "🎲 난수 2타"
        if "guaranteed 3HKO" in full_desc:
            return "🛡️ 확정 3타"
        if "효과 없음" in full_desc:
            return "❌ 무효 (0배)"
        return ""

    @staticmethod
    def _parse_damage_range(damage_val: Any) -> tuple[int, int]:
        """
        쇼다운 계산기 damage 결과에서 (min_dmg, max_dmg) 추출
        단타(1D 리스트), 다단히트(2D 리스트: Scale Shot 등), 단일 정수 모두 안전 처리
        """
        if not damage_val:
            return (0, 0)
        if isinstance(damage_val, (int, float)):
            v = int(damage_val)
            return (v, v)
        if isinstance(damage_val, list):
            if len(damage_val) == 0:
                return (0, 0)
            # 다단히트: [[min1, ..., max1], [min2, ..., max2], ...]
            if isinstance(damage_val[0], (list, tuple)):
                min_d = sum(int(hit[0]) for hit in damage_val if hit)
                max_d = sum(int(hit[-1]) for hit in damage_val if hit)
                return (min_d, max_d)
            # 단타: [min, ..., max]
            return (int(damage_val[0]), int(damage_val[-1]))
        return (0, 0)

    @staticmethod
    def _parse_damage_range_hits(damage_val: Any, hit_count: int = 0) -> tuple[int, int]:
        """다단히트 기술에서 실측 타수(hit_count)를 반영한 합산 (min_dmg, max_dmg) 추출"""
        if hit_count <= 0 or not isinstance(damage_val, list) or not damage_val:
            return BattleAdvisor._parse_damage_range(damage_val)
        if isinstance(damage_val[0], (list, tuple)):
            min_total = 0
            max_total = 0
            for idx in range(hit_count):
                hit_roll = damage_val[idx] if idx < len(damage_val) else damage_val[-1]
                if hit_roll:
                    min_total += int(hit_roll[0])
                    max_total += int(hit_roll[-1])
            return (min_total, max_total)
        # 단타 리스트가 온 경우 단타×타수 (보통 발생 안 함)
        min1, max1 = BattleAdvisor._parse_damage_range(damage_val)
        return (min1, max1)

    def calc_enemy_speed_specs(
        self,
        species_en: str,
        enemy_boosts: Optional[Boosts] = None,
        enemy_ability: Optional[str] = None,
        include_scarf: bool = True,
    ) -> Tuple[List[Tuple[str, int, int]], Optional[int]]:
        """
        @smogon/calc 를 통해 상대 종족의 티어별 (라벨, 0랭크 기본스피드, 랭크·도구·특성 반영 최종스피드) 및
        최속 스카프 참고 스피드를 직접 산출합니다.
        """
        bridge = self._get_or_create_bridge()
        dummy_atk = PokemonInput(species="Pikachu", level=50)
        move_en = self.adapter.to_move_en("몸통박치기") or "Tackle"

        configs = [
            ("최속", "Jolly", StatSpread(spe=32), None),
            ("준속", "Serious", StatSpread(spe=32), None),
            ("S0", "Serious", StatSpread(spe=0), None),
        ]
        tiers: List[Tuple[str, int, int]] = []
        for label, nat, evs, item in configs:
            dfn = PokemonInput(
                species=species_en,
                level=50,
                nature=nat,
                evs=evs,
                boosts=enemy_boosts,
                ability=enemy_ability,
                item=item,
            )
            res = bridge.calculate(CalcRequest(attacker=dummy_atk, defender=dfn, move=move_en, gen=0))
            if res.ok:
                raw_spe = int(res.defender_raw_stats.get("spe", 100))
                eff_spe = int(res.defender_stats.get("spe", raw_spe))
            else:
                raw_spe, eff_spe = 100, 100
            tiers.append((label, raw_spe, eff_spe))

        scarf_spe: Optional[int] = None
        if include_scarf:
            dfn_scarf = PokemonInput(
                species=species_en,
                level=50,
                nature="Jolly",
                evs=StatSpread(spe=32),
                boosts=enemy_boosts,
                ability=enemy_ability,
                item="Choice Scarf",
            )
            res_s = bridge.calculate(CalcRequest(attacker=dummy_atk, defender=dfn_scarf, move=move_en, gen=0))
            if res_s.ok:
                scarf_spe = int(res_s.defender_stats.get("spe", 150))

        return tiers, scarf_spe

    def _build_ally_input(self, ally_species_ko: str, is_ally_mega: bool = False) -> Tuple[Optional[dict], PokemonInput]:
        ally_sample = self.find_ally_sample(ally_species_ko)
        ally_mem = self.tracker.get_or_create_memory(ally_species_ko, is_ally=True)
        if ally_sample:
            ally_input = self.adapter.sample_to_pokemon_input(ally_sample, use_mega=is_ally_mega)
        else:
            s_en = self.adapter.to_species_en(ally_species_ko)
            nature_ko = "명랑" if "Timid" not in s_en else "겁쟁이"
            ally_input = PokemonInput(
                species=s_en,
                level=50,
                nature=self.adapter.to_nature_en(nature_ko),
                evs=StatSpread(hp=2, atk=32, spe=32),
            )
        if ally_mem.item_status == "소모됨 ❌":
            ally_input.item = None
        ally_input.boosts = ally_mem.boosts
        return ally_sample, ally_input

    def infer_enemy_bulk(
        self,
        ally_species_ko: str,
        enemy_species_ko: str,
        move_ko: str,
        damage_pct: int,
        hit_count: int = 0,
        ally_boosts: Optional[Boosts] = None,
        enemy_boosts: Optional[Boosts] = None,
        is_ally_mega: bool = False,
        is_enemy_mega: bool = False,
    ) -> Optional[str]:
        """
        실제 교전 후 상대방의 HP 감소량(%)과 아군 공격 기술/타수를 바탕으로
        상대의 내구 노력치 프리셋 범위(딜러형 vs H풀 vs HB/HD 막이)를 역추론합니다.
        """
        if damage_pct <= 0 or damage_pct >= 100 or not move_ko:
            return None

        move_en = self.adapter.to_move_en(move_ko)
        if not move_en or move_en == move_ko:
            return None

        bridge = self._get_or_create_bridge()
        _, ally_input = self._build_ally_input(ally_species_ko, is_ally_mega=is_ally_mega)
        if ally_boosts is not None:
            ally_input.boosts = ally_boosts

        enemy_mem = self.tracker.get_or_create_memory(enemy_species_ko, is_ally=False)
        enemy_en = self.adapter.to_species_en(enemy_species_ko)
        if is_enemy_mega and "-Mega" not in enemy_en:
            mega_en = self.adapter.to_species_en(f"메가{enemy_species_ko.replace('메가', '')}")
            if mega_en and "-Mega" in mega_en:
                enemy_en = mega_en

        # 먼저 카테고리(물리 vs 특수) 판별
        probe_def = PokemonInput(species=enemy_en, level=50, boosts=enemy_boosts)
        probe_res = bridge.calculate(CalcRequest(attacker=ally_input, defender=probe_def, move=move_en, gen=0))
        if not probe_res.ok or probe_res.move_category == "Status":
            return None

        is_physical = (probe_res.move_category == "Physical")
        if is_physical:
            presets = [
                ("H2 B0 (딜러형)", "명랑", StatSpread(hp=2, atk=32, spe=32)),
                ("H32 B0 (H투자)", "고집", StatSpread(hp=32, atk=32, spe=2)),
                ("H32 B32 (무보정HB)", "고집", StatSpread(hp=32, atk=2, def_=32)),
                ("H32 B32+ (보정HB)", "장난꾸러기", StatSpread(hp=32, atk=2, def_=32)),
            ]
        else:
            presets = [
                ("H2 D0 (딜러형)", "겁쟁이", StatSpread(hp=2, spa=32, spe=32)),
                ("H32 D0 (H투자)", "조심", StatSpread(hp=32, spa=32, spe=2)),
                ("H32 D32 (무보정HD)", "조심", StatSpread(hp=32, atk=0, spd=32, spa=2)),
                ("H32 D32+ (보정HD)", "차분", StatSpread(hp=32, atk=0, spd=32, spa=2)),
            ]

        matched: List[Tuple[str, str, StatSpread]] = []
        tol = 2.5  # 인게임 퍼센트 내림/반올림 및 난수 여유 오차

        for label, nat_ko, evs in presets:
            dfn = PokemonInput(
                species=enemy_en,
                level=50,
                nature=self.adapter.to_nature_en(nat_ko),
                evs=evs,
                boosts=enemy_boosts,
            )
            if enemy_mem.item_status == "확정 🔥" and enemy_mem.item_en:
                dfn.item = enemy_mem.item_en
            res = bridge.calculate(CalcRequest(attacker=ally_input, defender=dfn, move=move_en, gen=0))
            if not res.ok:
                continue
            max_hp = int(res.defender_stats.get("hp", 150))
            if hit_count > 0:
                min_d, max_d = self._parse_damage_range_hits(res.damage, hit_count=hit_count)
            elif isinstance(res.damage, list) and res.damage and isinstance(res.damage[0], (list, tuple)):
                # 다단히트 타수 미상 시 최소 2타 ~ 최대 5타 범위 검사
                min_d, _ = self._parse_damage_range_hits(res.damage, hit_count=2)
                _, max_d = self._parse_damage_range_hits(res.damage, hit_count=5)
            else:
                min_d, max_d = self._parse_damage_range(res.damage)

            if max_d <= 0:
                continue
            min_pct = (min_d / float(max_hp)) * 100.0
            max_pct = (max_d / float(max_hp)) * 100.0
            if (min_pct - tol) <= float(damage_pct) <= (max_pct + tol):
                matched.append((label, nat_ko, evs))

        if not matched or len(matched) == len(presets):
            return None

        # 기존 역추론 후보가 있으면 교집합으로만 좁히기 (불확실한 관측으로 범위가 다시 넓어지지 않게 방지)
        if enemy_mem.inferred_bulk_candidates is not None:
            narrowed = [m for m in matched if m[0] in enemy_mem.inferred_bulk_candidates]
            if not narrowed:
                return None
            if len(narrowed) >= len(enemy_mem.inferred_bulk_candidates):
                # 이미 같거나 더 정밀한 범위가 확정되어 있으므로 덮어쓰기/중복 경고 생략
                return None
            matched = narrowed

        enemy_mem.inferred_bulk_candidates = {m[0] for m in matched}

        # 일치하는 프리셋 범위 요약 및 보수적 대표 스펙 적용 (다음 턴 결정력 과대평가 방지)
        short_names = [m[0].split(" ")[0] + " " + m[0].split(" ")[1] for m in matched]
        range_str = " ~ ".join([short_names[0], short_names[-1]]) if len(short_names) > 1 else short_names[0]
        hits_tag = f" {hit_count}타" if hit_count > 0 else ""
        bulk_desc = f"{range_str} ({move_ko}{hits_tag} {damage_pct}% 피해)"

        # 대표 내구 스펙은 생존 후보 중 첫 번째 적용
        rep_label, rep_nat, rep_evs = matched[0]
        enemy_mem.inferred_bulk_label = bulk_desc
        enemy_mem.inferred_defender_nature = rep_nat
        enemy_mem.inferred_defender_evs = rep_evs
        enemy_mem.bulk_inference_note = f"🛡️ [내구 역산] 상대 {enemy_species_ko}: {bulk_desc}"
        return enemy_mem.bulk_inference_note

    def evaluate_turn(
        self,
        ally_species_ko: str,
        enemy_species_ko: str,
        ally_cur_hp: int,
        ally_max_hp: int,
        enemy_hp_percent: int,
        turn_index: Optional[int] = None,
        timestamp_sec: float = 0.0,
        is_ally_mega: bool = False,
        is_enemy_mega: bool = False,
        extra_warnings: Optional[List[str]] = None,
    ) -> TurnDecisionBrief:
        """
        한 턴의 실시간 데미지 및 다중 스피드 티어/내구 역추론 의사결정 브리핑을 생성합니다.
        """
        bridge = self._get_or_create_bridge()

        # 1. 아군 샘플 로드 (상대 샘플은 메타 미연동 원칙에 따라 비움)
        ally_sample = self.find_ally_sample(ally_species_ko)
        enemy_sample = self.find_enemy_sample(enemy_species_ko)

        # 2. 실시간 시계열 상태 추적 (교체 감지, 턴수 누적, 가속 랭크업, 도구/특성 상태 갱신)
        turn_num = turn_index if turn_index is not None else 1
        warnings = self.tracker.on_turn_update(
            turn_index=turn_num,
            ally_species_ko=ally_species_ko,
            enemy_species_ko=enemy_species_ko,
            ally_cur_hp=ally_cur_hp,
            ally_max_hp=ally_max_hp,
            enemy_hp_percent=enemy_hp_percent,
            is_ally_mega=is_ally_mega,
            is_enemy_mega=is_enemy_mega,
            ally_sample=ally_sample,
            enemy_sample=enemy_sample,
        )
        if extra_warnings:
            for ew in extra_warnings:
                if ew and ew not in warnings:
                    warnings.append(ew)

        ally_mem = self.tracker.get_or_create_memory(ally_species_ko, is_ally=True)
        enemy_mem = self.tracker.get_or_create_memory(enemy_species_ko, is_ally=False)

        # 아군 PokemonInput 구성
        _, ally_input = self._build_ally_input(ally_species_ko, is_ally_mega=is_ally_mega)

        # 상대 PokemonInput 구성 (역추론된 내구 스펙 우선 반영, 없으면 기본 스펙)
        if enemy_sample:
            enemy_input = self.adapter.sample_to_pokemon_input(enemy_sample, use_mega=is_enemy_mega)
        else:
            s_en = self.adapter.to_species_en(enemy_species_ko)
            if is_enemy_mega and "-Mega" not in s_en:
                mega_en = self.adapter.to_species_en(f"메가{enemy_species_ko.replace('메가', '')}")
                if mega_en and "-Mega" in mega_en:
                    s_en = mega_en
            if enemy_mem.inferred_defender_evs is not None and enemy_mem.inferred_defender_nature:
                enemy_input = PokemonInput(
                    species=s_en,
                    level=50,
                    nature=self.adapter.to_nature_en(enemy_mem.inferred_defender_nature),
                    evs=enemy_mem.inferred_defender_evs,
                )
            else:
                enemy_input = PokemonInput(
                    species=s_en,
                    level=50,
                    nature=self.adapter.to_nature_en("명랑"),
                    evs=StatSpread(hp=2, atk=32, spe=32),
                )
        enemy_input.boosts = enemy_mem.boosts

        # 상대 도구 추정 제거: 인게임 확정된 도구(메가스톤 등)만 전달
        if enemy_mem.item_status == "확정 🔥" and enemy_mem.item_en:
            enemy_input.item = enemy_mem.item_en
        else:
            enemy_input.item = None

        # 3. 양측 스피드(랭크·도구·특성·필드 모두 반영된 @smogon/calc stats.spe) 및 최대 HP 산출
        dummy_req = CalcRequest(
            attacker=ally_input,
            defender=enemy_input,
            move=self.adapter.to_move_en("몸통박치기") or "Tackle",
            gen=0,
        )
        dummy_res = bridge.calculate(dummy_req)

        ally_spe = int(dummy_res.attacker_stats.get("spe", 100))
        ally_base_spe = int(dummy_res.attacker_raw_stats.get("spe", ally_spe))
        enemy_max_hp = int(dummy_res.defender_stats.get("hp", 150))

        # 상대 다중 스피드 티어 산출 (@smogon/calc 직접 계산: 최속 / 준속 / S0 + 스카프 참고)
        has_confirmed_non_scarf_item = (
            enemy_mem.item_status in ("확정 🔥", "소모됨 ❌")
            and enemy_mem.item_ko != "구애스카프"
        )
        want_scarf_ref = enemy_mem.scarf_possible and not has_confirmed_non_scarf_item
        raw_tiers, scarf_ref = self.calc_enemy_speed_specs(
            species_en=enemy_input.species,
            enemy_boosts=enemy_mem.boosts,
            enemy_ability=enemy_input.ability,
            include_scarf=want_scarf_ref,
        )
        enemy_max_base = raw_tiers[0][1]
        e_spe_rank = enemy_mem.boosts.spe

        speed_tiers: List[SpeedTier] = []
        for lbl, b_spe, eff_spe in raw_tiers:
            elim = False
            elim_reason = ""
            if enemy_mem.max_possible_base_spe is not None and b_spe > enemy_mem.max_possible_base_spe:
                elim = True
                elim_reason = f"선공 역추론 배제 (≤{enemy_mem.max_possible_base_spe})"
            elif enemy_mem.min_possible_base_spe is not None and b_spe < enemy_mem.min_possible_base_spe:
                elim = True
                elim_reason = f"후공 역추론 배제 (≥{enemy_mem.min_possible_base_spe})"

            if ally_spe > eff_spe:
                rel = "ally_faster"
            elif ally_spe < eff_spe:
                rel = "enemy_faster"
            else:
                rel = "speed_tie"
            speed_tiers.append(
                SpeedTier(
                    label=lbl,
                    base_spe=b_spe,
                    effective_spe=eff_spe,
                    relation=rel,
                    is_eliminated=elim,
                    elim_reason=elim_reason,
                )
            )

        valid_tiers = [t for t in speed_tiers if not t.is_eliminated] or speed_tiers
        # 대표 상대 스피드: 살아남은 최상위 티어 기준 (기존 테스트 호환)
        enemy_spe = valid_tiers[0].effective_spe
        enemy_base_spe = valid_tiers[0].base_spe

        # 0랭크 대비 선후공 역전 체크 (최속/생존 최고 티어 기준)
        base_faster = (ally_base_spe > enemy_base_spe)
        # 실전 비교: 최속 및 준속 모두 대비 상태 판단
        valid_main_tiers = [t for t in valid_tiers if t.label in ("최속", "준속")] or valid_tiers
        all_faster = all(ally_spe > t.effective_spe for t in valid_tiers)
        main_slower = all(ally_spe < t.effective_spe for t in valid_main_tiers)

        ally_rank_str = f" [+{ally_mem.boosts.spe}랭크]" if ally_mem.boosts.spe > 0 else (f" [{ally_mem.boosts.spe}랭크]" if ally_mem.boosts.spe < 0 else "")
        enemy_rank_str = f" [+{e_spe_rank}랭크]" if e_spe_rank > 0 else (f" [{e_spe_rank}랭크]" if e_spe_rank < 0 else "")

        if all_faster:
            speed_rel = "ally_faster"
            if enemy_mem.max_possible_base_spe is not None and enemy_mem.max_possible_base_spe < enemy_max_base:
                bound_eff = (
                    valid_tiers[0].effective_spe
                    if enemy_mem.max_possible_base_spe == valid_tiers[0].base_spe
                    else int(enemy_mem.max_possible_base_spe * get_stat_multiplier(e_spe_rank))
                )
                scarf_note = "·스카프 배제" if not enemy_mem.scarf_possible else ""
                speed_desc = (
                    f"선공 🏃 (아군 {ally_spe}{ally_rank_str} vs 상대 ≤{bound_eff}{enemy_rank_str} [최속{scarf_note} ✅])"
                )
            else:
                speed_desc = (
                    f"선공 🏃 (아군 {ally_spe}{ally_rank_str} vs 최속 {speed_tiers[0].effective_spe}{enemy_rank_str} / 준속 {speed_tiers[1].effective_spe}{enemy_rank_str})"
                )
        elif main_slower:
            speed_rel = "enemy_faster"
            tier_strs = [f"{t.label} {t.effective_spe}" for t in valid_main_tiers]
            speed_desc = (
                f"후공 🐢 (아군 {ally_spe}{ally_rank_str} vs {' / '.join(tier_strs)}{enemy_rank_str})"
            )
        else:
            speed_rel = "mixed"
            parts = []
            for t in valid_tiers:
                badge = "선공🏃" if t.relation == "ally_faster" else ("후공🐢" if t.relation == "enemy_faster" else "동속🎲")
                parts.append(f"{t.label} {t.effective_spe}[{badge}]")
            scarf_str = f" | 스카프 {scarf_ref}" if scarf_ref else ""
            speed_desc = f"유동 ⚖️ (아군 {ally_spe}{ally_rank_str} vs {' / '.join(parts)}{enemy_rank_str}{scarf_str})"

        if enemy_mem.suspected_scarf:
            speed_desc += " 🚨스카프 의심"

        # 선후공 역전 경고
        if base_faster and speed_rel == "enemy_faster":
            rank_reason = f"가속(+{e_spe_rank}랭크 ⚡)" if enemy_mem.ability_ko == "가속" else f"랭크업({enemy_base_spe}➔{enemy_spe})"
            warnings.append(
                f"🚨 [선후공 역전 경고] 상대 {enemy_species_ko} {rank_reason}으로 선공 역전! (아군 선공 ➔ 후공 🐢)"
            )
        elif not base_faster and speed_rel == "ally_faster" and ally_mem.boosts.spe > 0:
            warnings.append(
                f"🏃 [선후공 역전 성공] 아군 {ally_species_ko} 스피드 +{ally_mem.boosts.spe}랭크로 선공 획득!"
            )

        # 상대 잔여 실 HP 추정 (퍼센트 기준)
        enemy_cur_hp = max(1, int(round(enemy_max_hp * (enemy_hp_percent / 100.0)))) if enemy_hp_percent > 0 else 0

        # 상대 도구/특성 요약 문자열
        enemy_item_str = (
            f"{enemy_mem.item_ko} ({enemy_mem.item_status})"
            if (enemy_mem.item_ko and enemy_mem.item_status in ("확정 🔥", "소모됨 ❌"))
            else ""
        )
        enemy_ability_str = (
            f"{enemy_mem.ability_ko} ({enemy_mem.ability_status})"
            if (enemy_mem.ability_ko and enemy_mem.ability_status in ("확정 🔥", "대기", "발동 (+1랭크 ⚡)", "발동 (+2랭크 ⚡)", "발동 (+3랭크 ⚡)", "발동 (+4랭크 ⚡)", "발동 (+5랭크 ⚡)", "발동 (+6랭크 ⚡)"))
            else ""
        )

        # 4. 아군 공격 기술 계산 (아군 ➔ 상대)
        offense_moves: List[MoveCalcBrief] = []
        ally_status_moves: List[str] = []
        ally_moves_ko = ally_sample.get("moves", []) if ally_sample else ["지진", "드래곤클로", "스톤에지", "아이언헤드"]

        defender_with_cur_hp = PokemonInput(
            species=enemy_input.species,
            level=enemy_input.level,
            item=enemy_input.item,
            ability=enemy_input.ability,
            nature=enemy_input.nature,
            evs=enemy_input.evs,
            ivs=enemy_input.ivs,
            boosts=enemy_input.boosts,
            cur_hp=enemy_cur_hp,
        )

        for m_ko in ally_moves_ko:
            m_en = self.adapter.to_move_en(m_ko)
            if not m_en or m_en == m_ko:
                continue
            req = CalcRequest(
                attacker=ally_input,
                defender=defender_with_cur_hp,
                move=m_en,
                gen=0,
            )
            res = bridge.calculate(req)
            if not res.ok:
                continue

            if res.move_category == "Status":
                ally_status_moves.append(m_ko)
                continue

            min_d, max_d = self._parse_damage_range(res.damage)
            is_ko = (min_d >= enemy_cur_hp) if enemy_cur_hp > 0 else False
            ko_desc = self._translate_ko_desc(res.full_desc or res.desc)
            if not ko_desc and is_ko:
                ko_desc = "💥 확정 1타 (KO)"

            offense_moves.append(
                MoveCalcBrief(
                    move_ko=m_ko,
                    move_en=m_en,
                    damage_range=(min_d, max_d),
                    percent_range_str=res.move_desc or f"{min_d}~{max_d}",
                    ko_desc=ko_desc,
                    full_desc=res.full_desc or res.desc,
                    category=res.move_category or "Physical",
                    is_ko=is_ko,
                )
            )

        # 5. 상대 공격 기술 피격 계산: 상대 기술 추정은 배제 (정식 메타 데이터 연동 시 처리)
        defense_moves: List[MoveCalcBrief] = []
        enemy_status_moves: List[str] = []

        ally_pct = (ally_cur_hp / float(ally_max_hp) * 100.0) if ally_max_hp > 0 else 0.0
        ally_boost_desc = self.tracker.format_boosts(ally_mem.boosts)

        return TurnDecisionBrief(
            turn_index=turn_index,
            timestamp_sec=timestamp_sec,
            ally_species_ko=ally_species_ko,
            ally_species_en=ally_input.species,
            ally_cur_hp=ally_cur_hp,
            ally_max_hp=ally_max_hp,
            ally_hp_percent=ally_pct,
            ally_speed=ally_spe,
            ally_item=ally_mem.item_ko,
            ally_ability=ally_mem.ability_ko,
            ally_boost_desc=ally_boost_desc,
            enemy_species_ko=enemy_species_ko,
            enemy_species_en=enemy_input.species,
            enemy_hp_percent=enemy_hp_percent,
            enemy_cur_hp_est=enemy_cur_hp,
            enemy_max_hp_est=enemy_max_hp,
            enemy_speed=enemy_spe,
            enemy_item=enemy_item_str,
            enemy_ability=enemy_ability_str,
            enemy_bulk_desc=enemy_mem.inferred_bulk_label,
            speed_relation=speed_rel,
            speed_desc=speed_desc,
            speed_tiers=speed_tiers,
            scarf_speed_ref=scarf_ref,
            warning_notes=warnings,
            offense_moves=offense_moves,
            defense_moves=defense_moves,
            ally_status_moves=ally_status_moves,
            enemy_status_moves=enemy_status_moves,
        )
