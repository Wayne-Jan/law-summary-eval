#!/usr/bin/env python3
"""Build static JSON data for GitHub Pages site.

Outputs JSON in the EXACT same format as /api/view/{case} returns,
so the frontend HTML can be copied from viz/static/view.html with
minimal changes (only swap fetch URLs to static paths).

Incremental rebuilds are optimized for the common case where only a
small number of eval results change: we reuse already-parsed chunk data
within each case and only rewrite JSON files whose serialized payload
actually changed. That keeps rebuilds faster and avoids dirtying the
entire static bundle on every run.

All output filenames use ASCII slugs (case_001, case_002, ...) to avoid
GitHub Pages issues with non-ASCII filenames.

Volume-aware: scans predictions/{cond}/{volume}/{case}/ where volume
is one of 上冊, 中冊, 下冊.

LLM-eval refresh workflow:
    1. Generate or update evaluation JSONs in Law_extraction_refactor
       under data/predictions/{cond}/{volume}/{case}/eval/.
    2. Run this script from law-summary-eval:
           python3 build.py
       to rebuild the static website data in data/.
    3. If metrics changed, also run:
           python3 build_metrics_data.py
       so metrics.html reads the refreshed eval_metrics_*.json files.

Usage:
    python build.py
"""

import json
import os
import hashlib
import re
import tempfile
import sys
import time
import subprocess
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_PROJECT = os.environ.get("LAW_PROJECT_ROOT", "/mnt/d/Law_extraction_refactor")
sys.path.insert(0, SOURCE_PROJECT)
from modules.extraction_v3_8.alignment_engine import smart_align

PREDICTIONS = os.path.join(SOURCE_PROJECT, "data", "predictions")
CHUNKS_DIR = os.path.join(SOURCE_PROJECT, "data", "chunks_20260105")
EXTRACTIONS_DIR_V39 = os.path.join(SOURCE_PROJECT, "data", "extractions_v3.9")
EXTRACTIONS_DIR_V3104_PATCHED = os.path.join(
    SOURCE_PROJECT, "data", "extractions_v3.10.4_patched_claude_manual_fix"
)
EXTRACTIONS_DIR_V3104 = os.path.join(SOURCE_PROJECT, "data", "extractions_v3.10.4")
SOURCE_TEXT_DIR = os.path.join(SOURCE_PROJECT, "原始判決書")
GT_SUMMARY_DIR = os.path.join(SOURCE_PROJECT, "摘要 (ground_truth)")
SITE_DATA = os.path.join(SCRIPT_DIR, "data")
TIMELINE_ALIGN_CACHE_DIR = os.path.join(
    tempfile.gettempdir(), "law-summary-eval-build-cache"
)
TIMELINE_ALIGN_CACHE_PATH = os.path.join(
    TIMELINE_ALIGN_CACHE_DIR, "timeline_align_cache.json"
)
TIMELINE_ALIGN_CACHE_VERSION = 1
VIEW_BUILD_CACHE_PATH = os.path.join(
    TIMELINE_ALIGN_CACHE_DIR, "view_build_cache.json"
)
VIEW_BUILD_CACHE_VERSION = 1
TIMELINE_V310_BUILD_CACHE_PATH = os.path.join(
    TIMELINE_ALIGN_CACHE_DIR, "timeline_v310_build_cache.json"
)
TIMELINE_V310_BUILD_CACHE_VERSION = 1

VOLUMES = ["上冊", "中冊", "下冊"]


def log_stage(start_ts, message):
    elapsed = time.time() - start_ts
    print(f"[{elapsed:6.1f}s] {message}", flush=True)

# Must match server.py VIEWER_CONDITION_LABELS / VIEWER_CONDITION_GROUPS
CONDITION_LABELS = {
    "claude_afg_v5.1": "LENS-Haiku 4.5-A",
    "ablation_no_afg": "LENS-Haiku 4.5-B",
    "ablation_no_react": "LENS-Haiku 4.5-C",
    "opensource_afg_v11": "Open-L1",
    "opensource_afg_v11_no_react": "Open-L2",
    "opensource_afg_v11_no_afg": "Open-L3",
    "baseline_claude-haiku": "Claude Haiku 4.5",
    "baseline_claude-sonnet": "Claude Sonnet 4.6",
    "baseline_gemini-3.0-flash": "Gemini 3.0 Flash",
    "baseline_gemini-3.1-pro": "Gemini 3.1 Pro",
    "baseline_gpt-5.3": "GPT-5.3 Instant",
    "baseline_gpt-5.4-thinking": "GPT-5.4 Thinking",
    "baseline_ollama_cogito-2.1-671b-cloud": "Cogito 2.1 (671B / 37A)",
    "baseline_ollama_deepseek-v3.1-671b-cloud": "DeepSeek V3.1 (671B / 37A)",
    "baseline_ollama_glm-5-cloud": "GLM 5 (744B / 40A)",
    "baseline_ollama_gpt-oss-120b-cloud": "GPT-OSS (117B / 5.1A)",
    "baseline_ollama_kimi-k2.5-cloud": "Kimi K2.5 (1T / 32A)",
    "baseline_ollama_mistral-large-3-675b-cloud": "Mistral Large 3 (675B / 41A)",
    "baseline_ollama_nemotron-3-super-cloud": "Nemotron 3 Super (120B / 12A)",
    "baseline_ollama_qwen3-next-80b-cloud": "Qwen3 Next (80B / 3A)",
    "baseline_ollama_qwen3.5-397b-cloud": "Qwen3.5 (397B / 17A)",
    "opensource_afg_v11_5": "LENS-GPT-OSS-A",
    "opensource_afg_v11_5_no_react": "LENS-GPT-OSS-B",
    "opensource_afg_v11_5_no_afg": "LENS-GPT-OSS-C",
    "opensource_afg_v11_5_writer_nemotron_super": "LENS-Nemotron Super-A",
    "opensource_afg_v11_5_no_react_writer_nemotron_super": "LENS-Nemotron Super-B",
    "opensource_afg_v11_5_no_afg_writer_nemotron_super": "LENS-Nemotron Super-C",
    "LENS-Full-DeepSeek_v31": "LENS-DeepSeek v3.1-A",
    "LENS-NoReact-DeepSeek_v31": "LENS-DeepSeek v3.1-B",
    "LENS-NoAFG-DeepSeek_v31": "LENS-DeepSeek v3.1-C",
}

