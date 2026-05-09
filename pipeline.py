"""
Question Bank Pipeline
----------------------
Checks for newly released Grade 7 Math tests from MCAS and STAAR,
downloads any new PDFs, extracts text, and appends new questions to the bank.

Run manually:   python pipeline.py
Scheduled by:   Windows Task Scheduler (see setup_schedule.ps1)
"""

import json, os, re, csv, sys, datetime, textwrap
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
PDF_DIR    = BASE_DIR / "pdfs"
TXT_DIR    = BASE_DIR / "txt"
LOG_DIR    = BASE_DIR / "logs"
MANIFEST   = BASE_DIR / "manifest.json"
CSV_OUT    = BASE_DIR / "grade7_math_question_bank.csv"
MD_OUT     = BASE_DIR / "grade7_math_question_bank.md"

for d in (PDF_DIR, TXT_DIR, LOG_DIR):
    d.mkdir(exist_ok=True)

# Source URLs — add new years here as they are released
SOURCES = [
    # MCAS Grade 7 Math — released each summer (July/August)
    {
        "name": "MCAS 2026 Grade 7",
        "filename": "mcas_2026_g7.pdf",
        "url": "https://www.doe.mass.edu/mcas/2026/release/g7-math.pdf",
        "grade": 7, "subject": "Math", "source_tag": "MCAS 2026",
    },
    {
        "name": "MCAS 2025 Practice Test (updated)",
        "filename": "mcas_practice_g7_2026.pdf",
        "url": "https://mcas.onlinehelp.cognia.org/wp-content/uploads/sites/30/2025/08/MCAS_26-27_PT_Math_G7_ADA.pdf",
        "grade": 7, "subject": "Math", "source_tag": "MCAS Practice 2026",
    },
    # STAAR Grade 7 Math — released each summer (June/July)
    {
        "name": "STAAR 2025 Grade 7 Test",
        "filename": "staar_2025_g7_test.pdf",
        "url": "https://tea.texas.gov/sites/default/files/staar-2025-g7-math-released.pdf",
        "grade": 7, "subject": "Math", "source_tag": "STAAR 2025",
    },
    {
        "name": "STAAR 2026 Grade 7",
        "filename": "staar_2026_g7_test.pdf",
        "url": "https://tea.texas.gov/sites/default/files/staar-2026-g7-math-released.pdf",
        "grade": 7, "subject": "Math", "source_tag": "STAAR 2026",
    },
]

# ── Logging ───────────────────────────────────────────────────────────────────
today      = datetime.date.today()
log_path   = LOG_DIR / f"pipeline_{today.isoformat()}.log"
_log_lines = []

def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    _log_lines.append(line)

def save_log():
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"Question Bank Pipeline — {today}\n")
        f.write("=" * 60 + "\n")
        f.write("\n".join(_log_lines))
    print(f"\nLog saved: {log_path}")

# ── Manifest ──────────────────────────────────────────────────────────────────
def load_manifest():
    if MANIFEST.exists():
        with open(MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    return {"last_run": None, "downloaded_pdfs": [], "processed_txt": [], "question_count": 0}

def save_manifest(m):
    m["last_run"] = today.isoformat()
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2)

# ── Step 1: Download new PDFs ─────────────────────────────────────────────────
def check_and_download(manifest):
    """Try each source URL. Download if not already in manifest."""
    try:
        import requests
    except ImportError:
        log("ERROR: 'requests' library not installed. Run: pip install requests")
        return []

    new_pdfs = []
    for src in SOURCES:
        fname = src["filename"]
        if fname in manifest["downloaded_pdfs"]:
            log(f"SKIP (already have): {fname}")
            continue

        pdf_path = PDF_DIR / fname
        if pdf_path.exists():
            log(f"SKIP (file exists): {fname}")
            manifest["downloaded_pdfs"].append(fname)
            continue

        log(f"Checking: {src['name']} ...")
        try:
            resp = requests.head(src["url"], timeout=15, allow_redirects=True)
            if resp.status_code == 200:
                log(f"  Found! Downloading {fname} ...")
                r = requests.get(src["url"], timeout=60)
                with open(pdf_path, "wb") as f:
                    f.write(r.content)
                size_kb = pdf_path.stat().st_size // 1024
                log(f"  Downloaded: {fname} ({size_kb} KB)")
                manifest["downloaded_pdfs"].append(fname)
                new_pdfs.append((pdf_path, src))
            else:
                log(f"  Not available yet (HTTP {resp.status_code}): {src['name']}")
        except Exception as e:
            log(f"  Error checking {src['name']}: {e}")

    return new_pdfs

