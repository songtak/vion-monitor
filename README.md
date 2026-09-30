# VION 제품 정보 변경 감시

자동화의 전체 구성, 비교 기준, 브랜드별 추출 방식과 운영 절차는 [자동화 파이프라인 문서](docs/automation-pipeline.md)를 참고하세요.

구글 시트의 `공식 상품 상세` URL을 읽고 브랜드·사이트별 규칙으로 제품명·할인 전 가격·용량·전성분을 수집합니다. 현재 시트 값과 다른 항목을 Slack에 보내고, 시트에 수집 상태와 변경 이력을 남깁니다. 원본 제품 데이터는 담당자가 검토한 뒤 수동으로 수정합니다.

## 현재 범위와 완료 기준

- URL 등록: 90개 제품 중 **56개**. `products.csv`는 처음 구축할 때의 참고 목록이며 운영 입력은 구글 시트입니다.
- 사이트 규칙: `sites.yaml`에 **32개 사이트 그룹** 등록. 같은 쇼핑몰 엔진의 공통 추출 규칙에 사이트별 선택자를 덧붙일 수 있습니다.
- **중요: 32개 사이트 전부의 실제 추출 정확도가 검증된 상태는 아닙니다.** 업로드 후 `probe` 실행 결과에서 각 제품·항목의 `확인/미수집/오류`를 검수하고 필요한 사이트 선택자를 보완해야 합니다. URL 등록만으로 모든 성분을 자동 수집할 수는 없습니다.
- URL이 없는 34개 제품은 감시에서 제외됩니다. URL을 시트와 `products.csv`에 채우고, 새 도메인이라면 `sites.yaml`에 추가하세요.
- 전성분이 이미지에만 있거나 페이지가 접근을 차단하면 **미수집**으로 분류합니다. OCR 추측값은 자동 비교에 사용하지 않습니다.

## 시작하기

1. 이 폴더 내용을 `.github/workflows/monitor.yml`까지 포함해 **비공개 GitHub 저장소의 기본 브랜치** 루트에 올립니다. 예약 실행과 수동 실행 메뉴를 사용하려면 기본 브랜치에 워크플로가 있어야 합니다.
2. 구글 클라우드 프로젝트에서 **Google Sheets API**를 활성화하고 서비스 계정을 만든 뒤 JSON 키를 발급합니다. 대상 구글 시트를 서비스 계정 이메일과 **편집자**로 공유합니다.
3. 시트의 제품 탭에 `제품 ID`, `제품명`, `가격(원)`, `브랜드명`, `용량`, `전성분`, `공식 상품 상세` 헤더가 있어야 합니다. `공식 상품 상세`는 **Q열 안쪽**에 위치해야 합니다. 기본 탭 이름은 `제품 데이터`이며, 이름이 다르면 필수 헤더를 기준으로 제품 탭을 자동으로 찾습니다. 필요하면 GitHub 변수 `PRODUCT_SHEET_NAME`으로 탭을 지정할 수 있습니다. 앞서 받은 XLSX의 `제품 데이터` 탭을 가져오면 A~P열 구조입니다.
   제품별 수집 실패는 Slack과 Actions 경고로 남기고 나머지 제품 처리를 계속합니다. 설정·인증·시트 접근처럼 실행 전체를 막는 오류가 있을 때만 Actions 실행을 실패로 표시합니다.
4. Slack 앱에 **Incoming Webhook**을 켜고 알림을 받을 채널의 웹훅 URL을 만듭니다.
5. GitHub 저장소 → **Settings → Secrets and variables → Actions**에 아래 값을 등록합니다.

   | 구분 | 이름 | 값 |
   |---|---|---|
   | Secret | `GOOGLE_SERVICE_ACCOUNT_JSON` | 서비스 계정 JSON **전체 내용** |
   | Secret | `GOOGLE_SPREADSHEET_ID` | 시트 URL `/d/`와 `/edit` 사이의 ID |
   | Secret | `SLACK_WEBHOOK_URL` | Slack 웹훅 URL |
   | Variable (선택) | `PRODUCT_SHEET_NAME` | 제품 탭 이름. 기본 `제품 데이터`, 불일치 시 자동 탐색 |