# Display order: Claude → OpenSource → Baselines
CONDITION_ORDER = [
    "claude_afg_v5.1",
    "ablation_no_afg",
    "ablation_no_react",
    "LENS-Full-DeepSeek_v31",
    "LENS-NoReact-DeepSeek_v31",
    "LENS-NoAFG-DeepSeek_v31",
    "opensource_afg_v11",
    "opensource_afg_v11_no_afg",
    "opensource_afg_v11_no_react",
    "baseline_claude-haiku",
    "baseline_claude-sonnet",
    "baseline_gemini-3.0-flash",
    "baseline_gemini-3.1-pro",
    "baseline_gpt-5.3",
    "baseline_gpt-5.4-thinking",
    "baseline_ollama_cogito-2.1-671b-cloud",
    "baseline_ollama_deepseek-v3.1-671b-cloud",
    "baseline_ollama_glm-5-cloud",
    "baseline_ollama_gpt-oss-120b-cloud",
    "baseline_ollama_kimi-k2.5-cloud",
    "baseline_ollama_mistral-large-3-675b-cloud",
    "baseline_ollama_nemotron-3-super-cloud",
    "baseline_ollama_qwen3-next-80b-cloud",
    "baseline_ollama_qwen3.5-397b-cloud",
    "opensource_afg_v11_5",
    "opensource_afg_v11_5_no_afg",
    "opensource_afg_v11_5_no_react",
    "opensource_afg_v11_5_writer_nemotron_super",
    "opensource_afg_v11_5_no_react_writer_nemotron_super",
    "opensource_afg_v11_5_no_afg_writer_nemotron_super",
]

CONDITION_GROUPS = {
    "claude_afg_v5.1": "商用模型",
    "ablation_no_afg": "商用模型",
    "ablation_no_react": "商用模型",
    "baseline_claude-haiku": "商用模型",
    "baseline_claude-sonnet": "商用模型",
    "baseline_gemini-3.0-flash": "商用模型",
    "baseline_gemini-3.1-pro": "商用模型",
    "baseline_gpt-5.3": "商用模型",
    "baseline_gpt-5.4-thinking": "商用模型",
    "baseline_ollama_cogito-2.1-671b-cloud": "開源模型",
    "baseline_ollama_deepseek-v3.1-671b-cloud": "開源模型",
    "baseline_ollama_glm-5-cloud": "開源模型",
    "baseline_ollama_gpt-oss-120b-cloud": "開源模型",
    "baseline_ollama_kimi-k2.5-cloud": "開源模型",
    "baseline_ollama_mistral-large-3-675b-cloud": "開源模型",
    "baseline_ollama_nemotron-3-super-cloud": "開源模型",
    "baseline_ollama_qwen3-next-80b-cloud": "開源模型",
    "baseline_ollama_qwen3.5-397b-cloud": "開源模型",
    "opensource_afg_v11": "開源模型",
    "opensource_afg_v11_no_afg": "開源模型",
    "opensource_afg_v11_no_react": "開源模型",
    "opensource_afg_v11_5": "開源模型",
    "opensource_afg_v11_5_no_afg": "開源模型",
    "opensource_afg_v11_5_no_react": "開源模型",
    "opensource_afg_v11_5_writer_nemotron_super": "開源模型",
    "opensource_afg_v11_5_no_react_writer_nemotron_super": "開源模型",
    "opensource_afg_v11_5_no_afg_writer_nemotron_super": "開源模型",
    "LENS-Full-DeepSeek_v31": "開源模型",
    "LENS-NoReact-DeepSeek_v31": "開源模型",
    "LENS-NoAFG-DeepSeek_v31": "開源模型",
}

SECTION_FILES = [
    ("facts", "section_01_facts.txt", "（一）公訴事實與起訴意旨"),
    ("defense", "section_02_defense.txt", "（二）被告回應"),
    ("opinions", "section_03_opinions.txt", "（三）鑑定意見"),
    ("verdict", "section_04_verdict.txt", "（四）判決結果"),
    ("reasoning", "section_05_reasoning.txt", "（五）判決理由"),
]


