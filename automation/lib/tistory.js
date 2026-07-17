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

// 에디터 다이얼로그 자동 처리:
// - "저장된 글이 있습니다. 이어서 작성하시겠습니까?" → 취소(새 글로 시작)
// - "작성 모드를 변경하시겠습니까?" (HTML 모드 전환 시) → 확인
function autoDismissDialogs(page) {
  page.on('dialog', async (dialog) => {
    const msg = dialog.message();
    const accept = /모드/.test(msg);
    console.log(`   [dialog] ${dialog.type()}: ${msg} → ${accept ? '확인' : '취소'}`);
    if (accept) await dialog.accept().catch(() => {});
    else await dialog.dismiss().catch(() => {});
  });
}

// 에디터를 HTML 모드로 전환 (CodeMirror 편집기 사용)
// 우측 상단 "기본모드" 드롭다운 → HTML 선택. 확인 다이얼로그는 autoDismissDialogs 가 수락.
async function switchToHtmlMode(page) {
  const already = await page.evaluate(() => !!document.querySelector('.CodeMirror'));
  if (already) return true;

  const opener = page
    .locator('#editor-mode-layer-btn-open, button:has-text("기본모드"), [class*="mode"] button')
    .first();
  if (!(await opener.isVisible().catch(() => false))) {
    console.log('   모드 전환 버튼을 찾지 못했습니다.');
    return false;
  }
  await opener.click();
  await page.waitForTimeout(600);

  const htmlItem = page
    .locator('#editor-mode-html, [data-value="html"], a:has-text("HTML"), span:has-text("HTML"), div:has-text("HTML")')
    .last();
  await htmlItem.click().catch(async () => {
    await page.evaluate(() => {
      const els = Array.from(document.querySelectorAll('a, span, div, button, li'));
      const el = els.find((e) => e.childElementCount === 0 && e.textContent.trim() === 'HTML' && e.offsetParent !== null);
      if (el) el.click();
    });
  });
  await page.waitForTimeout(2000);

  return page.evaluate(() => !!document.querySelector('.CodeMirror'));
}

// HTML 모드(CodeMirror)의 본문 읽기/쓰기
async function cmGetValue(page) {
  return page.evaluate(() => {
    const cm = document.querySelector('.CodeMirror');
    return cm && cm.CodeMirror ? cm.CodeMirror.getValue() : null;
  });
}

