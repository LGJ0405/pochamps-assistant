# -*- coding: utf-8 -*-
"""
phase_detector.py
[Step 3-3] 포챔스 인게임 화면 페이즈(선출 화면 / 배틀 커맨드 / 배틀 진행 / 화면 전환) 판별 모듈
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class GamePhase(str, Enum):
    """포챔스 인게임 화면 상태 페이즈"""
    TEAM_PREVIEW = "TEAM_PREVIEW"      # 선출 화면 (상대 6마리 & 내 엔트리 6마리 표시)
    BATTLE_COMMAND = "BATTLE_COMMAND"  # 배틀 행동/기술 선택 화면 (HUD + COMMAND 타이머 활성화)
    BATTLE_ACTIVE = "BATTLE_ACTIVE"    # 배틀 진행 화면 (상대/아군 HUD 표시 중, 연출 전/후)
    TRANSITION = "TRANSITION"          # 카메라 클로즈업 연출, 교체 메뉴, 대기/로딩 화면


@dataclass
class PhaseDetectionResult:
    """단일 프레임 페이즈 판별 결과"""
    phase: GamePhase
    confidence: float
    command_timer: Optional[int] = None
    reason: str = ""
