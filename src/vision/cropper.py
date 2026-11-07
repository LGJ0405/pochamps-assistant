# -*- coding: utf-8 -*-
"""
cropper.py
[Step 3-2] config/roi_coords.json에 정의된 고정 ROI 좌표를 기반으로
화면을 영역별로 분할(Crop)하고 디버그 이미지를 저장하는 모듈
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Union

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_ROI_CONFIG_PATH = PROJECT_ROOT / "config" / "roi_coords.json"


def imread_safe(path: Union[str, Path], flags: int = cv2.IMREAD_COLOR) -> np.ndarray:
    """Windows 한글 경로에서도 안전하게 동작하는 OpenCV 이미지 로더"""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"이미지 파일을 찾을 수 없습니다: {file_path}")
    raw = np.fromfile(str(file_path), dtype=np.uint8)
    img = cv2.imdecode(raw, flags)
    if img is None:
        raise ValueError(f"이미지 디코딩 실패: {file_path}")
    return img


def imwrite_safe(path: Union[str, Path], img: np.ndarray) -> bool:
    """Windows 한글 경로에서도 안전하게 동작하는 OpenCV 이미지 저장 함수"""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    ext = file_path.suffix or ".png"
    ok, encoded = cv2.imencode(ext, img)
    if not ok:
        return False
    encoded.tofile(str(file_path))
    return True


class ROICropper:
    """고정 해상도 기준 관심 영역(ROI) 크롭퍼"""

    def __init__(self, config_path: Optional[Union[str, Path]] = None):
        cfg_file = Path(config_path) if config_path else DEFAULT_ROI_CONFIG_PATH
        with open(cfg_file, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        self.target_width: int = self.config["resolution"]["width"]
        self.target_height: int = self.config["resolution"]["height"]
        self.enemy_team_slots: List[dict] = self.config.get("enemy_team_slots", [])
        self.ally_team_slots: List[dict] = self.config.get("ally_team_slots", [])
        self.battle_rois: Dict[str, dict] = self.config.get("battle_rois", {})

    def normalize_frame(self, frame: np.ndarray) -> np.ndarray:
        """입력 프레임 해상도가 기준 해상도와 다르면 자동 리사이즈합니다."""
        h, w = frame.shape[:2]
        if w == self.target_width and h == self.target_height:
            return frame
        return cv2.resize(
            frame,
            (self.target_width, self.target_height),
            interpolation=cv2.INTER_AREA if w > self.target_width else cv2.INTER_LINEAR,
        )

    @staticmethod
    def crop_rect(frame: np.ndarray, rect: dict) -> np.ndarray:
        """{"x", "y", "w", "h"} 딕셔너리 영역을 안전하게 잘라냅니다."""
        h, w = frame.shape[:2]
        x1 = max(0, int(rect["x"]))
        y1 = max(0, int(rect["y"]))
        x2 = min(w, x1 + int(rect["w"]))
        y2 = min(h, y1 + int(rect["h"]))
        return frame[y1:y2, x1:x2].copy()

    def crop_enemy_slots(self, frame: np.ndarray) -> List[np.ndarray]:
        """선출 화면의 상대 엔트리 6개 슬롯 아이콘 이미지를 순서대로 잘라내어 반환합니다."""
        norm = self.normalize_frame(frame)
        return [self.crop_rect(norm, slot_rect) for slot_rect in self.enemy_team_slots]

    def crop_ally_slots(self, frame: np.ndarray) -> List[np.ndarray]:
        """선출 화면의 아군 엔트리 6개 슬롯 아이콘 이미지를 순서대로 잘라내어 반환합니다."""
        norm = self.normalize_frame(frame)
        return [self.crop_rect(norm, slot_rect) for slot_rect in self.ally_team_slots]

    def draw_debug_overlay(self, frame: np.ndarray) -> np.ndarray:
        """정의된 ROI 박스를 프레임 위에 그려 디버그 오버레이 이미지를 반환합니다."""
        canvas = self.normalize_frame(frame).copy()

        for slot in self.enemy_team_slots:
            x, y, w, h = slot["x"], slot["y"], slot["w"], slot["h"]
            cv2.rectangle(canvas, (x, y), (x + w, y + h), (0, 255, 100), 3)
            cv2.putText(
                canvas,
                f"Enemy {slot.get('slot', '')}",
                (x, max(25, y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 100),
                2,
            )

        for slot in self.ally_team_slots:
            x, y, w, h = slot["x"], slot["y"], slot["w"], slot["h"]
            cv2.rectangle(canvas, (x, y), (x + w, y + h), (255, 200, 0), 3)
            cv2.putText(
                canvas,
                f"Ally {slot.get('slot', '')}",
                (x, max(25, y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 200, 0),
                2,
            )

        return canvas

    def save_debug_crops(
        self,
        frame: np.ndarray,
        output_dir: Union[str, Path],
        prefix: str = "team_preview",
    ) -> List[Path]:
        """크롭된 조각 이미지들과 전체 ROI 오버레이 이미지를 지정 폴더에 저장합니다."""
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        saved_files: List[Path] = []

        overlay = self.draw_debug_overlay(frame)
        overlay_file = out_path / f"{prefix}_overlay.png"
        imwrite_safe(overlay_file, overlay)
        saved_files.append(overlay_file)

        for idx, slot_img in enumerate(self.crop_enemy_slots(frame), 1):
            p = out_path / f"{prefix}_enemy_slot_{idx}.png"
            imwrite_safe(p, slot_img)
            saved_files.append(p)

        for idx, slot_img in enumerate(self.crop_ally_slots(frame), 1):
            p = out_path / f"{prefix}_ally_slot_{idx}.png"
            imwrite_safe(p, slot_img)
            saved_files.append(p)

        return saved_files


if __name__ == "__main__":
    cropper = ROICropper()
    sc_path = PROJECT_ROOT / "tests" / "screenshots" / "team_preview.png"
    debug_dir = PROJECT_ROOT / "tests" / "screenshots" / "debug_crops"
    img = imread_safe(sc_path)
    saved = cropper.save_debug_crops(img, debug_dir, prefix="team_preview")
    print(f"✅ [team_preview.png] 크롭 완료: 총 {len(saved)}개 파일 저장 -> {debug_dir}")
