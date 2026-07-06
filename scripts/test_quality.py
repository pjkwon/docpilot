"""
HWP 변환 품질 측정 스크립트
측정 항목: 구조 정확도(단락/표/셀/이미지/페이지), 텍스트 정확도, 처리 성능
실행: uv run python scripts/test_quality.py
"""
from __future__ import annotations

import contextlib
import io
import re
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

try:
    import psutil
    _proc = psutil.Process()
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("[경고] psutil 없음 — 메모리 측정 생략. `uv add psutil --dev`\n")

import pyhwpx
from lxml import etree

from docpilot.ingestion import hwpx as hwpx_ing

DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


@dataclass
class StructureCount:
    pages: int | None = None
    paragraphs: int = 0
    tables: int = 0
    cells: int = 0
    images: int = 0


@dataclass
class Result:
    name: str
    ok: bool = False
    error: str = ""
    elapsed_s: float = 0.0
    mem_delta_mb: float = 0.0
    hwp_bytes: int = 0
    hwpx_bytes: int = 0
    orig: StructureCount = field(default_factory=StructureCount)
    conv: StructureCount = field(default_factory=StructureCount)
    char_count: int = 0
    text_similarity: float | None = None


# ── pyhwpx에서 원본 구조 수집 ────────────────────────────────────────────────

def _get_orig_structure(hwp) -> StructureCount:
    s = StructureCount()
    for attr in ("page_count", "PageCount"):
        try:
            val = getattr(hwp, attr)
            s.pages = int(val() if callable(val) else val)
            break
        except Exception:
            pass
    return s


# ── HWPX XML에서 변환 결과 구조 수집 ─────────────────────────────────────────

def _find_section_names(zf: zipfile.ZipFile) -> list[str]:
    names = zf.namelist()
    hml = [n for n in names if n.endswith("content.hml")]
    if hml:
        return hml
    return sorted(
        (n for n in names if re.search(r"section\d+\.xml$", n, re.IGNORECASE)),
        key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)),
    )


def _get_conv_structure(hwpx_path: Path) -> StructureCount:
    s = StructureCount()
    try:
        with zipfile.ZipFile(hwpx_path) as zf:
            section_names = _find_section_names(zf)
            if not section_names:
                return s
            roots = [etree.fromstring(zf.read(n)) for n in section_names]

        for root in roots:
            ns = root.nsmap.get("hp", "http://www.hancom.co.kr/hwpml/2012/paragraph")
            hp = lambda tag, _ns=ns: f"{{{_ns}}}{tag}"  # noqa: E731
            s.paragraphs += sum(
                1 for p in root.iter(hp("p"))
                if "".join(el.text or "" for el in p.iter(hp("t"))).strip()
            )
            s.tables += sum(1 for _ in root.iter(hp("tbl")))
            s.cells  += sum(1 for _ in root.iter(hp("tc")))
            s.images += sum(1 for _ in root.iter(hp("pic")))
    except Exception:
        pass
    return s


# ── 텍스트 유사도 헬퍼 ───────────────────────────────────────────────────────

def _decode_hwp_text(raw: bytes) -> str:
    for enc in ("cp949", "utf-16", "utf-8"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="ignore")


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


# ── 파일 1개 측정 ────────────────────────────────────────────────────────────

def convert_and_measure(hwp, hwp_path: Path) -> Result:
    r = Result(name=hwp_path.name, hwp_bytes=hwp_path.stat().st_size)
    hwpx_out = OUTPUT_DIR / (hwp_path.stem + ".hwpx")
    txt_out  = OUTPUT_DIR / (hwp_path.stem + "_ref.txt")

    mem_before = _proc.memory_info().rss if HAS_PSUTIL else 0
    t0 = time.perf_counter()

    _buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(_buf), contextlib.redirect_stderr(_buf):
            hwp.open(str(hwp_path.resolve()))
            r.orig = _get_orig_structure(hwp)
            hwp.save_as(str(hwpx_out.resolve()), format="HWPX")
            try:
                hwp.save_as(str(txt_out.resolve()), format="TEXT")
            except Exception:
                txt_out = None
    except Exception as e:
        captured = _buf.getvalue().strip()
        r.error = f"{e}\n{captured}" if captured else str(e)
        return r

    r.elapsed_s = time.perf_counter() - t0
    if HAS_PSUTIL:
        r.mem_delta_mb = max(0.0, (_proc.memory_info().rss - mem_before) / 1024 ** 2)

    if not hwpx_out.exists():
        r.error = "HWPX 파일 미생성"
        return r

    r.hwpx_bytes = hwpx_out.stat().st_size
    r.conv = _get_conv_structure(hwpx_out)

    try:
        doc = hwpx_ing.ingest(hwpx_out)
        r.char_count = len(doc.content)
        if txt_out and txt_out.exists():
            ref_words  = set(_normalize(_decode_hwp_text(txt_out.read_bytes())).split())
            conv_words = set(_normalize(doc.content).split())
            union = ref_words | conv_words
            r.text_similarity = len(ref_words & conv_words) / len(union) if union else None
    except Exception as e:
        r.error = f"파싱 오류: {e}"
        return r

    r.ok = True
    return r


