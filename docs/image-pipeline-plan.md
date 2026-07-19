# 이미지 파이프라인 계획 (생성 → 업로드 → alt/캡션/파일명 매칭)

## 1. 티스토리 이미지 치환문 구조

이미지를 에디터에 업로드하면 카카오 CDN(kage)에 저장되고, 본문(HTML 모드)에는 아래 치환문이 들어간다:

```
[##_Image|kage@{경로}/img.png?credential=...&expires=...&signature=...|CDM|1.3|{옵션JSON}_##]
```

- `kage@...` : 카카오 CDN 경로 + 서명된 접근 파라미터 (업로드 시 서버가 발급, 직접 만들 수 없음)
- `CDM|1.3` : 에디터 콘텐츠 모듈 버전
- `{옵션JSON}` : 표시 옵션. 여기에 메타데이터를 넣는다:

| 키 | 의미 | 예시 |
|---|---|---|
| `originWidth`/`originHeight` | 원본 크기 (업로드 시 자동) | `1024`, `510` |
| `style` | 정렬 | `"alignCenter"` |
| `alt` | 대체텍스트 (SEO/접근성) | `"다음 내카페 바로가기 안내 이미지"` |
| `caption` | 캡션 (이미지 아래 표시) | `"...간편하게 확인하세요."` |
| `filename` | 파일명 (SEO에 영향) | `"다음내카페바로가기_썸네일.webp"` |

**핵심**: `kage@` 경로는 반드시 실제 업로드를 거쳐야 발급되므로, 자동화 순서는
"업로드 먼저 → 발급된 치환문 회수 → 옵션 JSON에 메타 주입 → 본문에 배치"가 된다.

## 2. 현재 구현된 흐름 (automation/lib/tistory.js)

1. **기본모드**에서 이미지 파일 업로드 (파일 인풋 주입 또는 사진 버튼 → 파일 선택)
2. **HTML 모드**로 전환 → CodeMirror에서 `[##_Image|...]` 치환문 추출 (업로드 순서 = 배열 순서)
3. 각 치환문의 옵션 JSON에 `alt` / `caption` / `filename` 주입
   (filename 미지정 시 실제 파일명 사용)
4. 본문 HTML의 `{{IMAGE_0}}`, `{{IMAGE_1}}` … 토큰 위치에 배치, 토큰이 없으면 본문 끝에 추가
5. 완성된 HTML을 CodeMirror에 setValue → 발행

글 데이터 JSON 예시 (`content/sample-post-with-image.json` 참고):

```json
{
  "title": "제목",
  "html": "<p>서두</p><p>{{IMAGE_0}}</p><p>본문...</p>",
  "tags": ["태그"],
  "images": [
    { "file": "images/썸네일.webp", "alt": "대체텍스트", "caption": "캡션", "filename": "SEO용_파일명.webp" }
  ]
}
```

## 3. 이미지 "생성" 단계 계획 (저렴한 생성 API 비교)

목표: 글 주제에 맞는 이미지를 저렴하게 생성 → `content/images/`에 저장 → 위 파이프라인으로 업로드.

| 서비스 | 모델 | 대략 비용/장 | 비고 |
|---|---|---|---|
| **Pollinations.ai** | FLUX 계열 | **무료** | API 키 불필요, URL로 바로 생성. 품질/안정성은 유료 대비 낮음. 테스트용 최적 |
| **Together AI** | FLUX.1 schnell | ~$0.003 | 매우 저렴, 빠름. 블로그용 실사용 추천 |
| **Fal.ai** | FLUX.1 schnell | ~$0.003 | 위와 유사, 응답 빠름 |
| **Replicate** | FLUX schnell / SDXL | ~$0.003~0.01 | 종량제, 모델 선택 폭 넓음 |
| **OpenAI** | gpt-image-1 (low) | ~$0.01~0.02 | 텍스트 렌더링 강함 |
| **Google** | Gemini 2.5 Flash Image | ~$0.04 | 편집/합성 강함 |

권장: **1차 테스트는 Pollinations(무료)** → 품질이 아쉬우면 **Together/Fal의 FLUX schnell(장당 0.3~0.4원 수준)**로 전환.

한글이 들어간 썸네일이 필요하면 생성 이미지 위에 로컬에서 텍스트를 합성하는 방식(sharp 라이브러리)이 생성 모델에 한글을 그리게 하는 것보다 안정적.

## 4. 전체 자동화 파이프라인 (최종 목표)

```
[주제 목록]
   │
   ▼
generate.js ──▶ Claude API: 제목/본문 HTML/태그 + 이미지 프롬프트/alt/캡션/파일명 생성
   │                (본문에는 {{IMAGE_n}} 토큰 포함)
   ▼
gen-image.js ──▶ 이미지 생성 API 호출 → content/images/ 저장 (webp 변환 권장)
   │
   ▼
post.js ──▶ 티스토리 업로드 + 치환문 메타 주입 + 예약발행
   │
   ▼
스케줄러(cron/작업 스케줄러) ──▶ 매일 N건 자동 실행
```

다음 구현 단계:

- [ ] `generate.js` 확장: 응답 JSON에 `images: [{prompt, alt, caption, filename}]` 포함
- [ ] `gen-image.js` 신규: prompt → 이미지 생성 API → 파일 저장 (Pollinations 무료판 먼저)
- [ ] webp 변환 + 파일명을 한글 키워드로 지정 (SEO)
- [ ] 대표이미지(썸네일) 지정 자동화 — 발행 레이어의 "대표이미지 추가"에 첫 이미지 지정
- [ ] 실패 시 재시도 / 발행 결과 로그 저장 (성공 URL 목록)
