# -*- coding: utf-8 -*-
"""
battle_ocr.py
[Step 3-3] RapidOCR(CRNN 텍스트 인식기) 기반 배틀 화면 체력(HP) 및 커맨드 배너 고속 OCR 모듈
- 이미 고정 좌표로 정밀 크롭된 단일 라인 텍스트 영역(enemy_hp_text, ally_hp_text, command_banner)에 대해
  무거운 텍스트 영역 검출기(DBNet)를 생략하고 CRNN 인식기(text_recognizer)만 배치(Batch) 호출하여
  인식률과 처리 속도를 극대화합니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR

_ENEMY_HP_PCT_RE = re.compile(r"(\d{1,3})\s*%")
_ENEMY_HP_DIGITS_RE = re.compile(r"(\d{1,3})")
_ALLY_HP_SLASH_RE = re.compile(r"(\d{1,3})\s*/\s*(\d{1,3})")
_COMMAND_BANNER_RE = re.compile(r"(?:COMMAND|COM)[A-Z]*\s*(\d{1,2})?", re.IGNORECASE)


@dataclass
class EnemyHPResult:
    """상대 포켓몬 남은 체력(%) OCR 결과"""
    hp_percent: Optional[int]
    raw_text: str
    confidence: float

    @property
    def is_valid(self) -> bool:
        return self.hp_percent is not None and 0 <= self.hp_percent <= 100


@dataclass
class AllyHPResult:
    """아군 포켓몬 남은 체력(현재/최대 및 %) OCR 결과"""
    cur_hp: Optional[int]
    max_hp: Optional[int]
    hp_percent: Optional[float]
    raw_text: str
    confidence: float

    @property
    def is_valid(self) -> bool:
        return (
            self.cur_hp is not None
            and self.max_hp is not None
            and self.max_hp > 0
            and 0 <= self.cur_hp <= self.max_hp
        )


@dataclass
class CommandBannerResult:
    """우측 상단 COMMAND 타이머 배너 OCR 결과"""
    is_command: bool
    timer_sec: Optional[int]
    raw_text: str
    confidence: float


class BattleOCR:
    """배틀 화면 체력(상대 %, 아군 현재/최대) 및 COMMAND 배너 고속 OCR 파서"""

    def __init__(self):
        # 이미 고정 ROI로 잘라낸 단일 라인 이미지이므로 DBNet 검출(use_text_det) 및 각도 분류(use_angle_cls) 비활성화
        self._ocr = RapidOCR(use_text_det=False, use_angle_cls=False)

    @staticmethod
    def _make_white_text_mask_bgr(img: np.ndarray) -> np.ndarray:
        """흰색 숫자(고명도·저채도)만 추출하여 흰 배경의 검은 글씨 BGR 이미지로 변환합니다."""
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (0, 0, 190), (180, 65, 255))
        inv = 255 - mask
        return cv2.cvtColor(inv, cv2.COLOR_GRAY2BGR)

    @staticmethod
    def parse_enemy_hp_text(raw_text: str, confidence: float) -> EnemyHPResult:
        """상대 체력 텍스트(예: '100%', ' 9%', ':28%', '网 1%')에서 0~100% 정수를 파싱합니다."""
        cleaned = raw_text.strip()
        m = _ENEMY_HP_PCT_RE.search(cleaned)
        if m:
            val = int(m.group(1))
            if 0 <= val <= 100:
                return EnemyHPResult(hp_percent=val, raw_text=cleaned, confidence=round(confidence, 3))
        return EnemyHPResult(hp_percent=None, raw_text=cleaned, confidence=round(confidence, 3))

    @staticmethod
    def parse_ally_hp_text(raw_text: str, confidence: float) -> AllyHPResult:
        """아군 체력 텍스트(예: '185/185', '131 /205', '1 /185')에서 현재/최대 체력을 파싱합니다."""
        cleaned = raw_text.strip()
        m = _ALLY_HP_SLASH_RE.search(cleaned)
        if m:
            cur_hp = int(m.group(1))
            max_hp = int(m.group(2))
            if max_hp >= 10 and 0 <= cur_hp <= max_hp:
                pct = round((cur_hp / max_hp) * 100.0, 1)
                return AllyHPResult(
                    cur_hp=cur_hp,
                    max_hp=max_hp,
                    hp_percent=pct,
                    raw_text=cleaned,
                    confidence=round(confidence, 3),
                )
        return AllyHPResult(
            cur_hp=None,
            max_hp=None,
            hp_percent=None,
            raw_text=cleaned,
            confidence=round(confidence, 3),
        )

    @staticmethod
    def parse_command_banner_text(raw_text: str, confidence: float) -> CommandBannerResult:
        """우측 상단 배너 텍스트(예: 'COMMAND 45', 'COMMAND44')에서 커맨드 페이즈 여부와 남은 초를 파싱합니다."""
        cleaned = raw_text.strip()
        m = _COMMAND_BANNER_RE.search(cleaned)
        if m:
            timer_val = int(m.group(1)) if m.group(1) else None
            return CommandBannerResult(
                is_command=True,
                timer_sec=timer_val,
                raw_text=cleaned,
                confidence=round(confidence, 3),
            )
        return CommandBannerResult(
            is_command=False,
            timer_sec=None,
            raw_text=cleaned,
            confidence=round(confidence, 3),
        )

    def recognize_enemy_hp(self, enemy_hp_img: np.ndarray) -> EnemyHPResult:
        """단일 상대 HP 크롭 이미지에서 체력(%)을 추출합니다."""
        rec_list, _ = self._ocr.text_recognizer([enemy_hp_img])
        raw_txt, score = rec_list[0] if rec_list else ("", 0.0)
        res = self.parse_enemy_hp_text(raw_txt, float(score))
        if res.is_valid:
            return res

        # 폴백: 흰색 글자 마스크 전처리 후 재시도
        mask_bgr = self._make_white_text_mask_bgr(enemy_hp_img)
        rec_list2, _ = self._ocr.text_recognizer([mask_bgr])
        raw_txt2, score2 = rec_list2[0] if rec_list2 else ("", 0.0)
        res2 = self.parse_enemy_hp_text(raw_txt2, float(score2))
        if res2.is_valid:
            return res2

        m_digits = _ENEMY_HP_DIGITS_RE.search(raw_txt2.strip())
        if m_digits and float(score2) >= 0.5:
            val = int(m_digits.group(1))
            if 0 <= val <= 100:
                return EnemyHPResult(hp_percent=val, raw_text=raw_txt2.strip(), confidence=round(float(score2), 3))
        return res

    def recognize_ally_hp(self, ally_hp_img: np.ndarray) -> AllyHPResult:
        """단일 아군 HP 크롭 이미지에서 현재/최대 체력을 추출합니다."""
        rec_list, _ = self._ocr.text_recognizer([ally_hp_img])
        raw_txt, score = rec_list[0] if rec_list else ("", 0.0)
        res = self.parse_ally_hp_text(raw_txt, float(score))
        if res.is_valid:
            return res

        mask_bgr = self._make_white_text_mask_bgr(ally_hp_img)
        rec_list2, _ = self._ocr.text_recognizer([mask_bgr])
        raw_txt2, score2 = rec_list2[0] if rec_list2 else ("", 0.0)
        return self.parse_ally_hp_text(raw_txt2, float(score2))

    def recognize_battle_hud_texts(
        self,
        enemy_hp_img: np.ndarray,
        ally_hp_img: np.ndarray,
        command_banner_img: np.ndarray,
    ) -> Tuple[EnemyHPResult, AllyHPResult, CommandBannerResult]:
        """
        상대 HP, 아군 HP, COMMAND 배너 3개 영역을 단일 배치(Batch) ONNX 추론으로 동시에 인식합니다.
        """
        rec_list, _ = self._ocr.text_recognizer([enemy_hp_img, ally_hp_img, command_banner_img])
        if not rec_list or len(rec_list) < 3:
            return (
                EnemyHPResult(None, "", 0.0),
                AllyHPResult(None, None, None, "", 0.0),
                CommandBannerResult(False, None, "", 0.0),
            )

        e_txt, e_score = rec_list[0]
        a_txt, a_score = rec_list[1]
        c_txt, c_score = rec_list[2]

        enemy_res = self.parse_enemy_hp_text(e_txt, float(e_score))
        if not enemy_res.is_valid:
            enemy_res = self.recognize_enemy_hp(enemy_hp_img)

        ally_res = self.parse_ally_hp_text(a_txt, float(a_score))
        if not ally_res.is_valid:
            ally_res = self.recognize_ally_hp(ally_hp_img)

        cmd_res = self.parse_command_banner_text(c_txt, float(c_score))
        return enemy_res, ally_res, cmd_res
