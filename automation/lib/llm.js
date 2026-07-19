// LLM 공급자 공통 래퍼 — OpenAI(GPT) / Google Gemini / Anthropic Claude
// 모두 "프롬프트 → JSON 텍스트 응답" 형태로 통일해서 사용한다.

const PROVIDERS = ['openai', 'gemini', 'claude'];

function pickProvider(requested) {
  if (requested) {
    if (!PROVIDERS.includes(requested)) {
      throw new Error(`지원하지 않는 provider: ${requested} (가능: ${PROVIDERS.join(', ')})`);
    }
    return requested;
  }
  if (process.env.GEN_PROVIDER) return pickProvider(process.env.GEN_PROVIDER);
  // 키가 설정된 공급자를 자동 선택
  if (process.env.OPENAI_API_KEY) return 'openai';
  if (process.env.GEMINI_API_KEY) return 'gemini';
  if (process.env.ANTHROPIC_API_KEY) return 'claude';
  throw new Error(
    '.env 에 OPENAI_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY 중 하나 이상을 설정하세요.'
  );
}

async function callOpenAI(prompt, opts = {}) {
  const key = process.env.OPENAI_API_KEY;
  if (!key) throw new Error('.env 에 OPENAI_API_KEY 를 설정하세요.');
  const model = opts.model || process.env.OPENAI_MODEL || 'gpt-4o-mini';

  const res = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` },
    body: JSON.stringify({
      model,
      messages: [
        { role: 'system', content: '당신은 한국어 SEO 블로그 전문 작가입니다. 요청한 형식 그대로 정확히 출력합니다.' },
        { role: 'user', content: prompt },
      ],
      ...(opts.json === false ? {} : { response_format: { type: 'json_object' } }),
      temperature: opts.temperature ?? 0.7,
    }),
  });
  if (!res.ok) {
    const body = await res.text();
    if (res.status === 429 && /insufficient_quota/.test(body)) {
      throw new Error(
        'OpenAI 크레딧(잔액)이 없습니다. OpenAI API는 유료라 선불 충전이 필요합니다 ' +
          '(ChatGPT Plus 구독과 별개). 결제: https://platform.openai.com/settings/organization/billing\n' +
          '→ 무료로 쓰려면 설정에서 공급자를 "제미나이(gemini)"로 바꾸세요.'
      );
    }
    if (res.status === 401) {
      throw new Error('OpenAI 키가 유효하지 않습니다(.env 의 OPENAI_API_KEY 확인). 키 발급: https://platform.openai.com/api-keys');
    }
    throw new Error(`OpenAI API 오류 ${res.status}: ${body}`);
  }
  const data = await res.json();
  return { text: data.choices[0].message.content, model };
}

async function callGemini(prompt, opts = {}) {
  const key = process.env.GEMINI_API_KEY;
  if (!key) throw new Error('.env 에 GEMINI_API_KEY 를 설정하세요.');
  const model = opts.model || process.env.GEMINI_MODEL || 'gemini-flash-latest';

  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${key}`,
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: {
          ...(opts.json === false ? {} : { responseMimeType: 'application/json' }),
          temperature: opts.temperature ?? 0.7,
        },
      }),
    }
  );
  if (!res.ok) {
    const body = await res.text();
    if (res.status === 404 && /model/i.test(body)) {
      throw new Error(
        `Gemini 모델 "${model}" 을(를) 쓸 수 없습니다. 설정 탭(또는 config/config.json, .env 의 GEMINI_MODEL)에서 ` +
          `모델명을 바꾸세요. 안전한 기본값: "gemini-flash-latest" (항상 최신). 사용 가능 목록: https://ai.google.dev/gemini-api/docs/models\n원문: ${body}`
      );
    }
    throw new Error(`Gemini API 오류 ${res.status}: ${body}`);
  }
  const data = await res.json();
  const text = (data.candidates?.[0]?.content?.parts || []).map((p) => p.text || '').join('');
  if (!text) throw new Error('Gemini 응답이 비어 있습니다: ' + JSON.stringify(data).slice(0, 500));
  return { text, model };
}

