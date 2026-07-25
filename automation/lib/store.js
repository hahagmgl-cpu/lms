// 콘텐츠 큐 저장소
// - 글 1건 = content/queue/<id>/ 폴더 (post.json + images/) 를 "원본"으로
// - 전체 목록은 엑셀(index.xlsx) + CSV(index.csv) 인덱스로 한눈에 보고 편집
// - 생성(produce)과 발행(publish)을 분리: 상태(status)와 예약시각으로 관리
//
// status: draft(초안) | ready(발행대기) | scheduled(예약) | published(완료) | failed(실패)

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..', '..');
const QUEUE_DIR = process.env.QUEUE_DIR || path.join(ROOT, 'content', 'queue');
const INDEX_XLSX = path.join(QUEUE_DIR, 'index.xlsx');
const INDEX_CSV = path.join(QUEUE_DIR, 'index.csv');

// 엑셀은 있으면 사용, 없으면 CSV만 (라이브러리 미설치 대비)
let XLSX = null;
try { XLSX = require('@e965/xlsx'); } catch { /* CSV 폴백 */ }

// 인덱스에서 사용자가 엑셀로 편집해 되돌릴 수 있는 컬럼
const EDITABLE = ['title', 'tags', 'status', 'scheduleAt', 'blog'];
const COLUMNS = ['id', 'keyword', 'title', 'tags', 'status', 'scheduleAt', 'publishedUrl', 'images', 'createdAt', 'updatedAt'];

function slugify(s) {
  return String(s || 'post')
    .trim()
    .replace(/[\\/:*?"<>|]+/g, '')
    .replace(/\s+/g, '-')
    .slice(0, 40) || 'post';
}

function stamp(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

function postDir(id) { return path.join(QUEUE_DIR, id); }
function postFile(id) { return path.join(postDir(id), 'post.json'); }
function imagesDir(id) { return path.join(postDir(id), 'images'); }

function getPost(id) {
  const f = postFile(id);
  if (!fs.existsSync(f)) return null;
  return JSON.parse(fs.readFileSync(f, 'utf8'));
}

function writePost(post) {
  fs.mkdirSync(postDir(post.id), { recursive: true });
  post.updatedAt = new Date().toISOString();
  fs.writeFileSync(postFile(post.id), JSON.stringify(post, null, 2), 'utf8');
  return post;
}

// 새 글을 큐에 생성. article = { title, html, tags, images, metaDescription, searchIntent }
function createPost(article, opts = {}) {
  const id = `${stamp()}-${slugify(opts.keyword || article.title)}`;
  const post = {
    id,
    keyword: opts.keyword || '',
    title: article.title || '',
    metaDescription: article.metaDescription || '',
    searchIntent: article.searchIntent || '',
    html: article.html || '',
    tags: article.tags || [],
    images: (article.images || []).map((im) => ({ ...im })),
    status: 'draft',
    scheduleAt: null,
    blog: opts.blog || '',
    publishedUrl: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  writePost(post);
  return post;
}

function updatePost(id, patch) {
  const post = getPost(id);
  if (!post) throw new Error('글을 찾을 수 없습니다: ' + id);
  Object.assign(post, patch);
  return writePost(post);
}

function listPosts() {
  if (!fs.existsSync(QUEUE_DIR)) return [];
  return fs
    .readdirSync(QUEUE_DIR)
    .filter((d) => fs.existsSync(postFile(d)))
    .map((d) => getPost(d))
    .filter(Boolean)
    .sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
}

function toRow(p) {
  return {
    id: p.id,
    keyword: p.keyword || '',
    title: p.title || '',
    tags: (p.tags || []).join(', '),
    status: p.status || 'draft',
    scheduleAt: p.scheduleAt || '',
    publishedUrl: p.publishedUrl || '',
    images: (p.images || []).length,
    createdAt: p.createdAt || '',
    updatedAt: p.updatedAt || '',
  };
}

// 수식 트리거 문자(=,+,-,@)로 시작하면 앞에 '(작은따옴표)를 붙여 Excel/CSV에서 수식으로 해석되지 않게 함
function csvCell(v) {
  let s = String(v == null ? '' : v);
  if (/^[=+\-@]/.test(s)) s = "'" + s;
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

// 인덱스(엑셀+CSV) 재작성
function writeIndex() {
  fs.mkdirSync(QUEUE_DIR, { recursive: true });
  const rows = listPosts().map(toRow);

  // CSV (UTF-8 BOM → 엑셀에서 한글 정상)
  const csv = [COLUMNS.join(',')]
    .concat(rows.map((r) => COLUMNS.map((c) => csvCell(r[c])).join(',')))
    .join('\n');
  fs.writeFileSync(INDEX_CSV, '﻿' + csv, 'utf8');

  if (XLSX) {
    const ws = XLSX.utils.json_to_sheet(rows, { header: COLUMNS });
    ws['!cols'] = [
      { wch: 22 }, { wch: 16 }, { wch: 40 }, { wch: 24 }, { wch: 10 },
      { wch: 18 }, { wch: 30 }, { wch: 7 }, { wch: 20 }, { wch: 20 },
    ];
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, '큐');
    XLSX.writeFile(wb, INDEX_XLSX);
  }
  return { csv: INDEX_CSV, xlsx: XLSX ? INDEX_XLSX : null, count: rows.length };
}

// 엑셀/CSV 에서 편집한 내용을 post.json 으로 반영 (편집 가능 컬럼만)
function syncFromIndex() {
  let rows = [];
  if (XLSX && fs.existsSync(INDEX_XLSX)) {
    const wb = XLSX.readFile(INDEX_XLSX);
    rows = XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]]);
  } else if (fs.existsSync(INDEX_CSV)) {
    rows = parseCsv(fs.readFileSync(INDEX_CSV, 'utf8').replace(/^﻿/, ''));
  } else {
    return { updated: 0 };
  }
  let updated = 0;
  for (const row of rows) {
    if (!row.id) continue;
    const post = getPost(String(row.id).trim());
    if (!post) continue;
    const patch = {};
    for (const key of EDITABLE) {
      if (row[key] === undefined) continue;
      if (key === 'tags') patch.tags = String(row.tags).split(',').map((t) => t.trim()).filter(Boolean);
      else patch[key] = row[key] === '' ? (key === 'scheduleAt' ? null : post[key]) : row[key];
    }
    if (Object.keys(patch).length) { updatePost(post.id, patch); updated++; }
  }
  return { updated };
}

// 아주 단순한 CSV 파서 (헤더 있는 표, 따옴표 처리)
function parseCsv(text) {
  const lines = [];
  let cur = [], field = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') q = false;
      else field += c;
    } else if (c === '"') q = true;
    else if (c === ',') { cur.push(field); field = ''; }
    else if (c === '\n') { cur.push(field); lines.push(cur); cur = []; field = ''; }
    else if (c === '\r') { /* skip */ }
    else field += c;
  }
  if (field.length || cur.length) { cur.push(field); lines.push(cur); }
  if (!lines.length) return [];
  const header = lines[0];
  return lines.slice(1).filter((l) => l.some((x) => x !== '')).map((l) => {
    const o = {};
    header.forEach((h, i) => (o[h] = l[i]));
    return o;
  });
}

module.exports = {
  QUEUE_DIR, INDEX_XLSX, INDEX_CSV, hasExcel: !!XLSX,
  slugify, postDir, postFile, imagesDir,
  createPost, getPost, updatePost, writePost, listPosts,
  writeIndex, syncFromIndex, toRow,
};
