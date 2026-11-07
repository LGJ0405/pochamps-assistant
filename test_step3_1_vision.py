# -*- coding: utf-8 -*-
"""
test_step3_1_vision.py
Step 3-1(선출 화면) 비전 테스트 스크립트: ROI 크롭 및 선출 6마리 아이콘 매칭 검증

실행:
    $env:PYTHONIOENCODING="utf-8"
    python test_step3_1_vision.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.vision import IconMatcher, ROICropper, imread_safe

SCREENSHOT_PATH = PROJECT_ROOT / "tests" / "screenshots" / "team_preview.png"
DEBUG_CROPS_DIR = PROJECT_ROOT / "tests" / "screenshots" / "debug_crops"


def test_step3_2_roi_crop():
    """[Step 3-2] 선출 화면 ROI 좌표 크롭 및 디버그 이미지 저장 테스트"""
    print("\n============================================================")
    print(" [검증 1] Step 3-2: 선출 화면 ROI 크롭 검증 (cropper.py)")
    print("============================================================")
    assert SCREENSHOT_PATH.exists(), f"스크린샷 파일이 없습니다: {SCREENSHOT_PATH}"

    cropper = ROICropper()
    frame = imread_safe(SCREENSHOT_PATH)
    saved_files = cropper.save_debug_crops(frame, DEBUG_CROPS_DIR, prefix="team_preview")

    print(f"   - 원본 해상도: {frame.shape[1]}x{frame.shape[0]}")
    print(f"   - 저장 경로: {DEBUG_CROPS_DIR} (총 {len(saved_files)}개 파일 생성)")
    print(f"   - 전체 ROI 박스 확인용 파일: {DEBUG_CROPS_DIR / 'team_preview_overlay.png'}")
    assert len(saved_files) == 13
    print("✅ Step 3-2 ROI 크롭 테스트 통과!")


def test_step3_3_icon_matching():
    """[Step 3-3] 선출 화면 상대 6마리 & 내 엔트리 6마리 아이콘 dHash 매칭 테스트"""
    print("\n============================================================")
    print(" [검증 2] Step 3-3: 선출 6마리 미니 아이콘 매칭 검증 (icon_matcher.py)")
    print("============================================================")

    cropper = ROICropper()
    matcher = IconMatcher()
    frame = imread_safe(SCREENSHOT_PATH)

    # 1. 상대 선출 6마리 매칭
    enemy_crops = cropper.crop_enemy_slots(frame)
    t0 = time.perf_counter()
    enemy_results = matcher.match_team(enemy_crops)
    enemy_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\n🔍 [상대 엔트리 6마리 매칭 결과] (소요 시간: {enemy_ms:.2f} ms)")
    for r in enemy_results:
        print(f"   - 슬롯 {r.slot}: {r.species_ko:12s} ➔ {r.species_en:18s} ({r.slug}.png, 일치율={r.similarity:.1f}%)")

    expected_enemy = ["lucario", "glimmora", "rotom-wash", "salamence", "aegislash-shield", "cinderace"]
    assert [r.slug for r in enemy_results] == expected_enemy, f"상대 엔트리 매칭 불일치: {[r.slug for r in enemy_results]}"

    # 2. 내 엔트리 6마리 매칭
    ally_crops = cropper.crop_ally_slots(frame)
    t1 = time.perf_counter()
    ally_results = matcher.match_team(ally_crops)
    ally_ms = (time.perf_counter() - t1) * 1000.0

    print(f"\n🔍 [내 엔트리 6마리 매칭 결과] (소요 시간: {ally_ms:.2f} ms)")
    for r in ally_results:
        print(f"   - 슬롯 {r.slot}: {r.species_ko:12s} ➔ {r.species_en:18s} ({r.slug}.png, 일치율={r.similarity:.1f}%)")

    expected_ally = ["hydreigon", "gholdengo", "kingambit", "glimmora", "garchomp", "salamence"]
    assert [r.slug for r in ally_results] == expected_ally, f"내 엔트리 매칭 불일치: {[r.slug for r in ally_results]}"

    print("\n✅ Step 3-3 선출 아이콘 매칭 100% 통과!")


if __name__ == "__main__":
    print("=" * 60)
    print("  포챔스 배틀 어시스턴트 - Step 3 비전 테스트 (1번 스크린샷)")
    print("=" * 60)
    test_step3_2_roi_crop()
    test_step3_3_icon_matching()
    print("\n" + "=" * 60)
    print("  🎉 1번 스크린샷(선출 화면) 비전 테스트 모두 통과!")
    print("=" * 60)
