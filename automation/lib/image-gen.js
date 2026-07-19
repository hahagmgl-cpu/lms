// 이미지 생성 공급자 래퍼 — 프롬프트 → 이미지 파일 저장
// 지원: pollinations / huggingface / together / openai
//
// 반환: 저장된 파일의 절대경로

const fs = require('fs');
const path = require('path');

const IMG_PROVIDERS = ['pollinations', 'huggingface', 'together', 'openai'];

function pickImageProvider(requested) {
  if (requested) {
    if (!IMG_PROVIDERS.includes(requested)) {
      throw new Error(`지원하지 않는 이미지 공급자: ${requested} (가능: ${IMG_PROVIDERS.join(', ')})`);
    }
    return requested;
  }
  if (process.env.IMG_PROVIDER) return pickImageProvider(process.env.IMG_PROVIDER);
  if (process.env.TOGETHER_API_KEY) return 'together';
  if (process.env.HF_TOKEN || process.env.HUGGINGFACE_TOKEN) return 'huggingface';
  if (process.env.OPENAI_API_KEY) return 'openai';
  return 'pollinations'; // 키 없이 시도하는 기본값 (무료 잔액 소진 시 402 가능)
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

// Pollinations: 토큰 없으면 무료 시도(잔액 소진 시 402). 토큰 있으면 Bearer 로 전송.
async function genPollinations(prompt, outFile, { width, height, seed, model }) {
  model = model || process.env.POLLINATIONS_MODEL || 'flux';
  const token = process.env.POLLINATIONS_TOKEN || process.env.POLLINATIONS_KEY;
  const params = new URLSearchParams({ width: String(width), height: String(height), nologo: 'true', model });
  if (seed !== undefined) params.set('seed', String(seed));
  if (process.env.POLLINATIONS_REFERRER) params.set('referrer', process.env.POLLINATIONS_REFERRER);
  const url = `https://image.pollinations.ai/prompt/${encodeURIComponent(prompt)}?${params}`;
  const headers = token ? { authorization: `Bearer ${token}` } : {};
  const res = await fetch(url, { method: 'GET', headers });
  if (!res.ok) {
    const body = (await res.text()).slice(0, 400);
    if (res.status === 402 || /PAYMENT_REQUIRED|budget too low/i.test(body)) {
      throw new Error(
        'Pollinations 무료 잔액(pollen)이 없습니다. 이미지 공급자를 바꾸세요:\n' +
          '  · 무료: Hugging Face (HF_TOKEN 발급 https://huggingface.co/settings/tokens, IMG_PROVIDER=huggingface)\n' +
          '  · 무료: Together FLUX (TOGETHER_API_KEY https://api.together.xyz, IMG_PROVIDER=together)\n' +
          '  · 또는 Pollinations 토큰 발급 후 .env 에 POLLINATIONS_TOKEN 설정\n원문: ' + body
      );
    }
    throw new Error(`Pollinations 이미지 오류 ${res.status}: ${body}`);
  }
  const buf = Buffer.from(await res.arrayBuffer());
  if (buf.length < 100) throw new Error('Pollinations 응답이 너무 작습니다(생성 실패).');
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  fs.writeFileSync(outFile, buf);
  return outFile;
}

// Hugging Face Inference: 무료 등급 제공 (무료 토큰 필요). FLUX.1-schnell 이미지 바이트 반환.
async function genHuggingFace(prompt, outFile, { model }) {
  const key = process.env.HF_TOKEN || process.env.HUGGINGFACE_TOKEN;
  if (!key) throw new Error('.env 에 HF_TOKEN 을 설정하세요 (무료 발급: https://huggingface.co/settings/tokens).');
  model = model || process.env.HF_IMAGE_MODEL || 'black-forest-labs/FLUX.1-schnell';
  const res = await fetch(`https://api-inference.huggingface.co/models/${model}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` },
    body: JSON.stringify({ inputs: prompt }),
  });
  if (!res.ok) {
    const body = (await res.text()).slice(0, 400);
    if (res.status === 503) throw new Error('Hugging Face 모델 로딩 중입니다. 잠시 후 다시 시도하세요.\n' + body);
    throw new Error(`Hugging Face 이미지 오류 ${res.status}: ${body}`);
  }
  const buf = Buffer.from(await res.arrayBuffer());
  if (buf.length < 100) throw new Error('Hugging Face 응답이 너무 작습니다(생성 실패).');
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  fs.writeFileSync(outFile, buf);
  return outFile;
}

// Together AI: FLUX.1 schnell (매우 저렴). base64 응답
async function genTogether(prompt, outFile, { width, height, model }) {
  const key = process.env.TOGETHER_API_KEY;
  if (!key) throw new Error('.env 에 TOGETHER_API_KEY 를 설정하세요.');
  model = model || process.env.TOGETHER_IMAGE_MODEL || 'black-forest-labs/FLUX.1-schnell-Free';
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
 * @param {object} opts { width, height, seed, provider, model }
 */
async function generateImage(prompt, outFile, opts = {}) {
  const provider = pickImageProvider(opts.provider);
  const width = opts.width || 1024;
  const height = opts.height || 576; // 16:9 기본
  const fn = { pollinations: genPollinations, huggingface: genHuggingFace, together: genTogether, openai: genOpenAI }[provider];
  console.log(`  이미지 생성(${provider}, ${width}x${height}): "${prompt.slice(0, 60)}..."`);
  return fn(prompt, outFile, { width, height, seed: opts.seed, model: opts.model });
}

module.exports = { generateImage, pickImageProvider, IMG_PROVIDERS };
