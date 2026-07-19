# 티스토리 블로그 자동 발행 (Tistory Auto-Posting)

Playwright 브라우저 자동화로 [티스토리](https://www.tistory.com/)에 로그인하고 글을 작성·발행(즉시/예약)하는 도구입니다.

> 티스토리 공식 Open API는 **2024년 2월에 종료**되었습니다. 그래서 브라우저 자동화가 사실상 유일한 프로그래밍 방식의 발행 수단입니다.

## 핵심 설계: 생산과 발행을 분리

```
①  생산(produce)              ②  발행(publish)
키워드 → 글·이미지 생성   →   큐에 저장   →   원할 때 개별/일괄 발행 (예약 가능)
                               (폴더 + 엑셀 인덱스)
```

- **생산**은 미리 여러 건을 만들어 큐(`content/queue/`)에 쌓아두고, **발행**은 나중에 따로 클릭(개별/일괄).
- 큐는 글 1건 = 폴더 1개(`post.json` + `images/`)가 **원본**, 전체 목록은 **엑셀/CSV 인덱스**로 한눈에 보고 편집(제목·태그·상태·예약시각을 엑셀에서 고쳐 되돌릴 수 있음).
- **모델은 언제든 교체** — 모든 공급자·모델명이 `config/defaults.json` 한 곳에. `config/config.json`(또는 GUI 설정 탭)으로 코드 수정 없이 덮어씀. API가 바뀌어도 이 파일만 고치면 됩니다.

## 구성

```
config/
  defaults.json   # 기본 모델·공급자 설정 (내가 정한 기본값)
  config.json     # 사용자 오버라이드 (gitignore, GUI 설정 탭이 여기 저장)
automation/
  server.js         # 웹 GUI (생산 / 큐·발행 / 설정 탭)
  produce.js        # ① 생산: 키워드 → 글·이미지 → 큐 저장 (발행 안 함)
  publish-queue.js  # ② 발행: 큐의 글을 티스토리에 발행 (개별/일괄/예약)
  auto.js           # 한 방 파이프라인 (생산+즉시발행을 한 번에)
  login.js          # 카카오 로그인 → 세션(state.json) 저장
  generate.js       # 키워드 → SEO 글 생성 (GPT/제미나이/Claude)
  gen-image.js      # 이미지 프롬프트 → 이미지 생성 (Pollinations 무료 등)
  post.js           # 단일 글 발행 CLI (임시저장/즉시/예약)
  lib/config.js     # 설정 로더 (defaults + override 병합)
  lib/store.js      # 큐 저장소 (폴더 원본 + 엑셀/CSV 인덱스)
  lib/tistory.js    # 로그인·글쓰기·이미지업로드 (셀렉터 폴백)
  lib/llm.js        # GPT/제미나이/Claude 공통 래퍼 (모델 교체 지원)
  lib/image-gen.js  # 이미지 생성 공급자 래퍼
  lib/env.js        # .env 로더
content/queue/      # 생산된 콘텐츠 큐 (git 제외)
docs/
  image-pipeline-plan.md
```

## 설치

```bash
npm install
npx playwright install chromium   # 로컬 PC에서 최초 1회
```

`.env.example` 을 복사해 `.env` 를 만들고 계정 정보를 채웁니다. **`.env` 와 `state.json` 은 절대 git에 커밋하지 마세요** (`.gitignore` 에 이미 등록됨).

```bash
cp .env.example .env
```

## 가장 쉬운 방법: 웹 GUI

```bash
node automation/login.js     # 최초 1회 로그인 (아래 참고)
node automation/server.js    # GUI 실행 → http://localhost:3000
```

3개 탭으로 구성:
- **① 생산** — 키워드(여러 개면 줄바꿈으로 일괄) 입력 → 글·이미지를 만들어 큐에 저장. 발행은 안 함.
- **② 큐·발행** — 큐 목록을 보고 개별/일괄 발행(예약 가능). 엑셀 다운로드/편집 반영 버튼 제공.
- **⚙ 설정** — 공급자·모델·이미지 크기 등을 바꿔 저장(코드 수정 불필요).

상단 배지로 API 키·로그인 세션·블로그 상태가 한눈에 보이고, 진행 상황이 실시간 로그로 표시됩니다.

## CLI로 생산 → 발행 (분리 워크플로)

```bash
# ① 생산: 여러 키워드를 미리 만들어 큐에 저장 (발행 안 함)
node automation/produce.js "제주도 겨울 여행" "2026 노트북 추천" "홈트 초보 루틴"
node automation/produce.js --file keywords.txt           # 파일에서 일괄 (한 줄 = 한 키워드)

# 큐 확인 / 엑셀 편집 반영
node automation/publish-queue.js --list
node automation/publish-queue.js --sync                  # 엑셀·CSV로 고친 제목/태그/상태/예약을 반영

# ② 발행: 원할 때 따로 (개별 또는 전체, 예약 가능)
node automation/publish-queue.js --id 20260720-093000-제주도-겨울-여행 --publish reserve --at "2026-07-21T09:00"
node automation/publish-queue.js --all --publish reserve --at "2026-07-21T09:00"
```

생산물은 `content/queue/<id>/`(post.json + images/)에 저장되고, 전체 목록은 `content/queue/index.xlsx`(+`.csv`)로 관리됩니다. 엑셀에서 `status`를 `ready`로, `scheduleAt`에 시각을 넣고 `--sync` 하면 그대로 반영됩니다.

## 모델 교체 (config)

`config/defaults.json` 에 기본값이 있고, 바꾸려면 `config/config.json` 을 만들어 같은 키만 덮어쓰거나 GUI 설정 탭을 쓰면 됩니다. 예:

```json
{ "text": { "provider": "openai", "models": { "openai": "gpt-4o" } },
  "image": { "provider": "together" } }
```

API 키는 `config` 가 아니라 `.env` 에 둡니다. 모델명은 env(`OPENAI_MODEL` 등)로도 덮어쓸 수 있습니다.

## 한 방 실행: 파이프라인 CLI

키워드 하나로 글 생성 → 이미지 생성 → 발행까지:

```bash
# 임시저장으로 안전하게 테스트 (이미지 1장, 무료 Pollinations)
node automation/auto.js "제주도 겨울 여행 코스"

# 예약발행 + 이미지 2장 + 공급자 지정
node automation/auto.js "노트북 추천" --provider gemini --img-provider pollinations \
  --imgs 2 --publish reserve --at "2026-07-20T09:00"

# 이미지 없이 글만
node automation/auto.js "키워드" --no-images --publish draft
```

## 단계별 사용법

### 1. 로그인 (최초 1회, 세션 저장)

```bash
node automation/login.js
```

카카오 2단계 인증(카카오톡 확인)이나 캡차가 걸리면 브라우저 창을 띄워 직접 통과:

```bash
HEADLESS=0 node automation/login.js
```

성공하면 `automation/state.json` 에 세션이 저장되어 이후에는 재로그인 없이 발행됩니다.

### 2. 테스트 글 발행

```bash
# 임시저장 (안전한 첫 테스트)
node automation/post.js --file content/sample-post.json

# 즉시 발행
node automation/post.js --file content/sample-post.json --publish now

# 예약 발행 (지정 시각)
node automation/post.js --file content/sample-post.json --publish reserve --at "2026-07-18T09:00"

# 예약 발행 (시각 생략 시 1시간 뒤 정시)
node automation/post.js --file content/sample-post.json --publish reserve
```

각 단계의 스크린샷이 `shots/` 에 저장되므로, 셀렉터가 안 맞아 실패하면 스크린샷으로 어느 단계에서 멈췄는지 확인할 수 있습니다.

### 3. 이미지 포함 발행 (alt/캡션/파일명 자동 주입)

```bash
node automation/post.js --file content/sample-post-with-image.json --publish reserve
```

본문의 `{{IMAGE_0}}` 토큰 위치에 업로드된 이미지가 들어가고, 치환문 `[##_Image|kage@...|CDM|1.3|{...}_##]` 의 옵션 JSON에 `alt`/`caption`/`filename` 이 자동으로 주입됩니다. 자세한 구조와 이미지 생성 계획은 [docs/image-pipeline-plan.md](docs/image-pipeline-plan.md) 참고.

> 본문 입력은 **HTML 모드(CodeMirror)** 로 전환해서 넣습니다. TinyMCE API 방식은 화면에는 보여도 저장 시 본문이 비는 문제가 있어 사용하지 않습니다.

### 4. 키워드 → SEO 글 자동 생성 (GPT / 제미나이 / Claude)

키워드를 주면 검색의도 분석 → SEO 제목/메타설명 → h2/h3 구조 본문(2,000자+) → FAQ → 태그 → 이미지 프롬프트(alt/캡션/파일명)까지 생성합니다. `.env` 에 사용할 API 키를 넣으면 됩니다 (`OPENAI_API_KEY` / `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` 중 하나 이상).

```bash
# 키가 있는 공급자 자동 선택
node automation/generate.js "제주도 겨울 여행 코스"

# 공급자 지정 + 이미지 슬롯 2개 + 타깃/니즈 지정
node automation/generate.js "제주도 겨울 여행 코스" --provider gemini --imgs 2 \
  --audience "아이 동반 가족" --intent "일정표와 예상 경비를 알고 싶어함"

# 생성된 글 예약발행
node automation/post.js --file content/generated.json --publish reserve --at "2026-07-20T09:00"
```

생성 JSON의 `images` 배열에는 이미지 생성용 `prompt`와 `alt`/`caption`/`filename`이 들어 있습니다. 이미지를 만들어 `file` 경로를 채우면 발행 시 자동 업로드되고, 채우지 않으면 해당 이미지는 건너뛰고 글만 발행됩니다.

글 데이터 JSON 형식:

```json
{
  "title": "제목",
  "html": "<p>본문 HTML</p><p>{{IMAGE_0}}</p>",
  "tags": ["태그1", "태그2"],
  "images": [{ "file": "images/a.webp", "alt": "...", "caption": "...", "filename": "..." }]
}
```

### 5. 이미지 자동 생성 (Pollinations 무료 / Together / OpenAI)

생성된 글 JSON의 `images[].prompt` 로 이미지를 만들어 `file` 경로를 자동으로 채웁니다.

```bash
# 무료 Pollinations (API 키 불필요)
node automation/gen-image.js content/generated.json

# 공급자·크기 지정
node automation/gen-image.js content/generated.json --provider together --width 1024 --height 576

# 이미지까지 채운 뒤 발행
node automation/post.js --file content/generated.json --publish reserve
```

이미지는 글 JSON 옆의 `content/images/` 에 저장되고, 파일명은 `filename`(한국어 SEO용) 기준으로 만들어집니다. 비용/공급자 비교는 [docs/image-pipeline-plan.md](docs/image-pipeline-plan.md) 참고. (`auto.js` 나 GUI를 쓰면 이 단계가 자동으로 포함됩니다.)

## 주의사항

- **계정 정보 보안**: 비밀번호는 `.env` 에만 두고, 채팅·코드·커밋에 남기지 마세요. 이미 외부에 노출된 비밀번호라면 변경을 권장합니다.
- **카카오 로그인 보안**: 새로운 기기/IP에서 자동 로그인하면 카카오가 2단계 인증을 요구할 수 있습니다. 최초 1회는 `HEADLESS=0` 으로 직접 인증하고, 이후 저장된 세션을 재사용하는 방식을 권장합니다.
- **에디터 셀렉터**: 티스토리가 에디터 UI를 변경하면 `automation/lib/tistory.js` 의 셀렉터를 갱신해야 합니다. 주요 지점마다 폴백 셀렉터와 스크린샷이 있어 디버깅이 쉽습니다.

## 로드맵 (다음 단계)

- [ ] 실환경(로컬 PC 또는 네트워크 허용 환경)에서 로그인·예약발행 라이브 테스트
- [ ] Claude API 생성 콘텐츠 파이프라인 정착 (주제 목록 → 일괄 예약발행)
- [ ] 이미지 자동 삽입 (이미지 생성 API 또는 무료 스톡 이미지 API에서 가져와 에디터에 업로드)
- [ ] 스케줄러 (cron) 로 매일 자동 생성·예약발행
