// 카카오 계정으로 티스토리에 로그인하고 세션을 automation/state.json 에 저장
//
// 사용법:
//   .env 에 TISTORY_ID / TISTORY_PW 설정 후
//   node automation/login.js
//
// 2단계 인증(카카오톡 확인)이 걸리면 HEADLESS=0 으로 창을 띄워 직접 승인:
//   HEADLESS=0 node automation/login.js

const { loadEnv } = require('./lib/env');
const { launch, saveState, login } = require('./lib/tistory');

loadEnv();

(async () => {
  const id = process.env.TISTORY_ID;
  const pw = process.env.TISTORY_PW;
  if (!id || !pw) {
    console.error('TISTORY_ID / TISTORY_PW 환경변수를 설정하세요 (.env 파일 사용 가능).');
    process.exit(1);
  }

  const { browser, context } = await launch();
  const page = await context.newPage();
  try {
    await login(page, id, pw);
    await saveState(context);
    console.log('\n로그인 성공. 이제 node automation/post.js 로 글을 발행할 수 있습니다.');
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error('ERROR:', e.message);
  process.exit(1);
});
