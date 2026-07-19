// 발행(publish) 단계: 큐에 쌓인 글을 티스토리에 발행 (생산과 분리)
//
// 사용법:
//   node automation/publish-queue.js --list                          # 큐 목록 보기
//   node automation/publish-queue.js --id 20260720-093000-키워드     # 특정 글 발행
//   node automation/publish-queue.js --all                           # ready 상태 전부 발행
//   node automation/publish-queue.js --all --publish reserve --at "2026-07-21T09:00"
//   node automation/publish-queue.js --sync                          # 엑셀/CSV 편집을 post.json 에 반영
//
// 발행 방식(--publish): draft | now | reserve  (기본: 각 글의 scheduleAt 있으면 reserve, 없으면 draft)

const path = require('path');
const { loadEnv } = require('./lib/env');
const { publishPost } = require('./post');
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

function printList() {
  const posts = store.listPosts();
  if (!posts.length) return console.log('큐가 비어 있습니다. 먼저 produce 로 생성하세요.');
  console.log(`\n큐 (${posts.length}건):`);
  for (const p of posts) {
    const imgs = (p.images || []).filter((i) => i.file).length;
    console.log(
      `  [${p.status}] ${p.id}\n     ${p.title}\n     이미지 ${imgs}/${(p.images || []).length} · 예약 ${p.scheduleAt || '-'} · ${p.publishedUrl || ''}`
    );
  }
}

// 글 1건 발행. 발행 방식 결정: 명시 > scheduleAt 있으면 reserve > 기본 draft
async function publishOne(post, opts = {}, log = console.log) {
  const c = cfg.load();
  const publish = opts.publish || (post.scheduleAt ? 'reserve' : c.post.defaultPublish || 'draft');
  const reserveAt = publish === 'reserve' ? (opts.at || post.scheduleAt) : null;
  const blog = opts.blog || post.blog || c.post.blog;

  log(`발행: ${post.id} (${publish}${reserveAt ? ' @ ' + reserveAt : ''})`);
  try {
    const result = await publishPost({
      blog,
      title: post.title,
      contentHtml: post.html,
      tags: post.tags,
      images: post.images,
      baseDir: store.postDir(post.id),
      publish,
      reserveAt,
    });
    store.updatePost(post.id, {
      status: publish === 'draft' ? 'draft' : publish === 'reserve' ? 'scheduled' : 'published',
      publishedUrl: result.url || post.publishedUrl || null,
      scheduleAt: reserveAt || post.scheduleAt || null,
    });
    log(`  완료: ${JSON.stringify(result)}`);
    return { ok: true, result };
  } catch (e) {
    store.updatePost(post.id, { status: 'failed' });
    log(`  실패: ${e.message}`);
    return { ok: false, error: e.message };
  }
}

async function publishMany(filterFn, opts = {}, log = console.log) {
  const posts = store.listPosts().filter(filterFn);
  if (!posts.length) { log('발행할 대상이 없습니다.'); return []; }
  const out = [];
  for (const p of posts) out.push({ id: p.id, ...(await publishOne(p, opts, log)) });
  store.writeIndex();
  return out;
}

if (require.main === module) {
  (async () => {
    const args = parseArgs(process.argv);

    if (args.sync) {
      const r = store.syncFromIndex();
      store.writeIndex();
      return console.log(`엑셀/CSV 편집 반영: ${r.updated}건 업데이트`);
    }
    if (args.list || (!args.id && !args.all)) {
      return printList();
    }

    const opts = { publish: args.publish, at: args.at, blog: args.blog };

    if (args.id) {
      const post = store.getPost(args.id);
      if (!post) { console.error('해당 id 없음:', args.id); process.exit(1); }
      await publishOne(post, opts);
      store.writeIndex();
      return;
    }
    if (args.all) {
      const res = await publishMany((p) => ['ready', 'draft'].includes(p.status), opts);
      const ok = res.filter((r) => r.ok).length;
      console.log(`\n발행 완료: 성공 ${ok} / 전체 ${res.length}건`);
    }
  })().catch((e) => { console.error('ERROR:', e.message); process.exit(1); });
}

module.exports = { publishOne, publishMany, printList };
