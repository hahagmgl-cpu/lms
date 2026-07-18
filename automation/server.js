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
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
      return res.end(PAGE);
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

    res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
    res.end('Not Found');
  } catch (e) {
    json(res, 500, { error: e.message });
  }
});

server.listen(PORT, () => {
  console.log(`\n티스토리 자동화 GUI 실행 중 → http://localhost:${PORT}\n`);
  const s = envStatus();
  console.log('글 생성 키:', Object.entries(s.llm).filter(([, v]) => v).map(([k]) => k).join(', ') || '없음(키 필요)');
  console.log('블로그:', s.blog || '(미설정 - .env TISTORY_BLOG)');
  console.log('로그인 세션:', s.loggedIn ? '있음' : '없음(먼저 node automation/login.js 실행)');
});

// --- 프론트엔드 (의존성 없이 단일 HTML) ---
const PAGE = `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>티스토리 자동 발행</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --line:#e3e6ea; --fg:#1c2024; --muted:#6b7280; --accent:#ff6b35; --accent2:#2563eb; --ok:#16a34a; --err:#dc2626; }
  @media (prefers-color-scheme: dark) { :root { --bg:#15171a; --card:#1e2126; --line:#2c3037; --fg:#e6e8eb; --muted:#9aa2ad; } }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic",sans-serif; background:var(--bg); color:var(--fg); }
  .wrap { max-width:960px; margin:0 auto; padding:24px 16px 60px; }
  h1 { font-size:22px; margin:8px 0 4px; }
  .sub { color:var(--muted); font-size:13px; margin-bottom:20px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:20px; margin-bottom:16px; }
  label { display:block; font-size:13px; font-weight:600; margin:12px 0 5px; }
  input, select, textarea { width:100%; padding:9px 11px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--fg); font-size:14px; font-family:inherit; }
  textarea { min-height:120px; resize:vertical; }
  .row { display:flex; gap:12px; flex-wrap:wrap; }
  .row > div { flex:1; min-width:140px; }
  .btn { border:none; border-radius:8px; padding:11px 18px; font-size:14px; font-weight:600; cursor:pointer; }
  .btn-primary { background:var(--accent); color:#fff; }
  .btn-go { background:var(--ok); color:#fff; }
  .btn-ghost { background:transparent; border:1px solid var(--line); color:var(--fg); }
  .btn:disabled { opacity:.5; cursor:not-allowed; }
  .btns { display:flex; gap:10px; margin-top:16px; flex-wrap:wrap; }
  .status { display:flex; gap:14px; flex-wrap:wrap; font-size:12px; color:var(--muted); margin-bottom:16px; }
  .badge { padding:3px 9px; border-radius:999px; border:1px solid var(--line); }
  .badge.on { color:var(--ok); border-color:var(--ok); }
  .badge.off { color:var(--muted); }
  pre.log { background:#0b0d0f; color:#cfe3d2; padding:14px; border-radius:8px; font-size:12px; line-height:1.5; white-space:pre-wrap; word-break:break-word; max-height:340px; overflow:auto; }
  .preview h2 { font-size:16px; margin:14px 0 4px; }
  .preview .meta { font-size:12px; color:var(--muted); margin-bottom:8px; }
  .imgcard { border:1px solid var(--line); border-radius:8px; padding:10px; margin-top:8px; font-size:12px; }
  .hide { display:none; }
  .note { font-size:12px; color:var(--muted); margin-top:6px; }
  a { color:var(--accent2); }
</style>
</head>
<body>
<div class="wrap">
  <h1>티스토리 자동 발행 <span style="font-size:13px;color:var(--muted)">GUI</span></h1>
  <div class="sub">키워드 → SEO 글 생성 → 이미지 생성 → 예약/발행까지 한 번에</div>
  <div class="status" id="status"></div>

  <div class="card">
    <label>키워드 *</label>
    <input id="keyword" placeholder="예: 제주도 겨울 여행 코스" />
    <div class="row">
      <div>
        <label>글 생성 AI</label>
        <select id="provider"><option value="">자동 선택</option><option value="openai">GPT (OpenAI)</option><option value="gemini">제미나이 (Gemini)</option><option value="claude">Claude</option></select>
      </div>
      <div>
        <label>이미지 생성</label>
        <select id="imgProvider"><option value="">자동 선택</option><option value="pollinations">Pollinations (무료)</option><option value="together">Together (FLUX)</option><option value="openai">OpenAI</option></select>
      </div>
      <div>
        <label>이미지 개수</label>
        <input id="imgs" type="number" value="1" min="0" max="5" />
      </div>
    </div>
    <div class="row">
      <div><label>타깃 독자 (선택)</label><input id="audience" placeholder="예: 아이 동반 가족" /></div>
      <div><label>검색 니즈 (선택)</label><input id="intent" placeholder="예: 일정표와 예상 경비" /></div>
    </div>
    <div class="btns">
      <button class="btn btn-primary" id="btnPreview">① 미리보기 생성</button>
    </div>
    <div class="note">먼저 글만 만들어 확인·수정한 뒤 발행하세요. (이미지 생성/발행은 아래 버튼)</div>
  </div>

  <div class="card preview hide" id="previewCard">
    <label>제목</label>
    <input id="pvTitle" />
    <label>태그 (쉼표 구분)</label>
    <input id="pvTags" />
    <label>본문 HTML <span class="note">({{IMAGE_n}} 위치에 이미지가 들어갑니다)</span></label>
    <textarea id="pvHtml"></textarea>
    <div id="pvImages"></div>

    <div class="row" style="margin-top:14px">
      <div>
        <label>발행 방식</label>
        <select id="publish"><option value="draft">임시저장</option><option value="reserve">예약 발행</option><option value="now">즉시 발행</option></select>
      </div>
      <div>
        <label>예약 시각 (예약 발행 시)</label>
        <input id="at" type="datetime-local" />
      </div>
      <div>
        <label>블로그 서브도메인</label>
        <input id="blog" placeholder="record7518" />
      </div>
    </div>
    <div class="btns">
      <button class="btn btn-go" id="btnRun">② 이미지 생성 + 발행</button>
      <button class="btn btn-ghost" id="btnRegen">글 다시 생성</button>
    </div>
  </div>

  <div class="card hide" id="logCard">
    <label>진행 상황</label>
    <pre class="log" id="log"></pre>
  </div>
</div>

<script>
const $ = (id) => document.getElementById(id);
let currentArticle = null;

async function loadEnv() {
  try {
    const s = await (await fetch('/api/env')).json();
    const b = (on, label) => '<span class="badge '+(on?'on':'off')+'">'+label+(on?' ✓':' –')+'</span>';
    $('status').innerHTML =
      b(s.llm.openai,'GPT') + b(s.llm.gemini,'제미나이') + b(s.llm.claude,'Claude') +
      b(true,'이미지:무료가능') +
      b(s.loggedIn,'로그인세션') + b(!!s.blog,'블로그:'+(s.blog||'미설정'));
    if (s.blog) $('blog').value = s.blog;
  } catch(e) { $('status').textContent = '환경 상태를 불러오지 못했습니다.'; }
}

function renderImages(images) {
  if (!images || !images.length) { $('pvImages').innerHTML = ''; return; }
  $('pvImages').innerHTML = '<label>이미지 정보</label>' + images.map((im,i) =>
    '<div class="imgcard"><b>{{IMAGE_'+i+'}}</b><br>'+
    'alt: <input data-i="'+i+'" data-k="alt" value="'+(im.alt||'').replace(/"/g,'&quot;')+'"><br>'+
    'caption: <input data-i="'+i+'" data-k="caption" value="'+(im.caption||'').replace(/"/g,'&quot;')+'"><br>'+
    'filename: <input data-i="'+i+'" data-k="filename" value="'+(im.filename||'').replace(/"/g,'&quot;')+'"><br>'+
    '<span class="note">프롬프트: '+(im.prompt||'-')+'</span></div>'
  ).join('');
  $('pvImages').oninput = (e) => {
    const t = e.target; if (t.dataset.i === undefined) return;
    currentArticle.images[+t.dataset.i][t.dataset.k] = t.value;
  };
}

function showPreview(a) {
  currentArticle = a;
  $('pvTitle').value = a.title || '';
  $('pvTags').value = (a.tags || []).join(', ');
  $('pvHtml').value = a.html || '';
  renderImages(a.images);
  $('previewCard').classList.remove('hide');
  $('previewCard').scrollIntoView({behavior:'smooth'});
}

$('btnPreview').onclick = $('btnRegen').onclick = async () => {
  const kw = $('keyword').value.trim();
  if (!kw) return alert('키워드를 입력하세요.');
  const btn = $('btnPreview'); btn.disabled = true; const old = btn.textContent; btn.textContent = '생성 중...';
  try {
    const r = await fetch('/api/generate', { method:'POST', headers:{'content-type':'application/json'},
      body: JSON.stringify({ keyword:kw, provider:$('provider').value||undefined, imgs:Number($('imgs').value),
        audience:$('audience').value||undefined, intent:$('intent').value||undefined }) });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    showPreview(d.article);
  } catch(e) { alert('오류: '+e.message); }
  finally { btn.disabled = false; btn.textContent = old; }
};

$('btnRun').onclick = async () => {
  if (!currentArticle) return alert('먼저 미리보기를 생성하세요.');
  currentArticle.title = $('pvTitle').value;
  currentArticle.tags = $('pvTags').value.split(',').map(t=>t.trim()).filter(Boolean);
  currentArticle.html = $('pvHtml').value;
  const btn = $('btnRun'); btn.disabled = true; const old = btn.textContent; btn.textContent = '실행 중...';
  $('logCard').classList.remove('hide'); $('log').textContent = '';
  try {
    const r = await fetch('/api/run', { method:'POST', headers:{'content-type':'application/json'},
      body: JSON.stringify({ article: currentArticle, imgProvider:$('imgProvider').value||undefined,
        imgs:Number($('imgs').value), images:Number($('imgs').value)>0,
        publish:$('publish').value, at:$('at').value||undefined, blog:$('blog').value||undefined }) });
    const reader = r.body.getReader(); const dec = new TextDecoder();
    for(;;){ const {done,value} = await reader.read(); if(done) break;
      $('log').textContent += dec.decode(value,{stream:true}); $('log').scrollTop = $('log').scrollHeight; }
  } catch(e) { $('log').textContent += '\\n오류: '+e.message; }
  finally { btn.disabled = false; btn.textContent = old; }
};

loadEnv();
</script>
</body>
</html>`;

module.exports = { server, envStatus };
