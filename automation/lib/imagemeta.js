// 이미지 메타데이터(alt / caption / filename)를 "생성 시점"에 확정·정규화한다.
// LLM이 값을 빠뜨려도 기본값을 채워, 이미지와 함께 저장되어 발행 시 치환문에 정확히 주입되게 한다.
//
// 규칙:
//  - alt      : 없으면 제목/키워드로 채움 (접근성·SEO 필수)
//  - caption  : 없으면 빈 문자열 (선택)
//  - filename : 없으면 "<키워드슬러그>-<번호>.webp", 항상 안전한 문자로 정리 + 이미지 확장자 보장

const IMG_EXT = ['webp', 'png', 'jpg', 'jpeg', 'gif'];

function slugify(s) {
  return String(s || '')
    .trim()
    .replace(/[\\/:*?"<>|]+/g, '')
    .replace(/\s+/g, '-')
    .slice(0, 40);
}

// 파일명 안전화: 경로/금지문자 제거, 공백→_, 이미지 확장자 보장 (한글 허용)
function sanitizeFilename(name, fallback) {
  let n = String(name || '').trim().replace(/[\\/:*?"<>|]+/g, '').replace(/\s+/g, '_');
  if (!n) n = fallback;
  const m = n.match(/\.([a-z0-9]+)$/i);
  if (!m || !IMG_EXT.includes(m[1].toLowerCase())) n = n.replace(/\.[a-z0-9]+$/i, '') + '.webp';
  return n.slice(0, 80);
}

// 확장자 뗀 이름 (디스크 저장 stem 용)
function stem(filename) {
  return String(filename || '').replace(/\.[a-z0-9]+$/i, '') || 'image';
}

/**
 * images 배열의 alt/caption/filename 을 확정·정규화 (생성 시점 호출)
 * @param {Array} images  [{prompt, alt?, caption?, filename?}]
 * @param {object} ctx    { title, keyword }
 */
function normalizeImages(images, ctx = {}) {
  const base = slugify(ctx.keyword || ctx.title || 'image') || 'image';
  const seen = new Set();
  return (images || []).map((im, i) => {
    const alt = (im.alt || '').trim() || (ctx.title || ctx.keyword || `이미지 ${i + 1}`);
    const caption = (im.caption || '').trim();
    let filename = sanitizeFilename(im.filename, `${base}-${i + 1}.webp`);
    // 파일명 중복 방지
    if (seen.has(filename.toLowerCase())) {
      const s = stem(filename), e = filename.slice(s.length);
      filename = `${s}-${i + 1}${e}`;
    }
    seen.add(filename.toLowerCase());
    return { ...im, alt, caption, filename };
  });
}

module.exports = { normalizeImages, sanitizeFilename, stem, slugify, IMG_EXT };
