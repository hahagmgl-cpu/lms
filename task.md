# 티스토리 자동화 — 개선 작업 계획

## 목표 (원하는 운영 시나리오)

1. 키워드 5개를 넣으면 글 5편 + 이미지를 생성해 **큐에 저장만** 한다 (발행 X)
2. 큐에 100편까지 비축해두고, 원할 때 **3개든 5개든 골라서** 발행을 건다
3. 고른 글들은 티스토리 **예약발행**으로 걸리되, 글 사이 간격이 **3~5시간 랜덤**으로 벌어진다
4. 이미지의 **파일명 / alt / 캡션이 생성 시점에 확정**되고, 본문의 **이미지 홀더 위치에 정확히** 들어간다

---

## 현재 코드 진단

### 이미 되는 것 (수정 불필요)

- 키워드 여러 개 → 글+이미지 생성 → 큐 저장: `automation/produce.js`, GUI ①탭
- 큐에서 체크박스로 골라 발행: `server.js` `/api/publish` (`ids`), `publish-queue.js` (`--ids`)
- 이미지 메타(alt/caption/filename) 생성 시점 확정: `lib/imagemeta.js` `normalizeImages()`
- 큐 엑셀/CSV 인덱스, GUI에서 이미지 메타 수정

### 고쳐야 하는 것 (실제로 돌려서 확인함)

**A. 이미지가 본문의 엉뚱한 홀더 위치에 들어간다 (요구사항 4)**

메타데이터가 이미지에 붙는 것 자체는 정상이지만, **배치 위치가 밀린다.**
이미지 3개 중 가운데(index 1) 생성이 실패한 상황을 재현한 결과:

```
입력 본문: <p>{{IMAGE_0}}</p> ... <p>{{IMAGE_1}}</p> ... <p>{{IMAGE_2}}</p>
이미지:    [0]=성공, [1]=생성실패(file 없음), [2]=성공

실제 결과: {{IMAGE_1}} 자리에 2번 이미지(ALT2/two.webp)가 들어감
           {{IMAGE_2}} 자리는 빈 <p></p> 로 남음
```

원인:
- `post.js:51` `prepareImages()`가 `file` 없는 이미지를 배열에서 **제거** → 뒤 항목들의 인덱스가 앞으로 당겨짐
- `lib/tistory.js:569` `mergeImagesIntoBody()`가 배열 순번 `i`로 `{{IMAGE_i}}`를 찾음 → 원래 슬롯 번호와 어긋남
- `post.js:69` 미사용 토큰 정리도 `prepared.length` 기준이라 잘못된 토큰을 지움

이미지 생성은 무료 공급자(Pollinations 잔액 소진, HF 503 등)에서 실패가 잦고,
`produce.js:77`이 실패를 잡고 계속 진행하므로 **실전에서 자주 터지는 경로**다.

**B. 여러 글을 발행하면 전부 같은 시각에 예약된다 (요구사항 3)**

- `publish-queue.js:50` — `reserveAt = opts.at || post.scheduleAt`
- `server.js:234` — 대상 전체 루프에 동일한 `body.at`을 그대로 전달

간격을 벌리는 로직이 **아예 없다.** 5개를 고르면 5개가 같은 시각에 예약된다.

**C. 예약 시각이 KST 아닌 머신에서 9시간 어긋난다**

`lib/tistory.js:424`가 `when.getHours()` 등 **Node 프로세스 로컬 타임존**으로 값을 만들어,
`timezoneId: 'Asia/Seoul'`로 고정된 페이지(`tistory.js:48`)에 타이핑한다.

```
현재 실제 KST         : 7/25 23:16
의도한 예약(3시간 뒤) : 7/26 02:16
실제 타이핑되는 값    : 7/25 17:16   ← 9시간 어긋남
```

사용자 PC(KST)에서 직접 돌리면 우연히 맞지만, 컨테이너/서버(UTC)에서는 어긋난다.
특히 "지금부터 N시간 뒤" 같은 **상대 시각 계산이 들어오는 순간** 문제가 된다 —
B번 작업이 바로 그 상대 시각 계산이므로 **같이 고쳐야 한다.**
과거 시각으로 계산되면 예약이 거부되거나 즉시 발행될 수 있다.

**D. 비축분 100개에서 N개 뽑을 때 최신 글부터 나간다**

`lib/store.js:91`이 `createdAt` 내림차순 정렬 → `--all --limit 3`이 **가장 최근 3개**를 집는다.
비축해둔 글은 오래된 것부터 소진(FIFO)되는 게 자연스럽다.

**E. 예약 설정 실패를 감지하지 못한다**

`tistory.js:478` — 날짜/시간 입력란을 못 찾으면 로그만 남기고 그대로 진행한다.
`writePost`는 발행 버튼 텍스트만 확인하고 끝나서(`tistory.js:337`),
예약이 안 걸린 채 **5개가 동시에 즉시 발행**되어도 "성공"으로 기록된다.

**F. 이미지 치환문 형식이 다르면 alt/캡션이 조용히 사라진다**

