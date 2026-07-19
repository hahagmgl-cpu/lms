// 글 JSON의 images[].prompt 로 이미지를 생성하고 file 경로를 채워 넣는다.
//
// 사용법:
//   node automation/gen-image.js content/generated.json
//   node automation/gen-image.js content/generated.json --provider pollinations
//   node automation/gen-image.js content/generated.json --width 1024 --height 576
//
// 결과: 같은 JSON 파일의 images[].file 이 채워지고, 이미지는 content/images/ 에 저장됨.
// 이후 바로 발행: node automation/post.js --file content/generated.json --publish reserve

const fs = require('fs');
const path = require('path');
const { loadEnv } = require('./lib/env');
const { generateImage } = require('./lib/image-gen');
const { normalizeImages, stem } = require('./lib/imagemeta');

loadEnv();

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 2; i < argv.length; i++) {
    if (argv[i].startsWith('--')) {
      const key = argv[i].slice(2);
      const val = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[++i] : true;
      args[key] = val;
    } else args._.push(argv[i]);
  }
  return args;
}

async function fillImages(jsonFile, opts) {
  const data = JSON.parse(fs.readFileSync(jsonFile, 'utf8'));
  // 메타(alt/caption/filename) 확정·정규화 후 저장 (생성 시점에 확정 보장)
  data.images = normalizeImages(data.images, { title: data.title, keyword: data.keyword });
  const images = data.images;
  if (!images.length) {
    console.log('images 항목이 없습니다. 건너뜁니다.');
    fs.writeFileSync(jsonFile, JSON.stringify(data, null, 2), 'utf8');
    return data;
  }
  const outDir = path.join(path.dirname(path.resolve(jsonFile)), 'images');
  const width = opts.width ? Number(opts.width) : 1024;
  const height = opts.height ? Number(opts.height) : 576;

  for (let i = 0; i < images.length; i++) {
    const img = images[i];
    if (img.file && fs.existsSync(path.resolve(path.dirname(jsonFile), img.file))) {
      console.log(`[${i}] 이미 파일 있음 → 건너뜀: ${img.file}`);
      continue;
    }
    if (!img.prompt) {
      console.log(`[${i}] prompt 없음 → 건너뜀`);
      continue;
    }
    const outFile = path.join(outDir, `${stem(img.filename)}.png`);
    try {
      await generateImage(img.prompt, outFile, { width, height, provider: opts.provider, seed: opts.seed });
      // JSON 에는 json 파일 기준 상대경로로 저장
      img.file = path.relative(path.dirname(path.resolve(jsonFile)), outFile).split(path.sep).join('/');
      console.log(`[${i}] 저장: ${img.file}`);
    } catch (e) {
      console.error(`[${i}] 생성 실패: ${e.message}`);
    }
  }

  fs.writeFileSync(jsonFile, JSON.stringify(data, null, 2), 'utf8');
  return data;
}

if (require.main === module) {
  const args = parseArgs(process.argv);
  const jsonFile = args._[0];
  if (!jsonFile) {
    console.error('사용법: node automation/gen-image.js <글JSON> [--provider pollinations|together|openai] [--width N --height N]');
    process.exit(1);
  }
  fillImages(jsonFile, args)
    .then(() => console.log('\n이미지 생성 완료.'))
    .catch((e) => {
      console.error('ERROR:', e.message);
      process.exit(1);
    });
}

module.exports = { fillImages };