# ── Step 2: Extract text from new PDFs ────────────────────────────────────────
def extract_text(new_pdfs, manifest):
    """Run pdfplumber on each new PDF and write .txt to txt/ directory."""
    try:
        import pdfplumber
    except ImportError:
        log("ERROR: 'pdfplumber' not installed. Run: pip install pdfplumber")
        return []

    new_txts = []
    for pdf_path, src in new_pdfs:
        txt_name = pdf_path.stem + ".txt"
        txt_path = TXT_DIR / txt_name

        if txt_name in manifest["processed_txt"]:
            log(f"SKIP (already extracted): {txt_name}")
            continue

        log(f"Extracting text: {pdf_path.name} ...")
        try:
            with pdfplumber.open(pdf_path) as pdf:
                pages = [f"=== PAGE {i+1} ===\n{page.extract_text() or ''}"
                         for i, page in enumerate(pdf.pages)]
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("\n\n".join(pages))
            log(f"  Extracted {len(pages)} pages → {txt_name}")
            manifest["processed_txt"].append(txt_name)
            new_txts.append((txt_path, src))
        except Exception as e:
            log(f"  Error extracting {pdf_path.name}: {e}")

    return new_txts

# ── Step 3: Parse questions from extracted text ───────────────────────────────
# This is a best-effort parser that finds MCAS-style questions.
# It captures question blocks and their answer tables from the end of the document.

MCAS_ANSWER_TABLE_RE = re.compile(
    r'(?P<item>\d+)\s+(?P<cat>[\w\s&/]+?)\s+'
    r'(?P<std>7\.[A-Z]+\.[A-Z]+\.\d+)\s+(?:SR|SA|CR|MS)\s+(?P<ans>[A-Z0-9;,.\s]+)',
    re.IGNORECASE
)

def parse_mcas_answer_key(text):
    """Extract item→(standard, answer) pairs from MCAS released-item tables."""
    answers = {}
    for m in MCAS_ANSWER_TABLE_RE.finditer(text):
        item_num = int(m.group("item"))
        std  = m.group("std").strip()
        ans  = m.group("ans").strip().split()[0]  # first token
        answers[item_num] = {"standard": std, "answer": ans}
    return answers

def extract_questions_from_text(txt_path, src):
    """Best-effort question extraction for MCAS-style tests."""
    with open(txt_path, encoding="utf-8") as f:
        raw = f.read()

    answer_key = parse_mcas_answer_key(raw)
    log(f"  Answer key entries found: {len(answer_key)}")

    # Split into pages
    pages = re.split(r"=== PAGE \d+ ===", raw)

    questions = []
    q_num = 0

    for page in pages:
        # Look for pages that contain answer choice patterns (A ... B ... C ... D)
        if not re.search(r'\bA\b.*\bB\b.*\bC\b', page, re.DOTALL):
            continue

        # Rough question block: text before first answer choice
        blocks = re.split(r'\n(?=[A-D]\n|\bA\)|B\)|C\)|D\))', page.strip())
        if len(blocks) < 2:
            continue

        stem = blocks[0].strip()
        choices_raw = " ".join(blocks[1:]).strip()

        # Skip non-question pages (directions, reference sheets, etc.)
        if len(stem) < 30 or any(skip in stem for skip in [
            "Directions", "Examples", "EXAMPLE", "Reference Sheet",
            "SESSION", "Practice Test", "You may"
        ]):
            continue

        q_num += 1
        key_data = answer_key.get(q_num, {})
        std  = key_data.get("standard", "")
        ans  = key_data.get("answer", "")

        # Map standard to IM unit
        unit_num, unit_name, ccss_domain = map_standard_to_unit(std)

        questions.append({
            "unit_number": unit_num,
            "unit_name": unit_name,
            "ccss_standard": std,
            "question_type": "Multiple Choice",
            "difficulty": "Medium",
            "has_diagram": "No",
            "diagram_description": "",
            "diagram_source_page": f"Page ~{q_num+3}, {src['name']} PDF",
            "question": stem[:600],  # cap length
            "answer_choices": choices_raw[:400],
            "correct_answer": ans,
            "solution_steps": "See source PDF for full worked solution.",
            "source": src["source_tag"],
            "source_url": src["url"],
        })

    log(f"  Parsed {len(questions)} candidate questions from {txt_path.name}")
    return questions

