# FinancialJuice 뉴스 중계 (GitHub Actions)

> 운영 상태 (2026-11-06 KST): **원본 RSS HTTP 429로 예약 수집 일시 중지**. GitHub Actions 수동 실행은 유지. 기존 데이터는 보존되지만 최신 뉴스가 아닙니다. ChatGPT 원래 분석 자동화는 비활성화 상태입니다.

## 목적

기존 Cloudflare Worker가 만든 FinancialJuice RSS JSON을 GitHub Actions로 읽어, ChatGPT에서 접근 가능한 공개 `news.json`으로 제공합니다. 별도의 AI API, 개인 PC 상시 실행, DNS 변경은 필요하지 않습니다.

```text
FinancialJuice RSS → 기존 Cloudflare Worker → GitHub Actions → news.json (공개) → ChatGPT 예약 자동화
```

## 설치 및 시험

1. 공개 저장소의 `.github/workflows/update-news.yml`이 기본 브랜치에 있는지 확인합니다.
2. GitHub `Settings → Actions → General → Workflow permissions`에서 `Read and write permissions`를 확인합니다. 저장소/조직 정책이 쓰기를 제한할 수도 있습니다.
3. 원본 429 원인을 해결하고 재개 승인을 받은 후에만 `Actions` 탭에서 `Refresh FinancialJuice news` → **Run workflow**를 눌러 시험합니다. (현재 자동 Cron 비활성화)
4. 실행 후 `news.json`의 `status: ok`, 실제 기사 `guid`, `pubDate`, `link`, `lastSuccessAt`을 확인합니다.
5. `status: error`라면 Actions 실행 로그를 확인하되, 오류를 '뉴스 없음'으로 해석하지 않습니다.
6. ChatGPT 일반 조회 **및 예약 자동화 실행 환경**에서 공개 `news.json`의 실수신을 구분 검증합니다.
7. 기존 FinancialJuice 예약 자동화는 **사용자 승인 전에 재활성화하지 않습니다**.

## 공개 JSON

`https://raw.githubusercontent.com/firetruck4159-art/financialjuice-news-relay/main/news.json`

- `status`: `not_initialized` / `ok` / `error`
- `lastAttemptAt`, `lastSuccessAt`: 수집 시도 및 성공 UTC 시각
- `sourceNewestAt`: 수신 기사 중 가장 최근 게시일
- `upstreamItemCount`: Worker가 반환한 항목 개수
- `articles`: 최근 12시간 이내 최신 기사 최대 150건 (GUID, 제목, 링크, 게시 시각, 짧은 설명)

## 주의사항

- **검증 전 상태**: `news.json`의 초기값은 `not_initialized`입니다. GitHub Actions 첫 실행 전에는 실제 수집 결과가 아닙니다.
- `?limit=50`을 요청하지만 Worker의 지원 상한은 아직 검증되지 않았습니다. 첫 실행 후 `upstreamItemCount`를 확인하세요.
- GitHub Actions 예약 실행은 지연되거나 누락될 수 있습니다. 공개 저장소에서 장기간 활동이 없으면 예약 실행이 비활성화될 수도 있습니다.
- 공개 저장소에는 인증 토큰과 개인정보를 넣지 마세요. 뉴스 원문 전체를 복제·재배포하지 않습니다.
- 공식 RSS 이용조건 및 재배포 범위를 확인하세요.
- 중복 분석·중복 발송을 완전히 막으려면 ChatGPT 예약 실행에서 발송 이력의 영구 관리가 별도로 필요합니다.
- 실패 시 기존 기사를 남겨두지만 `status: error`를 표시합니다.
- 15분마다 갱신하면 최대 약 96회/일 커밋이 생성될 수 있습니다. 운영 안정화 후 빈도·보관 구조를 최적화할 계획입니다.

## 개발자 단위 시험

```bash
python -m unittest discover -s tests -v
```

## 원본 요청 제한(429) 진단

2026-11-06 KST GitHub Actions의 실측 시험 결과:

- GitHub 예약 트리거는 작동함. 과거 수동 실행과 예약 실행에서는 JSON 수집도 성공한 이력이 있음.
- 이후 반복되는 실패는 **Cloudflare Worker HTTP 502**이며, Worker의 JSON 오류 응답에서 **`upstreamStatus: 429`**가 확인됨.
- 이는 FinancialJuice 원본 요청이 제한되었음을 의미함. 다만 요청 횟수, IP 제한, 차단 정책 중 정확한 적용 원인은 미확인.
- GitHub의 `scripts/fetch_news.py`는 `lastHttpStatus`에 Worker 응답, `upstreamHttpStatus`에 Worker가 알려준 원본 응답 코드를 각각 기록함.
- Worker의 502가 원본 429를 감싼 경우에는 **즉시 재시도하지 않음**. 일시적인 500/502/503/504이고 원본 403/429가 아닌 경우에만 3초 뒤 최대 한 번 재시도함.
- 실패 시 `news.json`의 `status`는 `error`, `lastSuccessAt`은 과거 성공 시각 그대로이며, 기존 기사는 보존됨. `status: ok` 또는 과거 기사 존재만으로 최신 데이터라고 판단하면 안 됨.
- GitHub 코드가 원본의 HTTP 429를 해제할 수는 없음. Cloudflare Worker의 실제 소스·실행 로그와 FinancialJuice RSS 정책/요청 제한을 확인한 뒤, 허용된 요청 빈도·캐시·대체 피드 등을 재검토해야 함.
- 추가 요청으로 차단이 악화될 수 있으므로 이 상태에서 무제한 재시도나 강제 새로고침을 하지 말 것.
- 네트워크나 인증정보가 필요하지 않은 단위 시험은 `Unit tests (no network)`에서 수행.
- 진단용 임시 `schedule-probe.yml`, `diagnose-relay.yml`은 점검 후 삭제함.
- 기존 ChatGPT 'FinancialJuice 중요 뉴스' 예약 자동화는 **비활성화 상태를 유지**하며 수정하지 않음.

## 2026-11-06 수집 중지 기록

- 이유: Worker HTTP 502의 응답 내부 `upstreamStatus: 429` 확인. 원본 요청 제한 미해결.
- `.github/workflows/update-news.yml`에서 `schedule`만 제거하고 `workflow_dispatch` 수동 실행은 보존함.
- 기존 `news.json`, 수집 Python 코드, 단위 테스트, GitHub 설정 및 ChatGPT 자동화는 유지.
- 재개 조건: Cloudflare Worker의 실제 소스/캐시/요청 정책을 확인하고 승인된 방법으로 원본 429 문제 해결 후 실측 검증.
