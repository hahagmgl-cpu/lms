// 티스토리 글 작성 + 발행 CLI
//
// 사용법:
//   node automation/post.js --file content/sample-post.json                  # JSON 파일로 작성, 임시저장
//   node automation/post.js --file content/sample-post.json --publish now    # 즉시 발행
//   node automation/post.js --file content/sample-post.json --publish reserve --at "2026-07-18T09:00"
//   node automation/post.js --title "제목" --content "<p>본문</p>" --publish now
//
// JSON 파일 형식:
// {
//   "title": "...",
//   "html": "<p>본문</p><p>{{IMAGE_0}}</p>",          // {{IMAGE_n}} 자리에 n번째 이미지 배치
//   "tags": ["태그1", "태그2"],
//   "images": [{ "file": "images/a.png", "alt": "대체텍스트", "caption": "캡션" }]
// }
// (Claude API 등으로 생성한 콘텐츠를 이 형식으로 저장하면 그대로 발행 가능)

const fs = require('fs');
const path = require('path');
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

// 예약 시각 계산: 값이 있으면 파싱, 없으면 다음다음 정시(약 1시간 뒤)
function resolveReserveAt(at) {
  if (at) {
    const d = new Date(at);
    if (isNaN(d.getTime())) throw new Error(`예약 시각이 올바르지 않습니다: ${at}`);
    return d;
  }
  const d = new Date(Date.now() + 60 * 60 * 1000);
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + 1);
  return d;
}

// 파일 없는 이미지 제거 + 본문에 남은 미사용 {{IMAGE_n}} 토큰 정리
function prepareImages(contentHtml, images, baseDir) {
  const prepared = (images || [])
    .filter((img) => {
      if (!img.file) {
        console.log(`[안내] 이미지 파일 미지정 → 건너뜀 (alt: "${img.alt || '-'}")`);
        return false;
      }
      return true;
    })
    .map((img) => ({
      ...img,
      file: path.isAbsolute(img.file) ? img.file : path.join(baseDir || process.cwd(), img.file),
    }));
  for (const img of prepared) {
    if (!fs.existsSync(img.file)) throw new Error(`이미지 파일이 없습니다: ${img.file}`);
  }
  let html = contentHtml;
  if (html) {
    html = html.replace(/<p>\s*\{\{IMAGE_(\d+)\}\}\s*<\/p>/g, (m, n) =>
      Number(n) < prepared.length ? m : ''
    );
  }
  return { html, images: prepared };
}

/**
 * 구조화된 옵션으로 글 발행 (GUI/파이프라인 공용)
 * @param {object} o { blog, title, contentHtml, tags, images, publish, reserveAt, baseDir }
 */
async function publishPost(o) {
  const blog = o.blog || process.env.TISTORY_BLOG;
  if (!blog) throw new Error('블로그 서브도메인이 필요합니다 (blog 또는 .env TISTORY_BLOG).');
  if (!o.title || !o.contentHtml) throw new Error('제목과 본문이 필요합니다.');

  const { html, images } = prepareImages(o.contentHtml, o.images, o.baseDir);
  const publish = o.publish || 'draft';
  const reserveAt = publish === 'reserve' ? resolveReserveAt(o.reserveAt) : null;
  if (reserveAt) console.log('예약발행 시각:', reserveAt.toString());

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
    return await writePost(page, {
      blog,
      title: o.title,
      contentHtml: html,
      tags: o.tags || [],
      publish,
      reserveAt,
      images,
    });
  } finally {
    await browser.close();
  }
}

async function cliMain() {
  const args = parseArgs(process.argv);
  const blog = args.blog || process.env.TISTORY_BLOG;
  if (!blog) {
    console.error('블로그 서브도메인을 지정하세요: --blog record7518 또는 .env 의 TISTORY_BLOG');
    process.exit(1);
  }

  let title = args.title;
  let contentHtml = args.content;
  let tags = args.tags ? String(args.tags).split(',').map((t) => t.trim()) : [];
  let images = args.images
    ? String(args.images).split(',').map((f) => ({ file: f.trim() }))
    : [];
  let baseDir = process.cwd();

  if (args.file) {
    const data = JSON.parse(fs.readFileSync(args.file, 'utf8'));
    title = title || data.title;
    contentHtml = contentHtml || data.html || data.content;
    if (data.tags && !tags.length) tags = data.tags;
    if (data.images && !images.length) images = data.images;
    baseDir = path.dirname(path.resolve(args.file)); // JSON 위치 기준 상대경로 허용
  }
  if (!title || !contentHtml) {
    console.error('제목과 본문이 필요합니다: --title/--content 또는 --file <json>');
    process.exit(1);
  }

  const result = await publishPost({
    blog,
    title,
    contentHtml,
    tags,
    images,
    baseDir,
    publish: args.publish || 'draft',
    reserveAt: args.at,
  });
  console.log('\n완료:', JSON.stringify(result, null, 2));
}

if (require.main === module) {
  cliMain().catch((e) => {
    console.error('ERROR:', e.message);
    process.exit(1);
  });
}

module.exports = { publishPost, resolveReserveAt, prepareImages };