UNIT_MAP = [
    # (ccss_prefix, unit_number, unit_name)
    ("7.G.A.1",  1, "Scale Drawings"),
    ("7.G.A",    1, "Scale Drawings"),          # fallback for A.2, A.3 → check domain
    ("7.RP.A.2", 2, "Introducing Proportional Relationships"),
    ("7.G.B.4",  3, "Measuring Circles"),
    ("7.RP.A.1", 4, "Proportional Relationships and Percentages"),
    ("7.RP.A.3", 4, "Proportional Relationships and Percentages"),
    ("7.NS",     5, "Rational Number Arithmetic"),
    ("7.EE",     6, "Expressions, Equations, and Inequalities"),
    ("7.G.A.2",  7, "Angles, Triangles, and Prisms"),
    ("7.G.A.3",  7, "Angles, Triangles, and Prisms"),
    ("7.G.B.5",  7, "Angles, Triangles, and Prisms"),
    ("7.G.B.6",  7, "Angles, Triangles, and Prisms"),
    ("7.SP",     8, "Probability and Sampling"),
]

def map_standard_to_unit(std):
    if not std:
        return (9, "Putting It All Together", "Mixed")
    for prefix, unum, uname in UNIT_MAP:
        if std.startswith(prefix):
            return (unum, uname, std.split(".")[0] + "." + std.split(".")[1])
    return (9, "Putting It All Together", "Mixed")

# ── Step 4: Deduplicate and append to question bank ───────────────────────────
FIELDNAMES = [
    "unit_number","unit_name","ccss_standard","question_type","difficulty",
    "has_diagram","diagram_description","diagram_source_page","question",
    "answer_choices","correct_answer","solution_steps","source","source_url"
]

