# -*- coding: utf-8 -*-
"""
download_sprites.py
[선택 사항 / 향후 GUI 확장용]
data/ko_to_en.json에 등록된 포챔스 347종(고유 영문 슬러그 344종, 일반/리전폼/메가진화 포함)의
인게임 정면 3D 렌더링 스프라이트(data/sprites/, 512x512 RGBA)를
영문 소문자 슬러그 파일명(예: salamence.png, gyarados-mega.png)으로 일괄 다운로드합니다.

※ 비전 인식 파이프라인(선출 화면 & 배틀 HUD 매칭)은 data/icons/ 미니 아이콘만 사용하므로,
   본 스크립트는 향후 GUI 대시보드에서 포켓몬 3D 일러스트를 표시할 때만 실행하면 됩니다.

실행:
    python scripts/download_sprites.py
"""

from __future__ import annotations

import io
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Tuple

import requests
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.download_icons import (
    DATA_DIR,
    _download_image_bytes,
    build_download_tasks,
)

SPRITES_DIR = DATA_DIR / "sprites"


def download_single_sprite(
    slug: str,
    poke_id: int,
    base_poke_id: Optional[int] = None,
    force: bool = False,
) -> Tuple[str, bool, str]:
    """단일 포켓몬의 포챔스 정면 3D 스프라이트(data/sprites/{slug}.png, 512x512)를 다운로드합니다."""
    sprite_path = SPRITES_DIR / f"{slug}.png"
    if not force and sprite_path.exists():
        return (slug, True, "cached")

    candidate_ids = [poke_id]
    if base_poke_id and base_poke_id != poke_id:
        candidate_ids.append(base_poke_id)

    sprite_urls: List[str] = []
    for pid in candidate_ids:
        sprite_urls.extend([
            f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-ix/champions/{pid}.webp",
            f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/home/{pid}.png",
        ])

    with requests.Session() as session:
        raw_sprite_bytes = _download_image_bytes(session, sprite_urls)
        if not raw_sprite_bytes:
            return (slug, False, f"3D 스프라이트 다운로드 실패 (id={poke_id})")

        try:
            with Image.open(io.BytesIO(raw_sprite_bytes)) as sp_img:
                sp_rgba = sp_img.convert("RGBA")
                sp_rgba.save(sprite_path, format="PNG")
            return (slug, True, "downloaded")
        except Exception as exc:
            return (slug, False, f"스프라이트 이미지 처리 오류: {exc}")


def main(force: bool = False) -> None:
    SPRITES_DIR.mkdir(parents=True, exist_ok=True)
    tasks = build_download_tasks()

    print(f"🚀 포챔스 3D 정면 스프라이트 다운로드 시작 (대상: {len(tasks)}종, 병렬 스레드: 16)...")
    success_count = 0
    cached_count = 0
    failures = []

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {
            executor.submit(download_single_sprite, slug, pid, base_id, force): slug
            for slug, pid, base_id in tasks
        }
        for idx, future in enumerate(as_completed(futures), 1):
            slug, ok, msg = future.result()
            if ok:
                success_count += 1
                if msg == "cached":
                    cached_count += 1
                if idx % 50 == 0 or idx == len(tasks):
                    print(f"   [{idx:3d}/{len(tasks)}] 완료 (최근: {slug}.png - {msg})")
            else:
                failures.append((slug, msg))
                print(f"   [{idx:3d}/{len(tasks)}] ❌ {slug}: {msg}")

    print("\n============================================================")
    print(f"✅ 3D 스프라이트 다운로드 요약: 성공 {success_count}/{len(tasks)} (캐시: {cached_count}, 신규: {success_count - cached_count})")
    print(f"   - 저장 경로: {SPRITES_DIR} ({len(list(SPRITES_DIR.glob('*.png')))}개 파일)")
    print("============================================================")

    if failures:
        raise RuntimeError(f"일부 3D 스프라이트 다운로드 실패: {failures}")


if __name__ == "__main__":
    main()
