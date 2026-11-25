"""Step 1 spike: real calls for the ShadowTree model stack (onnxruntime, tokenizers, model2vec,
flashrank, rapidocr, pypdfium2). Needs scripts/download_models.py to have run. Offline.

  backend\\.venv\\Scripts\\python.exe spikes\\shadowtree_spike.py <sample_folder>

Reads sample files with open(path, "rb") only. Prints timings and shapes for docs/api_notes.md.
"""
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import apply_env, get_settings, model_dir  # noqa: E402

apply_env()
import numpy as np  # noqa: E402

sample = Path(sys.argv[1])
t = time.perf_counter


def lap(label, t0):
    print(f"  [{label}] {t() - t0:.2f}s")


# ---- DeBERTa NLI (onnxruntime + tokenizers) ----------------------------------------
print("DeBERTa")
import onnxruntime as ort  # noqa: E402
from tokenizers import Tokenizer  # noqa: E402

d = model_dir("deberta")
cfg = json.loads((d / "config.json").read_bytes())
print("  id2label", cfg["id2label"], "max_pos", cfg.get("max_position_embeddings"))
ent = [int(k) for k, v in cfg["id2label"].items() if v == "entailment"][0]
t0 = t()
so = ort.SessionOptions()
so.intra_op_num_threads = get_settings().onnx_threads
sess = ort.InferenceSession(str(d / "onnx" / "model_quantized.onnx"), so, providers=["CPUExecutionProvider"])
tok = Tokenizer.from_file(str(d / "tokenizer.json"))
lap("load", t0)
print("  inputs", [(i.name, i.type, i.shape) for i in sess.get_inputs()], "outputs", [(o.name, o.shape) for o in sess.get_outputs()])
tok.enable_truncation(max_length=384, strategy="only_first")
tok.enable_padding(pad_id=tok.token_to_id("[PAD]") or 0, pad_token="[PAD]")
premise = (sample / "coffee receipt.txt").read_bytes().decode("utf-8", "replace")[:600]
hyps = ["This text is about receipts and payments.", "This text is about a personal diary."]
enc = tok.encode_batch([(premise, h) for h in hyps])
print("  tokens", enc[0].tokens[:8], "...", "type_ids", enc[0].type_ids[:6], "...")
feed = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64),
        "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64)}
feed = {k: v for k, v in feed.items() if k in {i.name for i in sess.get_inputs()}}
t0 = t()
logits = sess.run(None, feed)[0]
lap("run 2 pairs", t0)
e = np.exp(logits - logits.max(-1, keepdims=True))
p = e / e.sum(-1, keepdims=True)
print("  logits", logits.shape, "entailment scores", [round(float(x), 3) for x in p[:, ent]], "(receipt, diary)")

# ---- potion (model2vec) -----------------------------------------------------------
print("potion")
from model2vec import StaticModel  # noqa: E402

t0 = t()
m = StaticModel.from_pretrained(model_dir("potion-base-8M"))
lap("load", t0)
t0 = t()
v = m.encode(["money I spent", "coffee receipt total", "walk by the lake"])
lap("encode 3", t0)
vn = v / np.linalg.norm(v, axis=1, keepdims=True)
print("  vec", v.shape, v.dtype, "cos(money, receipt)=%.3f cos(money, lake)=%.3f" % (vn[0] @ vn[1], vn[0] @ vn[2]))

# ---- FlashRank ---------------------------------------------------------------------
print("FlashRank")
from flashrank import Ranker, RerankRequest  # noqa: E402

fr = model_dir("flashrank")
assert (fr / "ms-marco-TinyBERT-L-2-v2").is_dir(), "run download_models.py"
t0 = t()
rk = Ranker(model_name="ms-marco-TinyBERT-L-2-v2", cache_dir=str(fr), log_level="WARNING")
lap("load", t0)
passages = [{"id": i, "text": x} for i, x in enumerate(
    ["Coffee receipt. Total $4.50 paid by card.", "Dear diary, I walked by the lake.", "Invoice due 15 December, total $960."])]
t0 = t()
res = rk.rerank(RerankRequest(query="money I spent", passages=passages))
lap("rerank 3", t0)
print("  result keys", sorted(res[0]), [(r["id"], round(float(r["score"]), 4)) for r in res])

# ---- RapidOCR ----------------------------------------------------------------------
print("RapidOCR PP-OCRv5 mobile")
from rapidocr import ModelType, OCRVersion, RapidOCR  # noqa: E402

od = model_dir("ocr")
png = sample / "Screenshot 2026-11-20.png"
for rec in ("en_PP-OCRv5_rec_mobile.onnx", "ch_PP-OCRv5_rec_mobile.onnx"):
    dic = "ppocrv5_en_dict.txt" if rec.startswith("en") else "ppocrv5_dict.txt"
    params = {"Det.model_path": str(od / "ch_PP-OCRv5_det_mobile.onnx"), "Det.ocr_version": OCRVersion.PPOCRV5, "Det.model_type": ModelType.MOBILE,
              "Rec.model_path": str(od / rec), "Rec.rec_keys_path": str(od / dic), "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE,
              "Global.log_level": "warning", "EngineConfig.onnxruntime.intra_op_num_threads": get_settings().onnx_threads}
    t0 = t()
    eng = RapidOCR(params=params)
    lap(f"load {rec}", t0)
    img = png.read_bytes()
    t0 = t()
    out = eng(img)
    lap("ocr screenshot", t0)
    print("  type", type(out).__name__, "txts", out.txts, "scores", [round(float(s), 2) for s in (out.scores or [])])

# ---- pypdfium2 from bytes ------------------------------------------------------------
print("pypdfium2")
import pypdfium2 as pdfium  # noqa: E402

data = (sample / "invoice-2041.pdf").read_bytes()
t0 = t()
pdf = pdfium.PdfDocument(io.BytesIO(data))
print("  pages", len(pdf))
bm = pdf[0].render(scale=200 / 72)
im = bm.to_pil()
lap("render p1 @200dpi", t0)
print("  image", im.size, im.mode)
out = eng(np.array(im.convert("RGB"))[:, :, ::-1])
print("  ocr of pdf page:", (out.txts or [])[:6])
pdf.close()
