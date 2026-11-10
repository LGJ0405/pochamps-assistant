# -*- coding: utf-8 -*-
"""
icon_matcher.py
ImageHash(dHash) 기반 선출 화면 및 배틀 HUD 미니 아이콘 고속 종족 확정 모듈
- 부팅 시 data/icons/*.png의 흑백 윤곽선 해시(dHash)를 메모리에 인덱싱합니다.
- 흑백 그레이스케일 및 외곽선 변화량을 비교하므로 이로치 여부에 영향받지 않습니다.
- 별도의 ID 매핑 파일 없이 data/ko_to_en.json 사전을 참조하여 영문 종족명 및 한글명을 반환합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import cv2
import imagehash
import numpy as np
from PIL import Image

from ..adapter import DataAdapter
from .cropper import imread_safe

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_ICONS_DIR = PROJECT_ROOT / "data" / "icons"

# 인게임 선출 슬롯의 평균 배경 밝기(중간 톤 회색=105)로 알파 채널을 합성하여
# 반투명 배경(분홍/파랑) 위에서도 포켓몬의 검은색 외곽선과 내부 명암이 일관되게 유지되도록 설정
NEUTRAL_BG_GRAY = 105


@dataclass
class IconMatchResult:
    """단일 슬롯 미니 아이콘 매칭 결과"""
    slot: int
    slug: str
    species_en: str
    species_ko: str
    similarity: float  # 일치율 (0.0 ~ 100.0%)
    distance: int


def _extract_edge_and_gray_pil(gray_64: np.ndarray) -> Tuple[Image.Image, Image.Image]:
    """
    64x64 그레이스케일 이미지에서:
    1) 가우시안 블러 후 그레이스케일 PIL 이미지 (내부 명암 구조 dHash용)
    2) Sobel 그래디언트 크기 이미지 (배경색과 무관한 순수 윤곽선 dHash용)
    두 가지를 생성합니다.
    """
    blurred = cv2.GaussianBlur(gray_64, (3, 3), 0)
    gx = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    mag_u8 = np.clip(mag, 0, 255).astype(np.uint8)
    return Image.fromarray(blurred), Image.fromarray(mag_u8)


class IconMatcher:
    """ImageHash(dHash) 기반 선출 화면 미니 아이콘 고속 매칭기"""

    def __init__(
        self,
        icons_dir: Optional[Union[str, Path]] = None,
        adapter: Optional[DataAdapter] = None,
        hash_size: int = 12,
        include_mega_in_preview: bool = False,
    ):
        self.icons_dir = Path(icons_dir) if icons_dir else DEFAULT_ICONS_DIR
        self.adapter = adapter or DataAdapter()
        self.hash_size = hash_size
        self.include_mega_in_preview = include_mega_in_preview

        self._slugs: List[str] = []
        self._gray_bits: Optional[np.ndarray] = None  # shape: (N, hash_bits)
        self._edge_bits: Optional[np.ndarray] = None  # shape: (N, hash_bits)
        # {slug: (dilated_mask_bool, normalized_ref_edge_vector)}
        self._edge_vectors: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
        self._build_index()

    @staticmethod
    def _is_mega_slug(slug: str) -> bool:
        """메가진화 폼 슬러그 여부 판별 (선출 화면에서는 메가진화 전 기본 폼으로 표시됨)"""
        return "-mega" in slug

    def _build_index(self) -> None:
        """부팅 시 data/icons/*.png의 dHash 비트 행렬 및 윤곽선 벡터를 메모리에 인덱싱합니다."""
        if not self.icons_dir.exists():
            raise FileNotFoundError(f"아이콘 디렉토리가 존재하지 않습니다: {self.icons_dir}")

        self._slugs.clear()
        self._edge_vectors.clear()
        gray_list: List[np.ndarray] = []
        edge_list: List[np.ndarray] = []
        kernel = np.ones((3, 3), np.uint8)

        for icon_path in sorted(self.icons_dir.glob("*.png")):
            slug = icon_path.stem.lower()
            if not self.include_mega_in_preview and self._is_mega_slug(slug):
                continue

            bgra = imread_safe(icon_path, cv2.IMREAD_UNCHANGED)
            if bgra is None or bgra.ndim != 3 or bgra.shape[2] != 4:
                continue

            bgra_64 = cv2.resize(bgra, (64, 64), interpolation=cv2.INTER_AREA)
            bgr_64 = bgra_64[:, :, :3]
            alpha = bgra_64[:, :, 3].astype(np.float32) / 255.0
            gray_fg = cv2.cvtColor(bgr_64, cv2.COLOR_BGR2GRAY).astype(np.float32)

            # 중립 배경(NEUTRAL_BG_GRAY) 위에 알파 블렌딩
            composited = (gray_fg * alpha + NEUTRAL_BG_GRAY * (1.0 - alpha)).astype(np.uint8)
            pil_gray, pil_edge = _extract_edge_and_gray_pil(composited)

            h_gray = imagehash.dhash(pil_gray, hash_size=self.hash_size).hash.flatten().astype(np.uint8)
            h_edge = imagehash.dhash(pil_edge, hash_size=self.hash_size).hash.flatten().astype(np.uint8)

            mask_64 = (bgra_64[:, :, 3] > 25).astype(np.uint8)
            dilated_mask = cv2.dilate(mask_64, kernel, iterations=1) > 0
            edge_64 = np.array(pil_edge, dtype=np.float32)

            v1 = edge_64[dilated_mask]
            v1_norm = v1 - np.mean(v1)
            norm_len = float(np.linalg.norm(v1_norm))
            v1_unit = (v1_norm / norm_len) if norm_len > 1e-6 else v1_norm

            self._slugs.append(slug)
            gray_list.append(h_gray)
            edge_list.append(h_edge)
            self._edge_vectors[slug] = (dilated_mask, v1_unit)

        if gray_list:
            self._gray_bits = np.vstack(gray_list)
            self._edge_bits = np.vstack(edge_list)

    @property
    def indexed_count(self) -> int:
        return len(self._slugs)

    def match_single(
        self,
        slot_img: Union[np.ndarray, Image.Image],
        slot_num: int = 1,
        top_k: int = 8,
    ) -> IconMatchResult:
        """
        단일 슬롯 크롭 이미지에서:
        1차: NumPy 벡터화 XOR 연산으로 전체 도감 대상 초고속 dHash 해밍 거리 산출 및 상위 top_k 압축
        2차: 알파 마스크 내부 윤곽선 정규화 내적(Cosine Similarity)으로 최종 종족 확정
        """
        if self._gray_bits is None or self._edge_bits is None or not self._slugs:
            raise RuntimeError("아이콘 해시 인덱스가 비어 있습니다.")

        if isinstance(slot_img, Image.Image):
            rgb = np.array(slot_img.convert("RGB"))
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        else:
            gray = (
                cv2.cvtColor(slot_img, cv2.COLOR_BGR2GRAY)
                if slot_img.ndim == 3
                else slot_img
            )

        gray_64 = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
        pil_gray, pil_edge = _extract_edge_and_gray_pil(gray_64)

        t_gray = imagehash.dhash(pil_gray, hash_size=self.hash_size).hash.flatten().astype(np.uint8)
        t_edge = imagehash.dhash(pil_edge, hash_size=self.hash_size).hash.flatten().astype(np.uint8)
        target_edge_64 = np.array(pil_edge, dtype=np.float32)

        # 1차: 벡터화 해밍 거리 산출
        dist_edge = np.count_nonzero(self._edge_bits != t_edge, axis=1)
        dist_gray = np.count_nonzero(self._gray_bits != t_gray, axis=1)
        total_dist = dist_edge * 2 + dist_gray

        top_indices = np.argpartition(total_dist, min(top_k, len(self._slugs) - 1))[:top_k]

        # 2차: 상위 후보들에 대해 전경 윤곽선 상관계수 정밀 대조
        best_slug = self._slugs[int(top_indices[0])]
        best_dist = int(dist_edge[int(top_indices[0])])
        best_combined = -999.0
        max_hash_bits = self.hash_size * self.hash_size * 3

        for idx in top_indices:
            slug = self._slugs[int(idx)]
            dilated_mask, v1_unit = self._edge_vectors[slug]
            v2 = target_edge_64[dilated_mask]
            v2_norm = v2 - np.mean(v2)
            v2_len = float(np.linalg.norm(v2_norm))
            edge_corr = float(np.dot(v1_unit, v2_norm) / v2_len) if v2_len > 1e-6 else 0.0

            hash_sim = 1.0 - (float(total_dist[int(idx)]) / max_hash_bits)
            combined = 0.45 * hash_sim + 0.55 * edge_corr
            if combined > best_combined:
                best_combined = combined
                best_slug = slug
                best_dist = int(dist_edge[int(idx)])

        species_en = self.adapter.to_species_en(best_slug)
        species_ko = self.adapter.to_species_ko(best_slug)
        similarity_pct = round(max(0.0, min(100.0, best_combined * 100.0)), 1)
        return IconMatchResult(
            slot=slot_num,
            slug=best_slug,
            species_en=species_en,
            species_ko=species_ko,
            similarity=similarity_pct,
            distance=best_dist,
        )

    def match_team(self, slot_images: List[Union[np.ndarray, Image.Image]]) -> List[IconMatchResult]:
        """선출 화면의 6개 슬롯 이미지 리스트를 일괄 매칭하여 반환합니다."""
        return [
            self.match_single(slot_img, slot_num=idx)
            for idx, slot_img in enumerate(slot_images, 1)
        ]


if __name__ == "__main__":
    import time
    from .cropper import ROICropper

    cropper = ROICropper()
    matcher = IconMatcher()
    sc_path = PROJECT_ROOT / "tests" / "screenshots" / "team_preview.png"
    frame = imread_safe(sc_path)

    enemy_crops = cropper.crop_enemy_slots(frame)
    t0 = time.perf_counter()
    enemy_results = matcher.match_team(enemy_crops)
    enemy_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\n============================================================")
    print(f" 🔍 [상대 선출 6마리 매칭 결과] (소요 시간: {enemy_ms:.2f} ms)")
    print(f"============================================================")
    for r in enemy_results:
        print(f"   슬롯 {r.slot}: {r.species_ko:12s} ({r.species_en:18s} | {r.slug}.png) [일치율={r.similarity:.1f}%]")

    ally_crops = cropper.crop_ally_slots(frame)
    t1 = time.perf_counter()
    ally_results = matcher.match_team(ally_crops)
    ally_ms = (time.perf_counter() - t1) * 1000.0

    print(f"\n============================================================")
    print(f" 🔍 [내 엔트리 6마리 매칭 결과] (소요 시간: {ally_ms:.2f} ms)")
    print(f"============================================================")
    for r in ally_results:
        print(f"   슬롯 {r.slot}: {r.species_ko:12s} ({r.species_en:18s} | {r.slug}.png) [일치율={r.similarity:.1f}%]")
