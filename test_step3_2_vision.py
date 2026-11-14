# -*- coding: utf-8 -*-
"""
test_step3_2_vision.py
Step 3-2(배틀 정지 화면 비전 통합) 테스트 스크립트:
- 단일 배틀 스크린샷에서 [ROI 크롭 + HUD 아이콘 매칭 + 체력/COMMAND OCR]을 일괄 검증합니다.

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

from src.vision import BattleOCR, IconMatcher, ROICropper, imread_safe

SCREENSHOTS_DIR = PROJECT_ROOT / "tests" / "screenshots"
DEFAULT_BATTLE_SCREENSHOTS = [
    SCREENSHOTS_DIR / "battle_command.png",
    SCREENSHOTS_DIR / "battle_mega.png",
]
DEBUG_CROPS_DIR = SCREENSHOTS_DIR / "debug_crops"
ICONS_DIR = PROJECT_ROOT / "data" / "icons"

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


def test_battle_frame(
    screenshot_path: Path,
    cropper: Optional[ROICropper] = None,
    matcher: Optional[IconMatcher] = None,
    ocr: Optional[BattleOCR] = None,
):
    """
    단일 배틀 스크린샷에 대해 [ROI 크롭 -> HUD 아이콘 매칭 -> HP/COMMAND OCR]을
    한 번에 검증하고 간결한 요약 결과를 출력합니다.
    """
    cropper = cropper or ROICropper()
    matcher = matcher or IconMatcher(include_mega_in_preview=True)
    ocr = ocr or BattleOCR()

    t0 = time.perf_counter()
    frame = imread_safe(screenshot_path)
    prefix = screenshot_path.stem

    # 1. ROI 크롭 검증
    battle_crops = cropper.crop_battle_rois(frame)
    phase_crops = cropper.crop_phase_indicators(frame)
    saved_files = cropper.save_debug_crops(frame, DEBUG_CROPS_DIR, prefix=prefix, mode="battle")

    assert set(battle_crops.keys()) == EXPECTED_BATTLE_ROI_KEYS
    assert set(phase_crops.keys()) == EXPECTED_PHASE_INDICATOR_KEYS
    assert len(saved_files) == 10, f"저장된 배틀 디버그 파일 개수 오류: {len(saved_files)}"

    for key, img in battle_crops.items():
        cfg = cropper.battle_rois[key]
        assert img.shape[1] == cfg["w"] and img.shape[0] == cfg["h"]

    for key, img in phase_crops.items():
        cfg = cropper.phase_indicators[key]
        assert img.shape[1] == cfg["w"] and img.shape[0] == cfg["h"]

    # 2. 배틀 HUD 미니 아이콘 매칭 검증
    enemy_match = matcher.match_single(battle_crops["enemy_hud_icon"], slot_num=1)
    ally_match = matcher.match_single(battle_crops["ally_hud_icon"], slot_num=1)

    for label, r in [("상대", enemy_match), ("아군", ally_match)]:
        assert (ICONS_DIR / f"{r.slug}.png").exists(), f"[{label}] 아이콘 부재: {r.slug}"
        assert r.species_ko != r.slug, f"[{label}] 한글 역참조 실패: {r.slug}"
        assert r.similarity >= MIN_SIMILARITY_THRESHOLD, f"[{label}] 낮은 일치율: {r.similarity}%"

    # 3. 체력(HP) 및 COMMAND 배너 OCR 검증
    enemy_hp, ally_hp, cmd_banner = ocr.recognize_battle_hud_texts(
        battle_crops["enemy_hp_text"],
        battle_crops["ally_hp_text"],
        phase_crops["command_banner"],
    )

    assert enemy_hp.is_valid, f"상대 체력 OCR 실패: {enemy_hp}"
    assert ally_hp.is_valid, f"아군 체력 OCR 실패: {ally_hp}"
    assert 0 <= enemy_hp.hp_percent <= 100
    assert 0 <= ally_hp.cur_hp <= ally_hp.max_hp

    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    # 출력 요약
    e_mega_tag = " [🔥메가]" if "-mega" in enemy_match.slug else ""
    a_mega_tag = " [🔥메가]" if "-mega" in ally_match.slug else ""
    cmd_str = f"COMMAND {cmd_banner.timer_sec}s" if cmd_banner.timer_sec is not None else "COMMAND"
    status_str = f"✅ {cmd_str}" if cmd_banner.is_command else "대기/진행"

    print(f"\n📌 {screenshot_path.name} (원본: {frame.shape[1]}x{frame.shape[0]}, 소요: {elapsed_ms:.1f}ms)")
    print(f"   - ROI 크롭  : 배틀 4개 + 지시자 6개 영역 검증 완료 (디버그 10개 파일 저장)")
    print(
        f"   - 상대 필드 : {enemy_match.species_ko}{e_mega_tag} ({enemy_match.species_en}, {enemy_match.similarity:.1f}%) "
        f"| HP {enemy_hp.hp_percent:3d}% (OCR={enemy_hp.raw_text!r})"
    )
    print(
        f"   - 아군 필드 : {ally_match.species_ko}{a_mega_tag} ({ally_match.species_en}, {ally_match.similarity:.1f}%) "
        f"| HP {ally_hp.cur_hp}/{ally_hp.max_hp} ({ally_hp.hp_percent:.1f}%, OCR={ally_hp.raw_text!r})"
    )
    print(f"   - 커맨드배너 : {status_str} (신뢰도={cmd_banner.confidence:.3f}, 원본={cmd_banner.raw_text!r})")


def test_step3_2_battle_vision(custom_path: Optional[Path] = None):
    """Step 3-2 배틀 정지 화면 통합 테스트 진입점"""
    targets = _resolve_battle_screenshots(custom_path)
    shared_cropper = ROICropper()
    shared_matcher = IconMatcher(include_mega_in_preview=True)
    shared_ocr = BattleOCR()

    for sc_path in targets:
        test_battle_frame(
            sc_path,
            cropper=shared_cropper,
            matcher=shared_matcher,
            ocr=shared_ocr,
        )


if __name__ == "__main__":
    cli_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    targets = _resolve_battle_screenshots(cli_path)

    print("=" * 60)
    print("  포챔스 배틀 어시스턴트 - Step 3-2 배틀 정지 화면 비전 통합 테스트")
    print("=" * 60)

    test_step3_2_battle_vision(cli_path)

    print("\n" + "=" * 60)
    print(f"  🎉 배틀 화면 비전 테스트 모두 통과! (총 {len(targets)}개 이미지 검증)")
    print("=" * 60)
