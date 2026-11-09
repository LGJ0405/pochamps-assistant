# -*- coding: utf-8 -*-
"""
download_icons.py
data/ko_to_en.json에 등록된 포챔스 347종(고유 영문 슬러그 344종, 일반/리전폼/메가진화 포함)의
공식 2D 미니 아이콘(data/icons/, 128x128 RGBA)을
영문 소문자 슬러그 파일명(예: salamence.png, gyarados-mega.png)으로 일괄 다운로드합니다.

실행:
    python scripts/download_icons.py
"""

from __future__ import annotations

import io
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
KO_TO_EN_PATH = DATA_DIR / "ko_to_en.json"
ICONS_DIR = DATA_DIR / "icons"

# ko_to_en.json 영문명(소문자) -> PokeAPI pokemon 엔드포인트 슬러그 매핑
POKEAPI_SLUG_ALIASES: Dict[str, str] = {
    "basculegion": "basculegion-male",
    "basculegion-f": "basculegion-female",
    "gourgeist": "gourgeist-average",
    "indeedee": "indeedee-male",
    "indeedee-f": "indeedee-female",
    "lycanroc": "lycanroc-midday",
    "maushold": "maushold-family-of-four",
    "meowstic": "meowstic-male",
    "meowstic-f": "meowstic-female",
    "meowstic-m-mega": "meowstic-male-mega",
    "meowstic-f-mega": "meowstic-female-mega",
    "mimikyu": "mimikyu-disguised",
    "morpeko": "morpeko-full-belly",
    "mrmime": "mr-mime",
    "mrrime": "mr-rime",
    "palafin": "palafin-zero",
    "pyroar": "pyroar-male",
    "squawkabilly": "squawkabilly-green-plumage",
    "tauros-paldea-aqua": "tauros-paldea-aqua-breed",
    "tauros-paldea-blaze": "tauros-paldea-blaze-breed",
    "tauros-paldea-combat": "tauros-paldea-combat-breed",
    "toxtricity": "toxtricity-amped",
}


def to_asset_slug(en_name: str) -> str:
    """
    계산기 영문 종족명(예: 'Charizard-Mega-X', 'Salamence')을
    파일명용 ASCII 영문 소문자 슬러그('charizard-mega-x', 'salamence')로 변환합니다.
    """
    return en_name.strip().lower()


def fetch_pokeapi_id_map() -> Dict[str, int]:
    """PokeAPI 전체 포켓몬 목록을 조회하여 {api_slug: pokemon_id} 사전을 반환합니다."""
    url = "https://pokeapi.co/api/v2/pokemon?limit=2000"
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    id_map: Dict[str, int] = {}
    for item in results:
        name = item["name"]
        poke_id = int(item["url"].rstrip("/").split("/")[-1])
        id_map[name] = poke_id
    return id_map


def build_download_tasks() -> List[Tuple[str, int, Optional[int]]]:
    """ko_to_en.json의 종족 목록과 PokeAPI ID를 매핑하여 다운로드 작업 리스트를 생성합니다."""
    with open(KO_TO_EN_PATH, "r", encoding="utf-8") as f:
        ko_to_en = json.load(f)

    species_dict: Dict[str, str] = ko_to_en.get("species", {})
    unique_en_names = sorted(set(species_dict.values()))
    print(f"📦 ko_to_en.json 등록 종족: {len(species_dict)}개 (고유 영문 슬러그: {len(unique_en_names)}개)")

    print("🌐 PokeAPI 포켓몬 ID 인덱스 조회 중...")
    api_id_map = fetch_pokeapi_id_map()

    tasks: List[Tuple[str, int, Optional[int]]] = []
    for en_name in unique_en_names:
        slug = to_asset_slug(en_name)
        api_slug = POKEAPI_SLUG_ALIASES.get(slug, slug)
        poke_id = api_id_map.get(api_slug)

        base_slug = slug.split("-")[0]
        base_api_slug = POKEAPI_SLUG_ALIASES.get(base_slug, base_slug)
        base_id = api_id_map.get(base_api_slug)

        if poke_id is None:
            if base_id is not None:
                poke_id = base_id
            else:
                raise KeyError(f"PokeAPI에서 '{en_name}' (slug='{api_slug}') ID를 찾을 수 없습니다.")

        tasks.append((slug, poke_id, base_id))
    return tasks


def _download_image_bytes(session: requests.Session, urls: List[str]) -> Optional[bytes]:
    """후보 URL 리스트를 순회하며 가장 먼저 성공하는 이미지 바이트를 반환합니다."""
    for url in urls:
        try:
            r = session.get(url, timeout=15)
            if r.status_code == 200 and r.content:
                return r.content
        except requests.RequestException:
            continue
    return None


def download_single_icon(
    slug: str,
    poke_id: int,
    base_poke_id: Optional[int] = None,
    force: bool = False,
) -> Tuple[str, bool, str]:
    """단일 포켓몬의 포챔스 공식 128x128 미니 아이콘(data/icons/{slug}.png)을 다운로드합니다."""
    icon_path = ICONS_DIR / f"{slug}.png"
    if not force and icon_path.exists():
        return (slug, True, "cached")

    candidate_ids = [poke_id]
    if base_poke_id and base_poke_id != poke_id:
        candidate_ids.append(base_poke_id)

    icon_urls: List[str] = []
    for pid in candidate_ids:
        icon_urls.extend([
            f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-ix/champions/icons/{pid}.png",
            f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-viii/sword-shield/icons/{pid}.png",
        ])

    with requests.Session() as session:
        raw_icon_bytes = _download_image_bytes(session, icon_urls)
        if not raw_icon_bytes:
            return (slug, False, f"미니 아이콘 다운로드 실패 (id={poke_id})")

        try:
            with Image.open(io.BytesIO(raw_icon_bytes)) as ic_img:
                ic_rgba = ic_img.convert("RGBA")
                ic_rgba.save(icon_path, format="PNG")
            return (slug, True, "downloaded")
        except Exception as exc:
            return (slug, False, f"아이콘 이미지 처리 오류: {exc}")


def main(force: bool = False) -> None:
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    tasks = build_download_tasks()

    print(f"🚀 포챔스 미니 아이콘 다운로드 시작 (대상: {len(tasks)}종, 병렬 스레드: 16)...")
    success_count = 0
    cached_count = 0
    failures = []

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {
            executor.submit(download_single_icon, slug, pid, base_id, force): slug
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
    print(f"✅ 미니 아이콘 다운로드 요약: 성공 {success_count}/{len(tasks)} (캐시: {cached_count}, 신규: {success_count - cached_count})")
    print(f"   - 저장 경로: {ICONS_DIR} ({len(list(ICONS_DIR.glob('*.png')))}개 파일)")
    print("============================================================")

    if failures:
        raise RuntimeError(f"일부 미니 아이콘 다운로드 실패: {failures}")


if __name__ == "__main__":
    main()
