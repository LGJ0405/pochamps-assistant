# -*- coding: utf-8 -*-
"""
test_step3_2_vision.py
Step 3-2(배틀 화면 ROI 확장) 비전 테스트 스크립트:
- 배틀 화면 ROI(상태창 HUD 아이콘, 체력 텍스트, 페이즈 지시자) 크롭 검증
- 배틀 HUD 미니 아이콘 매칭(일반 폼 및 메가진화 폼 식별) 범용 검증

실행:
    # 기본 배틀 스크린샷(battle_command.png, battle_mega.png) 전체 테스트
    $env:PYTHONIOENCODING="utf-8"
    python test_step3_2_vision.py

    # 특정 배틀 스크린샷 파일을 지정하여 테스트
    python test_step3_2_vision.py tests/screenshots/battle_mega.png
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.vision import IconMatcher, ROICropper, imread_safe

SCREENSHOTS_DIR = PROJECT_ROOT / "tests" / "screenshots"
DEFAULT_BATTLE_SCREENSHOTS = [
    SCREENSHOTS_DIR / "battle_command.png",
    SCREENSHOTS_DIR / "battle_mega.png",
]
DEBUG_CROPS_DIR = SCREENSHOTS_DIR / "debug_crops"
ICONS_DIR = PROJECT_ROOT / "data" / "icons"

# 최소 허용 일치율 임계값 (%)
MIN_SIMILARITY_THRESHOLD = 50.0

EXPECTED_BATTLE_ROI_KEYS = {
    "enemy_hud_icon",
    "enemy_hp_text",
    "ally_hud_icon",
    "ally_hp_text",
}

EXPECTED_PHASE_INDICATOR_KEYS = {
    "team_preview_banner",
    "command_banner",
    "move_button_1",
    "move_button_2",
    "move_button_3",
    "move_button_4",
}


def _resolve_battle_screenshots(custom_path: Optional[Path] = None) -> List[Path]:
    """테스트할 배틀 스크린샷 목록을 결정합니다."""
    if custom_path is not None:
        if not custom_path.exists():
            raise FileNotFoundError(f"지정한 스크린샷 파일이 없습니다: {custom_path}")
        return [custom_path]

    existing = [p for p in DEFAULT_BATTLE_SCREENSHOTS if p.exists()]
    if existing:
        return existing

    candidates = sorted(SCREENSHOTS_DIR.glob("battle*.*"))
    if candidates:
        return candidates

    raise FileNotFoundError(f"{SCREENSHOTS_DIR} 내에 테스트할 배틀 화면 스크린샷이 없습니다.")


def _run_battle_roi_crop_single(
    screenshot_path: Path,
    cropper: ROICropper,
):
    """단일 배틀 스크린샷에 대한 ROI 좌표 크롭 크기 및 디버그 이미지 저장 검증"""
    prefix = screenshot_path.stem
    print("\n============================================================")
    print(f" [검증 1] 배틀 화면 ROI 크롭 검증 ({screenshot_path.name})")
    print("============================================================")

    frame = imread_safe(screenshot_path)

    battle_crops = cropper.crop_battle_rois(frame)
    phase_crops = cropper.crop_phase_indicators(frame)
    saved_files = cropper.save_debug_crops(frame, DEBUG_CROPS_DIR, prefix=prefix, mode="battle")

    print(f"   - 대상 파일: {screenshot_path.name} (원본 해상도: {frame.shape[1]}x{frame.shape[0]})")
    print(f"   - 정규화 해상도: {cropper.target_width}x{cropper.target_height}")
    print(f"   - 저장 경로: {DEBUG_CROPS_DIR} (총 {len(saved_files)}개 파일 생성)")
    print(f"   - 전체 ROI 박스 확인용 파일: {DEBUG_CROPS_DIR / f'{prefix}_overlay.png'}")

    assert set(battle_crops.keys()) == EXPECTED_BATTLE_ROI_KEYS, (
        f"battle_rois 키 불일치: {set(battle_crops.keys())}"
    )
    assert set(phase_crops.keys()) == EXPECTED_PHASE_INDICATOR_KEYS, (
        f"phase_indicators 키 불일치: {set(phase_crops.keys())}"
    )

    for key, img in battle_crops.items():
        cfg_rect = cropper.battle_rois[key]
        h, w = img.shape[:2]
        print(f"   - [battle_rois] {key:16s}: {w}x{h} px")
        assert w == cfg_rect["w"] and h == cfg_rect["h"], (
            f"{key} 크롭 크기 불일치: 기대=({cfg_rect['w']}x{cfg_rect['h']}), 실제=({w}x{h})"
        )

    for key, img in phase_crops.items():
        cfg_rect = cropper.phase_indicators[key]
        h, w = img.shape[:2]
        assert w == cfg_rect["w"] and h == cfg_rect["h"], (
            f"{key} 크롭 크기 불일치: 기대=({cfg_rect['w']}x{cfg_rect['h']}), 실제=({w}x{h})"
        )

    # overlay(1) + battle_rois(4) + phase_indicators 중 team_preview_banner 제외(5) = 10개
    assert len(saved_files) == 10, f"저장된 배틀 디버그 파일 개수 오류: {len(saved_files)}"
    print(f"✅ [{screenshot_path.name}] 배틀 ROI 크롭 검증 통과!")


def test_battle_roi_crop(
    screenshot_path: Optional[Path] = None,
    cropper: Optional[ROICropper] = None,
):
    """[검증 1] 배틀 화면 ROI 좌표 크롭 크기 및 디버그 이미지 저장 검증"""
    cropper = cropper or ROICropper()
    targets = _resolve_battle_screenshots(screenshot_path)
    for sc_path in targets:
        _run_battle_roi_crop_single(sc_path, cropper)


def _run_battle_hud_icon_matching_single(
    screenshot_path: Path,
    cropper: ROICropper,
    matcher: IconMatcher,
):
    """단일 배틀 스크린샷에 대한 HUD 미니 아이콘(일반 폼 및 메가진화 폼 포함) 매칭 검증"""
    print("\n============================================================")
    print(f" [검증 2] 배틀 HUD 미니 아이콘 매칭 검증 ({screenshot_path.name})")
    print("============================================================")

    frame = imread_safe(screenshot_path)
    battle_crops = cropper.crop_battle_rois(frame)

    t0 = time.perf_counter()
    enemy_match = matcher.match_single(battle_crops["enemy_hud_icon"], slot_num=1)
    ally_match = matcher.match_single(battle_crops["ally_hud_icon"], slot_num=1)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\n🔍 [배틀 필드 포켓몬 HUD 아이콘 매칭 결과] (소요 시간: {elapsed_ms:.2f} ms)")
    print(
        f"   - 상대 필드 포켓몬: {enemy_match.species_ko:12s} ➔ {enemy_match.species_en:18s} "
        f"({enemy_match.slug}.png, 일치율={enemy_match.similarity:.1f}%)"
    )
    print(
        f"   - 아군 필드 포켓몬: {ally_match.species_ko:12s} ➔ {ally_match.species_en:18s} "
        f"({ally_match.slug}.png, 일치율={ally_match.similarity:.1f}%)"
    )

    for label, r in [("상대", enemy_match), ("아군", ally_match)]:
        assert (ICONS_DIR / f"{r.slug}.png").exists(), f"[{label}] 존재하지 않는 아이콘 에셋: {r.slug}.png"
        assert r.species_ko != r.slug, f"[{label}] 한글 종족명 역참조 실패: {r.slug}"
        assert r.similarity >= MIN_SIMILARITY_THRESHOLD, (
            f"[{label}] ({r.species_ko}) 일치율이 임계값({MIN_SIMILARITY_THRESHOLD}%) 미만입니다: {r.similarity:.1f}%"
        )

    print(f"\n✅ [{screenshot_path.name}] 배틀 HUD 아이콘 매칭 통과!")


def test_battle_hud_icon_matching(
    screenshot_path: Optional[Path] = None,
    cropper: Optional[ROICropper] = None,
    matcher: Optional[IconMatcher] = None,
):
    """[검증 2] 배틀 HUD 미니 아이콘(일반 폼 및 메가진화 폼 포함) 매칭 검증"""
    cropper = cropper or ROICropper()
    # 배틀 중에는 메가진화 폼(예: 메가갸라도스)이 HUD 아이콘에 표시되므로 include_mega_in_preview=True 사용
    matcher = matcher or IconMatcher(include_mega_in_preview=True)
    targets = _resolve_battle_screenshots(screenshot_path)
    for sc_path in targets:
        _run_battle_hud_icon_matching_single(sc_path, cropper, matcher)


if __name__ == "__main__":
    cli_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    targets = _resolve_battle_screenshots(cli_path)

    print("=" * 60)
    print("  포챔스 배틀 어시스턴트 - Step 3-2 배틀 화면 ROI & HUD 매칭 테스트")
    print("=" * 60)

    shared_cropper = ROICropper()
    shared_matcher = IconMatcher(include_mega_in_preview=True)

    for sc_path in targets:
        test_battle_roi_crop(sc_path, cropper=shared_cropper)
        test_battle_hud_icon_matching(sc_path, cropper=shared_cropper, matcher=shared_matcher)

    print("\n" + "=" * 60)
    print(f"  🎉 배틀 화면 비전 테스트 모두 통과! (총 {len(targets)}개 이미지 검증)")
    print("=" * 60)