`tistory.js:553` 정규식이 `|CDM|<숫자>|{JSON}` 형태만 인식한다. 변형 테스트 결과:

| 치환문 형태 | alt/caption 주입 |
|---|---|
| `\|CDM\|1.3\|{...}` | 성공 |
| `\|CDM\|1.9\|{...}` | 성공 |
| `\|alignCenter\|data-origin-width=...\|{...}` | **실패(무시)** |
| 옵션 JSON 없음 | **실패(무시)** |

티스토리가 에디터를 바꿔 형식이 달라지면 경고 없이 메타가 유실된다.

---

## 작업 목록

### P0 — 요구사항 직결

- [ ] **1. 이미지 슬롯 번호 고정 (A)**
  - `lib/imagemeta.js` `normalizeImages()`에서 각 이미지에 `slot: i` 부여 (원래 홀더 번호)
  - `post.js` `prepareImages()`가 `file` 없는 항목을 걸러내도 `slot`은 그대로 보존
  - `lib/tistory.js` `mergeImagesIntoBody()`가 배열 순번이 아니라 `meta.slot`으로 `{{IMAGE_<slot>}}`를 타겟팅
  - 미사용 토큰 제거는 **실제 배치된 slot 집합** 기준으로 (`prepared.length` 기준 폐기)
  - 기존 큐 데이터(`slot` 없는 post.json)는 배열 순번을 slot으로 간주하는 폴백 유지
  - 검증: 가운데 이미지 실패 시나리오에서 0번→`{{IMAGE_0}}`, 2번→`{{IMAGE_2}}`, `{{IMAGE_1}}`은 흔적 없이 제거

- [ ] **2. 3~5시간 랜덤 간격 예약 스케줄러 (B)**
  - `automation/lib/schedule.js` 신규: 대상 개수 + `{startAt, minHours, maxHours}` → 예약 시각 배열 계산
  - 첫 글은 `startAt`(미지정 시 지금 + minHours), 이후 직전 시각 + `random(min~max)`시간
  - `server.js` `/api/publish`: `spacing` 파라미터 수신 → 대상별 예약 시각을 각각 `publishOne`에 전달
  - `publish-queue.js`: `--spread-min 3 --spread-max 5 --start-at "..."` CLI 옵션 추가
  - 계산된 시각을 각 post의 `scheduleAt`에 저장(발행 전 미리보기 가능하게)
  - GUI ②탭: "간격 3~5시간 랜덤으로 예약" 입력란 + 예약 시각 미리보기

- [ ] **3. 예약 시각 KST 고정 (C)**
  - `lib/tistory.js` `setReserveTime()`이 `Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Seoul'})`로 연/월/일/시/분 추출
  - `post.js` `resolveReserveAt()`의 기본값(`Date.now() + 1h`) 계산도 KST 기준으로
  - 타임존 없는 문자열(`"2026-07-26T09:00"`)은 **KST 입력으로 해석**한다고 명시
  - 검증: `TZ=UTC`와 `TZ=Asia/Seoul` 양쪽에서 같은 예약 시각이 나오는지 확인

### P1 — 100개 비축 운영

- [ ] **4. 배치 발행 순서를 FIFO로 (D)**
  - `publish-queue.js` `--all --limit N`이 **오래된 글부터** 집도록 (`--order newest`로 반대 선택 가능)
  - `server.js` `/api/publish`의 `all + limit` 경로도 동일하게

- [ ] **5. 예약 성공 검증 (E)**
  - `setReserveTime()`이 입력 후 실제 반영된 값을 다시 읽어 대조, 불일치 시 **예외로 중단**
  - `writePost` 반환값에 `reservedAt` 포함 → `publishOne`이 `scheduleAt`과 비교해 기록
  - 예약 실패 시 `status: 'failed'`로 남겨 즉시 발행 사고를 막는다

- [ ] **6. 큐 목록 경량화 (100건 대비)**
  - `store.listPosts()`에 본문 `html` 제외 옵션 추가 (`/api/queue`는 목록 필드만 읽기)
  - GUI ②탭에 상태 필터(ready/published/failed) + 키워드 검색

### P2 — 안정성

- [ ] **7. 치환문 정규식 폴백 + 경고 (F)**
  - `|CDM|<숫자>|` 고정 대신 **마지막 `|` 뒤 JSON**을 잡는 형태로 완화
  - 그래도 파싱 실패하면 조용히 넘기지 말고 로그에 경고 (`이미지 N: alt/caption 주입 실패`)

---

## 완료 기준

- 키워드 5개 투입 → 큐에 5편(글+이미지) 저장, 이미지 생성이 일부 실패해도 **남은 이미지가 제 홀더 위치에** 들어감
- 큐에서 3개 체크 → 발행 시 3개가 **3~5시간 랜덤 간격**으로 서로 다른 시각에 예약됨
- 예약 시각이 KST 기준으로 정확하고, 예약이 안 걸리면 성공으로 기록되지 않음
- 큐에 100건이 쌓여도 목록이 느려지지 않고 필터로 찾을 수 있음
