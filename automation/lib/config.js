// 설정 로더: config/defaults.json + config/config.json(사용자 오버라이드) 딥머지
// 모델·공급자를 언제든 바꿀 수 있게 한 곳에서 관리한다. API 키는 .env 에.

const fs = require('fs');
const path = require('path');

const CONFIG_DIR = path.join(__dirname, '..', '..', 'config');
const DEFAULTS = path.join(CONFIG_DIR, 'defaults.json');
const OVERRIDE = path.join(CONFIG_DIR, 'config.json');

function deepMerge(base, over) {
  if (Array.isArray(over)) return over.slice();
  if (over && typeof over === 'object' && base && typeof base === 'object' && !Array.isArray(base)) {
    const out = { ...base };
    for (const k of Object.keys(over)) out[k] = deepMerge(base[k], over[k]);
    return out;
  }
  return over === undefined ? base : over;
}

function load() {
  let cfg = {};
  if (fs.existsSync(DEFAULTS)) cfg = JSON.parse(fs.readFileSync(DEFAULTS, 'utf8'));
  if (fs.existsSync(OVERRIDE)) {
    try {
      cfg = deepMerge(cfg, JSON.parse(fs.readFileSync(OVERRIDE, 'utf8')));
    } catch (e) {
      console.error('config.json 파싱 오류(무시하고 기본값 사용):', e.message);
    }
  }
  delete cfg._comment;
  return cfg;
}

// 사용자 오버라이드 저장 (GUI 설정 탭에서 호출). defaults 는 건드리지 않음.
function saveOverride(partial) {
  fs.mkdirSync(CONFIG_DIR, { recursive: true });
  let cur = {};
  if (fs.existsSync(OVERRIDE)) {
    try { cur = JSON.parse(fs.readFileSync(OVERRIDE, 'utf8')); } catch {}
  }
  const merged = deepMerge(cur, partial);
  fs.writeFileSync(OVERRIDE, JSON.stringify(merged, null, 2), 'utf8');
  return merged;
}

// 텍스트 공급자별 모델명 (env 오버라이드 > config)
function textModel(cfg, provider) {
  const envMap = { openai: 'OPENAI_MODEL', gemini: 'GEMINI_MODEL', claude: 'CLAUDE_MODEL' };
  return process.env[envMap[provider]] || (cfg.text.models || {})[provider];
}

function imageModel(cfg, provider) {
  const envMap = { pollinations: 'POLLINATIONS_MODEL', together: 'TOGETHER_IMAGE_MODEL', openai: 'OPENAI_IMAGE_MODEL' };
  return process.env[envMap[provider]] || (cfg.image.models || {})[provider];
}

module.exports = { load, saveOverride, textModel, imageModel, deepMerge, CONFIG_DIR, OVERRIDE };
