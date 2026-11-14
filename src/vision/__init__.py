# -*- coding: utf-8 -*-
"""
src.vision 패키지
"""

from .battle_ocr import AllyHPResult, BattleOCR, CommandBannerResult, EnemyHPResult
from .cropper import ROICropper, imread_safe, imwrite_safe
from .icon_matcher import IconMatcher, IconMatchResult
from .party_ocr import KoreanOCR, PartyParser, PokemonSlotData

# 비디오/영상 추적 모듈 (선택적 임포트)
try:
    from .phase_detector import GamePhase, PhaseDetectionResult
except ImportError:
    GamePhase = None
    PhaseDetectionResult = None

try:
    from .video_tracker import (
        BattleTurnEvent,
        BattleVideoTracker,
        FrameVisionState,
        VideoAnalysisReport,
    )
except ImportError:
    BattleTurnEvent = None
    BattleVideoTracker = None
    FrameVisionState = None
    VideoAnalysisReport = None

# 루트 배틀 어드바이저 편의 노출
try:
    from ..battle_advisor import BattleAdvisor, MoveCalcBrief, TurnDecisionBrief
except ImportError:
    BattleAdvisor = None
    MoveCalcBrief = None
    TurnDecisionBrief = None

__all__ = [
    "ROICropper",
    "imread_safe",
    "imwrite_safe",
    "IconMatcher",
    "IconMatchResult",
    "GamePhase",
    "PhaseDetectionResult",
    "BattleOCR",
    "EnemyHPResult",
    "AllyHPResult",
    "CommandBannerResult",
    "KoreanOCR",
    "PartyParser",
    "PokemonSlotData",
    "BattleVideoTracker",
    "FrameVisionState",
    "BattleTurnEvent",
    "VideoAnalysisReport",
    "BattleAdvisor",
    "TurnDecisionBrief",
    "MoveCalcBrief",
]
