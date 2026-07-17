// 티스토리 브라우저 자동화 공용 라이브러리 (Playwright)
// - 카카오 계정 로그인 (세션을 state.json 에 저장해 재사용)
// - 글 작성 + 즉시발행 / 예약발행 / 임시저장
//
// 티스토리 공식 Open API는 2024년 2월에 종료되었기 때문에
// 브라우저 자동화가 사실상 유일한 프로그래밍 방식의 발행 수단입니다.

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..', '..');
const STATE_FILE = process.env.STATE_FILE || path.join(ROOT, 'automation', 'state.json');
const SHOTS_DIR = process.env.SHOTS_DIR || path.join(ROOT, 'shots');

function ts() {
  return new Date().toISOString().replace(/[:.]/g, '-');
}

async function shot(page, name) {
  fs.mkdirSync(SHOTS_DIR, { recursive: true });
  const file = path.join(SHOTS_DIR, `${name}.png`);
  try {
    await page.screenshot({ path: file });
    console.log(`  [shot] ${name} (${page.url()})`);
  } catch (e) {
    console.log(`  [shot] ${name} 실패: ${e.message}`);
  }
}

async function launch() {
  const browser = await chromium.launch({
    headless: process.env.HEADLESS !== '0',
    executablePath: process.env.CHROME_PATH || undefined,
    args: ['--disable-blink-features=AutomationControlled'],
  });
  const ctxOptions = {
    locale: 'ko-KR',
    timezoneId: 'Asia/Seoul',
    viewport: { width: 1440, height: 900 },
    userAgent:
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
  };
  if (fs.existsSync(STATE_FILE)) {
    ctxOptions.storageState = STATE_FILE;
    console.log('저장된 로그인 세션(state.json)을 불러왔습니다.');
  }
  const context = await browser.newContext(ctxOptions);
  return { browser, context };
}

async function saveState(context) {
  await context.storageState({ path: STATE_FILE });
  console.log(`로그인 세션 저장: ${STATE_FILE}`);
}

// 로그인 여부 확인: 관리 페이지 접근이 로그인 페이지로 튕기는지 검사
async function isLoggedIn(page, blog) {
  await page.goto(`https://${blog}.tistory.com/manage`, {
    waitUntil: 'domcontentloaded',
    timeout: 60000,
  });
  await page.waitForTimeout(2000);
  const url = page.url();
  return !/auth\/login|accounts\.kakao\.com/.test(url);
}

// 카카오 계정으로 티스토리 로그인
async function login(page, id, pw) {
  console.log('1) 티스토리 로그인 페이지 이동');
  await page.goto('https://www.tistory.com/auth/login', {
    waitUntil: 'domcontentloaded',
    timeout: 60000,
  });
  await page.waitForTimeout(2000);
  await shot(page, 'login-01-page');

  console.log('2) 카카오계정으로 로그인 클릭');
  const kakaoBtn = page
    .locator('a.btn_login.link_kakao_id, a:has-text("카카오계정으로 로그인")')
    .first();
  await kakaoBtn.click();
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3000);
  await shot(page, 'login-02-kakao');

  console.log('3) 아이디/비밀번호 입력');
  const idInput = page
    .locator('input[name="loginId"], input[type="email"], input[placeholder*="카카오메일"]')
    .first();
  await idInput.waitFor({ timeout: 15000 });
  await idInput.fill(id);
  await page.locator('input[name="password"], input[type="password"]').first().fill(pw);

  console.log('4) 로그인 제출');
  await page.locator('button[type="submit"], .btn_g.highlight.submit').first().click();
  await page.waitForTimeout(6000);
  await shot(page, 'login-03-after-submit');

  // 2단계 인증 / 추가 동의 화면 대응
  for (let i = 0; i < 3; i++) {
    const cont = page
      .locator('button:has-text("계속하기"), button:has-text("동의하고 계속하기"), button:has-text("확인")')
      .first();
    if (await cont.isVisible().catch(() => false)) {
      console.log('   추가 확인 화면 → 통과 시도');
      await cont.click();
      await page.waitForTimeout(4000);
      await shot(page, `login-04-confirm-${i}`);
    } else break;
  }

  await page.waitForTimeout(3000);
  await shot(page, 'login-05-final');
  const url = page.url();
  console.log('   로그인 후 URL:', url);

  if (/accounts\.kakao\.com/.test(url)) {
    throw new Error(
      '카카오 로그인 페이지에 머물러 있습니다. 2단계 인증(카카오톡 확인)이나 캡차가 필요할 수 있습니다. ' +
        'HEADLESS=0 으로 창을 띄워 직접 인증을 완료한 뒤 다시 시도하세요.'
    );
  }
  return url;
}

