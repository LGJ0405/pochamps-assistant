# -*- coding: utf-8 -*-
"""
calc_bridge.py
Python ↔ Node.js(@smogon/calc) 브릿지

subprocess로 calc_worker/worker.js를 실행하고,
stdin/stdout JSON-line 프로토콜로 통신합니다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .schemas import CalcRequest, CalcResult

# 프로젝트 루트 기준 worker.js 경로
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WORKER_SCRIPT = _PROJECT_ROOT / "calc_worker" / "worker.js"


class CalcBridge:
    """Node.js 워커 프로세스를 관리하고 데미지 계산을 실행하는 브릿지 클래스"""

    def __init__(self, node_path: str = "node"):
        self._node_path = node_path
        self._process: Optional[subprocess.Popen] = None

    # ── 라이프사이클 ──

    def start(self) -> None:
        """워커 프로세스를 시작합니다."""
        if self._process is not None and self._process.poll() is None:
            return  # 이미 실행 중

        self._process = subprocess.Popen(
            [self._node_path, str(_WORKER_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8-sig",
            cwd=str(_PROJECT_ROOT),
        )

    def stop(self) -> None:
        """워커 프로세스를 종료합니다."""
        if self._process is None:
            return
        try:
            self._process.stdin.close()
            self._process.wait(timeout=5)
        except Exception:
            self._process.kill()
        finally:
            self._process = None

    def is_alive(self) -> bool:
        """워커가 살아 있는지 확인합니다."""
        return self._process is not None and self._process.poll() is None

    def _read_response(self) -> str:
        """워커 프로세스에서 JSON 응답 라인을 안전하게 읽어옵니다."""
        accumulated = []
        while True:
            line = self._process.stdout.readline()
            if not line:
                stderr_out = ""
                if self._process and self._process.stderr:
                    try:
                        stderr_out = self._process.stderr.read()
                    except Exception:
                        pass
                raise RuntimeError(
                    f"워커에서 응답이 없습니다. stderr: {stderr_out}"
                    + (f"\n수신 시도된 출력: {accumulated}" if accumulated else "")
                )

            cleaned = line.lstrip("\ufeff").strip()
            if cleaned.startswith(("{", "[")):
                return cleaned
            if cleaned:
                accumulated.append(cleaned)

    # ── 계산 ──

    def calculate(self, request: CalcRequest) -> CalcResult:
        """
        데미지 계산을 실행합니다.

        Args:
            request: CalcRequest 인스턴스
        Returns:
            CalcResult 인스턴스
        Raises:
            RuntimeError: 워커가 실행 중이 아닐 때
        """
        if not self.is_alive():
            raise RuntimeError(
                "CalcBridge 워커가 실행 중이 아닙니다. bridge.start()를 먼저 호출하세요."
            )

        payload = json.dumps(request.to_dict(), ensure_ascii=False) + "\n"
        self._process.stdin.write(payload)
        self._process.stdin.flush()

        response_line = self._read_response()
        try:
            data = json.loads(response_line)
        except json.JSONDecodeError as err:
            stderr_out = self._process.stderr.read() if self._process and self._process.stderr else ""
            raise RuntimeError(
                f"워커 응답 JSON 파싱 실패: {err}\n수신된 라인: [{response_line!r}]\n워커 stderr: [{stderr_out}]"
            ) from err

        return CalcResult.from_worker_response(data)

    def calculate_dict(self, request_dict: dict) -> dict:
        """
        딕셔너리 기반 단순 계산 (스키마 없이 직접 JSON 전송)

        Args:
            request_dict: worker.js가 이해하는 JSON 딕셔너리
        Returns:
            worker.js 응답 딕셔너리
        """
        if not self.is_alive():
            raise RuntimeError(
                "CalcBridge 워커가 실행 중이 아닙니다. bridge.start()를 먼저 호출하세요."
            )

        payload = json.dumps(request_dict, ensure_ascii=False) + "\n"
        self._process.stdin.write(payload)
        self._process.stdin.flush()

        response_line = self._read_response()
        try:
            return json.loads(response_line)
        except json.JSONDecodeError as err:
            stderr_out = self._process.stderr.read() if self._process and self._process.stderr else ""
            raise RuntimeError(
                f"워커 응답 JSON 파싱 실패: {err}\n수신된 라인: [{response_line!r}]\n워커 stderr: [{stderr_out}]"
            ) from err

    # ── 컨텍스트 매니저 ──

    def __enter__(self) -> "CalcBridge":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
