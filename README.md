# 포챔스 배틀 어시스턴트 (pochamps-assistant)

포켓몬 챔피언스(포챔스)를 위한 지능형 배틀 어시스턴트 코어 프로젝트입니다.

## 🚀 빠른 시작

### 1. 의존성 설치

#### Node.js
```bash
npm install
```

#### Python
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Step 1 계산 엔진 테스트
```powershell
# Windows PowerShell
$env:PYTHONIOENCODING = "utf-8"
python test_step1_calc.py
```

### 3. Step 2 한영 데이터 링크 및 샘플 계산 테스트
```powershell
# Windows PowerShell
$env:PYTHONIOENCODING = "utf-8"
python test_step2_data_link.py
```

### 4. Step 3 비전 크롭 및 아이콘 매칭 테스트 (선출 화면 & 배틀 HUD)
```powershell
# Windows PowerShell
$env:PYTHONIOENCODING = "utf-8"
python scripts/download_icons.py
python test_step3_1_vision.py
python test_step3_2_vision.py
```

## 📚 문서 목록
* [Step 1: 계산 엔진 통합 상세 가이드](docs/STEP1_GUIDE.md)
* [Step 2: 한영 데이터 링크 및 샘플 기반 계산 가이드](docs/STEP2_GUIDE.md)
* [Step 3: 화면 인식 및 비전 파이프라인 가이드 (Part 1~2)](docs/STEP3_GUIDE.md)
