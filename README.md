# 티스토리 블로그 자동 발행 (Tistory Auto-Posting)

Playwright 브라우저 자동화로 [티스토리](https://www.tistory.com/)에 로그인하고 글을 작성·발행(즉시/예약)하는 도구입니다.

> 티스토리 공식 Open API는 **2024년 2월에 종료**되었습니다. 그래서 브라우저 자동화가 사실상 유일한 프로그래밍 방식의 발행 수단입니다.

## 구성

```
automation/
  login.js        # 카카오 계정 로그인 → 세션(state.json) 저장
  post.js         # 글 작성 + 임시저장/즉시발행/예약발행 CLI
  generate.js     # Claude API로 제목/본문/태그 자동 생성
  lib/tistory.js  # 로그인·글쓰기 공용 로직 (셀렉터 폴백 포함)
  lib/env.js      # .env 로더
content/
  sample-post.json  # 테스트 글 데이터
shots/              # 실행 중 단계별 스크린샷 (디버깅용, git 제외)
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

## 사용법

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

## 주의사항

- **계정 정보 보안**: 비밀번호는 `.env` 에만 두고, 채팅·코드·커밋에 남기지 마세요. 이미 외부에 노출된 비밀번호라면 변경을 권장합니다.
- **카카오 로그인 보안**: 새로운 기기/IP에서 자동 로그인하면 카카오가 2단계 인증을 요구할 수 있습니다. 최초 1회는 `HEADLESS=0` 으로 직접 인증하고, 이후 저장된 세션을 재사용하는 방식을 권장합니다.
- **에디터 셀렉터**: 티스토리가 에디터 UI를 변경하면 `automation/lib/tistory.js` 의 셀렉터를 갱신해야 합니다. 주요 지점마다 폴백 셀렉터와 스크린샷이 있어 디버깅이 쉽습니다.

## 로드맵 (다음 단계)

- [ ] 실환경(로컬 PC 또는 네트워크 허용 환경)에서 로그인·예약발행 라이브 테스트
- [ ] Claude API 생성 콘텐츠 파이프라인 정착 (주제 목록 → 일괄 예약발행)
- [ ] 이미지 자동 삽입 (이미지 생성 API 또는 무료 스톡 이미지 API에서 가져와 에디터에 업로드)
- [ ] 스케줄러 (cron) 로 매일 자동 생성·예약발행