async function cmSetValue(page, html) {
  return page.evaluate((v) => {
    const cm = document.querySelector('.CodeMirror');
    if (!cm || !cm.CodeMirror) return false;
    cm.CodeMirror.setValue(v);
    if (cm.CodeMirror.refresh) cm.CodeMirror.refresh();
    return true;
  }, html);
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
  const { blog, title, contentHtml, tags = [], publish = 'draft', reserveAt, images = [] } = opts;

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

  // 이미지가 있으면 기본모드에서 먼저 업로드 (카카오 서버 업로드 → [##_Image|kage@...] 치환문 생성)
  let bodyHtml = contentHtml;
  if (images.length) {
    console.log(`2.5) 이미지 ${images.length}개 업로드`);
    await uploadImagesAndCollect(page, images);
  }

  console.log('3) 본문 입력 (HTML 모드)');
  // TinyMCE setContent 는 화면에는 보여도 티스토리 내부 저장 상태에 반영되지 않아
  // 발행 시 본문이 비는 문제가 있음 → HTML 모드(CodeMirror)로 전환해서 확실하게 입력.
  const htmlMode = await switchToHtmlMode(page);

  if (htmlMode) {
    // 이미지 업로드로 이미 삽입된 kage@ 치환문을 회수해서 본문의 {{IMAGE_n}} 위치에 배치
    if (images.length) {
      const current = (await cmGetValue(page)) || '';
      const placeholders = extractImagePlaceholders(current);
      console.log(`   업로드된 이미지 치환문 ${placeholders.length}개 발견`);
      bodyHtml = mergeImagesIntoBody(contentHtml, placeholders, images);
    }
    const ok = await cmSetValue(page, bodyHtml);
    if (!ok) throw new Error('CodeMirror 에 본문을 쓰지 못했습니다.');
    const written = (await cmGetValue(page)) || '';
    console.log(`   본문 입력 확인: ${written.length}자`);
    if (written.length < Math.min(bodyHtml.length, 10)) {
      throw new Error('본문이 입력되지 않았습니다. shots/post-03-content.png 확인.');
    }
  } else {
    // 폴백: 에디터 iframe 안의 body에 직접 타이핑 (서식 없는 텍스트)
    console.log('   HTML 모드 전환 실패 → iframe 직접 타이핑 폴백');
    const frame = page.frameLocator('#editor-tistory_ifr, iframe[id*="_ifr"]').first();
    const body = frame.locator('body#tinymce, body[contenteditable="true"], body').first();
    await body.click();
    const plain = bodyHtml.replace(/<[^>]+>/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
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

  console.log('6) 공개 설정: 공개 (기본값이 비공개이므로 반드시 변경)');
  await selectPublicVisibility(page);
  await shot(page, 'post-05-visibility');

  if (publish === 'reserve') {
    const when = reserveAt instanceof Date ? reserveAt : new Date(reserveAt);
    if (isNaN(when.getTime())) throw new Error(`예약 시각이 올바르지 않습니다: ${reserveAt}`);
    console.log('7) 예약발행 설정:', when.toString());
    await setReserveTime(page, when);
    await shot(page, 'post-06-reserve-set');
  }

  console.log('8) 발행 버튼 클릭');
  // 공개+즉시 → "공개 발행", 공개+예약 → "예약 발행". "비공개 저장"은 절대 클릭하지 않음.
  let publishBtn = page
    .locator('button:has-text("예약 발행"), button:has-text("공개 발행"), button:has-text("보호 발행")')
    .first();
  if (!(await publishBtn.isVisible().catch(() => false))) {
    publishBtn = page
      .locator('button', { hasText: /발행/ })
      .filter({ hasNotText: '비공개' })
      .first();
  }
  if (!(await publishBtn.isVisible().catch(() => false))) {
    await shot(page, 'post-07-no-publish-btn');
    throw new Error(
      '발행 버튼을 찾지 못했습니다. 공개 설정이 적용되지 않아 "비공개 저장"만 보이는 상태일 수 있습니다. ' +
        'shots/post-05-visibility.png 와 shots/post-07-no-publish-btn.png 를 확인하세요.'
    );
  }
  const btnLabel = (await publishBtn.textContent().catch(() => '')).trim();
  console.log(`   클릭할 버튼: "${btnLabel}"`);
  await publishBtn.click();
  await page.waitForTimeout(5000);
  await shot(page, 'post-07-published');
  console.log('   발행 후 URL:', page.url());

  return { status: publish, button: btnLabel, url: page.url() };
}

// 화면에 보이는 요소 중 텍스트가 정확히 일치하는 것을 클릭 (커스텀 라디오/버튼 대응)
async function clickExactText(page, text) {
  return page.evaluate((t) => {
    const els = Array.from(document.querySelectorAll('label, button, span, a, em, strong, div'));
    const el = els.find(
      (e) => e.childElementCount === 0 && e.textContent.trim() === t && e.offsetParent !== null
    );
    if (el) {
      el.click();
      return true;
    }
    return false;
  }, text);
}

// 발행 레이어 하단의 저장/발행 버튼 텍스트 확인 ("비공개 저장" ↔ "공개 발행" ↔ "예약 발행")
async function bottomButtonText(page) {
  return page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('button')).filter(
      (b) => /발행|저장/.test(b.textContent) && b.offsetParent !== null
    );
    const b = btns[btns.length - 1];
    return b ? b.textContent.trim() : '';
  });
}

