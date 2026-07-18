// 이미지 생성 공급자 래퍼 — 프롬프트 → 이미지 파일 저장
// 지원: pollinations(무료, 키 불필요) / together(FLUX schnell) / openai(gpt-image-1)
//
// 반환: 저장된 파일의 절대경로

const fs = require('fs');
const path = require('path');

const IMG_PROVIDERS = ['pollinations', 'together', 'openai'];

function pickImageProvider(requested) {
  if (requested) {
    if (!IMG_PROVIDERS.includes(requested)) {
      throw new Error(`지원하지 않는 이미지 공급자: ${requested} (가능: ${IMG_PROVIDERS.join(', ')})`);
    }
    return requested;
  }
  if (process.env.IMG_PROVIDER) return pickImageProvider(process.env.IMG_PROVIDER);
  if (process.env.TOGETHER_API_KEY) return 'together';
  if (process.env.OPENAI_API_KEY) return 'openai';
  return 'pollinations'; // 키가 없어도 동작하는 무료 기본값
}

async function fetchToFile(url, options, outFile) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`이미지 요청 실패 ${res.status}: ${(await res.text()).slice(0, 300)}`);
  const buf = Buffer.from(await res.arrayBuffer());
  if (buf.length < 100) throw new Error('이미지 응답이 너무 작습니다(생성 실패로 추정).');
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  fs.writeFileSync(outFile, buf);
  return outFile;
}

// Pollinations: 무료, API 키 불필요. GET 요청으로 바로 이미지 반환
async function genPollinations(prompt, outFile, { width, height, seed }) {
  const model = process.env.POLLINATIONS_MODEL || 'flux';
  const params = new URLSearchParams({
    width: String(width),
    height: String(height),
    nologo: 'true',
    model,
  });
  if (seed !== undefined) params.set('seed', String(seed));
  const url = `https://image.pollinations.ai/prompt/${encodeURIComponent(prompt)}?${params}`;
  return fetchToFile(url, { method: 'GET' }, outFile);
}

// Together AI: FLUX.1 schnell (매우 저렴). base64 응답
async function genTogether(prompt, outFile, { width, height }) {
  const key = process.env.TOGETHER_API_KEY;
  if (!key) throw new Error('.env 에 TOGETHER_API_KEY 를 설정하세요.');
  const model = process.env.TOGETHER_IMAGE_MODEL || 'black-forest-labs/FLUX.1-schnell-Free';
  const res = await fetch('https://api.together.xyz/v1/images/generations', {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` },
    body: JSON.stringify({ model, prompt, width, height, n: 1, response_format: 'b64_json' }),
  });
  if (!res.ok) throw new Error(`Together 이미지 오류 ${res.status}: ${(await res.text()).slice(0, 300)}`);
  const data = await res.json();
  const b64 = data.data?.[0]?.b64_json;
  if (!b64) throw new Error('Together 응답에 이미지가 없습니다: ' + JSON.stringify(data).slice(0, 300));
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  fs.writeFileSync(outFile, Buffer.from(b64, 'base64'));
  return outFile;
}

// OpenAI gpt-image-1
async function genOpenAI(prompt, outFile, { width, height }) {
  const key = process.env.OPENAI_API_KEY;
  if (!key) throw new Error('.env 에 OPENAI_API_KEY 를 설정하세요.');
  // gpt-image-1 은 정사각/세로/가로 프리셋만 허용 → 비율로 근사
  const size = width > height ? '1536x1024' : width < height ? '1024x1536' : '1024x1024';
  const res = await fetch('https://api.openai.com/v1/images/generations', {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` },
    body: JSON.stringify({ model: 'gpt-image-1', prompt, size, n: 1 }),
  });
  if (!res.ok) throw new Error(`OpenAI 이미지 오류 ${res.status}: ${(await res.text()).slice(0, 300)}`);
  const data = await res.json();
  const b64 = data.data?.[0]?.b64_json;
  if (!b64) throw new Error('OpenAI 응답에 이미지가 없습니다: ' + JSON.stringify(data).slice(0, 300));
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  fs.writeFileSync(outFile, Buffer.from(b64, 'base64'));
  return outFile;
}

/**
 * 이미지 한 장 생성
 * @param {string} prompt 영문 이미지 프롬프트
 * @param {string} outFile 저장 경로
 * @param {object} opts { width, height, seed, provider }
 */
async function generateImage(prompt, outFile, opts = {}) {
  const provider = pickImageProvider(opts.provider);
  const width = opts.width || 1024;
  const height = opts.height || 576; // 16:9 기본
  const fn = { pollinations: genPollinations, together: genTogether, openai: genOpenAI }[provider];
  console.log(`  이미지 생성(${provider}, ${width}x${height}): "${prompt.slice(0, 60)}..."`);
  return fn(prompt, outFile, { width, height, seed: opts.seed });
}

module.exports = { generateImage, pickImageProvider, IMG_PROVIDERS };
