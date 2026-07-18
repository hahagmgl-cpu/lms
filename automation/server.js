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
