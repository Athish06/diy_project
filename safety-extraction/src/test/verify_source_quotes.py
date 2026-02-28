import json
import re
from pathlib import Path
import fitz  # PyMuPDF

# ================= CONFIG =================
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
JSON_FILE  = str(_PROJECT_ROOT / "output" / "batch_23_docs_20260228_184812.json")
PDF_FOLDER = str(_PROJECT_ROOT / "input")

# ================= PDF TEXT EXTRACTION =================

def extract_page_text(page):
    """
    Extract text from a single fitz page.
    If no selectable text exists, fall back to PyMuPDF's built-in OCR.
    Returns (text, method) where method is 'native' or 'ocr'.
    """
    text = page.get_text().strip()
    if text:
        return text, "native"

    # OCR fallback using PyMuPDF's built-in OCR (no Tesseract needed)
    try:
        tp = page.get_textpage_ocr(flags=0, full=True)
        ocr_text = page.get_text(textpage=tp).strip()
        if ocr_text:
            return ocr_text, "ocr"
    except Exception:
        pass

    # Second attempt with different flags
    try:
        tp = page.get_textpage_ocr(flags=fitz.TEXT_PRESERVE_WHITESPACE, full=True)
        ocr_text = page.get_text(textpage=tp).strip()
        if ocr_text:
            return ocr_text, "ocr"
    except Exception as e:
        return "", f"ocr_failed({e})"

    return "", "none"