6. **Actions → VION product monitor → Run workflow**에서 먼저 `probe=true`로 실행합니다. 완료 후 `vion-site-probe` 파일을 내려받아 `수집검증.csv`의 56개 행과 `evidence` 근거 파일을 확인합니다. `미수집`이 있는 사이트는 `sites.yaml`의 브랜드·사이트별 선택자를 보완하세요.
7. 검증 후 `probe=false`, `force=true`로 처음 실행합니다. 첫 실행부터 현재 시트 값과 공식 페이지 값이 다르면 변경 알림을 보냅니다. `수집상태`, `실행설정`, `변경이력` 탭은 자동으로 생성됩니다.
8. 현재 테스트 단계에서는 GitHub Actions가 매시 **02, 07, 12, …, 57분**에 5분 간격으로 실행됩니다. 공식 URL이 있는 제품 중 브랜드가 겹치지 않는 30개를 우선 선택합니다. 예약 실행은 시간 간격 검사를 우회하며 GitHub 사정에 따라 지연될 수 있습니다. 테스트 종료 후에는 `TEST_PRODUCT_LIMIT`과 `TEST_DISTINCT_BRANDS` 설정을 제거하고 원래 계획인 3일 간격으로 되돌릴 예정입니다.

수동 실행의 기본값은 `probe=true`, `force=false`입니다. `probe`는 시트 대신 저장소의 `products.csv`를 검사하며 Secrets 없이도 실행할 수 있습니다. `probe=true`이면 `force`는 무시됩니다. 보고서는 실행 화면의 **Artifacts → vion-site-probe**에서 내려받으며 30일간 보관됩니다. 보고서의 `추출`은 값이 발견됐다는 뜻으로, 실제 제품 정보와 일치하는지는 별도 검수가 필요합니다.

워크플로는 Python 3.11 의존성 설치와 단위 테스트 후 Chromium을 설치합니다. 동시에 여러 실행이 시트의 기준값을 수정하지 않도록 직렬 실행하며, 실행 제한 시간은 120분입니다. 본 실행의 종료 코드 2는 실패로 표시됩니다. `probe`는 미수집 항목이 있어도 완료될 수 있으므로 성공 표시뿐 아니라 보고서도 확인하세요.

## 수집 규칙 수정

`sites.yaml`은 **사이트 도메인 + 경로**로 제품 URL에 맞는 규칙을 찾습니다. `engine`은 `cafe24`, `godomall`, `makeshop`, `custom` 가운데 하나입니다. 브랜드·사이트별 `name`, `regular_price`, `base_price`, `volume`, `ingredients` 선택자를 앞에서부터 시도합니다. JavaScript 렌더링이 필요한 사이트는 `render: true`를 사용합니다. 새 브랜드는 독립된 규칙을 추가한 뒤 probe를 다시 실행하세요.

## 변경 판정과 오류 처리

- 기준: Google Sheets `제품 데이터` 탭의 **현재 제품명·가격·용량·전성분**. 첫 성공 수집부터 차이를 알립니다.
- `None`(추출 실패/정보 없음)은 이전 값과 비교하지 않으며 기존 기준값도 지우지 않습니다. 이미지 성분·접근 차단·용량 불일치 등은 검수 알림으로 모읍니다.
- 전성분은 추가·삭제·순서 변경을 분리해서 표시합니다. 문자열 정규화만 적용하며 원료명 동의어는 임의로 합치지 않습니다.
- 가격은 정상가·소비자가를 우선하고, 없으면 기본 판매가를 사용합니다. 쿠폰·회원가·최대 혜택가는 제외합니다.
- 변경이력 기록 후 Slack을 발송하고 알림 상태를 저장합니다. 기록이나 발송이 실패하면 다음 실행에서 재시도합니다.
- 56개 중 일부만 추출되더라도 실행 끝에 검수 알림을 보내고 종료 코드 2로 표시합니다. GitHub Actions의 실패 표시가 곧 전체 수집 실패를 뜻하지는 않습니다.

## 로컬 실행

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
python -m unittest discover -s tests -v
python -m vion_monitor.probe
```

`probe`는 외부 계정 연결 없이 `products.csv`의 URL 56개를 읽고 `local-output/수집검증.csv`를 생성합니다. 실제 시트 반영 실행은 위 세 가지 GitHub Secret과 같은 이름의 환경변수가 필요하며 `python -m vion_monitor`로 시작합니다. 로컬에 키 파일을 커밋하지 마세요.

## 파일

| 파일 | 역할 |
|---|---|
| `products.csv` | 90개 제품의 초기 URL 목록과 로컬 검증 입력 |
| `sites.yaml` | 32개 사이트별 URL 매핑·선택자 |
| `vion_monitor/extract.py` | 상품 페이지 필드 추출·값 정규화 |
| `vion_monitor/compare.py` | 시트 기준값과 공식 페이지 값 비교·중복 알림 방지 |
| `vion_monitor/sheets.py` | 구글 시트 읽기·스냅샷·이력 |
| `vion_monitor/__main__.py` | 예약 실행·비교·슬랙 알림 |
| `vion_monitor/probe.py` | 56개 URL 항목별 검증 보고서 |
| `.github/workflows/monitor.yml` | 정기/수동 GitHub Actions 실행 |