# ── 리포트 출력 ──────────────────────────────────────────────────────────────

def _na(val, fmt="{}", fallback="N/A"):
    return fmt.format(val) if val is not None else fallback


def print_report(results: list[Result]) -> None:
    ok   = [r for r in results if r.ok]
    fail = [r for r in results if not r.ok]

    W = 72
    print(f"\n{'─'*W}")
    print("[ 처리 성능 ]")
    hdr = f"{'파일':<24} {'시간(s)':>7} {'MB/s':>6} {'압축비':>6} {'메모리(MB)':>10} {'Jaccard':>7}"
    print(hdr)
    print("─" * W)
    for r in results:
        if r.ok:
            mb    = r.hwp_bytes / 1024 ** 2
            mbs   = f"{mb / r.elapsed_s:.2f}" if r.elapsed_s > 0 else "—"
            ratio = f"{r.hwpx_bytes / r.hwp_bytes:.2f}" if r.hwp_bytes else "—"
            mem   = f"{r.mem_delta_mb:.1f}" if HAS_PSUTIL else "N/A"
            sim   = _na(r.text_similarity, "{:.1%}")
            print(f"{r.name[:24]:<24} {r.elapsed_s:>7.2f} {mbs:>6} {ratio:>6} {mem:>10} {sim:>7}")
        else:
            print(f"{r.name[:24]:<24}  [실패] {r.error[:46]}")

    print(f"\n{'─'*W}")
    print("[ 구조 정확도 ]  변환(HWPX XML)")
    shdr = f"{'파일':<24} {'페이지':>6} {'문단':>6} {'표':>5} {'셀':>6} {'이미지':>6}"
    print(shdr)
    print("─" * W)
    for r in results:
        if not r.ok:
            print(f"{r.name[:24]:<24}  [실패]")
            continue
        o, c = r.orig, r.conv
        pages = _na(o.pages)
        print(f"{r.name[:24]:<24} {pages:>6} {c.paragraphs:>6} {c.tables:>5} {c.cells:>6} {c.images:>6}")

    total = len(results)
    print(f"\n{'─'*W}")
    print(f"총 {total}개  성공 {len(ok)}  실패 {len(fail)}  실패율 {len(fail)/total:.1%}")
    if ok:
        avg_t = sum(r.elapsed_s for r in ok) / len(ok)
        avg_mbs = sum(r.hwp_bytes / 1024**2 / r.elapsed_s for r in ok if r.elapsed_s > 0) / len(ok)
        print(f"평균 변환 시간  : {avg_t:.2f}s  ({avg_mbs:.2f} MB/s)")
        if HAS_PSUTIL:
            print(f"평균 메모리     : {sum(r.mem_delta_mb for r in ok)/len(ok):.1f} MB")
        sims = [r.text_similarity for r in ok if r.text_similarity is not None]
        if sims:
            print(f"평균 Jaccard 유사도: {sum(sims)/len(sims):.1%}")


# ── 엔트리포인트 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    hwp_files = sorted(DATA_DIR.glob("**/*.hwp"))
    if not hwp_files:
        print("data/ 폴더에 .hwp 파일이 없습니다.")
        sys.exit(0)

    print(f"총 {len(hwp_files)}개 파일 측정 시작...\n")

    _init_buf = io.StringIO()
    with contextlib.redirect_stdout(_init_buf), contextlib.redirect_stderr(_init_buf):
        hwp = pyhwpx.Hwp(visible=False)

    results = []
    try:
        for hwp_path in hwp_files:
            print(f"  {hwp_path.name} ...", end=" ", flush=True)
            r = convert_and_measure(hwp, hwp_path)
            results.append(r)
            print("완료" if r.ok else f"실패 ({r.error[:50]})")
    finally:
        try:
            hwp.quit()
        except Exception:
            pass

    print_report(results)
