// 티스토리 자동화 웹 GUI
//
// 실행:
//   node automation/server.js
//   → 브라우저에서 http://localhost:3000 접속
//
// 키워드를 넣고 "미리보기 생성"으로 글을 확인/수정한 뒤,
// "이미지 생성 + 발행"으로 이미지까지 만들어 티스토리에 발행(임시저장/즉시/예약)합니다.

const http = require('http');
const fs = require('fs');
const path = require('path');
const { loadEnv } = require('./lib/env');
const { generateArticle } = require('./generate');
const { runPipeline } = require('./auto');
const { produceOne } = require('./produce');
const { publishOne } = require('./publish-queue');
const store = require('./lib/store');
const cfg = require('./lib/config');

loadEnv();

const PORT = Number(process.env.PORT || process.env.GUI_PORT || 3000);
const STATE_FILE = path.join(__dirname, 'state.json');

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (c) => {
      data += c;
      if (data.length > 5e6) reject(new Error('요청이 너무 큽니다.'));
    });
    req.on('end', () => resolve(data));
    req.on('error', reject);
  });
}

function json(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, { 'content-type': 'application/json; charset=utf-8' });
  res.end(body);
}

// 어떤 공급자 키가 준비됐는지 등 환경 상태
function envStatus() {
  return {
    llm: {
      openai: !!process.env.OPENAI_API_KEY,
      gemini: !!process.env.GEMINI_API_KEY,
      claude: !!process.env.ANTHROPIC_API_KEY,
    },
    image: {
      pollinations: true, // 무료, 항상 사용 가능
      together: !!process.env.TOGETHER_API_KEY,
      openai: !!process.env.OPENAI_API_KEY,
    },
    blog: process.env.TISTORY_BLOG || '',
    loggedIn: fs.existsSync(STATE_FILE),
    hasCredentials: !!(process.env.TISTORY_ID && process.env.TISTORY_PW),
  };
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host}`);

    if (req.method === 'GET' && url.pathname === '/') {
      const html = fs.readFileSync(path.join(__dirname, 'public', 'index.html'));
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
      return res.end(html);
    }

    if (req.method === 'GET' && url.pathname === '/api/env') {
      return json(res, 200, envStatus());
    }

    // 글만 생성 (미리보기)
    if (req.method === 'POST' && url.pathname === '/api/generate') {
      const body = JSON.parse((await readBody(req)) || '{}');
      if (!body.keyword) return json(res, 400, { error: '키워드를 입력하세요.' });
      const article = await generateArticle(body.keyword, {
        imgs: body.imgs,
        audience: body.audience,
        intent: body.intent,
        provider: body.provider,
      });
      return json(res, 200, { article });
    }

    // 전체 실행: (이미지 생성 +) 발행. 진행 로그를 청크로 스트리밍.
    if (req.method === 'POST' && url.pathname === '/api/run') {
      const body = JSON.parse((await readBody(req)) || '{}');
      res.writeHead(200, {
        'content-type': 'text/plain; charset=utf-8',
        'transfer-encoding': 'chunked',
        'cache-control': 'no-cache',
      });
      const log = (line) => res.write(line.endsWith('\n') ? line : line + '\n');
      try {
        const result = await runPipeline(body.keyword || (body.article && body.article.title) || '', {
          article: body.article, // 미리보기에서 수정한 글을 그대로 사용
          provider: body.provider,
          imgProvider: body.imgProvider,
          imgs: body.imgs,
          images: body.images !== false,
          audience: body.audience,
          intent: body.intent,
          publish: body.publish || 'draft',
          at: body.at,
          blog: body.blog,
        }, log);
        log('\n=== 성공 ===');
        log(JSON.stringify(result.publishResult || {}, null, 2));
        if (result.publishResult && result.publishResult.url) log('URL: ' + result.publishResult.url);
      } catch (e) {
        log('\n=== 오류 ===');
        log(e.message);
      }
      return res.end();
    }

    // --- 설정 (모델 교체) ---
    if (req.method === 'GET' && url.pathname === '/api/config') {
      return json(res, 200, cfg.load());
    }
    if (req.method === 'POST' && url.pathname === '/api/config') {
      const body = JSON.parse((await readBody(req)) || '{}');
      const merged = cfg.saveOverride(body);
      return json(res, 200, { ok: true, config: merged });
    }

    // --- 큐 ---
    if (req.method === 'GET' && url.pathname === '/api/queue') {
      const posts = store.listPosts().map((p) => ({
        id: p.id, title: p.title, keyword: p.keyword, status: p.status,
        tags: p.tags, scheduleAt: p.scheduleAt, publishedUrl: p.publishedUrl,
        images: (p.images || []).map((i) => ({
          file: i.file || '', alt: i.alt || '', caption: i.caption || '', filename: i.filename || '',
        })),
      }));
      return json(res, 200, { posts, hasExcel: store.hasExcel });
    }
    if (req.method === 'GET' && url.pathname === '/api/queue/download') {
      const file = store.hasExcel && fs.existsSync(store.INDEX_XLSX) ? store.INDEX_XLSX : store.INDEX_CSV;
      if (!fs.existsSync(file)) return json(res, 404, { error: '인덱스가 아직 없습니다.' });
      const name = path.basename(file);
      res.writeHead(200, {
        'content-type': file.endsWith('.xlsx')
          ? 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
          : 'text/csv; charset=utf-8',
        'content-disposition': `attachment; filename="${name}"`,
      });
      return res.end(fs.readFileSync(file));
    }
    if (req.method === 'POST' && url.pathname === '/api/queue/sync') {
      const r = store.syncFromIndex();
      store.writeIndex();
      return json(res, 200, r);
    }
    if (req.method === 'GET' && url.pathname === '/api/queue/get') {
      const p = store.getPost(url.searchParams.get('id'));
      return p ? json(res, 200, p) : json(res, 404, { error: '없음' });
    }
    if (req.method === 'POST' && url.pathname === '/api/queue/update') {
      const body = JSON.parse((await readBody(req)) || '{}');
      if (!body.id) return json(res, 400, { error: 'id 필요' });
      const patch = {};
      ['title', 'tags', 'status', 'scheduleAt', 'blog', 'html'].forEach((k) => {
        if (body[k] !== undefined) patch[k] = body[k];
      });
      // 이미지 메타(alt/caption/filename) 수정: 인덱스별 병합
      if (Array.isArray(body.images)) {
        const cur = store.getPost(body.id);
        if (cur) {
          patch.images = (cur.images || []).map((im, i) => {
            const e = body.images[i] || {};
            return {
              ...im,
              alt: e.alt !== undefined ? e.alt : im.alt,
              caption: e.caption !== undefined ? e.caption : im.caption,
              filename: e.filename !== undefined ? e.filename : im.filename,
            };
          });
        }
      }
      const p = store.updatePost(body.id, patch);
      store.writeIndex();
      return json(res, 200, { ok: true, post: p });
    }

    // --- 생산: 키워드 → 글+이미지 생성 → 큐 저장 (발행 안 함), 스트리밍 ---
    if (req.method === 'POST' && url.pathname === '/api/produce') {
      const body = JSON.parse((await readBody(req)) || '{}');
      const keywords = (body.keywords || (body.keyword ? [body.keyword] : []))
        .map((k) => String(k).trim()).filter(Boolean);
      res.writeHead(200, { 'content-type': 'text/plain; charset=utf-8', 'transfer-encoding': 'chunked' });
      const log = (l) => res.write(l.endsWith('\n') ? l : l + '\n');
      if (!keywords.length) { log('키워드가 없습니다.'); return res.end(); }
      try {
        let ok = 0;
        for (const kw of keywords) {
          try { await produceOne(kw, {
            provider: body.provider, imgProvider: body.imgProvider,
            imgs: body.imgs, images: body.images !== false,
            audience: body.audience, intent: body.intent, blog: body.blog,
          }, log); ok++; }
          catch (e) { log(`✗ "${kw}" 실패: ${e.message}`); }
        }
        const idx = store.writeIndex();
        log(`\n=== 성공 === 생산 ${ok}/${keywords.length}건, 인덱스 ${idx.count}건`);
      } catch (e) { log('\n=== 오류 ===\n' + e.message); }
      return res.end();
    }

    // --- 발행: 큐의 특정/전체 글을 티스토리에 발행, 스트리밍 ---
    if (req.method === 'POST' && url.pathname === '/api/publish') {
      const body = JSON.parse((await readBody(req)) || '{}');
      res.writeHead(200, { 'content-type': 'text/plain; charset=utf-8', 'transfer-encoding': 'chunked' });
      const log = (l) => res.write(l.endsWith('\n') ? l : l + '\n');
      try {
        let targets = [];
        if (Array.isArray(body.ids) && body.ids.length) {
          targets = body.ids.map((id) => store.getPost(id)).filter(Boolean);
        } else if (body.id) {
          const p = store.getPost(body.id); if (p) targets = [p];
        } else if (body.all) {
          targets = store.listPosts().filter((p) => ['ready', 'draft'].includes(p.status));
          if (body.limit) targets = targets.slice(0, Number(body.limit)); // 앞에서 N개만
        }
        if (!targets.length) { log('발행할 대상이 없습니다.'); return res.end(); }
        log(`발행 대상 ${targets.length}건`);
        let ok = 0;
        for (const p of targets) {
          const r = await publishOne(p, { publish: body.publish, at: body.at, blog: body.blog }, log);
          if (r.ok) ok++;
        }
        store.writeIndex();
        log(`\n=== 성공 === 발행 ${ok}/${targets.length}건`);
      } catch (e) { log('\n=== 오류 ===\n' + e.message); }
      return res.end();
    }

    res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
    res.end('Not Found');
  } catch (e) {
    json(res, 500, { error: e.message });
  }
});

function start() {
  server.listen(PORT, () => {
    console.log(`\n티스토리 자동화 GUI 실행 중 → http://localhost:${PORT}\n`);
    const s = envStatus();
    console.log('글 생성 키:', Object.entries(s.llm).filter(([, v]) => v).map(([k]) => k).join(', ') || '없음(키 필요)');
    console.log('블로그:', s.blog || '(미설정 - .env TISTORY_BLOG)');
    console.log('로그인 세션:', s.loggedIn ? '있음' : '없음(먼저 node automation/login.js 실행)');
  });
}

if (require.main === module) start();

module.exports = { server, envStatus, start };
