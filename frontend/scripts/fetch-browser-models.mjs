// Downloads the pinned Desert Ant model files into frontend/public/models/<model>/
// so the browser can load them with modelBaseUrl instead of Hugging Face.
// Idempotent: a file whose size already matches is skipped. LFS files are
// checked against the sha256 that the Hub lists for the pinned tag.
//
// Files and tags: the ones the 5.0.0 SDKs request (docs/api_notes.md), plus
// the small JSON sidecars next to them. Tags are pinned inside the SDK.
import { createHash } from 'node:crypto';
import { mkdir, stat, writeFile, rename } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const OUT = fileURLToPath(new URL('../public/models/', import.meta.url));

const MODELS = {
  redact: {
    tag: 'v0.4.2',
    files: ['redact.tflite', 'redact_tokenizer.bin', 'labels.json', 'redact_meta.json'],
  },
  gist: {
    tag: 'v2.2.0',
    files: [
      'gist.tflite', 'gist_embedding.i8', 'gist_tokenizer.bin',
      'gist_embedding.json', 'gist_config.json', 'taxonomy.json',
    ],
  },
  emo: {
    tag: 'v0.7.0',
    files: ['emo.tflite', 'emo_tokenizer.bin', 'emo_meta.json'],
  },
};

const HUB = 'https://huggingface.co';
let failed = 0;

for (const [model, { tag, files }] of Object.entries(MODELS)) {
  const dir = path.join(OUT, model);
  await mkdir(dir, { recursive: true });
  let listing;
  try {
    const r = await fetch(`${HUB}/api/models/desert-ant-labs/${model}/tree/${tag}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    listing = new Map((await r.json()).map((e) => [e.path, e]));
  } catch (e) {
    console.error(`${model}: cannot list ${tag}: ${e.message}`);
    failed++;
    continue;
  }
  for (const name of files) {
    const entry = listing.get(name);
    if (!entry) {
      console.error(`${model}/${name}: not in tag ${tag}`);
      failed++;
      continue;
    }
    const dest = path.join(dir, name);
    const have = await stat(dest).then((s) => s.size, () => -1);
    if (have === entry.size) {
      console.log(`ok (cached)  ${model}/${name}  ${entry.size} B`);
      continue;
    }
    const r = await fetch(`${HUB}/desert-ant-labs/${model}/resolve/${tag}/${name}`);
    if (!r.ok) {
      console.error(`${model}/${name}: HTTP ${r.status}`);
      failed++;
      continue;
    }
    const buf = Buffer.from(await r.arrayBuffer());
    const want = entry.lfs?.oid;
    const got = createHash('sha256').update(buf).digest('hex');
    if (buf.length !== entry.size || (want && want !== got)) {
      console.error(`${model}/${name}: size or sha256 mismatch`);
      failed++;
      continue;
    }
    await writeFile(dest + '.part', buf);
    await rename(dest + '.part', dest);
    console.log(`downloaded   ${model}/${name}  ${buf.length} B${want ? '  sha256 ok' : ''}`);
  }
}
if (failed) {
  console.error(`${failed} file(s) failed. The app falls back to the Hugging Face download.`);
  process.exit(1);
}
