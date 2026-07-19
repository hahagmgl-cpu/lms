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
const { generateText } = require('./lib/llm');
const { normalizeImages } = require('./lib/imagemeta');
const cfg = require('./lib/config');

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

// JSON 대신 구분자(@@@섹션@@@) 형식을 쓴다.
// 본문 HTML에 큰따옴표·줄바꿈이 아무리 많아도 파싱이 깨지지 않는다(이스케이프 불필요).
function buildPrompt(keyword, { imgs, audience, intent }) {
  const imageRule =
    imgs > 0
      ? `- 본문 중 자연스러운 위치 ${imgs}곳에 {{IMAGE_0}}${imgs > 1 ? ` ~ {{IMAGE_${imgs - 1}}}` : ''} 토큰을 <p> 단독 문단으로 배치하세요.
- @@@IMAGES@@@ 섹션에 이미지 정보를 ${imgs}줄 작성하세요. 각 줄은 아래 형식(구분자 ' ||| '):
  영문프롬프트 ||| 한국어alt ||| 한국어캡션 ||| SEO파일명.webp
  (영문프롬프트=사진풍·텍스트없는 이미지 묘사 / alt=키워드 포함 대체텍스트 / caption=도움되는 한 문장 / 파일명=공백대신_ .webp)`
      : `- 이미지는 사용하지 않습니다. @@@IMAGES@@@ 섹션은 비워두세요.`;

  return `당신은 한국어 SEO 블로그 전문 작가입니다. 아래 키워드로 티스토리 블로그 글을 작성하세요.

키워드: "${keyword}"${audience ? `\n타깃 독자: ${audience}` : ''}${intent ? `\n검색 니즈: ${intent}` : ''}

작성 원칙 (SEO + 검색 니즈):
1. 이 키워드를 검색하는 사람의 의도(정보탐색/비교/구매/문제해결)를 파악하고, 그 니즈에 정면으로 답하세요.
2. 제목: 45자 이내, 핵심 키워드를 앞쪽에, 숫자·연도·혜택 등 클릭 유도 요소 포함.
3. 도입부(첫 문단): 검색자가 원하는 답을 2~3문장으로 즉시 요약(스니펫 대비).
4. 본문: <h2> 소제목 3~5개, 필요 시 <h3>. 소제목에도 연관 키워드 포함.
5. 가독성: 문단 2~4문장, 목록(<ul>/<ol>)·표(<table>) 활용.
6. 글 끝에 <h2>자주 묻는 질문</h2> + Q&A 3개(질문 <h3>, 답변 <p>).
7. 분량: 본문 2,000자 이상(한글 기준).
8. 키워드 자연스럽게 5~8회 배치, 동의어·연관어 함께.
9. 과장·허위 금지, 실용적·구체적으로.
${imageRule}

[출력 형식 - 반드시 이대로. 각 @@@...@@@ 표시는 반드시 줄 맨 앞에 단독으로]
@@@TITLE@@@
(SEO 제목)
@@@META@@@
(150자 내외 메타 설명)
@@@INTENT@@@
(파악한 검색 의도 한 문장)
@@@TAGS@@@
(태그5개, 쉼표로 구분)
@@@HTML@@@
(본문 HTML 전체 - 큰따옴표·줄바꿈 자유롭게 사용 가능. 여기에는 이스케이프가 전혀 필요 없습니다)
@@@IMAGES@@@
${imgs > 0 ? '(위 형식대로 ' + imgs + '줄)' : '(비움)'}
@@@END@@@

위 형식 외의 다른 텍스트(코드펜스, 설명)는 절대 출력하지 마세요.`;
}

// @@@섹션@@@ 형식 파싱 → 글 객체. HTML은 원문 그대로 보존.
function parseArticleSections(text, keyword) {
  const marker = /^@@@([A-Z]+)@@@[ \t]*$/gm;
  const sections = {};
  const hits = [];
  let m;
  while ((m = marker.exec(text)) !== null) hits.push({ name: m[1], start: m.index, end: marker.lastIndex });
  if (!hits.length) throw new Error('구분자(@@@) 형식을 찾지 못했습니다: ' + text.slice(0, 200));
  for (let i = 0; i < hits.length; i++) {
    const name = hits[i].name;
    if (name === 'END') continue;
    const contentStart = hits[i].end;
    const contentEnd = i + 1 < hits.length ? hits[i + 1].start : text.length;
    sections[name] = text.slice(contentStart, contentEnd).replace(/^\s*\n/, '').replace(/\s+$/, '');
  }
  const title = (sections.TITLE || '').trim();
  const html = (sections.HTML || '').trim();
  if (!title || !html) throw new Error('TITLE/HTML 섹션이 비었습니다.');

  const tags = (sections.TAGS || '').split(/[,\n]/).map((t) => t.trim()).filter(Boolean);
  const images = (sections.IMAGES || '')
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l && l.includes('|||'))
    .map((l) => {
      const [prompt, alt, caption, filename] = l.split('|||').map((s) => s.trim());
      return { prompt, alt, caption, filename };
    });

  return {
    keyword,
    title,
    metaDescription: (sections.META || '').trim(),
    searchIntent: (sections.INTENT || '').trim(),
    html,
    tags,
    images,
  };
}

// 키워드 → SEO 글 객체 생성 (GUI/파이프라인에서 재사용)
// 공급자·모델·이미지수·타깃·니즈는 설정(config)을 기본값으로, opts 로 언제든 덮어씀
async function generateArticle(keyword, opts = {}) {
  if (!keyword) throw new Error('키워드가 필요합니다.');
  const c = cfg.load();
  const provider = opts.provider || c.text.provider;
  const imgs = opts.imgs !== undefined ? Number(opts.imgs) : (c.image.count ?? 1);
  const audience = opts.audience || c.seo.audience || undefined;
  const intent = opts.intent || c.seo.intent || undefined;
  const prompt = buildPrompt(keyword, { imgs, audience, intent });
  const post = await generateText(
    prompt,
    provider,
    { model: cfg.textModel(c, provider), temperature: c.text.temperature, maxTokens: c.text.maxTokens },
    (text) => parseArticleSections(text, keyword)
  );
  // alt/caption/filename 을 생성 시점에 확정·정규화 (이후 발행 치환에 그대로 사용됨)
  post.images = normalizeImages(post.images, { title: post.title, keyword });
  return post;
}

if (require.main === module) {
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
    const post = await generateArticle(keyword, {
      imgs,
      audience: args.audience,
      intent: args.intent,
      provider: args.provider,
    });

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
}

module.exports = { generateArticle, buildPrompt, parseArticleSections };
