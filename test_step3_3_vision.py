# -*- coding: utf-8 -*-
"""
test_step3_3_vision.py
Step 3-3(배틀 녹화 영상 실시간 비전 추적) 테스트 스크립트:
- 배틀 녹화 영상(tests/battle_play.mp4 또는 CLI 인자 영상)을 실시간으로 스캔하며 이벤트를 즉시 출력합니다:
  1) 선출 화면(TEAM_PREVIEW) 감지 즉시 6v6 엔트리 자동 잠금 및 출력
  2) 턴별 커맨드 페이즈(BATTLE_COMMAND) 감지 즉시 대진 및 체력 실시간 스트리밍
  3) 턴 도중 교전/교체/기절(BATTLE_ACTIVE) 발생 즉시 실시간 알림

실행:
    # 기본 녹화 영상(tests/battle_play.mp4) 테스트
    $env:PYTHONIOENCODING="utf-8"
    python test_step3_3_vision.py

    # 특정 배틀 녹화 영상(.mp4) 파일을 지정하여 테스트
    python test_step3_3_vision.py tests/battle_play.mp4
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.vision import BattleTurnEvent, BattleVideoTracker
from src.battle_advisor import BattleAdvisor

SCREENSHOTS_DIR = PROJECT_ROOT / "tests" / "screenshots"
DEFAULT_VIDEO_PATH = PROJECT_ROOT / "tests" / "battle_play_v4.mp4"
ICONS_DIR = PROJECT_ROOT / "data" / "icons"
MIN_SIMILARITY_THRESHOLD = 50.0


def test_video_battle_tracking(
    video_path: Optional[Path] = None,
    tracker: Optional[BattleVideoTracker] = None,
    sample_interval_sec: float = 1.0,
):
    """배틀 녹화 영상(.mp4) 기반 실시간 이벤트 스트리밍 비전 상태 추적 테스트"""
    target_video = video_path or DEFAULT_VIDEO_PATH
    print("\n============================================================")
    print(f" [검증] 배틀 녹화 영상 시계열 비전 추적 ({target_video.name})")
    print("============================================================")

    if not target_video.exists():
        print(f"⚠️ 녹화 영상 파일({target_video})이 존재하지 않아 영상 테스트를 건너뜁니다.")
        return

    tracker = tracker or BattleVideoTracker()
    advisor = BattleAdvisor()
    tracker.advisor = advisor

    def _on_event(event_type: str, data: Any):
        if event_type == "progress":
            cur_s = data["current_sec"]
            tot_s = data["total_sec"]
            pct = data["percent"]
            sys.stdout.write(f"\r⏳ [영상 스캔 진행 중] {cur_s:5.1f}s / {tot_s:.1f}s ({pct:4.1f}%) ...")
            sys.stdout.flush()

        elif event_type == "preview_locked":
            sys.stdout.write("\r" + " " * 60 + "\r")  # 진행률 한 줄 지우기
            e_team = data["enemy"]
            a_team = data["ally"]
            t_sec = data["timestamp_sec"]
            e_str = ", ".join(f"{r.species_ko}({r.similarity:.0f}%)" for r in e_team)
            a_str = ", ".join(f"{r.species_ko}({r.similarity:.0f}%)" for r in a_team)
            print(f"\n🔍 [선출 6v6 자동 잠금 | {t_sec:4.1f}s 감지]")
            print(f"   - 상대 엔트리: {e_str}")
            print(f"   - 아군 엔트리: {a_str}\n")
            sys.stdout.flush()

        elif event_type == "turn_detected":
            sys.stdout.write("\r" + " " * 60 + "\r")
            turn: BattleTurnEvent = data
            e_mega = " [🔥메가]" if turn.is_enemy_mega else ""
            a_mega = " [🔥메가]" if turn.is_ally_mega else ""
            cmd_str = f"COMMAND {turn.command_timer:2d}s" if turn.command_timer is not None else "COMMAND"
            print(
                f"⚔️ [Turn {turn.turn_index:2d} | {turn.timestamp_sec:5.1f}s | {cmd_str}] "
                f"아군: {turn.ally_species_ko}{a_mega} ({turn.ally_cur_hp:3d}/{turn.ally_max_hp:3d}, {turn.ally_hp_percent:5.1f}%) "
                f"vs 상대: {turn.enemy_species_ko}{e_mega} (HP {turn.enemy_hp_percent:3d}%)"
            )
            # 실시간 의사결정 / 데미지 브리핑 출력
            if turn.decision_brief:
                brief_text = turn.decision_brief.format_console_text()
                # 첫 줄(헤더)을 제외한 공격/피격 상세 출력
                detail_lines = brief_text.splitlines()[1:]
                if detail_lines:
                    print(f"   📊 [실시간 의사결정 브리핑 | {turn.decision_brief.speed_desc}]")
                    for d_line in detail_lines:
                        print(f"   {d_line}")
            sys.stdout.flush()

        elif event_type == "active_detected":
            sys.stdout.write("\r" + " " * 60 + "\r")
            evt: BattleTurnEvent = data
            e_mega = " [🔥메가]" if evt.is_enemy_mega else ""
            a_mega = " [🔥메가]" if evt.is_ally_mega else ""
            print(
                f"   ⚡ [{evt.timestamp_sec:5.1f}s | 교전·기절] "
                f"아군: {evt.ally_species_ko}{a_mega} ({evt.ally_cur_hp:3d}/{evt.ally_max_hp:3d}, {evt.ally_hp_percent:5.1f}%) "
                f"vs 상대: {evt.enemy_species_ko}{e_mega} (HP {evt.enemy_hp_percent:3d}%)"
            )
            sys.stdout.flush()

    t0 = time.perf_counter()
    try:
        report = tracker.analyze_video(
            target_video,
            sample_interval_sec=sample_interval_sec,
            on_event=_on_event,
        )
    finally:
        advisor.close()
    total_sec = time.perf_counter() - t0

    # 마지막 줄 바꿈 및 정리
    sys.stdout.write("\r" + " " * 60 + "\r")
    sys.stdout.flush()

    print(f"\n🎬 [분석 완료 요약]")
    print(f"   - 영상 길이: {report.duration_sec:.1f}초 ({report.fps:.2f} FPS) | 분석 프레임: {report.sampled_frames}개")
    print(f"   - 총 소요 시간: {total_sec:.2f}초 (프레임당 평균 {report.avg_frame_ms:.2f} ms)")
    print(f"   - 감지 결과: 선출 6v6 확정, 총 {len(report.command_turns)}개 커맨드 턴, {len(report.state_events)}건 상태 이벤트")

    # 사후 무결성 검증
    assert len(report.enemy_preview_team) == 6
    assert len(report.ally_preview_team) == 6
    assert len(report.command_turns) >= 1

    enemy_allowed = tracker.battle_matcher.expand_candidate_slugs(
        [r.slug for r in report.enemy_preview_team]
    )
    ally_allowed = tracker.battle_matcher.expand_candidate_slugs(
        [r.slug for r in report.ally_preview_team]
    )

    for turn in report.command_turns:
        assert (ICONS_DIR / f"{turn.enemy_slug}.png").exists()
        assert (ICONS_DIR / f"{turn.ally_slug}.png").exists()
        assert turn.enemy_slug in enemy_allowed, f"미등록 상대 포켓몬: {turn.enemy_slug}"
        assert turn.ally_slug in ally_allowed, f"미등록 아군 포켓몬: {turn.ally_slug}"
        assert 0 <= turn.enemy_hp_percent <= 100
        assert 0 <= turn.ally_cur_hp <= turn.ally_max_hp

    print("\n✅ 배틀 녹화 영상 시계열 비전 상태 추적 검증 통과!")


if __name__ == "__main__":
    cli_video = Path(sys.argv[1]) if len(sys.argv) > 1 else None

    print("=" * 60)
    print("  포챔스 배틀 어시스턴트 - Step 3-3 배틀 녹화 영상 비전 추적 테스트")
    print("=" * 60)

    shared_tracker = BattleVideoTracker()
    test_video_battle_tracking(video_path=cli_video, tracker=shared_tracker, sample_interval_sec=1.0)

    print("\n" + "=" * 60)
    print("  🎉 Step 3-3 배틀 녹화 영상 비전 추적 테스트 통과!")
    print("=" * 60)
