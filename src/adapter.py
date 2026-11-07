# -*- coding: utf-8 -*-
"""
adapter.py
한국어로 작성된 포챔스 배틀 데이터(샘플, 파티)를
데미지 계산 엔진(@smogon/calc)이 요구하는 영문 PokemonInput / CalcRequest로 변환하는 어댑터
"""

import json
from pathlib import Path
from typing import Any, Optional

from .schemas import PokemonInput, StatSpread, CalcRequest, FieldInput

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_KO_TO_EN_PATH = _PROJECT_ROOT / "data" / "ko_to_en.json"


class DataAdapter:
    """한영 사전(ko_to_en.json) 기반 데이터 변환기"""

    def __init__(self, ko_to_en_path: Optional[Path] = None):
        path = ko_to_en_path or _KO_TO_EN_PATH
        with open(path, "r", encoding="utf-8") as f:
            self._dict = json.load(f)

        self._species = self._dict.get("species", {})
        self._moves = self._dict.get("moves", {})
        self._abilities = self._dict.get("abilities", {})
        self._items = self._dict.get("items", {})
        self._natures = self._dict.get("natures", {})

        # 역참조 사전 구축 (영문 소문자 슬러그 -> 정식 영문 종족명 / 한글 종족명)
        self._slug_to_en: dict[str, str] = {}
        self._en_to_ko: dict[str, str] = {}
        for ko_name, en_name in self._species.items():
            slug = en_name.strip().lower()
            self._slug_to_en[slug] = en_name
            if en_name not in self._en_to_ko:
                self._en_to_ko[en_name] = ko_name
            if slug not in self._en_to_ko:
                self._en_to_ko[slug] = ko_name

    def to_species_en(self, name_ko: str) -> str:
        """포켓몬 한글명 또는 영문 슬러그 -> 계산기용 정식 영문 종족명"""
        if name_ko in self._species:
            return self._species[name_ko]
        slug = name_ko.strip().lower()
        return self._slug_to_en.get(slug, name_ko)

    def to_species_ko(self, name_en_or_slug: str) -> str:
        """영문 종족명 또는 파일명 슬러그 -> 한글 종족명 역참조"""
        if name_en_or_slug in self._en_to_ko:
            return self._en_to_ko[name_en_or_slug]
        slug = name_en_or_slug.strip().lower()
        return self._en_to_ko.get(slug, name_en_or_slug)

    def to_move_en(self, move_ko: str) -> str:
        """기술 한글명 -> 영문 기술명"""
        return self._moves.get(move_ko, move_ko)

    def to_ability_en(self, ability_ko: str) -> str:
        """특성 한글명 -> 영문 특성명"""
        return self._abilities.get(ability_ko, ability_ko)

    def to_item_en(self, item_ko: str) -> str:
        """도구 한글명 -> 영문 도구명"""
        return self._items.get(item_ko, item_ko)

    def to_nature_en(self, nature_ko: str) -> str:
        """성격 한글명 -> 영문 성격명"""
        return self._natures.get(nature_ko, nature_ko)

    def sample_to_pokemon_input(self, sample: dict[str, Any], use_mega: bool = True) -> PokemonInput:
        """
        포챔스 한글 샘플 객체 -> PokemonInput 변환
        use_mega=True인 경우 gimmick.mega가 있으면 메가진화 폼과 특성을 우선 적용합니다.
        """
        # 메가진화 적용 여부 판단
        gimmick = sample.get("gimmick", {})
        mega_info = gimmick.get("mega") if (use_mega and gimmick) else None

        if mega_info:
            target_species_ko = mega_info.get("form", sample["name"])
            target_ability_ko = mega_info.get("ability", sample.get("ability", ""))
        else:
            target_species_ko = sample["name"]
            target_ability_ko = sample.get("ability", "")

        species_en = self.to_species_en(target_species_ko)
        item_en = self.to_item_en(sample.get("item", ""))
        ability_en = self.to_ability_en(target_ability_ko)
        nature_en = self.to_nature_en(sample.get("nature", "성실"))

        evs_raw = sample.get("evs", {})
        evs = StatSpread(
            hp=evs_raw.get("hp", 0),
            atk=evs_raw.get("atk", 0),
            def_=evs_raw.get("def", 0),
            spa=evs_raw.get("spa", 0),
            spd=evs_raw.get("spd", 0),
            spe=evs_raw.get("spe", 0),
        )

        return PokemonInput(
            species=species_en,
            level=sample.get("level", 50),
            item=item_en or None,
            ability=ability_en or None,
            nature=nature_en or None,
            evs=evs,
        )
