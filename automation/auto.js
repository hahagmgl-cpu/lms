// 전체 파이프라인: 키워드 → SEO 글 생성 → 이미지 생성 → 티스토리 발행
//
// 사용법:
//   node automation/auto.js "제주도 겨울 여행 코스"
//   node automation/auto.js "키워드" --provider gemini --img-provider pollinations --imgs 2 --publish reserve --at "2026-07-20T09:00"
//   node automation/auto.js "키워드" --publish draft          # 이미지·글만 만들고 임시저장
//   node automation/auto.js "키워드" --no-images              # 이미지 없이 글만
//
// 옵션:
//   --provider      글 생성 LLM (openai|gemini|claude)
//   --img-provider  이미지 생성 (pollinations|together|openai)
//   --imgs N        이미지 개수 (기본 1)
//   --audience, --intent  타깃/니즈
//   --publish       draft|now|reserve (기본 draft)
//   --at            예약 시각 (reserve일 때)
//   --no-images     이미지 단계 건너뜀
//   --out           글 JSON 저장 경로

const fs = require('fs');
const path = require('path');
const { loadEnv } = require('./lib/env');
const { generateArticle } = require('./generate');
const { fillImages } = require('./gen-image');
const { publishPost } = require('./post');

loadEnv();

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 2; i < argv.length; i++) {
    if (argv[i].startsWith('--')) {
      const key = argv[i].slice(2);
      const val = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[++i] : true;
      args[key] = val;
    } else args._.push(argv[i]);
  }
  return args;
}

/**
 * 파이프라인 실행. log 콜백으로 진행 상황을 스트리밍(GUI 재사용).
 * @returns {object} { jsonFile, article, publishResult }
 */
async function runPipeline(keyword, opts = {}, log = console.log) {
  if (!keyword) throw new Error('키워드가 필요합니다.');
  const withImages = opts.images !== false;
  const imgs = withImages ? (opts.imgs !== undefined ? Number(opts.imgs) : 1) : 0;

  let article;
  if (opts.article && opts.article.title && opts.article.html) {
    log('[1/3] 글 생성 건너뜀 (미리보기에서 전달된 글 사용)');
    article = opts.article;
  } else {
    log(`[1/3] 글 생성 (키워드: ${keyword})`);
    article = await generateArticle(keyword, {
      imgs,
      audience: opts.audience,
      intent: opts.intent,
      provider: opts.provider,
    });
  }
  const outFile =
    opts.out || path.join(__dirname, '..', 'content', `post-${Date.now()}.json`);
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  fs.writeFileSync(outFile, JSON.stringify(article, null, 2), 'utf8');
  log(`      제목: ${article.title}`);
  log(`      저장: ${outFile}`);

  if (withImages && (article.images || []).length) {
    log(`[2/3] 이미지 생성 (${article.images.length}개)`);
    await fillImages(outFile, {
      provider: opts.imgProvider,
      width: opts.width,
      height: opts.height,
    });
  } else {
    log('[2/3] 이미지 단계 건너뜀');
  }

  const publish = opts.publish || 'draft';
  log(`[3/3] 발행 (${publish})`);
  const reloaded = JSON.parse(fs.readFileSync(outFile, 'utf8'));
  const publishResult = await publishPost({
    blog: opts.blog,
    title: reloaded.title,
    contentHtml: reloaded.html,
    tags: reloaded.tags,
    images: reloaded.images,
    baseDir: path.dirname(path.resolve(outFile)),
    publish,
    reserveAt: opts.at,
  });
  log(`      완료: ${JSON.stringify(publishResult)}`);
  return { jsonFile: outFile, article: reloaded, publishResult };
}

if (require.main === module) {
  (async () => {
    const args = parseArgs(process.argv);
    const keyword = args._[0];
    if (!keyword) {
      console.error('사용법: node automation/auto.js "키워드" [--provider ...] [--img-provider ...] [--imgs N] [--publish draft|now|reserve] [--at 시각]');
      process.exit(1);
    }
    await runPipeline(keyword, {
      provider: args.provider,
      imgProvider: args['img-provider'],
      imgs: args.imgs,
      images: args['no-images'] ? false : true,
      audience: args.audience,
      intent: args.intent,
      publish: args.publish || 'draft',
      at: args.at,
      blog: args.blog,
      out: args.out,
      width: args.width,
      height: args.height,
    });
    console.log('\n파이프라인 완료.');
  })().catch((e) => {
    console.error('ERROR:', e.message);
    process.exit(1);
  });
}

module.exports = { runPipeline };
