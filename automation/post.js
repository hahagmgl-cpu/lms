// 티스토리 글 작성 + 발행 CLI
//
// 사용법:
//   node automation/post.js --file content/sample-post.json                  # JSON 파일로 작성, 임시저장
//   node automation/post.js --file content/sample-post.json --publish now    # 즉시 발행
//   node automation/post.js --file content/sample-post.json --publish reserve --at "2026-07-18T09:00"
//   node automation/post.js --title "제목" --content "<p>본문</p>" --publish now
//
// JSON 파일 형식: { "title": "...", "html": "<p>...</p>", "tags": ["태그1", "태그2"] }
// (Claude API 등으로 생성한 콘텐츠를 이 형식으로 저장하면 그대로 발행 가능)

const fs = require('fs');
const { loadEnv } = require('./lib/env');
const { launch, isLoggedIn, login, saveState, writePost } = require('./lib/tistory');

loadEnv();

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i++) {
    if (argv[i].startsWith('--')) {
      const key = argv[i].slice(2);
      const val = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[++i] : true;
      args[key] = val;
    }
  }
  return args;
}

(async () => {
  const args = parseArgs(process.argv);
  const blog = args.blog || process.env.TISTORY_BLOG;
  if (!blog) {
    console.error('블로그 서브도메인을 지정하세요: --blog record7518 또는 .env 의 TISTORY_BLOG');
    process.exit(1);
  }

  let title = args.title;
  let contentHtml = args.content;
  let tags = args.tags ? String(args.tags).split(',').map((t) => t.trim()) : [];

  if (args.file) {
    const data = JSON.parse(fs.readFileSync(args.file, 'utf8'));
    title = title || data.title;
    contentHtml = contentHtml || data.html || data.content;
    if (data.tags && !tags.length) tags = data.tags;
  }
  if (!title || !contentHtml) {
    console.error('제목과 본문이 필요합니다: --title/--content 또는 --file <json>');
    process.exit(1);
  }

  const publish = args.publish || 'draft'; // draft | now | reserve
  let reserveAt = null;
  if (publish === 'reserve') {
    // --at 미지정 시 기본: 1시간 뒤 정시
    if (args.at) {
      reserveAt = new Date(args.at);
    } else {
      reserveAt = new Date(Date.now() + 60 * 60 * 1000);
      reserveAt.setMinutes(0, 0, 0);
      reserveAt.setHours(reserveAt.getHours() + 1);
    }
    console.log('예약발행 시각:', reserveAt.toString());
  }

  const { browser, context } = await launch();
  const page = await context.newPage();
  try {
    if (!(await isLoggedIn(page, blog))) {
      console.log('세션이 없거나 만료됨 → 로그인 시도');
      const id = process.env.TISTORY_ID;
      const pw = process.env.TISTORY_PW;
      if (!id || !pw) throw new Error('로그인이 필요한데 TISTORY_ID / TISTORY_PW 가 없습니다.');
      await login(page, id, pw);
      await saveState(context);
    }

    const result = await writePost(page, { blog, title, contentHtml, tags, publish, reserveAt });
    console.log('\n완료:', JSON.stringify(result, null, 2));
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error('ERROR:', e.message);
  process.exit(1);
});