async function callClaude(prompt, opts = {}) {
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) throw new Error('.env 에 ANTHROPIC_API_KEY 를 설정하세요.');
  const model = opts.model || process.env.CLAUDE_MODEL || 'claude-sonnet-5';

  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-api-key': key,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model,
      max_tokens: opts.maxTokens || 8192,
      messages: [{ role: 'user', content: prompt }],
    }),
  });
  if (!res.ok) throw new Error(`Claude API 오류 ${res.status}: ${await res.text()}`);
  const data = await res.json();
  return { text: data.content.map((b) => b.text || '').join(''), model };
}

// 응답 텍스트에서 JSON 객체 파싱 (코드펜스/앞뒤 잡담 + 흔한 깨짐 자동 복구)
function parseJsonResponse(text) {
  const cleaned = text.replace(/```json\s*|```\s*/g, '');
  const m = cleaned.match(/\{[\s\S]*\}/);
  if (!m) throw new Error('응답에서 JSON을 찾지 못했습니다:\n' + text.slice(0, 800));
  const noTrailComma = (s) => s.replace(/,(\s*[}\]])/g, '$1');
  // 모든 제어문자(U+0000~U+001F: 줄바꿈·탭·수직탭·폼피드 등)를 공백으로.
  // JSON 문자열 안의 이스케이프 안 된 제어문자가 "Bad control character" 오류의 원인.
  const stripCtrl = (s) => s.replace(/[\u0000-\u001f]+/g, ' ');
  const candidates = [
    m[0],
    noTrailComma(m[0]),
    noTrailComma(stripCtrl(m[0])),
  ];
  let lastErr;
  for (const c of candidates) {
    try { return JSON.parse(c); } catch (e) { lastErr = e; }
  }
  throw lastErr;
}

// opts: { model, temperature, maxTokens } — 설정에서 넘긴 모델을 그대로 사용
// JSON 파싱 실패 시 최대 3회까지 재생성 (모델 응답이 비결정적이라 대개 재시도로 해결)
async function generateJson(prompt, provider, opts = {}) {
  const p = pickProvider(provider);
  const call = { openai: callOpenAI, gemini: callGemini, claude: callClaude }[p];
  console.log(`공급자: ${p}`);
  let lastErr;
  for (let attempt = 1; attempt <= 3; attempt++) {
    const { text, model } = await call(prompt, opts);
    if (attempt === 1) console.log(`모델: ${model}`);
    try {
      return parseJsonResponse(text);
    } catch (e) {
      lastErr = e;
      console.log(`  JSON 파싱 실패 (시도 ${attempt}/3): ${e.message}${attempt < 3 ? ' → 재생성' : ''}`);
    }
  }
  throw new Error('여러 번 시도했지만 유효한 JSON을 얻지 못했습니다: ' + lastErr.message);
}

// 원문 텍스트 생성 (JSON 모드 끔). parseFn 으로 검증/파싱, 실패 시 최대 3회 재생성.
async function generateText(prompt, provider, opts = {}, parseFn) {
  const p = pickProvider(provider);
  const call = { openai: callOpenAI, gemini: callGemini, claude: callClaude }[p];
  console.log(`공급자: ${p}`);
  let lastErr;
  for (let attempt = 1; attempt <= 3; attempt++) {
    const { text, model } = await call(prompt, { ...opts, json: false });
    if (attempt === 1) console.log(`모델: ${model}`);
    if (!parseFn) return text;
    try {
      return parseFn(text);
    } catch (e) {
      lastErr = e;
      console.log(`  응답 파싱 실패 (시도 ${attempt}/3): ${e.message}${attempt < 3 ? ' → 재생성' : ''}`);
    }
  }
  throw new Error('여러 번 시도했지만 형식에 맞는 응답을 얻지 못했습니다: ' + lastErr.message);
}

module.exports = { generateJson, generateText, pickProvider, parseJsonResponse, PROVIDERS };
