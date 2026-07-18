// 키워드 → SEO 최적화 블로그 글 생성 (GPT / Gemini / Claude 선택 가능)
//
// 사용법:
//   node automation/generate.js "키워드"
//   node automation/generate.js "키워드" --provider gemini
//   node automation/generate.js "키워드" --provider openai --out content/생성글.json --imgs 2
//
// 옵션:
//   --provider openai|gemini|claude   (생략 시 .env 의 GEN_PROVIDER, 그것도 없으면 키가 있는 것 자동 선택)
//   --out <파일>                      출력 JSON 경로 (기본: content/generated.json)
//   --imgs <N>                        본문에 배치할 이미지 슬롯 수 (기본 1, 0이면 이미지 없음)
//   --audience "..."                  타깃 독자 (예: "30대 직장인")
//   --intent "..."                    검색 니즈 보강 설명 (예: "가격 비교를 원함")
//
// 출력 JSON은 post.js 로 바로 발행 가능:
//   node automation/post.js --file content/generated.json --publish reserve --at "2026-07-20T09:00"
// (images 항목의 "file"은 이미지 생성/준비 후 채워 넣으면 함께 업로드됩니다)

const fs = require('fs');
const path = require('path');
const { loadEnv } = require('./lib/env');
const { generateJson } = require('./lib/llm');

loadEnv();

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 2; i < argv.length; i++) {
    if (argv[i].startsWith('--')) {
      const key = argv[i].slice(2);
      const val = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[++i] : true;
      args[key] = val;
    } else {
      args._.push(argv[i]);
    }
  }
  return args;
}

function buildPrompt(keyword, { imgs, audience, intent }) {
  const imageSection =
    imgs > 0
      ? `
- 본문 중 자연스러운 위치 ${imgs}곳에 {{IMAGE_0}}${imgs > 1 ? ` ~ {{IMAGE_${imgs - 1}}}` : ''} 토큰을 <p> 단독 문단으로 배치
- "images" 배열에 각 토큰에 대응하는 이미지 정보를 ${imgs}개 작성:
  - "prompt": 이미지 생성 AI에 줄 영문 프롬프트 (사진풍, 텍스트 없는 이미지)
  - "alt": 한국어 대체텍스트 (키워드 포함, 이미지 내용 묘사)
  - "caption": 한국어 캡션 (독자에게 도움되는 한 문장)
  - "filename": SEO용 한국어 파일명 (공백 대신 _, 확장자 .webp)`
      : `
- 이미지는 사용하지 않음. "images"는 빈 배열로.`;

  return `당신은 한국어 SEO 블로그 전문 작가입니다. 아래 키워드로 티스토리 블로그 글을 작성하세요.

키워드: "${keyword}"${audience ? `\n타깃 독자: ${audience}` : ''}${intent ? `\n검색 니즈: ${intent}` : ''}

작성 원칙 (SEO + 검색 니즈):
1. 먼저 이 키워드를 검색하는 사람의 의도(정보탐색/비교/구매/문제해결)를 파악하고, 그 니즈에 정면으로 답하는 글을 쓸 것
2. 제목: 45자 이내, 핵심 키워드를 앞쪽에 배치, 숫자·연도·혜택 등 클릭 유도 요소 포함
3. 도입부(첫 문단): 검색자가 원하는 답을 2~3문장으로 즉시 요약 (검색엔진 스니펫 노출 대비)
4. 본문 구조: <h2> 소제목 3~5개, 필요 시 <h3> 하위 소제목. 소제목에도 연관 키워드를 자연스럽게 포함
5. 가독성: 문단은 2~4문장, 목록(<ul>/<ol>)과 표(<table>)를 적극 활용
6. 글 마지막에 <h2>자주 묻는 질문</h2> 섹션으로 Q&A 3개 (질문은 <h3>, 답변은 <p>)
7. 분량: 본문 2,000자 이상 (한글 기준)
8. 키워드를 본문에 자연스럽게 5~8회 배치 (억지 반복 금지), 동의어·연관어 함께 사용
9. 과장·허위 정보 금지, 실용적이고 구체적인 정보 위주${imageSection}

아래 JSON 형식으로만 응답하세요 (코드펜스 없이, 다른 텍스트 없이):
{
  "keyword": "${keyword}",
  "searchIntent": "파악한 검색 의도 한 문장",
  "title": "SEO 제목",
  "metaDescription": "150자 내외 메타 설명",
  "html": "<p>도입부...</p><h2>...</h2>...",
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
  "images": []
}`;
}

(async () => {
  const args = parseArgs(process.argv);
  const keyword = args._[0];
  if (!keyword) {
    console.error('사용법: node automation/generate.js "키워드" [--provider openai|gemini|claude] [--out 파일] [--imgs N]');
    process.exit(1);
  }
  const outFile = args.out || args._[1] || path.join(__dirname, '..', 'content', 'generated.json');
  const imgs = args.imgs !== undefined ? Number(args.imgs) : 1;

  console.log(`키워드: ${keyword}`);
  const prompt = buildPrompt(keyword, { imgs, audience: args.audience, intent: args.intent });
  const post = await generateJson(prompt, args.provider);

  // post.js 가 바로 쓸 수 있는지 최소 검증
  if (!post.title || !post.html) {
    throw new Error('생성 결과에 title/html 이 없습니다:\n' + JSON.stringify(post).slice(0, 500));
  }

  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  fs.writeFileSync(outFile, JSON.stringify(post, null, 2), 'utf8');

  console.log(`\n생성 완료 → ${outFile}`);
  console.log(`검색 의도: ${post.searchIntent || '-'}`);
  console.log(`제목: ${post.title}`);
  console.log(`메타 설명: ${post.metaDescription || '-'}`);
  console.log(`태그: ${(post.tags || []).join(', ')}`);
  console.log(`본문 길이: ${post.html.length}자, 이미지 슬롯: ${(post.images || []).length}개`);
  if ((post.images || []).length) {
    console.log('\n이미지 정보 (file 경로를 채우면 발행 시 함께 업로드됩니다):');
    post.images.forEach((im, i) => console.log(`  [${i}] alt="${im.alt}" filename="${im.filename}"`));
  }
  console.log(`\n발행: node automation/post.js --file ${outFile} --publish reserve`);
})().catch((e) => {
  console.error('ERROR:', e.message);
  process.exit(1);
});