// "공개" 라디오 선택 + 실제로 적용됐는지 하단 버튼 텍스트로 검증
async function selectPublicVisibility(page) {
  await clickExactText(page, '공개');
  await page.waitForTimeout(700);
  let btn = await bottomButtonText(page);
  console.log(`   하단 버튼 상태: "${btn}"`);

  if (!btn || /비공개/.test(btn)) {
    console.log('   라벨 클릭이 안 먹힘 → 라디오 인풋 직접 클릭 재시도');
    await page.evaluate(() => {
      const byId = document.querySelector('#open20');
      const byVal = document.querySelector('input[type="radio"][value="20"]');
      const byLabel = Array.from(document.querySelectorAll('input[type="radio"]')).find((x) => {
        const lb = x.id && document.querySelector(`label[for="${x.id}"]`);
        return lb && lb.textContent.trim() === '공개';
      });
      const r = byId || byVal || byLabel;
      if (r) {
        r.click();
        r.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
    await page.waitForTimeout(700);
    btn = await bottomButtonText(page);
    console.log(`   하단 버튼 상태(재시도 후): "${btn}"`);
  }

  if (/비공개/.test(btn)) {
    await shot(page, 'post-05-visibility-fail');
    throw new Error(
      '공개 설정 선택에 실패했습니다 (여전히 "비공개 저장" 상태). shots/post-05-visibility-fail.png 를 확인하세요.'
    );
  }
}

// 발행일 → "예약" 선택 후 날짜/시간 입력
async function setReserveTime(page, when) {
  // "예약" 옵션 클릭 (발행일 영역이 접혀 있으면 먼저 펼친다)
  let ok = await clickExactText(page, '예약');
  if (!ok) {
    await clickExactText(page, '발행일');
    await page.waitForTimeout(700);
    ok = await clickExactText(page, '예약');
  }
  if (!ok) {
    await shot(page, 'post-06-reserve-fail');
    throw new Error('발행 레이어에서 "예약" 옵션을 찾지 못했습니다. shots/post-06-reserve-fail.png 확인.');
  }
  await page.waitForTimeout(1000);
  await shot(page, 'post-06-reserve-open');

  const dateStr = `${when.getFullYear()}-${String(when.getMonth() + 1).padStart(2, '0')}-${String(
    when.getDate()
  ).padStart(2, '0')}`;
  const hh = String(when.getHours()).padStart(2, '0');
  const mm = String(when.getMinutes()).padStart(2, '0');

  // React 입력란에도 확실히 반영되도록 네이티브 setter + input/change 이벤트 사용
  const applied = await page.evaluate(
    ({ dateStr, hh, mm }) => {
      const visible = (el) => el.offsetParent !== null;
      const setVal = (el, v) => {
        const proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      };
      const report = { date: null, hour: null, min: null };

      // 날짜: input[type=date] 또는 날짜 형식 값/플레이스홀더를 가진 인풋
      const dateInp =
        Array.from(document.querySelectorAll('input[type="date"]')).find(visible) ||
        Array.from(document.querySelectorAll('input')).find(
          (i) =>
            visible(i) &&
            (/\d{4}\s*[-./]\s*\d{1,2}\s*[-./]\s*\d{1,2}/.test(i.value) ||
              /\d{4}\s*[-./]/.test(i.placeholder || ''))
        );
      if (dateInp) {
        setVal(dateInp, dateInp.type === 'date' ? dateStr : dateStr.replace(/-/g, '. '));
        report.date = dateInp.value;
      }

      // 시/분: 숫자 옵션을 가진 select 들 (통상 순서대로 시 → 분)
      const numSels = Array.from(document.querySelectorAll('select')).filter(
        (s) => visible(s) && Array.from(s.options).some((o) => /^\d{1,2}$/.test(o.value.trim()))
      );
      const pickNearest = (sel, target) => {
        const opts = Array.from(sel.options)
          .map((o) => o.value.trim())
          .filter((v) => /^\d{1,2}$/.test(v));
        let best = opts[0];
        for (const v of opts) {
          if (Math.abs(Number(v) - Number(target)) < Math.abs(Number(best) - Number(target))) best = v;
        }
        setVal(sel, best);
        return best;
      };
      if (numSels[0]) report.hour = pickNearest(numSels[0], hh);
      if (numSels[1]) report.min = pickNearest(numSels[1], mm);
      return report;
    },
    { dateStr, hh, mm }
  );
  console.log('   예약 입력 결과:', JSON.stringify(applied));
  if (!applied.date && applied.hour === null) {
    console.log('   날짜/시간 입력란을 찾지 못했습니다. 기본값(현재 시각 근처)으로 예약될 수 있습니다.');
  }
  await page.waitForTimeout(700);
}

// ---------------------------------------------------------------------------
// 이미지 처리
// 티스토리는 이미지를 업로드하면 카카오 CDN(kage@...)으로 올리고 본문에는
// [##_Image|kage@...|CDM|1.3|{...옵션 JSON...}_##] 치환문을 넣는다.
// 흐름: 기본모드에서 업로드 → HTML 모드로 전환해 치환문 회수 →
//       옵션 JSON에 alt/caption/filename 주입 → 본문의 {{IMAGE_n}} 위치에 배치.
// ---------------------------------------------------------------------------

// 기본모드 에디터에서 이미지 파일들을 업로드 (치환문은 이후 HTML 모드에서 회수)
async function uploadImagesAndCollect(page, images) {
  const countEditorImages = () =>
    page.evaluate(() => {
      const ifr = document.querySelector('iframe[id*="_ifr"]');
      if (!ifr || !ifr.contentDocument) return -1;
      return ifr.contentDocument.querySelectorAll('img').length;
    });

  for (let i = 0; i < images.length; i++) {
    const img = images[i];
    console.log(`   업로드 ${i + 1}/${images.length}: ${img.file}`);
    const before = await countEditorImages();

    // 1차: 숨겨진 파일 인풋에 직접 주입
    let uploaded = false;
    const direct = page.locator('input[type="file"]');
    if ((await direct.count()) > 0) {
      try {
        await direct.first().setInputFiles(img.file);
        uploaded = true;
      } catch (e) {
        console.log(`   파일 인풋 직접 주입 실패(${e.message}) → 사진 버튼 시도`);
      }
    }
    // 2차: 사진 툴바 버튼 클릭 → 파일 선택 다이얼로그
    if (!uploaded) {
      const btn = page
        .locator('[aria-label*="사진"], button[title*="사진"], .mce-i-image, #mceu_0 button')
        .first();
      const [chooser] = await Promise.all([
        page.waitForEvent('filechooser', { timeout: 15000 }),
        btn.click(),
      ]);
      await chooser.setFiles(img.file);
    }

    // 업로드 완료 대기: 에디터 안의 이미지 개수가 늘어날 때까지
    await page
      .waitForFunction(
        (prev) => {
          const ifr = document.querySelector('iframe[id*="_ifr"]');
          if (!ifr || !ifr.contentDocument) return false;
          return ifr.contentDocument.querySelectorAll('img').length > prev;
        },
        before,
        { timeout: 30000 }
      )
      .catch(() => console.log('   업로드 완료를 감지하지 못했습니다 (계속 진행).'));
    await page.waitForTimeout(1500);
  }
  await shot(page, 'post-02b-images-uploaded');
}

// 본문(HTML 모드 텍스트)에서 이미지 치환문 추출
function extractImagePlaceholders(html) {
  return html.match(/\[##_Image\|[\s\S]*?_##\]/g) || [];
}

// 치환문의 옵션 JSON에 alt / caption / filename 주입
function enhancePlaceholder(ph, meta = {}) {
  const m = ph.match(/^(\[##_Image\|[\s\S]*?\|CDM\|[\d.]+\|)(\{[\s\S]*\})(_##\])$/);
  if (!m) return ph;
  let opts;
  try {
    opts = JSON.parse(m[2]);
  } catch {
    return ph;
  }
  if (meta.alt) opts.alt = meta.alt;
  if (meta.caption) opts.caption = meta.caption;
  if (meta.filename) opts.filename = meta.filename;
  return m[1] + JSON.stringify(opts) + m[3];
}

// 업로드로 생긴 치환문(순서대로)을 images 메타와 매칭해 본문의 {{IMAGE_n}} 자리에 배치.
// 토큰이 없는 이미지는 본문 끝에 덧붙인다.
function mergeImagesIntoBody(bodyHtml, placeholders, images) {
  let out = bodyHtml;
  placeholders.forEach((ph, i) => {
    const meta = images[i] || {};
    const enhanced = enhancePlaceholder(ph, {
      alt: meta.alt,
      caption: meta.caption,
      filename: meta.filename || (meta.file ? path.basename(meta.file) : undefined),
    });
    const token = `{{IMAGE_${i}}}`;
    const wrapped = new RegExp(`<p>\\s*\\{\\{IMAGE_${i}\\}\\}\\s*</p>`);
    if (wrapped.test(out)) {
      out = out.replace(wrapped, `<p>${enhanced}</p>`); // 이미 <p>로 감싸져 있으면 그대로 교체
    } else if (out.includes(token)) {
      out = out.replace(token, `<p>${enhanced}</p>`);
    } else {
      out += `\n<p>${enhanced}</p>`;
    }
  });
  return out.replace(/\{\{IMAGE_\d+\}\}/g, ''); // 매칭 안 된 토큰 정리
}

module.exports = {
  launch,
  saveState,
  isLoggedIn,
  login,
  writePost,
  shot,
  STATE_FILE,
  extractImagePlaceholders,
  enhancePlaceholder,
  mergeImagesIntoBody,
};
