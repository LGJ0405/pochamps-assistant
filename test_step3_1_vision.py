# -*- coding: utf-8 -*-
"""
test_step3_1_vision.py
Step 3-1(선출 화면) 비전 테스트 스크립트: ROI 크롭 및 선출 6마리 아이콘 매칭 범용 검증

실행:
    # 기본 설정된 스크린샷(또는 tests/screenshots/team_preview*.png) 테스트
    $env:PYTHONIOENCODING="utf-8"
    python test_step3_1_vision.py

    # 특정 스크린샷 파일을 지정하여 테스트
    python test_step3_1_vision.py tests/screenshots/team_preview_v1.png
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.vision import IconMatcher, ROICropper, imread_safe

SCREENSHOTS_DIR = PROJECT_ROOT / "tests" / "screenshots"
DEFAULT_SCREENSHOT_PATH = SCREENSHOTS_DIR / "team_preview*.png"
DEBUG_CROPS_DIR = SCREENSHOTS_DIR / "debug_crops"
ICONS_DIR = PROJECT_ROOT / "data" / "icons"

# 최소 허용 일치율 임계값 (%)
MIN_SIMILARITY_THRESHOLD = 50.0


def _resolve_screenshot_path(custom_path: Optional[Path] = None) -> Path:
    """테스트할 대상 스크린샷 경로를 결정합니다."""
    if custom_path is not None:
        return custom_path
    if DEFAULT_SCREENSHOT_PATH.exists():
        return DEFAULT_SCREENSHOT_PATH
    fallback = SCREENSHOTS_DIR / "team_preview.png"
    if fallback.exists():
        return fallback
    candidates = sorted(SCREENSHOTS_DIR.glob("team_preview*.*"))
    if candidates:
        return candidates[0]
    raise FileNotFoundError(f"{SCREENSHOTS_DIR} 내에 테스트할 선출 화면 스크린샷이 없습니다.")


def test_step3_2_roi_crop(screenshot_path: Optional[Path] = None):
    """[Step 3-2] 선출 화면 ROI 좌표 크롭 및 디버그 이미지 저장 테스트"""
    target_path = _resolve_screenshot_path(screenshot_path)
    prefix = target_path.stem

    print("\n============================================================")
    print(f" [검증 1] Step 3-2: 선출 화면 ROI 크롭 검증 ({target_path.name})")
    print("============================================================")
    assert target_path.exists(), f"스크린샷 파일이 없습니다: {target_path}"

    cropper = ROICropper()
    frame = imread_safe(target_path)
    saved_files = cropper.save_debug_crops(frame, DEBUG_CROPS_DIR, prefix=prefix)

    print(f"   - 대상 파일: {target_path.name} (원본 해상도: {frame.shape[1]}x{frame.shape[0]})")
    print(f"   - 저장 경로: {DEBUG_CROPS_DIR} (총 {len(saved_files)}개 파일 생성)")
    print(f"   - 전체 ROI 박스 확인용 파일: {DEBUG_CROPS_DIR / f'{prefix}_overlay.png'}")
    assert len(saved_files) == 13, f"저장된 디버그 파일 개수 오류: {len(saved_files)}"
    print("✅ Step 3-2 ROI 크롭 테스트 통과!")


def test_step3_3_icon_matching(screenshot_path: Optional[Path] = None):
    """[Step 3-3] 임의의 선출 화면 상대 6마리 & 내 엔트리 6마리 아이콘 매칭 범용 검증"""
    target_path = _resolve_screenshot_path(screenshot_path)

    print("\n============================================================")
    print(f" [검증 2] Step 3-3: 선출 6마리 미니 아이콘 매칭 검증 ({target_path.name})")
    print("============================================================")

    cropper = ROICropper()
    matcher = IconMatcher()
    frame = imread_safe(target_path)

    # 1. 상대 선출 6마리 매칭
    enemy_crops = cropper.crop_enemy_slots(frame)
    t0 = time.perf_counter()
    enemy_results = matcher.match_team(enemy_crops)
    enemy_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\n🔍 [상대 엔트리 6마리 매칭 결과] (소요 시간: {enemy_ms:.2f} ms)")
    assert len(enemy_results) == 6, f"상대 슬롯 개수가 6개가 아닙니다: {len(enemy_results)}"
    for r in enemy_results:
        print(f"   - 슬롯 {r.slot}: {r.species_ko:12s} ➔ {r.species_en:18s} ({r.slug}.png, 일치율={r.similarity:.1f}%)")
        assert (ICONS_DIR / f"{r.slug}.png").exists(), f"존재하지 않는 아이콘 에셋: {r.slug}.png"
        assert r.species_ko != r.slug, f"한글 종족명 역참조 실패: {r.slug}"
        assert r.similarity >= MIN_SIMILARITY_THRESHOLD, (
            f"슬롯 {r.slot} ({r.species_ko}) 일치율이 임계값({MIN_SIMILARITY_THRESHOLD}%) 미만입니다: {r.similarity:.1f}%"
        )

    # 2. 내 엔트리 6마리 매칭
    ally_crops = cropper.crop_ally_slots(frame)
    t1 = time.perf_counter()
    ally_results = matcher.match_team(ally_crops)
    ally_ms = (time.perf_counter() - t1) * 1000.0

    print(f"\n🔍 [내 엔트리 6마리 매칭 결과] (소요 시간: {ally_ms:.2f} ms)")
    assert len(ally_results) == 6, f"내 엔트리 슬롯 개수가 6개가 아닙니다: {len(ally_results)}"
    for r in ally_results:
        print(f"   - 슬롯 {r.slot}: {r.species_ko:12s} ➔ {r.species_en:18s} ({r.slug}.png, 일치율={r.similarity:.1f}%)")
        assert (ICONS_DIR / f"{r.slug}.png").exists(), f"존재하지 않는 아이콘 에셋: {r.slug}.png"
        assert r.species_ko != r.slug, f"한글 종족명 역참조 실패: {r.slug}"
        assert r.similarity >= MIN_SIMILARITY_THRESHOLD, (
            f"슬롯 {r.slot} ({r.species_ko}) 일치율이 임계값({MIN_SIMILARITY_THRESHOLD}%) 미만입니다: {r.similarity:.1f}%"
        )

    print("\n✅ Step 3-3 선출 아이콘 매칭 통과!")


if __name__ == "__main__":
    cli_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    print("=" * 60)
    print("  포챔스 배틀 어시스턴트 - Step 3-1 선출 화면 비전 테스트")
    print("=" * 60)
    test_step3_2_roi_crop(cli_path)
    test_step3_3_icon_matching(cli_path)
    print("\n" + "=" * 60)
    print("  🎉 선출 화면 비전 테스트 모두 통과!")
    print("=" * 60)
