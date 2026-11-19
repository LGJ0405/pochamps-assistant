# -*- coding: utf-8 -*-
"""
battle_ocr.py
[Step 3-3] RapidOCR(CRNN 텍스트 인식기) 기반 배틀 화면 체력(HP) 및 커맨드 배너 고속 OCR 모듈
- 이미 고정 좌표로 정밀 크롭된 단일 라인 텍스트 영역(enemy_hp_text, ally_hp_text, command_banner)에 대해
  무거운 텍스트 영역 검출기(DBNet)를 생략하고 CRNN 인식기(text_recognizer)만 배치(Batch) 호출하여
  인식률과 처리 속도를 극대화합니다.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR

_ENEMY_HP_PCT_RE = re.compile(r"(\d{1,3})\s*%")
_ENEMY_HP_DIGITS_RE = re.compile(r"(\d{1,3})")
_ALLY_HP_SLASH_RE = re.compile(r"(\d{1,3})\s*/\s*(\d{1,3})")
_COMMAND_BANNER_RE = re.compile(r"(?:COMMAND|COM|CONM|OMM)[A-Z]*\s*(\d{1,2})?", re.IGNORECASE)
_COMMAND_TOKEN_NUM_RE = re.compile(r"([A-Z]{1,12})\s*(\d{1,2})?", re.IGNORECASE)
_COMMAND_VALID_SUBSTRS = ("COMMAND", "COMMAN", "OMMAND", "COMAND", "CONMAND", "COMM", "MAND", "ND")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
KO_TO_EN_PATH = PROJECT_ROOT / "data" / "ko_to_en.json"


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
        """
        우측 상단 배너 텍스트(예: 'COMMAND 45', 'CONMAND44', 'ND44')에서
        커맨드 페이즈 여부와 남은 초를 파싱합니다.
        """
        cleaned = raw_text.strip()
        if not cleaned:
            return CommandBannerResult(
                is_command=False,
                timer_sec=None,
                raw_text="",
                confidence=round(confidence, 3),
            )

        m = _COMMAND_BANNER_RE.search(cleaned)
        if m:
            timer_val = int(m.group(1)) if m.group(1) else None
            return CommandBannerResult(
                is_command=True,
                timer_sec=timer_val,
                raw_text=cleaned,
                confidence=round(confidence, 3),
            )

        # 퍼지/부분 매칭 폴백 (CONMAND44, ND44, C45 등 CRNN 일부 깨짐 구제)
        m_tok = _COMMAND_TOKEN_NUM_RE.search(cleaned)
        if m_tok:
            word = m_tok.group(1).upper()
            num_str = m_tok.group(2)
            timer_val = int(num_str) if num_str else None
            sim = difflib.SequenceMatcher(None, word, "COMMAND").ratio()
            is_valid_timer = timer_val is not None and 1 <= timer_val <= 60
            is_cmd_word = (
                sim >= 0.57
                or (len(word) >= 2 and word in _COMMAND_VALID_SUBSTRS and is_valid_timer)
                or (word == "C" and timer_val is not None and 30 <= timer_val <= 45)
            )
            if is_cmd_word:
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

    def recognize_command_banner(self, command_banner_img: np.ndarray) -> CommandBannerResult:
        """단독 COMMAND 배너 크롭 이미지에서 커맨드 여부 및 타이머를 인식합니다."""
        rec_list, _ = self._ocr.text_recognizer([command_banner_img])
        raw_txt, score = rec_list[0] if rec_list else ("", 0.0)
        res = self.parse_command_banner_text(raw_txt, float(score))
        if res.is_command:
            return res

        # 흰색 텍스트 마스크 폴백 재시도
        mask_bgr = self._make_white_text_mask_bgr(command_banner_img)
        rec_list2, _ = self._ocr.text_recognizer([mask_bgr])
        raw_txt2, score2 = rec_list2[0] if rec_list2 else ("", 0.0)
        res2 = self.parse_command_banner_text(raw_txt2, float(score2))
        return res2 if res2.is_command else res

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
        if not cmd_res.is_command and c_txt.strip():
            # 배너에 텍스트 노이즈가 읽혔는데 매칭 실패 시 흰색 마스크 폴백 1회 시도
            mask_bgr = self._make_white_text_mask_bgr(command_banner_img)
            rec_cmd2, _ = self._ocr.text_recognizer([mask_bgr])
            if rec_cmd2:
                c2_txt, c2_score = rec_cmd2[0]
                cmd_res2 = self.parse_command_banner_text(c2_txt, float(c2_score))
                if cmd_res2.is_command:
                    cmd_res = cmd_res2
        return enemy_res, ally_res, cmd_res


_STAT_KO_MAP = {
    "공격": "atk",
    "방어": "def_",
    "특수공격": "spa",
    "특공": "spa",
    "특수방어": "spd",
    "특방": "spd",
    "스피드": "spe",
}
_STAT_CHANGE_RE = re.compile(
    r"(상대\s*)?([가-힣a-zA-Z0-9\-\s]{1,16}?)의\s*(공격|방어|특수공격|특공|특수방어|특방|스피드)[이가을를]?\s*(크게\s*)?(올라갔다|떨어졌다)"
)
_MOVE_USE_RE = re.compile(r"(상대\s*)?([가-힣a-zA-Z0-9\-\s]{1,16}?)의\s+([가-힣a-zA-Z0-9\s\-]{2,20})[!！]?")
_HIT_COUNT_RE = re.compile(r"(\d)\s*번\s*맞았다")


@dataclass
class BattleSubtitleEvent:
    """배틀 중 하단 자막에서 파싱된 단일 이벤트"""
    event_type: str  # "move_use", "stat_change", "hit_count", "critical", "stealth_rock", "forced_switch"
    is_ally: Optional[bool] = None
    actor_ko: str = ""
    move_ko: str = ""
    stat_key: str = ""
    stat_delta: int = 0
    hit_count: int = 0
    raw_texts: List[str] = field(default_factory=list)


class BattleSubtitleOCR:
    """
    배틀 애니메이션/교전 중 하단 중앙 자막을 고속으로 감지·파싱하는 한국어 OCR 파서.
    - 흰색 텍스트 마스크 비율 검사(~0.1ms) 및 연속 중복 스킵으로 빈 프레임 오버헤드 최소화
    - 기술 사용, 선후공 순서, 다단히트 타수, 스탯 랭크 변화, 필드 효과를 구조화
    """

    def __init__(self, ko_to_en_path: Optional[Path] = None):
        self._ko_to_en_path = Path(ko_to_en_path or KO_TO_EN_PATH)
        self._ocr = None
        self._move_names: List[str] = []
        self._jamo_sim_fn = None
        self._prev_thumb: Optional[np.ndarray] = None
        self._prev_events: List[BattleSubtitleEvent] = []

    def _ensure_loaded(self) -> None:
        if self._ocr is not None:
            return
        from .party_ocr import KoreanOCR, jamo_similarity

        self._ocr = KoreanOCR()
        self._jamo_sim_fn = jamo_similarity
        if self._ko_to_en_path.exists():
            with open(self._ko_to_en_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._move_names = list(data.get("moves", {}).keys())

    def reset(self) -> None:
        self._prev_thumb = None
        self._prev_events = []

    @staticmethod
    def extract_white_mask(sub_img: np.ndarray) -> np.ndarray:
        """자막 영역에서 밝은 흰색 글자 마스크(0/255 단일 채널)를 추출합니다."""
        hsv = cv2.cvtColor(sub_img, cv2.COLOR_BGR2HSV)
        return cv2.inRange(hsv, (0, 0, 185), (180, 75, 255))

    def match_move_ko(self, raw_move: str, threshold: float = 0.72) -> Optional[str]:
        """자막에서 추출된 기술명(오타 포함)을 공식 기술명 사전과 자모 유사도로 교정합니다."""
        self._ensure_loaded()
        cleaned = re.sub(r"[!！?.\s]", "", raw_move)
        if len(cleaned) < 2:
            return None
        if cleaned in self._move_names:
            return cleaned

        best_move = None
        best_score = 0.0
        assert self._jamo_sim_fn is not None
        for m in self._move_names:
            score = self._jamo_sim_fn(cleaned, m)
            if score > best_score:
                best_score = score
                best_move = m
        return best_move if best_score >= threshold else None

    def parse_subtitle_lines(
        self,
        lines: List[str],
        ally_species_ko: str = "",
        enemy_species_ko: str = "",
    ) -> List[BattleSubtitleEvent]:
        """OCR 추출 텍스트 줄 목록에서 배틀 이벤트를 파싱합니다."""
        if not lines:
            return []

        joined = " ".join(line.strip() for line in lines if line.strip())
        events: List[BattleSubtitleEvent] = []

        # 1. 다단히트 타수 ("2번 맞았다!")
        m_hit = _HIT_COUNT_RE.search(joined)
        if m_hit:
            events.append(
                BattleSubtitleEvent(
                    event_type="hit_count",
                    hit_count=int(m_hit.group(1)),
                    raw_texts=list(lines),
                )
            )
            return events

        # 2. 급소 판정 ("급소에 맞았다!")
        if "급소에" in joined and "맞았다" in joined:
            events.append(BattleSubtitleEvent(event_type="critical", raw_texts=list(lines)))
            return events

        # 3. 강제 교체 ("배틀에 끌려 나왔다!")
        if "배틀에" in joined and "끌려" in joined:
            events.append(BattleSubtitleEvent(event_type="forced_switch", raw_texts=list(lines)))
            return events

        # 4. 스텔스록 ("뾰족한 바위가 박혔다!")
        if "뾰족한" in joined and "바위가" in joined:
            events.append(BattleSubtitleEvent(event_type="stealth_rock", raw_texts=list(lines)))
            return events

        # 5. 능력치 랭크 변화 ("한카리아스의 스피드가 올라갔다!")
        m_stat = _STAT_CHANGE_RE.search(joined)
        if m_stat:
            is_enemy_prefix = bool(m_stat.group(1))
            actor = m_stat.group(2).strip()
            stat_ko = m_stat.group(3)
            is_greatly = bool(m_stat.group(4))
            direction = m_stat.group(5)
            delta = (2 if is_greatly else 1) * (1 if direction == "올라갔다" else -1)
            stat_key = _STAT_KO_MAP.get(stat_ko, "")
            if stat_key:
                is_ally = self._resolve_is_ally(is_enemy_prefix, actor, ally_species_ko, enemy_species_ko)
                events.append(
                    BattleSubtitleEvent(
                        event_type="stat_change",
                        is_ally=is_ally,
                        actor_ko=actor,
                        stat_key=stat_key,
                        stat_delta=delta,
                        raw_texts=list(lines),
                    )
                )
                return events

        # 6. 기술 사용 선언 ("한카리아스의 스케일샷!", "상대한카리아스의 스텔스록!")
        m_move = _MOVE_USE_RE.search(joined)
        if m_move:
            is_enemy_prefix = bool(m_move.group(1))
            actor = m_move.group(2).strip()
            raw_move = m_move.group(3).strip()
            # '효과가 굉장했다' 등 비기술 문구 제외
            if any(skip in raw_move for skip in ("올라갔다", "떨어졌다", "굉장했다", "별로", "맞았다", "박혔다")):
                return events
            matched_move = self.match_move_ko(raw_move)
            if matched_move:
                is_ally = self._resolve_is_ally(is_enemy_prefix, actor, ally_species_ko, enemy_species_ko)
                events.append(
                    BattleSubtitleEvent(
                        event_type="move_use",
                        is_ally=is_ally,
                        actor_ko=actor,
                        move_ko=matched_move,
                        raw_texts=list(lines),
                    )
                )
        return events

    @staticmethod
    def _resolve_is_ally(
        is_enemy_prefix: bool,
        actor_ko: str,
        ally_species_ko: str,
        enemy_species_ko: str,
    ) -> bool:
        """'상대' 접두사 및 양측 종족명을 교차 확인해 아군/상대 여부를 결정합니다."""
        if is_enemy_prefix:
            return False
        clean_a = ally_species_ko.replace("메가", "")
        clean_e = enemy_species_ko.replace("메가", "")
        if clean_a and clean_e and clean_a != clean_e:
            if clean_e in actor_ko and clean_a not in actor_ko:
                return False
        return True

    def recognize_and_parse(
        self,
        sub_img: np.ndarray,
        ally_species_ko: str = "",
        enemy_species_ko: str = "",
    ) -> List[BattleSubtitleEvent]:
        """
        하단 자막 ROI를 검사해 실제 텍스트 줄 컨투어가 있고 화면이 바뀌었을 때만
        DBNet 없이 고속 CRNN 배치(text_recognizer)로 자막을 추출/파싱합니다.
        """
        hsv = cv2.cvtColor(sub_img, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (0, 0, 210), (180, 50, 255))
        white_ratio = float(np.count_nonzero(mask)) / float(mask.size)
        if white_ratio < 0.0015 or white_ratio > 0.12:
            self._prev_thumb = None
            self._prev_events = []
            return []

        # 띄어쓰기를 포함해 한 줄 단위로 병합하는 모폴로지 팽창 후 줄 후보 박스 추출
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (50, 4))
        dil = cv2.dilate(mask, kernel, iterations=1)
        cnts, _ = cv2.findContours(dil, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes: List[Tuple[int, int, int, int]] = []
        for c in cnts:
            x, y, w, h = cv2.boundingRect(c)
            if w >= 65 and 18 <= h <= 85:
                boxes.append((y, x, w, h))

        if not boxes:
            self._prev_thumb = None
            self._prev_events = []
            return []

        thumb = cv2.resize(mask, (160, 40), interpolation=cv2.INTER_AREA)
        if self._prev_thumb is not None:
            diff = float(np.mean(np.abs(thumb.astype(np.float32) - self._prev_thumb.astype(np.float32))))
            if diff < 3.5:
                return []  # 동일 자막 유지 중이므로 중복 이벤트 발생 방지

        # 행 그룹(약 28px 단위) 우선 정렬 후 좌->우(x) 정렬로 어순 뒤바뀜 방지
        boxes.sort(key=lambda b: (b[0] // 28, b[1]))

        self._ensure_loaded()
        assert self._ocr is not None
        inv = 255 - mask
        crops: List[np.ndarray] = []
        sh, sw = sub_img.shape[:2]
        for y, x, w, h in boxes:
            x1 = max(0, x - 8)
            y1 = max(0, y - 8)
            x2 = min(sw, x + w + 8)
            y2 = min(sh, y + h + 8)
            crops.append(cv2.cvtColor(inv[y1:y2, x1:x2], cv2.COLOR_GRAY2BGR))

        rec_list, _ = self._ocr.text_recognizer(crops)
        self._prev_thumb = thumb

        if not rec_list:
            return []

        lines = [txt for txt, score in rec_list if float(score) >= 0.58 and txt.strip()]
        events = self.parse_subtitle_lines(lines, ally_species_ko=ally_species_ko, enemy_species_ko=enemy_species_ko)
        self._prev_events = events
        return events
