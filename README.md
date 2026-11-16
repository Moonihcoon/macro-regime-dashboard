# 매크로 레짐 전략 대시보드

글로벌 매크로 지표 5개(미국 2년물 금리, 원/달러, 필라델피아 반도체지수, 구리, 미국 하이일드 스프레드)로
레짐 점수를 계산해 **KODEX 200과 현금 사이의 비중**을 조절하는 전략의 대시보드입니다.

- 화면: GitHub Pages (`index.html` + `app.js` + `data/dashboard.json`)
- 자동 갱신: GitHub Actions가 **한국 시간 평일 07:30**에 데이터 수집 → 백테스트 → `data/dashboard.json` 갱신 → 커밋

> 연구용 코드이며 투자 권유가 아닙니다.

## 처음 한 번 설정

1. **Pages 켜기**: 저장소 **Settings → Pages** → Source를 `Deploy from a branch`, Branch를 `main` / `/ (root)`로 두고 Save
2. **Actions 쓰기 권한**: **Settings → Actions → General → Workflow permissions**에서 `Read and write permissions` 선택 후 Save
3. **(선택) 한국은행 ECOS 키**: **Settings → Secrets and variables → Actions → New repository secret**, 이름 `ECOS_KEY`, 값에 발급받은 키
   - 없으면 현금 수익률을 연 3%로 고정해 계산합니다.
4. **첫 실행**: **Actions** 탭 → `Daily update` → `Run workflow`

몇 분 뒤 `https://<아이디>.github.io/macro-regime-dashboard/` 에서 화면을 볼 수 있습니다.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `config.py` | 데이터 시리즈, 발표 시차, 레짐 파라미터, 비용 설정 |
| `data_collector.py` | FRED · Yahoo Finance · (선택) 한국은행 ECOS 수집, 시점 기준 정렬 |
| `regime.py` | 피처, 롤링 z-score, 레짐 점수, 4국면, 위기 필터, 목표 비중 |
| `backtest.py` | 비중 조절 백테스트, 국면 검증, 파라미터 민감도 |
| `export_site.py` | 백테스트 결과를 `data/dashboard.json`으로 내보내기 |
| `index.html`, `app.js` | 대시보드 화면 |
| `.github/workflows/update.yml` | 매일 자동 실행 |

## PC에서 직접 돌려보기

```bash
pip install -r requirements.txt
python data_collector.py
python backtest.py
python export_site.py
python -m http.server 8000   # 브라우저에서 http://localhost:8000
```

## 알려진 한계

- FRED가 하이일드 스프레드를 최근 3년치만 제공해, 그 이전 구간은 신용 지표 없이 계산됩니다.
- Yahoo의 코스피200 지수 이력이 짧아 KODEX 200 가격(2007년~)을 사용합니다.
- 파라미터를 정한 기간과 평가한 기간이 같습니다 (표본 외 검증은 다음 단계).
