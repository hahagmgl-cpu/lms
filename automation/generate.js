// Claude API로 블로그 글(제목/본문 HTML/태그) 자동 생성
//
// 사용법:
//   .env 에 ANTHROPIC_API_KEY 설정 후
//   node automation/generate.js "주제 키워드" [출력파일.json]
//
// 생성된 JSON은 post.js 로 바로 발행할 수 있습니다:
//   node automation/generate.js "여름 제철 음식 추천" content/generated.json
//   node automation/post.js --file content/generated.json --publish reserve --at "2026-07-18T09:00"

const fs = require('fs');
const path = require('path');
const { loadEnv } = require('./lib/env');

loadEnv();

const MODEL = process.env.CLAUDE_MODEL || 'claude-sonnet-5';

async function generatePost(topic) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) throw new Error('.env 에 ANTHROPIC_API_KEY 를 설정하세요.');

  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 4096,
      messages: [
        {
          role: 'user',
          content:
            `다음 주제로 티스토리 블로그 글을 한국어로 작성해줘: "${topic}"\n\n` +
            '요구사항:\n' +
            '- 제목은 검색 노출(SEO)에 유리하게\n' +
            '- 본문은 HTML로 작성 (h2/h3 소제목, p, ul/li 활용, 1500자 이상)\n' +
            '- 태그 5개 추천\n\n' +
            '아래 JSON 형식으로만 응답해 (다른 텍스트 없이):\n' +
            '{"title": "...", "html": "...", "tags": ["...", "..."]}',
        },
      ],
    }),
  });

  if (!res.ok) {
    throw new Error(`Claude API 오류 ${res.status}: ${await res.text()}`);
  }
  const data = await res.json();
  const text = data.content.map((b) => b.text || '').join('');
  const jsonMatch = text.match(/\{[\s\S]*\}/);
  if (!jsonMatch) throw new Error('응답에서 JSON을 찾지 못했습니다:\n' + text);
  return JSON.parse(jsonMatch[0]);
}

(async () => {
  const topic = process.argv[2];
  const outFile = process.argv[3] || path.join(__dirname, '..', 'content', 'generated.json');
  if (!topic) {
    console.error('사용법: node automation/generate.js "주제" [출력파일.json]');
    process.exit(1);
  }

  console.log(`주제: ${topic}\n모델: ${MODEL}\n생성 중...`);
  const post = await generatePost(topic);
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  fs.writeFileSync(outFile, JSON.stringify(post, null, 2), 'utf8');
  console.log(`\n생성 완료 → ${outFile}`);
  console.log(`제목: ${post.title}`);
  console.log(`태그: ${(post.tags || []).join(', ')}`);
  console.log(`\n발행: node automation/post.js --file ${outFile} --publish now`);
})().catch((e) => {
  console.error('ERROR:', e.message);
  process.exit(1);
});
