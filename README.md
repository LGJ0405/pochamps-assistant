# 포챔스 배틀 어시스턴트 (pochamps-assistant)

포켓몬 챔피언스(포챔스)를 위한 지능형 배틀 어시스턴트 코어 프로젝트입니다.

## 🚀 빠른 시작

### 1. 의존성 설치 및 환경 변수 설정

#### Node.js
```bash
npm install
```

#### Python
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
$env:PYTHONIOENCODING = "utf-8"
```

### 2. Step 1 계산 엔진 테스트
```powershell
# Windows PowerShell
python test_step1_calc.py
```

### 3. Step 2 한영 데이터 링크 및 샘플 계산 테스트
```powershell
# Windows PowerShell
python test_step2_data_link.py
```

### 4. Step 3 비전 화면 인식, 파티 OCR 및 배틀 추론 테스트
```powershell
# Windows PowerShell
python scripts/download_icons.py
python test_party_ocr.py        # 내 파티 스크린샷 한국어 PP-OCRv4 파싱 -> data/my_team.json 자동 생성
python test_step3_1_vision.py   # 선출 화면 ROI 크롭 및 6v6 아이콘 매칭
python test_step3_2_vision.py   # 배틀 화면 ROI 크롭, HUD 아이콘 매칭 & HP/COMMAND OCR
python test_battle_state.py     # 배틀 상태 추적(가속/랭크업/메가진화/선후공·내구 역추론) 단위 테스트
python test_step3_3_vision.py   # 배틀 녹화 영상(.mp4) 전 구간 시계열 추적 & 실시간 의사결정 브리핑
```

## 📚 문서 목록
* [Step 1: 계산 엔진 통합 상세 가이드](docs/STEP1_GUIDE.md)
* [Step 2: 한영 데이터 링크 및 파티 스펙 가이드](docs/STEP2_GUIDE.md)
* [Step 3: 화면 인식, 비전 파이프라인 및 배틀 어드바이저 가이드](docs/STEP3_GUIDE.md)