// 첫 클릭/타이핑 시 뜨는 "저장된 글이 있습니다" 등의 다이얼로그 자동 처리
function autoDismissDialogs(page) {
  page.on('dialog', async (dialog) => {
    console.log(`   [dialog] ${dialog.type()}: ${dialog.message()} → 취소(새 글 작성)`);
    // "이어서 작성하시겠습니까?" → 취소를 눌러 새 글로 시작
    await dialog.dismiss().catch(() => {});
  });
}

/**
 * 글 작성 + 발행
 * @param {import('playwright').Page} page
 * @param {object} opts
 *  - blog: 블로그 서브도메인 (예: record7518)
 *  - title: 제목
 *  - contentHtml: 본문 HTML
 *  - tags: string[] 태그 목록
 *  - publish: 'now' | 'reserve' | 'draft'
 *  - reserveAt: 예약발행 시각 (Date 또는 ISO 문자열, publish==='reserve'일 때)
 */
async function writePost(page, opts) {
  const { blog, title, contentHtml, tags = [], publish = 'draft', reserveAt } = opts;

  autoDismissDialogs(page);

  console.log('1) 글쓰기 페이지 이동');
  await page.goto(`https://${blog}.tistory.com/manage/newpost/?type=post`, {
    waitUntil: 'domcontentloaded',
    timeout: 60000,
  });
  await page.waitForTimeout(4000);
  await shot(page, 'post-01-editor');

  if (/auth\/login|accounts\.kakao\.com/.test(page.url())) {
    throw new Error('로그인이 필요합니다. 먼저 `node automation/login.js` 를 실행하세요.');
  }

  console.log('2) 제목 입력');
  const titleInput = page
    .locator('#post-title-inp, textarea[placeholder*="제목"], .textarea_tit')
    .first();
  await titleInput.waitFor({ timeout: 20000 });
  await titleInput.click();
  await titleInput.fill(title);
  await shot(page, 'post-02-title');

  console.log('3) 본문 입력');
  // 1순위: TinyMCE API 직접 호출 (신 에디터는 TinyMCE 기반)
  const setViaTiny = await page
    .evaluate((html) => {
      if (window.tinymce && window.tinymce.activeEditor) {
        window.tinymce.activeEditor.setContent(html);
        return true;
      }
      return false;
    }, contentHtml)
    .catch(() => false);

  if (!setViaTiny) {
    // 2순위: 에디터 iframe 안의 body에 직접 타이핑
    console.log('   TinyMCE API 미탐지 → iframe 직접 입력 시도');
    const frame = page.frameLocator('#editor-tistory_ifr, iframe[id*="_ifr"]').first();
    const body = frame.locator('body#tinymce, body[contenteditable="true"], body').first();
    await body.click();
    const plain = contentHtml.replace(/<[^>]+>/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
    await page.keyboard.type(plain, { delay: 5 });
  }
  await page.waitForTimeout(1500);
  await shot(page, 'post-03-content');

  if (tags.length) {
    console.log('4) 태그 입력:', tags.join(', '));
    const tagInput = page
      .locator('#tagText, input[name="tagText"], input[placeholder*="태그"]')
      .first();
    if (await tagInput.isVisible().catch(() => false)) {
      for (const tag of tags) {
        await tagInput.fill(tag);
        await page.keyboard.press('Enter');
        await page.waitForTimeout(300);
      }
    } else {
      console.log('   태그 입력란을 찾지 못해 건너뜁니다.');
    }
  }

  if (publish === 'draft') {
    console.log('5) 임시저장');
    const saveBtn = page.locator('#save-btn, button:has-text("임시저장"), .btn_save').first();
    await saveBtn.click();
    await page.waitForTimeout(2500);
    await shot(page, 'post-04-draft-saved');
    return { status: 'draft' };
  }

  console.log('5) 완료 버튼 클릭 → 발행 레이어 열기');
  const completeBtn = page
    .locator('#publish-layer-btn, button:has-text("완료"), .btn-publish')
    .first();
  await completeBtn.click();
  await page.waitForTimeout(2500);
  await shot(page, 'post-04-publish-layer');

  console.log('6) 공개 설정: 공개');
  const publicRadio = page.locator('#open20, label[for="open20"], input[value="20"]').first();
  if (await publicRadio.isVisible().catch(() => false)) {
    await publicRadio.click().catch(async () => {
      await page.locator('label[for="open20"]').click();
    });
  } else {
    const publicLabel = page.locator('label:has-text("공개")').first();
    if (await publicLabel.isVisible().catch(() => false)) await publicLabel.click();
  }
  await page.waitForTimeout(800);

  if (publish === 'reserve') {
    const when = reserveAt instanceof Date ? reserveAt : new Date(reserveAt);
    if (isNaN(when.getTime())) throw new Error(`예약 시각이 올바르지 않습니다: ${reserveAt}`);
    console.log('7) 예약발행 설정:', when.toString());

    // "예약" 옵션 활성화 (라디오/버튼/탭 등 여러 형태 대응)
    const reserveToggle = page
      .locator('#reserve, input[name="publishTime"][value="reserve"], label:has-text("예약"), button:has-text("예약")')
      .first();
    await reserveToggle.waitFor({ timeout: 10000 });
    await reserveToggle.click();
    await page.waitForTimeout(1200);
    await shot(page, 'post-05-reserve-open');

    // 날짜 입력 (YYYY-MM-DD)
    const dateStr = `${when.getFullYear()}-${String(when.getMonth() + 1).padStart(2, '0')}-${String(
      when.getDate()
    ).padStart(2, '0')}`;
    const hh = String(when.getHours()).padStart(2, '0');
    const mm = String(when.getMinutes()).padStart(2, '0');

    const dateInput = page
      .locator('#reserve-date, input[type="date"], input[placeholder*="날짜"]')
      .first();
    if (await dateInput.isVisible().catch(() => false)) {
      await dateInput.fill(dateStr);
    } else {
      console.log('   날짜 입력란을 찾지 못했습니다. 스크린샷을 확인하세요.');
    }

    // 시/분: select 또는 텍스트 입력 두 형태 모두 대응
    const hourSel = page.locator('#reserve-hour, select[name*="hour"], .reserve_hour select').first();
    const minSel = page.locator('#reserve-min, select[name*="min"], .reserve_min select').first();
    if (await hourSel.isVisible().catch(() => false)) {
      await hourSel.selectOption(hh).catch(() => hourSel.selectOption(String(when.getHours())));
      if (await minSel.isVisible().catch(() => false)) {
        await minSel.selectOption(mm).catch(() => minSel.selectOption(String(when.getMinutes())));
      }
    } else {
      const hourInp = page.locator('input[name*="hour"], input[placeholder*="시"]').first();
      const minInp = page.locator('input[name*="min"], input[placeholder*="분"]').first();
      if (await hourInp.isVisible().catch(() => false)) await hourInp.fill(hh);
      if (await minInp.isVisible().catch(() => false)) await minInp.fill(mm);
    }
    await page.waitForTimeout(800);
    await shot(page, 'post-06-reserve-set');
  }

  console.log('8) 발행 버튼 클릭');
  const publishBtn = page
    .locator('#publish-btn, button:has-text("예약 발행"), button:has-text("발행"), button:has-text("공개 발행")')
    .first();
  await publishBtn.click();
  await page.waitForTimeout(5000);
  await shot(page, 'post-07-published');
  console.log('   발행 후 URL:', page.url());

  return { status: publish, url: page.url() };
}

module.exports = { launch, saveState, isLoggedIn, login, writePost, shot, STATE_FILE };
