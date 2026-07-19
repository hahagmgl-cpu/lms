// 생산(produce) 단계: 키워드 → SEO 글 + 이미지 생성 → 큐에 저장 (발행하지 않음)
//
// 발행은 나중에 따로: node automation/publish-queue.js
//
// 사용법:
//   node automation/produce.js "제주도 겨울 여행"                     # 1건 생산
//   node automation/produce.js "키워드1" "키워드2" "키워드3"           # 여러 건 일괄
//   node automation/produce.js --file keywords.txt                    # 파일에서 (한 줄 = 한 키워드)
//   node automation/produce.js "키워드" --provider gemini --img-provider pollinations --imgs 2 --no-images
//
// 결과: content/queue/<id>/ 폴더에 post.json + images/, 그리고 content/queue/index.xlsx(.csv) 갱신

const fs = require('fs');
const path = require('path');
const { loadEnv } = require('./lib/env');
const { generateArticle } = require('./generate');
const { generateImage } = require('./lib/image-gen');
const { normalizeImages, stem } = require('./lib/imagemeta');
const store = require('./lib/store');
const cfg = require('./lib/config');

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
 * 키워드 1건 생산: 글 생성 → 큐 저장 → 이미지 생성 → 상태 ready
 * @returns {object} 저장된 post
 */
async function produceOne(keyword, opts = {}, log = console.log) {
  const c = cfg.load();
  const withImages = opts.images !== false;
  const imgs = withImages ? (opts.imgs !== undefined ? Number(opts.imgs) : c.image.count ?? 1) : 0;

  log(`· 글 생성: "${keyword}"`);
  const article = await generateArticle(keyword, {
    imgs,
    provider: opts.provider,
    audience: opts.audience,
    intent: opts.intent,
  });

  // 안전장치: article 이 아직 정규화 안 됐으면 여기서 확정 (alt/caption/filename 보장)
  article.images = normalizeImages(article.images, { title: article.title, keyword });

  const post = store.createPost(article, { keyword, blog: opts.blog || c.post.blog });
  log(`  저장: ${post.id} — ${post.title}`);

  if (withImages && (post.images || []).length) {
    const dir = store.imagesDir(post.id);
    fs.mkdirSync(dir, { recursive: true });
    const imgProvider = opts.imgProvider || c.image.provider;
    for (let i = 0; i < post.images.length; i++) {
      const im = post.images[i];
      if (!im.prompt) { log(`  이미지[${i}] prompt 없음 → 건너뜀`); continue; }
      // 디스크 파일명 = SEO 파일명의 stem + 실제 포맷(.png). im.filename(SEO)은 치환문에 그대로 사용.
      const outFile = path.join(dir, `${stem(im.filename)}.png`);
      try {
        await generateImage(im.prompt, outFile, {
          provider: imgProvider,
          model: cfg.imageModel(c, imgProvider),
          width: opts.width || c.image.width,
          height: opts.height || c.image.height,
        });
        im.file = path.relative(store.postDir(post.id), outFile).split(path.sep).join('/');
        log(`  이미지[${i}] 저장: ${im.file}`);
      } catch (e) {
        log(`  이미지[${i}] 생성 실패: ${e.message}`);
      }
    }
  }

  post.status = 'ready'; // 발행 대기
  store.writePost(post);
  return post;
}

async function produce(keywords, opts = {}, log = console.log) {
  const results = [];
  for (const kw of keywords) {
    try {
      results.push(await produceOne(kw, opts, log));
    } catch (e) {
      log(`✗ "${kw}" 생산 실패: ${e.message}`);
      results.push({ keyword: kw, error: e.message });
    }
  }
  const idx = store.writeIndex();
  log(`\n인덱스 갱신: ${idx.count}건 → ${idx.xlsx || idx.csv}`);
  return results;
}

if (require.main === module) {
  (async () => {
    const args = parseArgs(process.argv);
    let keywords = args._.slice();
    if (args.file) {
      const lines = fs.readFileSync(args.file, 'utf8').split('\n').map((l) => l.trim()).filter(Boolean);
      keywords = keywords.concat(lines);
    }
    if (!keywords.length) {
      console.error('사용법: node automation/produce.js "키워드" ["키워드2" ...] [--file keywords.txt] [--imgs N] [--no-images] [--provider ...] [--img-provider ...]');
      process.exit(1);
    }
    console.log(`총 ${keywords.length}건 생산 시작\n`);
    const res = await produce(keywords, {
      provider: args.provider,
      imgProvider: args['img-provider'],
      imgs: args.imgs,
      images: args['no-images'] ? false : true,
      audience: args.audience,
      intent: args.intent,
      blog: args.blog,
    });
    const ok = res.filter((r) => !r.error).length;
    console.log(`\n완료: 성공 ${ok} / 전체 ${res.length}건`);
    console.log('발행하려면: node automation/publish-queue.js  (또는 GUI 큐 탭)');
  })().catch((e) => { console.error('ERROR:', e.message); process.exit(1); });
}

module.exports = { produce, produceOne };
