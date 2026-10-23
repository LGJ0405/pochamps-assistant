# -*- coding: utf-8 -*-
"""
schemas.py
데미지 계산 요청/응답 데이터 구조 (Pydantic 또는 dataclass)
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class StatSpread:
    """노력치(EV) 또는 개체값(IV) 분배"""
    hp: int = 0
    atk: int = 0
    def_: int = 0  # 'def'는 예약어라 def_로 표기
    spa: int = 0
    spd: int = 0
    spe: int = 0

    def to_dict(self) -> dict:
        """@smogon/calc 호환 딕셔너리 변환"""
        return {
            "hp": self.hp,
            "atk": self.atk,
            "def": self.def_,
            "spa": self.spa,
            "spd": self.spd,
            "spe": self.spe,
        }


@dataclass
class Boosts:
    """능력치 변화 랭크 (-6 ~ +6)"""
    atk: int = 0
    def_: int = 0
    spa: int = 0
    spd: int = 0
    spe: int = 0

    def to_dict(self) -> dict:
        return {
            "atk": self.atk,
            "def": self.def_,
            "spa": self.spa,
            "spd": self.spd,
            "spe": self.spe,
        }


@dataclass
class PokemonInput:
    """계산에 필요한 포켓몬 정보 (메가진화/리전폼은 species에 'Garchomp-Mega', 'Ninetales-Alola' 형태로 직접 지정)"""
    species: str
    level: int = 50
    item: Optional[str] = None
    ability: Optional[str] = None
    nature: Optional[str] = None
    evs: Optional[StatSpread] = None
    ivs: Optional[StatSpread] = None
    boosts: Optional[Boosts] = None
    status: Optional[str] = None   # 'brn', 'par', 'psn', 'tox', 'slp', 'frz'
    cur_hp: Optional[int] = None   # 현재 HP (백분율 또는 실수)

    def to_dict(self) -> dict:
        """JSON 직렬화용 딕셔너리"""
        d: dict = {"species": self.species, "level": self.level}
        if self.item:
            d["item"] = self.item
        if self.ability:
            d["ability"] = self.ability
        if self.nature:
            d["nature"] = self.nature
        if self.evs:
            d["evs"] = self.evs.to_dict()
        if self.ivs:
            d["ivs"] = self.ivs.to_dict()
        if self.boosts:
            d["boosts"] = self.boosts.to_dict()
        if self.status:
            d["status"] = self.status
        if self.cur_hp is not None:
            d["curHP"] = self.cur_hp
        return d


@dataclass
class FieldInput:
    """필드 상태 (날씨, 필드, 스크린 등)"""
    weather: Optional[str] = None        # 'Sun', 'Rain', 'Sand', 'Hail', 'Snow'
    terrain: Optional[str] = None        # 'Electric', 'Grassy', 'Misty', 'Psychic'
    is_gravity: bool = False
    # 공격 측 조건
    is_reflect: bool = False
    is_light_screen: bool = False
    is_aurora_veil: bool = False
    # 스텔스록, 압정 등은 방어 측
    is_stealth_rock: bool = False
    spikes: int = 0                      # 0~3

    def to_dict(self) -> dict:
        d: dict = {}
        if self.weather:
            d["weather"] = self.weather
        if self.terrain:
            d["terrain"] = self.terrain
        if self.is_gravity:
            d["isGravity"] = True
        # 방어 측 사이드
        defender_side: dict = {}
        if self.is_reflect:
            defender_side["isReflect"] = True
        if self.is_light_screen:
            defender_side["isLightScreen"] = True
        if self.is_aurora_veil:
            defender_side["isAuroraVeil"] = True
        if self.is_stealth_rock:
            defender_side["isSR"] = True
        if self.spikes:
            defender_side["spikes"] = self.spikes
        if defender_side:
            d["defenderSide"] = defender_side
        return d


@dataclass
class CalcRequest:
    """데미지 계산 요청"""
    attacker: PokemonInput
    defender: PokemonInput
    move: str
    field: Optional[FieldInput] = None
    gen: int = 9

    def to_dict(self) -> dict:
        d = {
            "attacker": self.attacker.to_dict(),
            "defender": self.defender.to_dict(),
            "move": self.move,
            "gen": self.gen,
        }
        if self.field:
            d["field"] = self.field.to_dict()
        return d


@dataclass
class CalcResult:
    """데미지 계산 응답"""
    ok: bool
    damage: list | None = None
    desc: str = ""
    full_desc: str = ""
    move_desc: str = ""
    attacker_species: str = ""
    attacker_stats: dict = field(default_factory=dict)
    defender_species: str = ""
    defender_stats: dict = field(default_factory=dict)
    error: str = ""

    @classmethod
    def from_worker_response(cls, data: dict) -> "CalcResult":
        """worker.js 응답 JSON → CalcResult"""
        if not data.get("ok"):
            return cls(ok=False, error=data.get("error", "Unknown error"))
        r = data["result"]
        return cls(
            ok=True,
            damage=r.get("damage"),
            desc=r.get("desc", ""),
            full_desc=r.get("fullDesc", ""),
            move_desc=r.get("moveDesc", ""),
            attacker_species=r.get("attacker", {}).get("species", ""),
            attacker_stats=r.get("attacker", {}).get("stats", {}),
            defender_species=r.get("defender", {}).get("species", ""),
            defender_stats=r.get("defender", {}).get("stats", {}),
        )