def read_text(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json_if_changed(path, obj):
    """Write JSON only when the serialized payload differs.

    This keeps incremental rebuilds fast and preserves clean git diffs
    when only a few cases change between runs.
    """
    payload = json.dumps(obj, ensure_ascii=False, indent=1)
    if os.path.exists(path):
        existing = read_text(path)
        if existing == payload:
            return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(payload)
    return True


def get_build_version():
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=SCRIPT_DIR,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        sha = time.strftime("%Y%m%d")
    return sha


def load_timeline_align_cache():
    """Load the local cache that stores aligned timeline events.

    The cache lives outside the repo so rebuilds stay fast without
    polluting git status. It is only an optimization: if the cache is
    missing or stale, the build still works.
    """
    cache = read_json(TIMELINE_ALIGN_CACHE_PATH)
    if not isinstance(cache, dict):
        return {"version": TIMELINE_ALIGN_CACHE_VERSION, "cases": {}}
    if cache.get("version") != TIMELINE_ALIGN_CACHE_VERSION:
        return {"version": TIMELINE_ALIGN_CACHE_VERSION, "cases": {}}
    cases = cache.get("cases", {})
    if not isinstance(cases, dict):
        cases = {}
    return {"version": TIMELINE_ALIGN_CACHE_VERSION, "cases": cases}


def save_timeline_align_cache(cache):
    os.makedirs(TIMELINE_ALIGN_CACHE_DIR, exist_ok=True)
    write_json_if_changed(TIMELINE_ALIGN_CACHE_PATH, cache)


def load_view_build_cache():
    cache = read_json(VIEW_BUILD_CACHE_PATH)
    if not isinstance(cache, dict):
        return {"version": VIEW_BUILD_CACHE_VERSION, "cases": {}}
    if cache.get("version") != VIEW_BUILD_CACHE_VERSION:
        return {"version": VIEW_BUILD_CACHE_VERSION, "cases": {}}
    cases = cache.get("cases", {})
    if not isinstance(cases, dict):
        cases = {}
    return {"version": VIEW_BUILD_CACHE_VERSION, "cases": cases}


def save_view_build_cache(cache):
    os.makedirs(TIMELINE_ALIGN_CACHE_DIR, exist_ok=True)
    write_json_if_changed(VIEW_BUILD_CACHE_PATH, cache)


def load_timeline_v310_build_cache():
    cache = read_json(TIMELINE_V310_BUILD_CACHE_PATH)
    if not isinstance(cache, dict):
        return {"version": TIMELINE_V310_BUILD_CACHE_VERSION, "cases": {}}
    if cache.get("version") != TIMELINE_V310_BUILD_CACHE_VERSION:
        return {"version": TIMELINE_V310_BUILD_CACHE_VERSION, "cases": {}}
    cases = cache.get("cases", {})
    if not isinstance(cases, dict):
        cases = {}
    return {"version": TIMELINE_V310_BUILD_CACHE_VERSION, "cases": cases}


def save_timeline_v310_build_cache(cache):
    os.makedirs(TIMELINE_ALIGN_CACHE_DIR, exist_ok=True)
    write_json_if_changed(TIMELINE_V310_BUILD_CACHE_PATH, cache)


def _stat_sig(path):
    if not os.path.exists(path):
        return "-"
    st = os.stat(path)
    return f"{st.st_mtime_ns}:{st.st_size}"


def _hash_parts(parts):
    h = hashlib.sha1()
    for part in parts:
        h.update(str(part).encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def compute_view_input_fingerprint(case_dir, case_name, volume, cond):
    parts = [
        "view_v1",
        cond,
        case_name,
        volume,
        json.dumps(CONDITION_LABELS, ensure_ascii=False, sort_keys=True),
        json.dumps(CONDITION_GROUPS, ensure_ascii=False, sort_keys=True),
    ]

    section_dir = os.path.join(case_dir, "workspace", "sections")
    if not os.path.isdir(section_dir):
        section_dir = case_dir
    for _, filename, _ in SECTION_FILES:
        file_path = os.path.join(section_dir, filename)
        parts.extend([file_path, _stat_sig(file_path)])

    candidate_paths = [
        os.path.join(case_dir, "citations.txt"),
        os.path.join(case_dir, "meta", "citations.json"),
        os.path.join(case_dir, "workspace", "chunk_alias_mapping.json"),
        os.path.join(case_dir, "meta", "metadata.json"),
        os.path.join(CHUNKS_DIR, volume, f"{case_name}.json"),
    ]
    for path in candidate_paths:
        parts.extend([path, _stat_sig(path)])

    eval_dir = os.path.join(case_dir, "eval")
    if os.path.isdir(eval_dir):
        for name in sorted(os.listdir(eval_dir)):
            path = os.path.join(eval_dir, name)
            parts.extend([path, _stat_sig(path)])
    else:
        parts.extend([eval_dir, "-"])

    return _hash_parts(parts)


def find_v310_master_path(case_name):
    master_path = os.path.join(EXTRACTIONS_DIR_V3104_PATCHED, case_name, "master.json")
    if os.path.exists(master_path):
        return master_path
    return None


def compute_v310_timeline_fingerprint(case_name, volume):
    master_path = find_v310_master_path(case_name)
    if not master_path:
        return None
    parts = [
        "timeline_v310_v1",
        case_name,
        volume,
        master_path,
        _stat_sig(master_path),
    ]
    chunk_path = os.path.join(CHUNKS_DIR, volume, f"{case_name}.json")
    parts.extend([chunk_path, _stat_sig(chunk_path)])
    return _hash_parts(parts)


def fingerprint_event_texts(events):
    """Hash the extraction texts that drive alignment.

    If the source text and these texts stay the same, we can reuse the
    previous alignment result without calling smart_align again.
    """
    h = hashlib.sha1()
    for evt in events:
        txt = (evt.get("extraction_text") or "").strip()
        h.update(txt.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def find_in_volumes(base_dir, relative_path):
    """Search for a file across all volume subdirectories."""
    for vol in VOLUMES:
        full = os.path.join(base_dir, vol, relative_path)
        if os.path.exists(full):
            return full, vol
    return None, None


# ─── Case display name extraction ───

# 上冊: "有罪1.臺灣苗栗地方法院88年訴字第68號刑事判決"
_UPPER_RE = re.compile(r"^(有罪|無罪)(\d+)\.(.+?)(?:\d+年度?\S+字\S+號|$)")
# 中冊/下冊: "原始判決書_04_第四案 車禍未做神經學檢查案"
_MIDDLE_LOWER_RE = re.compile(r"^原始判決書[_*](\d+)[_*]第.+?案\s*(.+)$")
_LEADING_CASE_ORDINAL_RE = re.compile(r"^第[一二三四五六七八九十百千零〇兩\d]+案[\s\u3000]*")


def normalize_case_title(title):
    if not title:
        return ""
    title = title.strip().replace("\u3000", " ")
    title = _LEADING_CASE_ORDINAL_RE.sub("", title).strip()
    return re.sub(r"\s+", " ", title)


def extract_case_title(case_name, volume):
    """Return concise UI title without verdict / court name noise."""
    m = _MIDDLE_LOWER_RE.match(case_name)
    if m:
        return normalize_case_title(m.group(2))

    gt_path = Path(GT_SUMMARY_DIR) / volume / f"摘要_{case_name}.txt"
    if gt_path.exists():
        for line in gt_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                return normalize_case_title(line)

    return normalize_case_title(case_name)


def extract_case_info(case_name):
    """Extract structured display info from a case directory name.

    Returns dict with keys: number (str), display (str), verdict (str|None).

    上冊: "有罪01 — 臺灣苗栗地方法院"
    中冊/下冊: "04 — 車禍未做神經學檢查案"
    """
    m = _UPPER_RE.match(case_name)
    if m:
        verdict = m.group(1)  # "有罪" or "無罪"
        num = int(m.group(2))
        # Extract court name (up to 地方法院/高等法院)
        after_dot = case_name.split(".", 1)[1] if "." in case_name else ""
        short_court = re.match(r"^(.+?(?:地方法院|高等法院))", after_dot)
        court = short_court.group(1) if short_court else after_dot
        number = f"{num:02d}"
        return {
            "number": number,
            "display": f"{verdict}{number} — {court}",
            "verdict": verdict,
        }

    m = _MIDDLE_LOWER_RE.match(case_name)
    if m:
        num = int(m.group(1))
        short_desc = m.group(2).strip()
        number = f"{num:02d}"
        return {
            "number": number,
            "display": f"{number} — {short_desc}",
            "verdict": None,
        }

    # Fallback: use full name
    return {
        "number": "00",
        "display": case_name,
        "verdict": None,
    }


def load_sections(case_dir):
    """Load sections in the same format as /api/view/{case} returns."""
    sections = []
    section_dir = os.path.join(case_dir, "workspace", "sections")
    if not os.path.isdir(section_dir):
        section_dir = case_dir

    for section_id, filename, default_title in SECTION_FILES:
        file_path = os.path.join(section_dir, filename)
        if os.path.exists(file_path):
            raw = read_text(file_path).strip()
            body = raw
            first_line, _, remainder = raw.partition("\n")
            if first_line.strip().startswith("（") and "）" in first_line:
                body = remainder.strip()
            sections.append({"id": section_id, "title": default_title, "content": body})
        else:
            sections.append({"id": section_id, "title": default_title, "content": ""})

    return sections


def load_chunks_for_case(case_name, case_dir, volume):
    """Build CH_XX -> content mapping, same logic as server.py."""
    chunks = {}
    raw_chunks = None

    # 1. Try citations.txt (pre-built)
    citations_txt_path = os.path.join(case_dir, "citations.txt")
    if os.path.exists(citations_txt_path):
        current_alias = None
        current_content = []
        for line in read_text(citations_txt_path).split("\n"):
            if line.startswith("=== CH_") and line.endswith(" ==="):
                if current_alias and current_content:
                    chunks[current_alias] = "\n".join(current_content).strip()
                current_alias = line.replace("=== ", "").replace(" ===", "")
                current_content = []
            elif current_alias:
                current_content.append(line)
        if current_alias and current_content:
            chunks[current_alias] = "\n".join(current_content).strip()

    chunks_json_path = os.path.join(CHUNKS_DIR, volume, f"{case_name}.json")
    if os.path.exists(chunks_json_path):
        raw_chunks = read_json(chunks_json_path)
        if isinstance(raw_chunks, list):
            chunk_list = raw_chunks
        elif isinstance(raw_chunks, dict):
            chunk_list = raw_chunks.get("chunks", [])
        else:
            chunk_list = []
    else:
        chunk_list = []

    # 2. Build citations_map from meta/citations.json or chunk_alias_mapping
    citations_map = {}
    cit_json = read_json(os.path.join(case_dir, "meta", "citations.json"))
    if cit_json:
        citations_map = cit_json.get("alias_to_chunk_id", {})

    if not citations_map:
        mapping = read_json(
            os.path.join(case_dir, "workspace", "chunk_alias_mapping.json")
        )
        if mapping:
            for alias, val in mapping.items():
                if isinstance(val, dict):
                    citations_map[alias] = val.get("original_id", "")
                else:
                    citations_map[alias] = val

    # 3. Fallback: positional mapping from chunks JSON (volume-aware)
    if not citations_map and chunk_list:
        for idx, chunk in enumerate(chunk_list, start=1):
            alias = f"CH_{idx:02d}"
            chunk_id = chunk.get("chunk_id", "")
            if chunk_id:
                citations_map[alias] = chunk_id

    # 4. Fill missing chunks from raw chunks JSON
    if citations_map and chunk_list:
        missing = sorted(set(citations_map.keys()) - set(chunks.keys()))
        if missing:
            id_to_content = {
                c.get("chunk_id", ""): c.get("content", "") for c in chunk_list
            }
            for alias in missing:
                chunk_id = citations_map.get(alias, "")
                if chunk_id in id_to_content:
                    chunks[alias] = id_to_content[chunk_id]

    # 5. Last resort: if still no chunks, use positional content
    if not chunks and chunk_list:
        for idx, chunk in enumerate(chunk_list, start=1):
            chunks[f"CH_{idx:02d}"] = chunk.get("content", "")

    return chunks, citations_map


def load_metadata(case_dir):
    md = read_json(os.path.join(case_dir, "meta", "metadata.json"))
    return md or {}


def load_v310_timeline(case_name, volume):
    """Load a v3.10.4 timeline master and normalize it for the static viewer."""
    master_path = find_v310_master_path(case_name)
    if not master_path or not os.path.exists(master_path):
        return None

    master = read_json(master_path)
    if not isinstance(master, dict):
        return None

    tl_result = master.get("timeline", {})
    events = tl_result.get("timeline", tl_result.get("events", []))
    if not events:
        return None

    chunks = []
    chunk_path = os.path.join(CHUNKS_DIR, volume, f"{case_name}.json")
    if os.path.exists(chunk_path):
        raw_chunks = read_json(chunk_path)
        if isinstance(raw_chunks, list):
            chunk_list = raw_chunks
        elif isinstance(raw_chunks, dict):
            chunk_list = raw_chunks.get("chunks", [])
        else:
            chunk_list = []
        for chunk in chunk_list:
            chunks.append(
                {
                    "chunk_id": chunk.get("chunk_id", ""),
                    "title": chunk.get("title", ""),
                    "content": chunk.get("content", ""),
                    "start_char": chunk.get("start_char", 0),
                    "end_char": chunk.get("end_char", 0),
                }
            )

    tl_summary = tl_result.get("timeline_summary", {})
    time_gaps = tl_result.get("time_gaps", tl_summary.get("time_gaps", []))
    return {
        "case_name": case_name,
        "volume": volume,
        "source": "v3.10.4",
        "events": events,
        "timeline_summary": tl_summary,
        "time_gaps": time_gaps,
        "causation_chain": tl_result.get("causation_chain", []),
        "chunks": chunks,
        "entities": normalize_v310_entities(master),
    }


def normalize_v310_entities(master):
    """Extract a stable entity payload for the static viewer."""
    entities = master.get("entities", {})
    if not isinstance(entities, dict):
        return {}

    def normalize_list(key):
        value = entities.get(key, [])
        return value if isinstance(value, list) else []

    institutions = normalize_list("institutions")
    institution_lookup = {}
    for inst in institutions:
        if isinstance(inst, dict) and inst.get("id"):
            institution_lookup[inst["id"]] = inst.get("name") or inst["id"]

    def normalize_actor_list(key):
        value = normalize_list(key)
        normalized = []
        for item in value:
            if not isinstance(item, dict):
                normalized.append(item)
                continue
            cloned = dict(item)
            institution = cloned.get("institution")
            if isinstance(institution, str) and institution in institution_lookup:
                cloned["institution"] = institution_lookup[institution]
                cloned.setdefault("institution_id", institution)
            normalized.append(cloned)
        return normalized

    return {
        "defendants": normalize_actor_list("defendants"),
        "victims": normalize_list("victims"),
        "other_actors": normalize_actor_list("other_actors"),
        "institutions": institutions,
        "all_actor_names": normalize_list("all_actor_names"),
    }


def extract_eval_summary(eval_dir):
    report = read_json(os.path.join(eval_dir, "report.json"))
    if report and "scores" in report:
        return report["scores"]
    result = {}
    rule = read_json(os.path.join(eval_dir, "rule_metrics.json"))
    if rule and "_summary" in rule:
        result["rule_based_avg"] = rule["_summary"].get("rule_based_avg")
    fact = read_json(os.path.join(eval_dir, "fact_recall.json"))
    if fact:
        result["fact_recall_avg"] = fact.get("overall_fact_recall")
    quality = read_json(os.path.join(eval_dir, "quality.json"))
    if quality and "overall" in quality:
        result["quality_avg"] = quality["overall"].get("overall_quality")
    faith = read_json(os.path.join(eval_dir, "faithfulness.json"))
    if faith:
        result["faithfulness"] = faith.get("faithfulness_score")
    return result if result else None


def parse_gt_sections(raw_text):
    """Parse GT summary into sections — copied from server.py _parse_gt_sections."""
    section_map = {
        "一": "facts",
        "二": "defense",
        "三": "opinions",
        "四": "verdict",
        "五": "reasoning",
    }
    strip_labels = {
        "facts": ["公訴事實與起訴意旨", "自訴事實與意旨", "自訴事實與自訴意旨"],
        "defense": ["被告回應"],
        "opinions": ["鑑定意見"],
        "verdict": ["判決結果"],
        "reasoning": ["判決理由"],
    }
    default_result = {
        "facts": raw_text.strip(),
        "defense": "",
        "opinions": "",
        "verdict": "",
        "reasoning": "",
    }

    marker_pattern = re.compile(
        r"^\s*[（(]\s*([一二三四五])\s*[）)]\s*(.*)$", re.MULTILINE
    )
    marker_matches = list(marker_pattern.finditer(raw_text))

    ordered_sections = []
    seen = set()
    for match in marker_matches:
        section_id = section_map.get(match.group(1))
        if not section_id or section_id in seen:
            continue
        ordered_sections.append((section_id, match))
        seen.add(section_id)
        if len(ordered_sections) == 5:
            break

    if len(ordered_sections) < 5:
        return default_result

    def _strip_leading_label(sid, text):
        cleaned = text.lstrip()
        for label in strip_labels.get(sid, []):
            cleaned = re.sub(
                rf"^\s*{re.escape(label)}\s*([：:、，。]?\s*)?",
                "",
                cleaned,
                count=1,
            )
        return cleaned.strip()

    ordered_sections.sort(key=lambda x: x[1].start())
    result = {
        "facts": "",
        "defense": "",
        "opinions": "",
        "verdict": "",
        "reasoning": "",
    }

    for idx, (section_id, match) in enumerate(ordered_sections):
        start = match.start(2)
        end = (
            ordered_sections[idx + 1][1].start()
            if idx + 1 < len(ordered_sections)
            else len(raw_text)
        )
        raw_block = raw_text[start:end]
        result[section_id] = _strip_leading_label(section_id, raw_block)

    return result


def build():
    build_started = time.time()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    os.makedirs(SITE_DATA, exist_ok=True)
    site_meta = {
        "version": get_build_version(),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    write_json_if_changed(os.path.join(SITE_DATA, "site_meta.json"), site_meta)
    timeline_align_cache = load_timeline_align_cache()
    timeline_align_cases = timeline_align_cache.setdefault("cases", {})
    view_build_cache = load_view_build_cache()
    view_build_cases = view_build_cache.setdefault("cases", {})
    rewritten_outputs = 0
    unchanged_outputs = 0

    log_stage(build_started, "Stage 1/7: collecting cases and conditions")
    # Collect all conditions and cases (volume-aware)
    # all_conditions: cond -> {case_name -> {"dir": case_dir, "volume": vol}}
    all_conditions = {}
    all_cases = set()
    case_volumes = {}  # case_name -> volume

    for cond in sorted(os.listdir(PREDICTIONS)):
        cond_dir = os.path.join(PREDICTIONS, cond)
        if not os.path.isdir(cond_dir) or cond.startswith(".") or cond in ("Old",):
            continue
        cases = {}
        for vol in VOLUMES:
            vol_dir = os.path.join(cond_dir, vol)
            if not os.path.isdir(vol_dir):
                continue
            for case in sorted(os.listdir(vol_dir)):
                case_dir = os.path.join(vol_dir, case)
                if not os.path.isdir(case_dir):
                    continue
                if not os.path.exists(os.path.join(case_dir, "summary_clean.txt")):
                    continue
                cases[case] = {"dir": case_dir, "volume": vol}
                all_cases.add(case)
                case_volumes[case] = vol
        if cases:
            all_conditions[cond] = cases

    # Sort cases: by volume order, then verdict group (有罪 first, 無罪 second), then by numeric case number
    vol_order = {v: i for i, v in enumerate(VOLUMES)}
    verdict_order = {"有罪": 0, "無罪": 1}
    all_cases = sorted(all_cases, key=lambda c: (
        vol_order.get(case_volumes.get(c, ""), 99),
        verdict_order.get(extract_case_info(c)["verdict"], 0),
        int(extract_case_info(c)["number"]),
    ))

    # Sort conditions by CONDITION_ORDER, then alphabetically for unlisted ones
    order_map = {c: i for i, c in enumerate(CONDITION_ORDER)}
    cond_list = sorted(all_conditions.keys(), key=lambda c: (order_map.get(c, 999), c))

    # Build case_name -> slug mapping (ASCII-safe filenames for GitHub Pages)
    case_slugs = {}
    for idx, case in enumerate(all_cases, start=1):
        case_slugs[case] = f"case_{idx:03d}"

    log_stage(build_started, "Stage 2/7: building slug and GT mappings")
    # Also build slug mapping for ALL GT cases (may include cases not in predictions)
    # GT names may differ from prediction names:
    #   prediction: "原始判決書_04_第四案 車禍未做神經學檢查案"
    #   GT:         "04_第四案 車禍未做神經學檢查案"
    # Build a lookup: for each prediction case, strip "原始判決書_" to find its GT name.
    pred_to_gt = {}   # prediction_name -> gt_name (for cases with prefix mismatch)
    gt_to_pred = {}   # gt_name -> prediction_name

    gt_case_names = []
    gt_case_volume = {}  # gt_case -> volume
    if os.path.isdir(GT_SUMMARY_DIR):
        for vol in VOLUMES:
            vol_dir = os.path.join(GT_SUMMARY_DIR, vol)
            if not os.path.isdir(vol_dir):
                continue
            for fname in sorted(os.listdir(vol_dir)):
                if fname.startswith("摘要_") and fname.endswith(".txt"):
                    gt_case = fname[len("摘要_"):-len(".txt")]
                    gt_case_names.append(gt_case)
                    gt_case_volume[gt_case] = vol
                    if gt_case not in case_volumes:
                        case_volumes[gt_case] = vol

    # Match GT names to prediction names via prefix stripping
    gt_name_set = set(gt_case_names)
    for pred_case in all_cases:
        if pred_case in gt_name_set:
            # Exact match (上冊 cases)
            pred_to_gt[pred_case] = pred_case
            gt_to_pred[pred_case] = pred_case
        elif pred_case.startswith("原始判決書_"):
            stripped = pred_case[len("原始判決書_"):]
            if stripped in gt_name_set:
                pred_to_gt[pred_case] = stripped
                gt_to_pred[stripped] = pred_case

    # Add GT-only cases to slug map; GT cases that map to a prediction use its slug
    next_idx = len(all_cases) + 1
    for gt_case in gt_case_names:
        if gt_case in case_slugs:
            # Already has a slug (exact match with prediction)
            continue
        if gt_case in gt_to_pred and gt_to_pred[gt_case] in case_slugs:
            # Map GT to same slug as its prediction case
            case_slugs[gt_case] = case_slugs[gt_to_pred[gt_case]]
        else:
            # GT-only case, no matching prediction
            case_slugs[gt_case] = f"case_{next_idx:03d}"
            next_idx += 1

    # For each case, find which conditions are available
    case_to_conditions = {}
    for case in all_cases:
        case_to_conditions[case] = [
            c for c in cond_list if case in all_conditions.get(c, {})
        ]

    log_stage(build_started, "Stage 3/7: writing per-condition case data")
    # Build per-condition per-case JSON (same format as /api/view/{case})
    manifest_conditions = {}
    for cond in cond_list:
        label = CONDITION_LABELS.get(cond, cond)
        group = CONDITION_GROUPS.get(cond, "other")
        cases = all_conditions[cond]
        eval_count = 0

        cond_out_dir = os.path.join(SITE_DATA, cond)
        os.makedirs(cond_out_dir, exist_ok=True)

        for case, info in cases.items():
            case_dir = info["dir"]
            volume = info["volume"]
            slug = case_slugs[case]
            out_path = os.path.join(cond_out_dir, slug + ".json")
            cache_key = f"{cond}/{case}"
            fingerprint = compute_view_input_fingerprint(case_dir, case, volume, cond)
            cached = view_build_cases.get(cache_key)
            if (
                isinstance(cached, dict)
                and cached.get("fingerprint") == fingerprint
                and os.path.exists(out_path)
            ):
                if cached.get("has_llm"):
                    eval_count += 1
                unchanged_outputs += 1
                continue

            sections = load_sections(case_dir)
            chunks, citations_map = load_chunks_for_case(case, case_dir, volume)
            metadata = load_metadata(case_dir)

            eval_dir = os.path.join(case_dir, "eval")
            eval_scores = (
                extract_eval_summary(eval_dir) if os.path.isdir(eval_dir) else None
            )
            has_llm = False
            if eval_scores:
                q = eval_scores.get("quality")
                if isinstance(q, (int, float)):
                    has_llm = True
                elif isinstance(q, dict):
                    # Various report.json formats: .avg, .overall_quality, .overall (float)
                    ov = q.get("avg") or q.get("overall_quality") or q.get("overall")
                    if ov is not None:
                        has_llm = True
                elif eval_scores.get("quality_avg") is not None:
                    has_llm = True
            if has_llm:
                eval_count += 1

            view_data = {
                "case_name": case,
                "volume": volume,
                "condition": cond,
                "available_conditions": case_to_conditions.get(case, []),
                "condition_labels": CONDITION_LABELS,
                "condition_groups": CONDITION_GROUPS,
                "sections": sections,
                "citations_map": citations_map,
                "chunks": chunks,
                "verdict_type": metadata.get("verdict_type", "unknown"),
                "complexity_score": metadata.get("complexity_score", 0),
                "eval": eval_scores,
            }

            if write_json_if_changed(out_path, view_data):
                rewritten_outputs += 1
            else:
                unchanged_outputs += 1
            view_build_cases[cache_key] = {
                "fingerprint": fingerprint,
                "has_llm": has_llm,
            }

        manifest_conditions[cond] = {
            "label": label,
            "group": group,
            "case_count": len(cases),
            "eval_count": eval_count,
        }
        print(f"  {cond:45s}  {len(cases):3d} cases  {eval_count:3d} evals")

    log_stage(build_started, "Stage 4/7: writing cases and GT summaries")
    # Build cases list (same as /api/view-cases)
    cases_json_path = os.path.join(SITE_DATA, "cases.json")
    if write_json_if_changed(cases_json_path, all_cases):
        rewritten_outputs += 1
    else:
        unchanged_outputs += 1

    # Build GT data (same format as /api/view-gt/{case})
    if os.path.isdir(GT_SUMMARY_DIR):
        gt_out_dir = os.path.join(SITE_DATA, "gt")
        os.makedirs(gt_out_dir, exist_ok=True)
        gt_count = 0
        for gt_case in gt_case_names:
            vol = gt_case_volume.get(gt_case, "")
            raw = read_text(os.path.join(GT_SUMMARY_DIR, vol, f"摘要_{gt_case}.txt"))
            if not raw:
                continue
            parsed = parse_gt_sections(raw)
            gt_data = {
                "case_name": gt_case,
                "volume": vol,
                "sections": [
                    {"id": sid, "title": title, "content": parsed.get(sid, "")}
                    for sid, _, title in SECTION_FILES
                ],
            }
            slug = case_slugs[gt_case]
            gt_path = os.path.join(gt_out_dir, slug + ".json")
            if write_json_if_changed(gt_path, gt_data):
                rewritten_outputs += 1
            else:
                unchanged_outputs += 1
            gt_count += 1
        print(f"  {'_gt (teacher summaries)':45s}  {gt_count:3d} cases")

    log_stage(build_started, "Stage 5/7: building timeline v3.9 cache")
    # Build timeline data (extraction v3.9 only, volume-aware)
    tl_out_dir = os.path.join(SITE_DATA, "timeline")
    os.makedirs(tl_out_dir, exist_ok=True)
    tl_count = 0
    tl_realign_count = 0
    tl_cache_hits = 0
    tl_cache_misses = 0
    extraction_dir = EXTRACTIONS_DIR_V39
    if not os.path.isdir(extraction_dir):
        print("  WARNING: extraction v3.9 directory not found, skipping timeline")
        extraction_dir = None

    if extraction_dir:
        for vol in VOLUMES:
            vol_dir = os.path.join(extraction_dir, vol)
            if not os.path.isdir(vol_dir):
                continue
            for case_name in sorted(os.listdir(vol_dir)):
                master_path = os.path.join(vol_dir, case_name, "master.json")
                if not os.path.exists(master_path):
                    continue
                master = read_json(master_path)
                if not isinstance(master, dict):
                    continue
                tl_result = master.get("timeline", master.get("timeline_result", {}))
                events = tl_result.get("timeline", tl_result.get("events", []))
                if not events:
                    continue

                cache_key = f"{vol}/{case_name}"
                source_path = os.path.join(SOURCE_TEXT_DIR, vol, case_name + ".txt")
                source_sig = None
                if os.path.exists(source_path):
                    st = os.stat(source_path)
                    source_sig = f"{st.st_mtime_ns}:{st.st_size}"
                text_sig = fingerprint_event_texts(events)
                cached = timeline_align_cases.get(cache_key)
                if (
                    isinstance(cached, dict)
                    and cached.get("source_sig") == source_sig
                    and cached.get("text_sig") == text_sig
                    and isinstance(cached.get("events"), list)
                ):
                    events = cached["events"]
                    tl_realign_count += int(cached.get("realigned", 0) or 0)
                    tl_cache_hits += 1
                else:
                    # Realign char_start/char_end using smart_align (volume-aware)
                    if os.path.exists(source_path):
                        source_text = open(source_path, encoding="utf-8").read()
                        realigned = 0
                        for evt in events:
                            txt = (evt.get("extraction_text") or "").strip()
                            if not txt:
                                continue
                            hit = smart_align(source_text, txt)
                            if hit:
                                evt["char_start"] = hit.start
                                evt["char_end"] = hit.end
                                realigned += 1
                        if realigned:
                            tl_realign_count = tl_realign_count + realigned
                    else:
                        realigned = 0
                    timeline_align_cases[cache_key] = {
                        "source_sig": source_sig,
                        "text_sig": text_sig,
                        "realigned": realigned,
                        "events": events,
                    }
                    tl_cache_misses += 1

                # Load chunks for this case (volume-aware)
                chunk_path = os.path.join(CHUNKS_DIR, vol, case_name + ".json")
                chunks_data = []
                if os.path.exists(chunk_path):
                    raw_chunks = read_json(chunk_path)
                    if isinstance(raw_chunks, list):
                        chunks_data = [
                            {
                                "chunk_id": c.get("chunk_id", ""),
                                "title": c.get("title", ""),
                                "content": c.get("content", ""),
                                "start_char": c.get("start_char", 0),
                                "end_char": c.get("end_char", 0),
                            }
                            for c in raw_chunks
                        ]
                tl_summary = tl_result.get("timeline_summary", {})
                time_gaps = tl_result.get("time_gaps", tl_summary.get("time_gaps", []))
                tl_data = {
                    "case_name": case_name,
                    "volume": vol,
                    "events": events,
                    "timeline_summary": tl_summary,
                    "time_gaps": time_gaps,
                    "causation_chain": tl_result.get("causation_chain", []),
                    "chunks": chunks_data,
                }
                slug = case_slugs.get(case_name)
                if not slug:
                    slug = f"case_{next_idx:03d}"
                    case_slugs[case_name] = slug
                    next_idx += 1
                    case_volumes[case_name] = vol
                tl_path = os.path.join(tl_out_dir, slug + ".json")
                if write_json_if_changed(tl_path, tl_data):
                    rewritten_outputs += 1
                else:
                    unchanged_outputs += 1
                tl_count += 1

    print(f"  {'timeline (extraction v3.9 only)':45s}  {tl_count:3d} cases  ({tl_realign_count} spans realigned)")
    print(f"  {'timeline alignment cache':45s}  {tl_cache_hits:3d} hits  {tl_cache_misses:3d} misses")

    log_stage(build_started, "Stage 6/7: building timeline v3.10.4 views")
    # Build timeline data (extraction v3.10.4 via timeline_v310 artifact path)
    tl_v310_out_dir = os.path.join(SITE_DATA, "timeline_v310")
    os.makedirs(tl_v310_out_dir, exist_ok=True)
    tl_v310_count = 0
    patched_v310_dir = EXTRACTIONS_DIR_V3104_PATCHED
    if not os.path.isdir(patched_v310_dir):
        print("  WARNING: extraction v3.10.4 patched directory not found, skipping timeline_v310")
    else:
        emitted_v310_paths = set()
        v310_case_names = sorted(
            case_name
            for case_name in os.listdir(patched_v310_dir)
            if os.path.isdir(os.path.join(patched_v310_dir, case_name))
        )
        for case_name in v310_case_names:
            case_dir = os.path.join(patched_v310_dir, case_name)
            master_path = os.path.join(case_dir, "master.json")
            if not os.path.exists(master_path):
                continue
            master = read_json(master_path)
            if not isinstance(master, dict):
                continue
            volume = case_volumes.get(case_name, "")
            if not volume:
                continue
            tl_data = load_v310_timeline(case_name, volume)
            if not tl_data:
                continue
            slug = case_slugs.get(case_name)
            if not slug:
                slug = f"case_{next_idx:03d}"
                case_slugs[case_name] = slug
                next_idx += 1
                case_volumes[case_name] = volume
            tl_path = os.path.join(tl_v310_out_dir, slug + ".json")
            emitted_v310_paths.add(os.path.abspath(tl_path))
            if write_json_if_changed(tl_path, tl_data):
                rewritten_outputs += 1
            else:
                unchanged_outputs += 1
            tl_v310_count += 1
        for name in sorted(os.listdir(tl_v310_out_dir)):
            if not name.endswith(".json"):
                continue
            stale_path = os.path.abspath(os.path.join(tl_v310_out_dir, name))
            if stale_path in emitted_v310_paths:
                continue
            os.remove(stale_path)
            rewritten_outputs += 1
        print(
            f"  {'timeline (extraction v3.10.4 patched only)':45s}  {tl_v310_count:3d} cases"
        )

    log_stage(build_started, "Stage 7/7: writing eval whitelist and manifest")
    # Load human eval 30-case whitelist
    eval_candidates_path = os.path.join(SOURCE_PROJECT, "data", "human_eval_30_candidates.json")
    eval_case_set = {}   # case_name -> {"volume": vol, "short_name": str}
    if os.path.exists(eval_candidates_path):
        with open(eval_candidates_path, encoding="utf-8") as f:
            ec = json.load(f)
        for vol in VOLUMES:
            for entry in ec.get(vol, []):
                eval_case_set[entry["case"]] = {
                    "volume": vol,
                    "short_name": entry.get("short_name", ""),
                }

    # Build case_info for display names
    case_info = {}
    for case in all_cases:
        info = extract_case_info(case)
        vol = case_volumes.get(case, "")
        info["volume"] = vol
        short = extract_case_title(case, vol)
        info["short_title"] = short
        verdict = info.get("verdict")
        if vol == "上冊" and verdict:
            info["display"] = f"{vol[:1]}-{verdict}{info['number']}・{short}" if short else case
        else:
            vol_mark = vol[:1] if vol else ""
            info["display"] = f"{vol_mark}-{info['number']}・{short}" if short else case
        case_info[case] = info

    # Build eval_cases list (30 cases, ordered by volume then by manifest order)
    eval_cases = [c for c in all_cases if c in eval_case_set]
    eval_slugs = [case_slugs[c] for c in eval_cases if c in case_slugs]
    print(f"  {'eval whitelist':45s}  {len(eval_cases):3d} cases")

    # Build manifest (includes slug mapping and volume info for frontend)
    manifest = {
        "conditions": manifest_conditions,
        "condition_labels": CONDITION_LABELS,
        "condition_groups": CONDITION_GROUPS,
        "cases": all_cases,
        "eval_cases": eval_cases,
        "eval_slugs": eval_slugs,
        "case_slugs": case_slugs,
        "case_volumes": case_volumes,
        "case_info": case_info,
        "volumes": VOLUMES,
    }
    if write_json_if_changed(os.path.join(SITE_DATA, "manifest.json"), manifest):
        rewritten_outputs += 1
    else:
        unchanged_outputs += 1

    total = sum(c["case_count"] for c in manifest_conditions.values())
    vol_counts = {}
    for c in all_cases:
        v = case_volumes.get(c, "")
        vol_counts[v] = vol_counts.get(v, 0) + 1
    vol_summary = ", ".join(f"{v}:{vol_counts.get(v, 0)}" for v in VOLUMES)
    print(
        f"\n  Total: {len(manifest_conditions)} conditions, {len(all_cases)} cases ({vol_summary}), {total} data files"
    )
    print(
        f"  Rewritten: {rewritten_outputs} files, unchanged skipped: {unchanged_outputs}"
    )

    save_timeline_align_cache(timeline_align_cache)
    save_view_build_cache(view_build_cache)
    log_stage(build_started, "Build complete")


if __name__ == "__main__":
    build()