def load_all_pdfs(pdf_folder):
    """
    Load all PDFs from the folder with OCR fallback for scanned pages.
    Returns a dict: { stem_lower: (pdf_path, pages_list, normalized_pages_list) }
    """
    pdfs = list(Path(pdf_folder).glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in: {pdf_folder}")
        return {}

    pdf_texts = {}
    no_text_files = []

    for pdf_path in pdfs:
        try:
            doc = fitz.open(str(pdf_path))
        except Exception as e:
            print(f"  ERROR opening {pdf_path.name}: {e}")
            continue

        if len(doc) == 0:
            print(f"  WARNING: {pdf_path.name} has 0 pages — skipping.")
            no_text_files.append(pdf_path.name)
            doc.close()
            continue

        pages = []
        normed_pages = []
        ocr_count = 0
        native_count = 0

        for page in doc:
            text, method = extract_page_text(page)
            pages.append(text)
            normed_pages.append(normalize(text))
            if method == "native":
                native_count += 1
            elif method == "ocr":
                ocr_count += 1

        doc.close()

        total_text = sum(len(p) for p in pages)
        if total_text == 0:
            print(f"  NO TEXT : {pdf_path.name}  ({len(pages)} pages, even after OCR)")
            no_text_files.append(pdf_path.name)
        else:
            mode_note = ""
            if ocr_count > 0 and native_count > 0:
                mode_note = f"  [{native_count} native + {ocr_count} OCR pages]"
            elif ocr_count > 0:
                mode_note = f"  [all {ocr_count} pages via OCR]"
            print(f"  Loaded : {pdf_path.name}  ({len(pages)} pages){mode_note}")

        pdf_texts[pdf_path.stem.lower()] = (pdf_path, pages, normed_pages)

    if no_text_files:
        print(f"\n  FILES WITH NO EXTRACTABLE TEXT ({len(no_text_files)}):")
        for name in no_text_files:
            print(f"    - {name}")

    return pdf_texts


def normalize(text):
    """Collapse all whitespace into single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def find_matching_pdf(source_document, pdf_texts):
    """
    Find the best matching loaded PDF for a rule's source_document name.
    Returns the key into pdf_texts, or None if no match.
    """
    if not source_document:
        return None
    src_lower = source_document.lower()
    # Exact stem match
    if src_lower in pdf_texts:
        return src_lower
    # Partial match: src is substring of stem, or stem is substring of src
    for stem in pdf_texts:
        if src_lower in stem or stem in src_lower:
            return stem
    return None


# ================= CHECKER =================

def check_source_quotes(json_file, pdf_folder):
    # Load JSON
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Support both formats: root array OR { "rules": [...] }
    if isinstance(data, list):
        rules = data
    else:
        rules = data.get("rules", [])

    print(f"\nJSON     : {Path(json_file).name}")
    print(f"Rules    : {len(rules)}")
    print(f"PDF folder: {pdf_folder}")
    print("=" * 70)
    print("Loading PDFs...")
    pdf_texts = load_all_pdfs(pdf_folder)
    print(f"PDFs loaded: {len(pdf_texts)}")
    print("=" * 70)

    matched    = []   # (rule_id, source_doc, original_text, match_type, pdf_name, page_num)
    unmatched  = []   # (rule_id, source_doc, original_text, reason, page_num)
    no_pdf     = []   # (rule_id, source_doc) — no matching PDF in folder

    for rule in rules:
        rule_id     = rule.get("rule_id", "???")
        source_doc  = rule.get("source_document", "")
        original    = rule.get("original_text") or rule.get("source_quote")
        page_num    = rule.get("page_number")  # 1-based page number

        if not original or not str(original).strip():
            unmatched.append((rule_id, source_doc, original, "EMPTY/NULL original_text", page_num))
            continue

        original = str(original).strip()

        # Find the PDF for this rule
        pdf_key = find_matching_pdf(source_doc, pdf_texts)

        if pdf_key is None:
            no_pdf.append((rule_id, source_doc, original))
            continue

        pdf_path, pages, normed_pages = pdf_texts[pdf_key]
        pdf_name = Path(pdf_path).name
        total_pages = len(pages)

        # Check full document first
        full_raw = "\n".join(pages)
        full_normed = normalize(full_raw)

        # 1. Exact match in full document
        if original in full_raw:
            matched.append((rule_id, source_doc, original, "EXACT (full)", pdf_name, page_num))
            continue

        # 2. Normalized match in full document
        if normalize(original) in full_normed:
            matched.append((rule_id, source_doc, original, "NORMALIZED (full)", pdf_name, page_num))
            continue

        # 3. Check specific page if page_number is provided
        if page_num and isinstance(page_num, int) and 1 <= page_num <= total_pages:
            page_idx = page_num - 1  # 0-based
            page_raw = pages[page_idx]
            page_normed = normed_pages[page_idx]

            if original in page_raw:
                matched.append((rule_id, source_doc, original, f"EXACT (page {page_num})", pdf_name, page_num))
                continue

            if normalize(original) in page_normed:
                matched.append((rule_id, source_doc, original, f"NORMALIZED (page {page_num})", pdf_name, page_num))
                continue

            # Page specified but not found on that page
            unmatched.append((rule_id, source_doc, original, f"NOT FOUND on page {page_num} (but PDF exists)", page_num))
            continue

        # No page specified or invalid page, but not found in full document
        unmatched.append((rule_id, source_doc, original, f"NOT FOUND in {pdf_name}", page_num))

    total = len(rules)

    # ---- MATCHED ----
    print(f"\nMATCHED  ({len(matched)})")
    print("-" * 70)
    for rule_id, src, text, match_type, pdf_name, page_num in matched:
        short = (text[:70] + "...") if len(text) > 70 else text
        page_info = f" (page {page_num})" if page_num else ""
        print(f"  [{match_type:20}]  {str(rule_id)[:36]}  [{src}]{page_info}")
        print(f"             {short}")

    # ---- UNMATCHED ----
    print(f"\nUNMATCHED  ({len(unmatched)})")
    print("-" * 70)
    for rule_id, src, text, reason, page_num in unmatched:
        short = (str(text or '')[:70] + "...") if text and len(str(text)) > 70 else text
        page_info = f" (page {page_num})" if page_num else ""
        print(f"  [{reason[:30]:30}]  {str(rule_id)[:36]}  [{src}]{page_info}")
        if short:
            print(f"             {short}")

    # ---- NO PDF IN FOLDER ----
    print(f"\nNO MATCHING PDF IN FOLDER  ({len(no_pdf)})")
    print("-" * 70)
    by_src = {}
    for rule_id, src, _ in no_pdf:
        by_src.setdefault(src, 0)
        by_src[src] += 1
    for src, count in sorted(by_src.items(), key=lambda x: -x[1]):
        print(f"  {count:>4} rules  —  source: '{src}'")

    # ---- SUMMARY ----
    print("\n" + "=" * 70)
    print(f"  TOTAL              : {total}")
    print(f"  MATCHED            : {len(matched)}  ({len(matched)/total*100:.1f}%)")
    print(f"  UNMATCHED (PDF exists but text not found): {len(unmatched)}  ({len(unmatched)/total*100:.1f}%)")
    print(f"  NO PDF IN FOLDER   : {len(no_pdf)}  ({len(no_pdf)/total*100:.1f}%)")
    print("=" * 70)

    if matched:
        matched_ids = ", ".join(str(rule_id) for rule_id, *_ in matched)
        print(f"\n  Matched rule IDs:\n  {matched_ids}")
    else:
        print("\n  No rules matched.")


# ================= MAIN =================

if __name__ == "__main__":
    check_source_quotes(JSON_FILE, PDF_FOLDER)