def load_existing_questions():
    if not CSV_OUT.exists():
        return []
    with open(CSV_OUT, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def dedup_and_append(new_qs, existing_qs):
    """Append new questions that aren't already in the bank (by source + question snippet)."""
    existing_keys = {
        (r["source"], r["question"][:80])
        for r in existing_qs
    }
    added = []
    for q in new_qs:
        key = (q["source"], q["question"][:80])
        if key not in existing_keys:
            existing_qs.append(q)
            existing_keys.add(key)
            added.append(q)
    return added

def write_csv(all_qs):
    with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(all_qs)

def write_markdown(all_qs):
    from collections import defaultdict
    UNIT_NAMES = {
        1:"Scale Drawings", 2:"Introducing Proportional Relationships",
        3:"Measuring Circles", 4:"Proportional Relationships and Percentages",
        5:"Rational Number Arithmetic", 6:"Expressions, Equations, and Inequalities",
        7:"Angles, Triangles, and Prisms", 8:"Probability and Sampling",
        9:"Putting It All Together",
    }
    by_unit = defaultdict(list)
    for item in all_qs:
        by_unit[int(item["unit_number"])].append(item)

    with open(MD_OUT, "w", encoding="utf-8") as f:
        f.write("# Newton Public Schools — Grade 7 Math Question Bank\n\n")
        f.write("**Curriculum:** Illustrative Mathematics (IM) / Desmos Math  \n")
        f.write(f"**Total Questions:** {len(all_qs)}  \n")
        f.write(f"**Last Updated:** {today}  \n\n---\n\n")
        for unit_num in sorted(by_unit.keys()):
            items = by_unit[unit_num]
            uname = UNIT_NAMES.get(unit_num, "Mixed")
            standards = ", ".join(sorted(set(i["ccss_standard"] for i in items if i["ccss_standard"])))
            f.write(f"## Unit {unit_num}: {uname}\n\n")
            f.write(f"**Standards:** {standards}  \n**Questions:** {len(items)}  \n\n")
            for idx, item in enumerate(items, 1):
                f.write(f"### Q{unit_num}.{idx}\n\n")
                f.write(f"**Type:** {item['question_type']} | "
                        f"**Standard:** {item['ccss_standard']} | "
                        f"**Difficulty:** {item['difficulty']} | "
                        f"**Source:** {item['source']}\n\n")
                if item.get("has_diagram") == "Yes" and item.get("diagram_source_page"):
                    f.write(f"> **Diagram:** See {item['diagram_source_page']}\n\n")
                f.write(f"{item['question']}\n\n")
                if item.get("answer_choices"):
                    for ch in item["answer_choices"].split("  "):
                        if ch.strip():
                            f.write(f"- {ch.strip()}\n")
                    f.write("\n")
                f.write("<details><summary>Answer</summary>\n\n")
                f.write(f"**Correct Answer:** {item['correct_answer']}\n\n")
                if item.get("solution_steps"):
                    f.write(f"**Solution:** {item['solution_steps']}\n\n")
                f.write("</details>\n\n---\n\n")

# ── Step 5: Summary report ────────────────────────────────────────────────────
def write_report(added_qs, total_before, total_after):
    report_path = LOG_DIR / f"report_{today.isoformat()}.md"
    from collections import Counter
    by_unit = Counter(str(q["unit_number"]) for q in added_qs)
    by_src  = Counter(q["source"] for q in added_qs)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Question Bank Update Report — {today}\n\n")
        f.write(f"- Questions before: **{total_before}**\n")
        f.write(f"- Questions added:  **{len(added_qs)}**\n")
        f.write(f"- Questions after:  **{total_after}**\n\n")
        if added_qs:
            f.write("## Added by Unit\n\n")
            for u, cnt in sorted(by_unit.items()):
                f.write(f"- Unit {u}: {cnt} new questions\n")
            f.write("\n## Added by Source\n\n")
            for s, cnt in sorted(by_src.items()):
                f.write(f"- {s}: {cnt} new questions\n")
            f.write("\n## New Questions (preview)\n\n")
            for q in added_qs[:10]:
                f.write(f"- **[Unit {q['unit_number']}]** {q['question'][:100]}...\n")
            if len(added_qs) > 10:
                f.write(f"- *(and {len(added_qs)-10} more)*\n")
        else:
            f.write("No new questions were added this run.\n")
    log(f"Report: {report_path}")
    return report_path

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log("=" * 60)
    log("Grade 7 Math Question Bank Pipeline")
    log(f"Run date: {today}")
    log("=" * 60)

    manifest = load_manifest()
    log(f"Manifest loaded. Known PDFs: {len(manifest['downloaded_pdfs'])}")

    # Step 1: Check and download new PDFs
    log("\n--- Step 1: Checking for new test releases ---")
    new_pdfs = check_and_download(manifest)
    if not new_pdfs:
        log("No new PDFs found this run.")

    # Step 2: Extract text from new PDFs
    log("\n--- Step 2: Extracting text ---")
    new_txts = extract_text(new_pdfs, manifest) if new_pdfs else []

    # Step 3: Parse questions
    log("\n--- Step 3: Parsing questions ---")
    new_qs = []
    for txt_path, src in new_txts:
        qs = extract_questions_from_text(txt_path, src)
        new_qs.extend(qs)
    log(f"Total new candidate questions: {len(new_qs)}")

    # Step 4: Deduplicate and append
    log("\n--- Step 4: Updating question bank ---")
    existing = load_existing_questions()
    total_before = len(existing)
    if new_qs:
        added = dedup_and_append(new_qs, existing)
        log(f"New unique questions added: {len(added)}")
        if added:
            write_csv(existing)
            write_markdown(existing)
            manifest["question_count"] = len(existing)
            log(f"Bank updated: {len(existing)} total questions")
    else:
        added = []
        log("No new questions to add.")

    # Step 5: Report
    log("\n--- Step 5: Writing report ---")
    report = write_report(added, total_before, len(existing))

    # Save manifest
    save_manifest(manifest)
    log("\nManifest saved.")

    # Final summary
    log("\n" + "=" * 60)
    log(f"DONE. Bank size: {len(existing)} questions. Added: {len(added)}.")
    log("=" * 60)
    save_log()

if __name__ == "__main__":
    main()
