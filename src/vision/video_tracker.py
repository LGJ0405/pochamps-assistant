# -*- coding: utf-8 -*-
"""
video_tracker.py
[Step 3-3] 정지 스크린샷 및 배틀 녹화 영상(.mp4) 기반 비전 상태 추적기
- 단일 프레임에서 페이즈(TEAM_PREVIEW / BATTLE_COMMAND / BATTLE_ACTIVE / TRANSITION)를 판별합니다.
- 선출 화면(TEAM_PREVIEW)이 감지되면 상대 6마리 및 아군 6마리 엔트리를 자동 잠금(Lock-in)하고,
  배틀 중 등장 가능한 후보군(일반 폼 + 메가진화/폼체인지)을 구성합니다.
- 배틀 화면(BATTLE_COMMAND / BATTLE_ACTIVE)에서는 HUD 미니 아이콘으로 현재 필드 포켓몬 및 메가진화 여부를 식별하고,
  RapidOCR 배치 추론으로 상대 체력(%)과 아군 체력(현재/최대) 및 COMMAND 타이머를 추출합니다.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional, Set, Tuple, Union

import cv2
import numpy as np

from .battle_ocr import (
    AllyHPResult,
    BattleOCR,
    BattleSubtitleEvent,
    BattleSubtitleOCR,
    CommandBannerResult,
    EnemyHPResult,
)
from .cropper import ROICropper
from .icon_matcher import IconMatcher, IconMatchResult
from .phase_detector import GamePhase

# 순환 참조 방지를 위해 지연 로드 또는 선택적 임포트
try:
    from ..battle_advisor import BattleAdvisor, TurnDecisionBrief
except ImportError:
    BattleAdvisor = None
    TurnDecisionBrief = None


@dataclass
class FrameVisionState:
    """단일 프레임의 비전 인식 결과 스냅샷"""
    timestamp_sec: float
    phase: GamePhase
    elapsed_ms: float
    # 선출 화면 결과 (TEAM_PREVIEW 시 채워짐)
    enemy_team: List[IconMatchResult] = field(default_factory=list)
    ally_team: List[IconMatchResult] = field(default_factory=list)
    # 배틀 화면 결과 (BATTLE_COMMAND / BATTLE_ACTIVE 시 채워짐)
    active_enemy: Optional[IconMatchResult] = None
    active_ally: Optional[IconMatchResult] = None
    enemy_hp: Optional[EnemyHPResult] = None
    ally_hp: Optional[AllyHPResult] = None
    command_banner: Optional[CommandBannerResult] = None
    is_enemy_mega: bool = False
    is_ally_mega: bool = False
    # 배틀 중 하단 자막 인식 이벤트
    subtitle_events: List[BattleSubtitleEvent] = field(default_factory=list)


@dataclass
class BattleTurnEvent:
    """녹화 영상에서 추출된 턴/상태 변화 이벤트"""
    event_index: int
    turn_index: Optional[int]  # BATTLE_COMMAND 기준 턴 번호 (1, 2, ...)
    timestamp_sec: float
    phase: GamePhase
    enemy_species_ko: str
    enemy_species_en: str
    enemy_slug: str
    enemy_similarity: float
    enemy_hp_percent: int
    is_enemy_mega: bool
    ally_species_ko: str
    ally_species_en: str
    ally_slug: str
    ally_similarity: float
    ally_cur_hp: int
    ally_max_hp: int
    ally_hp_percent: float
    is_ally_mega: bool
    command_timer: Optional[int] = None
    decision_brief: Optional[Any] = None  # TurnDecisionBrief 인스턴스 (실시간 데미지/선후공 브리핑)


@dataclass
class VideoAnalysisReport:
    """녹화 영상 전체 비전 분석 리포트"""
    video_path: Path
    duration_sec: float
    fps: float
    sampled_frames: int
    avg_frame_ms: float
    preview_timestamp_sec: Optional[float]
    enemy_preview_team: List[IconMatchResult]
    ally_preview_team: List[IconMatchResult]
    command_turns: List[BattleTurnEvent]
    state_events: List[BattleTurnEvent]


@dataclass
class _PendingTurnContext:
    """직전 커맨드 턴부터 다음 커맨드 턴까지 교전/자막/체력 변화를 누적하는 컨텍스트"""
    turn_index: int
    ally_species_ko: str
    enemy_species_ko: str
    ally_slug: str
    enemy_slug: str
    ally_eff_spe: int
    enemy_spe_rank: int
    enemy_max_base_spe: int
    enemy_hp_start_pct: int
    ally_boosts_snapshot: Optional[Any] = None
    enemy_boosts_snapshot: Optional[Any] = None
    is_ally_mega: bool = False
    is_enemy_mega: bool = False
    first_actor: Optional[str] = None
    ally_move_ko: str = ""
    enemy_move_ko: str = ""
    hit_count: int = 0
    enemy_hp_after_pct: Optional[int] = None
    extra_warnings: List[str] = field(default_factory=list)


class BattleVideoTracker:
    """포챔스 배틀 화면 및 녹화 영상 비전 상태 추적기"""

    def __init__(
        self,
        cropper: Optional[ROICropper] = None,
        preview_matcher: Optional[IconMatcher] = None,
        battle_matcher: Optional[IconMatcher] = None,
        ocr: Optional[BattleOCR] = None,
        subtitle_ocr: Optional[BattleSubtitleOCR] = None,
        enable_subtitle_ocr: bool = True,
        hud_similarity_threshold: float = 60.0,
        preview_avg_threshold: float = 62.0,
        preview_min_threshold: float = 50.0,
    ):
        self.cropper = cropper or ROICropper()
        self.preview_matcher = preview_matcher or IconMatcher(include_mega_in_preview=False)
        self.battle_matcher = battle_matcher or IconMatcher(include_mega_in_preview=True)
        self.ocr = ocr or BattleOCR()
        self.enable_subtitle_ocr = enable_subtitle_ocr
        self.subtitle_ocr = subtitle_ocr or (BattleSubtitleOCR() if enable_subtitle_ocr else None)

        self.hud_similarity_threshold = hud_similarity_threshold
        self.preview_avg_threshold = preview_avg_threshold
        self.preview_min_threshold = preview_min_threshold

        # 실시간 의사결정 브리퍼 (선택적 활성화)
        self.advisor: Optional[Any] = None

        # 선출 화면에서 확정된 6마리 엔트리 및 배틀 후보 슬러그 집합
        self.locked_enemy_team: List[IconMatchResult] = []
        self.locked_ally_team: List[IconMatchResult] = []
        self.locked_preview_timestamp: Optional[float] = None
        self._best_preview_avg_sim: float = 0.0
        self._enemy_candidate_slugs: Set[str] = set()
        self._ally_candidate_slugs: Set[str] = set()
        # 교체 창 등 HUD 일부가 가려진 커맨드 상태 보존용 직전 활성 배틀 상태
        self._last_active_state: Optional[FrameVisionState] = None

    def reset_session(self) -> None:
        """새로운 배틀 영상/세션 분석을 위해 선출 엔트리 잠금 상태를 초기화합니다."""
        self.locked_enemy_team.clear()
        self.locked_ally_team.clear()
        self.locked_preview_timestamp = None
        self._best_preview_avg_sim = 0.0
        self._enemy_candidate_slugs.clear()
        self._ally_candidate_slugs.clear()
        self._last_active_state = None
        if self.subtitle_ocr is not None:
            self.subtitle_ocr.reset()
        if self.advisor and hasattr(self.advisor, "reset_session"):
            self.advisor.reset_session()

    def analyze_frame(self, frame: np.ndarray, timestamp_sec: float = 0.0) -> FrameVisionState:
        """단일 프레임을 분석하여 페이즈, 선출 6마리 또는 배틀 필드 포켓몬·체력 정보를 반환합니다."""
        t0 = time.perf_counter()

        # ------------------------------------------------------------------
        # 1단계: 배틀 상태창(HUD) 미니 아이콘 고속 검사 (~2ms)
        # ------------------------------------------------------------------
        battle_crops = self.cropper.crop_battle_rois(frame)
        enemy_hud = self.battle_matcher.match_single(battle_crops["enemy_hud_icon"], slot_num=1)
        ally_hud = self.battle_matcher.match_single(battle_crops["ally_hud_icon"], slot_num=1)

        if (
            enemy_hud.similarity >= self.hud_similarity_threshold
            and ally_hud.similarity >= self.hud_similarity_threshold
        ):
            # 선출 화면 엔트리가 이미 잠금되어 있다면 후보군(메가진화 포함) 내 매칭으로 교차 보정
            if self._enemy_candidate_slugs and enemy_hud.slug not in self._enemy_candidate_slugs:
                cand_e = self.battle_matcher.match_single(
                    battle_crops["enemy_hud_icon"],
                    slot_num=1,
                    allowed_slugs=self._enemy_candidate_slugs,
                )
                if cand_e.similarity >= self.preview_min_threshold:
                    enemy_hud = cand_e

            if self._ally_candidate_slugs and ally_hud.slug not in self._ally_candidate_slugs:
                cand_a = self.battle_matcher.match_single(
                    battle_crops["ally_hud_icon"],
                    slot_num=1,
                    allowed_slugs=self._ally_candidate_slugs,
                )
                if cand_a.similarity >= self.preview_min_threshold:
                    ally_hud = cand_a

            cmd_crop = self.cropper.crop_rect(frame, self.cropper.phase_indicators["command_banner"])
            enemy_hp, ally_hp, cmd_banner = self.ocr.recognize_battle_hud_texts(
                battle_crops["enemy_hp_text"],
                battle_crops["ally_hp_text"],
                cmd_crop,
            )

            if enemy_hp.is_valid and ally_hp.is_valid:
                phase = GamePhase.BATTLE_COMMAND if cmd_banner.is_command else GamePhase.BATTLE_ACTIVE
                sub_events: List[BattleSubtitleEvent] = []
                if phase == GamePhase.BATTLE_ACTIVE and self.enable_subtitle_ocr and self.subtitle_ocr is not None:
                    sub_crop = self.cropper.crop_battle_subtitle(frame)
                    sub_events = self.subtitle_ocr.recognize_and_parse(
                        sub_crop,
                        ally_species_ko=ally_hud.species_ko,
                        enemy_species_ko=enemy_hud.species_ko,
                    )
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                st = FrameVisionState(
                    timestamp_sec=timestamp_sec,
                    phase=phase,
                    elapsed_ms=elapsed_ms,
                    active_enemy=enemy_hud,
                    active_ally=ally_hud,
                    enemy_hp=enemy_hp,
                    ally_hp=ally_hp,
                    command_banner=cmd_banner,
                    is_enemy_mega="-mega" in enemy_hud.slug,
                    is_ally_mega="-mega" in ally_hud.slug,
                    subtitle_events=sub_events,
                )
                self._last_active_state = st
                return st

        # ------------------------------------------------------------------
        # 2단계: 선출 화면(TEAM_PREVIEW) 여부 고속 검사
        # 1번 슬롯 2개만 먼저 프로빙(~0.7ms) 후 통과 시 12슬롯 전체 매칭(~4ms)
        # ------------------------------------------------------------------
        e_slot1_img = self.cropper.crop_rect(frame, self.cropper.enemy_team_slots[0])
        a_slot1_img = self.cropper.crop_rect(frame, self.cropper.ally_team_slots[0])

        probe_e1 = self.preview_matcher.match_single(e_slot1_img, slot_num=1)
        probe_a1 = self.preview_matcher.match_single(a_slot1_img, slot_num=1)

        if (
            probe_e1.similarity >= self.preview_min_threshold
            and probe_a1.similarity >= self.preview_min_threshold
        ):
            enemy_slots = self.cropper.crop_enemy_slots(frame)
            ally_slots = self.cropper.crop_ally_slots(frame)
            enemy_team = [probe_e1] + [
                self.preview_matcher.match_single(img, slot_num=i)
                for i, img in enumerate(enemy_slots[1:], 2)
            ]
            ally_team = [probe_a1] + [
                self.preview_matcher.match_single(img, slot_num=i)
                for i, img in enumerate(ally_slots[1:], 2)
            ]
            all_sims = [r.similarity for r in enemy_team + ally_team]
            avg_sim = float(np.mean(all_sims))
            min_sim = float(np.min(all_sims))

            if avg_sim >= self.preview_avg_threshold and min_sim >= self.preview_min_threshold:
                if avg_sim > self._best_preview_avg_sim:
                    self._best_preview_avg_sim = avg_sim
                    self.locked_enemy_team = enemy_team
                    self.locked_ally_team = ally_team
                    if self.locked_preview_timestamp is None:
                        self.locked_preview_timestamp = timestamp_sec
                    self._enemy_candidate_slugs = self.battle_matcher.expand_candidate_slugs(
                        [r.slug for r in enemy_team]
                    )
                    self._ally_candidate_slugs = self.battle_matcher.expand_candidate_slugs(
                        [r.slug for r in ally_team]
                    )

                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                return FrameVisionState(
                    timestamp_sec=timestamp_sec,
                    phase=GamePhase.TEAM_PREVIEW,
                    elapsed_ms=elapsed_ms,
                    enemy_team=enemy_team,
                    ally_team=ally_team,
                )

        # ------------------------------------------------------------------
        # 2.5단계: 교체 선택 메뉴(포켓몬 창) / 기술 설명 창 등 HUD가 가려진 커맨드 상태 보존
        # ------------------------------------------------------------------
        if (
            self._last_active_state is not None
            and self._last_active_state.ally_hp is not None
            and self._last_active_state.ally_hp.cur_hp is not None
            and self._last_active_state.ally_hp.cur_hp > 0
            and self._last_active_state.enemy_hp is not None
            and self._last_active_state.enemy_hp.hp_percent is not None
            and self._last_active_state.enemy_hp.hp_percent > 0
        ):
            cmd_crop = self.cropper.crop_rect(frame, self.cropper.phase_indicators["command_banner"])
            cmd_banner = self.ocr.recognize_command_banner(cmd_crop)
            if cmd_banner.is_command:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                return FrameVisionState(
                    timestamp_sec=timestamp_sec,
                    phase=GamePhase.BATTLE_COMMAND,
                    elapsed_ms=elapsed_ms,
                    active_enemy=self._last_active_state.active_enemy,
                    active_ally=self._last_active_state.active_ally,
                    enemy_hp=self._last_active_state.enemy_hp,
                    ally_hp=self._last_active_state.ally_hp,
                    command_banner=cmd_banner,
                    is_enemy_mega=self._last_active_state.is_enemy_mega,
                    is_ally_mega=self._last_active_state.is_ally_mega,
                )

        # ------------------------------------------------------------------
        # 3단계: 연출/애니메이션/대기 화면 (TRANSITION) + 하단 자막 OCR 감지
        # ------------------------------------------------------------------
        sub_events = []
        if (
            self.enable_subtitle_ocr
            and self.subtitle_ocr is not None
            and self._last_active_state is not None
            and self._last_active_state.active_ally is not None
            and self._last_active_state.active_enemy is not None
        ):
            sub_crop = self.cropper.crop_battle_subtitle(frame)
            sub_events = self.subtitle_ocr.recognize_and_parse(
                sub_crop,
                ally_species_ko=self._last_active_state.active_ally.species_ko,
                enemy_species_ko=self._last_active_state.active_enemy.species_ko,
            )

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return FrameVisionState(
            timestamp_sec=timestamp_sec,
            phase=GamePhase.TRANSITION,
            elapsed_ms=elapsed_ms,
            subtitle_events=sub_events,
        )

    def _finalize_pending_turn(
        self,
        pending: _PendingTurnContext,
        next_ally_ko: str,
        next_enemy_ko: str,
        next_enemy_hp_pct: int,
    ) -> List[str]:
        """직전 커맨드 턴 이후 교전 결과(랭크 보완, 선후공 역추론, 내구 역산)를 정산합니다."""
        ally_same = (pending.ally_species_ko.replace("메가", "") == next_ally_ko.replace("메가", ""))
        notes: List[str] = [
            w for w in pending.extra_warnings
            if ally_same or "[랭크 변화] 아군" not in w
        ]
        if self.advisor is None or not hasattr(self.advisor, "tracker"):
            return notes

        tracker = self.advisor.tracker

        # 1. 기술 사용에 따른 자가 랭크 변화 보완 (자막에서 1줄 놓친 경우 자동 복구)
        if pending.ally_move_ko:
            side_msgs = tracker.apply_move_side_effects(
                pending.ally_species_ko, is_ally=True, move_ko=pending.ally_move_ko, turn_index=pending.turn_index
            )
            if ally_same:
                notes.extend(side_msgs)
        if pending.enemy_move_ko:
            notes.extend(
                tracker.apply_move_side_effects(
                    pending.enemy_species_ko, is_ally=False, move_ko=pending.enemy_move_ko, turn_index=pending.turn_index
                )
            )

        # 2. 실전 선후공 역추론 (아군이 교체 턴이 아닐 때만 순수 스피드 역추론 적용)
        if pending.first_actor == "ally" or (pending.first_actor == "enemy" and pending.ally_move_ko):
            order_note = tracker.record_turn_order(
                ally_species_ko=pending.ally_species_ko,
                enemy_species_ko=pending.enemy_species_ko,
                first_actor=pending.first_actor,
                ally_move_ko=pending.ally_move_ko,
                enemy_move_ko=pending.enemy_move_ko,
                ally_eff_spe_at_action=pending.ally_eff_spe,
                enemy_spe_rank_at_action=pending.enemy_spe_rank,
                enemy_max_base_spe=pending.enemy_max_base_spe,
                turn_index=pending.turn_index,
            )
            if order_note:
                notes.append(order_note)

        # 3. 상대 내구 범위 역추론 (아군 공격 후 동일 상대 잔여 HP 감소량 기반)
        clean_prev_e = pending.enemy_species_ko.replace("메가", "")
        clean_next_e = next_enemy_ko.replace("메가", "")
        end_hp_pct: Optional[int] = None
        if clean_prev_e == clean_next_e:
            end_hp_pct = next_enemy_hp_pct
        elif pending.enemy_hp_after_pct is not None:
            end_hp_pct = pending.enemy_hp_after_pct

        if (
            pending.ally_move_ko
            and end_hp_pct is not None
            and 0 < end_hp_pct < pending.enemy_hp_start_pct
            and hasattr(self.advisor, "infer_enemy_bulk")
        ):
            delta_pct = pending.enemy_hp_start_pct - end_hp_pct
            bulk_note = self.advisor.infer_enemy_bulk(
                ally_species_ko=pending.ally_species_ko,
                enemy_species_ko=pending.enemy_species_ko,
                move_ko=pending.ally_move_ko,
                damage_pct=delta_pct,
                hit_count=pending.hit_count,
                ally_boosts=pending.ally_boosts_snapshot,
                enemy_boosts=pending.enemy_boosts_snapshot,
                is_ally_mega=pending.is_ally_mega,
                is_enemy_mega=pending.is_enemy_mega,
            )
            if bulk_note:
                notes.append(bulk_note)

        return notes

    def analyze_video(
        self,
        video_path: Union[str, Path],
        sample_interval_sec: float = 1.0,
        start_sec: float = 0.0,
        end_sec: Optional[float] = None,
        on_event: Optional[Callable[[str, Any], None]] = None,
    ) -> VideoAnalysisReport:
        """
        배틀 녹화 영상(.mp4)을 일정 간격(sample_interval_sec)으로 순회하며
        1) 선출 화면 6v6 엔트리 자동 잠금
        2) 턴별 커맨드 페이즈(BATTLE_COMMAND) 및 주요 교전 상태 변화(BATTLE_ACTIVE) 시계열 추출
        3) 교전 중 자막 기반 기술·랭크·타수·선후공 역추론 및 내구 역산
        을 수행하여 리포트를 반환합니다.
        """
        vpath = Path(video_path)
        if not vpath.exists():
            raise FileNotFoundError(f"배틀 녹화 영상을 찾을 수 없습니다: {vpath}")

        self.reset_session()
        cap = cv2.VideoCapture(str(vpath))
        if not cap.isOpened():
            raise RuntimeError(f"배틀 녹화 영상을 열 수 없습니다: {vpath}")

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration_sec = total_frames / fps if fps > 0 else 0.0
        stop_sec = min(duration_sec, end_sec) if end_sec is not None else duration_sec

        command_turns: List[BattleTurnEvent] = []
        state_events: List[BattleTurnEvent] = []
        frame_times_ms: List[float] = []
        sampled_count = 0
        preview_reported = False
        pending_turn: Optional[_PendingTurnContext] = None

        start_frame = max(0, int(round(start_sec * fps)))
        stop_frame = min(total_frames - 1, int(round(stop_sec * fps))) if total_frames > 0 else 0
        step_frames = max(1, int(round(sample_interval_sec * fps)))

        if start_frame > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        frame_idx = start_frame
        while frame_idx <= stop_frame:
            ok = cap.grab()
            if not ok:
                break

            if (frame_idx - start_frame) % step_frames != 0:
                frame_idx += 1
                continue

            ok_ret, frame = cap.retrieve()
            if not ok_ret or frame is None:
                frame_idx += 1
                continue

            cur_sec = frame_idx / fps
            sampled_count += 1
            state = self.analyze_frame(frame, timestamp_sec=round(cur_sec, 1))
            frame_times_ms.append(state.elapsed_ms)

            # 선출 화면 최초 확정 시 콜백 호출
            if not preview_reported and self.locked_enemy_team and self.locked_ally_team:
                preview_reported = True
                if on_event:
                    on_event("preview_locked", {
                        "enemy": list(self.locked_enemy_team),
                        "ally": list(self.locked_ally_team),
                        "timestamp_sec": self.locked_preview_timestamp,
                    })

            # 교전 중 하단 자막 이벤트 처리 (TRANSITION 또는 BATTLE_ACTIVE)
            if state.subtitle_events and pending_turn is not None:
                for sub_evt in state.subtitle_events:
                    if sub_evt.event_type == "move_use":
                        if pending_turn.first_actor is None:
                            pending_turn.first_actor = "ally" if sub_evt.is_ally else "enemy"
                        if sub_evt.is_ally and not pending_turn.ally_move_ko:
                            pending_turn.ally_move_ko = sub_evt.move_ko
                        elif sub_evt.is_ally is False and not pending_turn.enemy_move_ko:
                            pending_turn.enemy_move_ko = sub_evt.move_ko
                    elif sub_evt.event_type == "stat_change" and self.advisor and hasattr(self.advisor, "tracker"):
                        target_species = (
                            pending_turn.ally_species_ko if sub_evt.is_ally else pending_turn.enemy_species_ko
                        )
                        msg = self.advisor.tracker.apply_stat_change(
                            species_ko=target_species,
                            is_ally=bool(sub_evt.is_ally),
                            stat_key=sub_evt.stat_key,
                            delta=sub_evt.stat_delta,
                            turn_index=pending_turn.turn_index,
                        )
                        if msg:
                            pending_turn.extra_warnings.append(msg)
                    elif sub_evt.event_type == "hit_count" and sub_evt.hit_count > 0:
                        pending_turn.hit_count = sub_evt.hit_count

            if state.phase in (GamePhase.BATTLE_COMMAND, GamePhase.BATTLE_ACTIVE):
                assert state.active_enemy is not None and state.active_ally is not None
                assert state.enemy_hp is not None and state.ally_hp is not None
                assert state.enemy_hp.hp_percent is not None
                assert state.ally_hp.cur_hp is not None and state.ally_hp.max_hp is not None
                assert state.ally_hp.hp_percent is not None

                cur_sig = (
                    state.active_enemy.slug,
                    state.enemy_hp.hp_percent,
                    state.active_ally.slug,
                    state.ally_hp.cur_hp,
                )

                # 1) 커맨드 턴(BATTLE_COMMAND) 중복 제거 및 턴 번호 부여
                if state.phase == GamePhase.BATTLE_COMMAND:
                    is_new_turn = True
                    cur_timer = state.command_banner.timer_sec if state.command_banner else None
                    if command_turns:
                        prev_turn = command_turns[-1]
                        prev_sig = (
                            prev_turn.enemy_slug,
                            prev_turn.enemy_hp_percent,
                            prev_turn.ally_slug,
                            prev_turn.ally_cur_hp,
                        )
                        timer_restarted = (
                            cur_timer is not None
                            and prev_turn.command_timer is not None
                            and cur_timer > prev_turn.command_timer + 1
                        )
                        # 같은 포켓몬·같은 체력 상태이고 타이머 리셋 없이 15초 미만 연속이면 동일 턴 중복
                        if cur_sig == prev_sig and (state.timestamp_sec - prev_turn.timestamp_sec) < 15.0 and not timer_restarted:
                            is_new_turn = False

                    if is_new_turn:
                        turn_num = len(command_turns) + 1

                        # 직전 턴 교전 정산 (랭크 보완, 선후공 역추론, 내구 역산)
                        extra_warnings: List[str] = []
                        if pending_turn is not None:
                            extra_warnings = self._finalize_pending_turn(
                                pending=pending_turn,
                                next_ally_ko=state.active_ally.species_ko,
                                next_enemy_ko=state.active_enemy.species_ko,
                                next_enemy_hp_pct=state.enemy_hp.hp_percent,
                            )

                        # 실시간 의사결정 브리핑 (BattleAdvisor 연동)
                        brief = None
                        if self.advisor is not None:
                            try:
                                brief = self.advisor.evaluate_turn(
                                    ally_species_ko=state.active_ally.species_ko,
                                    enemy_species_ko=state.active_enemy.species_ko,
                                    ally_cur_hp=state.ally_hp.cur_hp,
                                    ally_max_hp=state.ally_hp.max_hp,
                                    enemy_hp_percent=state.enemy_hp.hp_percent,
                                    turn_index=turn_num,
                                    timestamp_sec=state.timestamp_sec,
                                    is_ally_mega=state.is_ally_mega,
                                    is_enemy_mega=state.is_enemy_mega,
                                    extra_warnings=extra_warnings,
                                )
                            except Exception:
                                brief = None

                        # 새 턴의 교전 추적을 위한 스냅샷 생성
                        ally_boosts_snap = None
                        enemy_boosts_snap = None
                        e_spe_rank = 0
                        e_max_base_spe = 0
                        if self.advisor is not None and hasattr(self.advisor, "tracker"):
                            a_m = self.advisor.tracker.get_or_create_memory(state.active_ally.species_ko, is_ally=True)
                            e_m = self.advisor.tracker.get_or_create_memory(state.active_enemy.species_ko, is_ally=False)
                            ally_boosts_snap = copy.deepcopy(a_m.boosts)
                            enemy_boosts_snap = copy.deepcopy(e_m.boosts)
                            e_spe_rank = e_m.boosts.spe
                        if brief is not None and brief.speed_tiers:
                            e_max_base_spe = brief.speed_tiers[0].base_spe

                        pending_turn = _PendingTurnContext(
                            turn_index=turn_num,
                            ally_species_ko=state.active_ally.species_ko,
                            enemy_species_ko=state.active_enemy.species_ko,
                            ally_slug=state.active_ally.slug,
                            enemy_slug=state.active_enemy.slug,
                            ally_eff_spe=brief.ally_speed if brief else 0,
                            enemy_spe_rank=e_spe_rank,
                            enemy_max_base_spe=e_max_base_spe,
                            enemy_hp_start_pct=state.enemy_hp.hp_percent,
                            ally_boosts_snapshot=ally_boosts_snap,
                            enemy_boosts_snapshot=enemy_boosts_snap,
                            is_ally_mega=state.is_ally_mega,
                            is_enemy_mega=state.is_enemy_mega,
                        )

                        turn_evt = BattleTurnEvent(
                            event_index=len(state_events) + 1,
                            turn_index=turn_num,
                            timestamp_sec=state.timestamp_sec,
                            phase=state.phase,
                            enemy_species_ko=state.active_enemy.species_ko,
                            enemy_species_en=state.active_enemy.species_en,
                            enemy_slug=state.active_enemy.slug,
                            enemy_similarity=state.active_enemy.similarity,
                            enemy_hp_percent=state.enemy_hp.hp_percent,
                            is_enemy_mega=state.is_enemy_mega,
                            ally_species_ko=state.active_ally.species_ko,
                            ally_species_en=state.active_ally.species_en,
                            ally_slug=state.active_ally.slug,
                            ally_similarity=state.active_ally.similarity,
                            ally_cur_hp=state.ally_hp.cur_hp,
                            ally_max_hp=state.ally_hp.max_hp,
                            ally_hp_percent=state.ally_hp.hp_percent,
                            is_ally_mega=state.is_ally_mega,
                            command_timer=cur_timer,
                            decision_brief=brief,
                        )
                        command_turns.append(turn_evt)
                        state_events.append(turn_evt)
                        if on_event:
                            on_event("turn_detected", turn_evt)

                # 2) 일반 배틀 진행(BATTLE_ACTIVE) 중 포켓몬/체력이 변한 경우도 상태 타임라인에 기록
                else:
                    if pending_turn is not None and state.active_enemy.slug == pending_turn.enemy_slug:
                        if state.enemy_hp.hp_percent < pending_turn.enemy_hp_start_pct:
                            pending_turn.enemy_hp_after_pct = state.enemy_hp.hp_percent

                    should_record_active = False
                    if not state_events:
                        should_record_active = True
                    else:
                        last_evt = state_events[-1]
                        last_sig = (
                            last_evt.enemy_slug,
                            last_evt.enemy_hp_percent,
                            last_evt.ally_slug,
                            last_evt.ally_cur_hp,
                        )
                        if cur_sig != last_sig:
                            should_record_active = True

                    if should_record_active:
                        if self.advisor and hasattr(self.advisor, "tracker"):
                            self.advisor.tracker.on_active_event(
                                ally_species_ko=state.active_ally.species_ko,
                                enemy_species_ko=state.active_enemy.species_ko,
                                ally_cur_hp=state.ally_hp.cur_hp,
                                ally_max_hp=state.ally_hp.max_hp,
                                enemy_hp_percent=state.enemy_hp.hp_percent,
                            )
                        active_evt = BattleTurnEvent(
                            event_index=len(state_events) + 1,
                            turn_index=None,
                            timestamp_sec=state.timestamp_sec,
                            phase=state.phase,
                            enemy_species_ko=state.active_enemy.species_ko,
                            enemy_species_en=state.active_enemy.species_en,
                            enemy_slug=state.active_enemy.slug,
                            enemy_similarity=state.active_enemy.similarity,
                            enemy_hp_percent=state.enemy_hp.hp_percent,
                            is_enemy_mega=state.is_enemy_mega,
                            ally_species_ko=state.active_ally.species_ko,
                            ally_species_en=state.active_ally.species_en,
                            ally_slug=state.active_ally.slug,
                            ally_similarity=state.active_ally.similarity,
                            ally_cur_hp=state.ally_hp.cur_hp,
                            ally_max_hp=state.ally_hp.max_hp,
                            ally_hp_percent=state.ally_hp.hp_percent,
                            is_ally_mega=state.is_ally_mega,
                            command_timer=None,
                        )
                        state_events.append(active_evt)
                        if on_event:
                            on_event("active_detected", active_evt)

            # 진행률 콜백
            if on_event and sampled_count % 5 == 0:
                pct = min(100.0, (cur_sec / stop_sec) * 100.0) if stop_sec > 0 else 0.0
                on_event("progress", {
                    "current_sec": round(cur_sec, 1),
                    "total_sec": round(stop_sec, 1),
                    "percent": round(pct, 1),
                    "sampled_count": sampled_count,
                })

            frame_idx += 1

        cap.release()
        avg_ms = float(np.mean(frame_times_ms)) if frame_times_ms else 0.0

        return VideoAnalysisReport(
            video_path=vpath,
            duration_sec=round(duration_sec, 1),
            fps=round(fps, 2),
            sampled_frames=sampled_count,
            avg_frame_ms=round(avg_ms, 2),
            preview_timestamp_sec=self.locked_preview_timestamp,
            enemy_preview_team=list(self.locked_enemy_team),
            ally_preview_team=list(self.locked_ally_team),
            command_turns=command_turns,
            state_events=state_events,
        )
