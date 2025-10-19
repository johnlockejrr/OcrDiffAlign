import re
import csv
import argparse
import uuid
import os
from rapidfuzz import process, fuzz
import difflib
from collections import Counter

# --- Normalization ---
def normalize_hebrew(text):
    text = re.sub(r"[^\u0590-\u05FF\s]", "", text)  # keep only Hebrew letters + spaces
    return text.strip()

# --- Build candidate windows ---
def build_windows(reference_text, window_size):
    words = reference_text.split()
    return [" ".join(words[i:i+window_size]) for i in range(len(words)-window_size+1)]

# --- Character-level diff + confusion tracking ---
def diff_strings(ocr, ref, confusion_log):
    diff = list(difflib.ndiff(ocr, ref))
    i = 0
    while i < len(diff):
        d = diff[i]
        if d.startswith("-"):
            if i+1 < len(diff) and diff[i+1].startswith("+"):
                ocr_char = d[-1]
                ref_char = diff[i+1][-1]
                confusion_log.append((ocr_char, ref_char))
                i += 1
            else:
                confusion_log.append((d[-1], ""))  # deletion
        elif d.startswith("+"):
            confusion_log.append(("", d[-1]))  # insertion
        i += 1

# --- Align OCR lines ---
def align_ocr_lines(ocr_lines, reference_text, outdir, threshold=70):
    os.makedirs(outdir, exist_ok=True)
    ref_norm = normalize_hebrew(reference_text)
    results = []
    confusion_log = []

    uid = uuid.uuid4().hex[:8]
    csv_path = os.path.join(outdir, f"alignment_{uid}.csv")
    txt_path = os.path.join(outdir, f"alignment_{uid}.txt")
    confusion_path = os.path.join(outdir, f"confusions_{uid}.csv")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["OCR Line", "Best Match", "Score", "Start Index", "Final Match"])

        for line in ocr_lines:
            norm_line = normalize_hebrew(line)
            #window_size = max(1, len(norm_line.split()))
            #candidates = build_windows(ref_norm, window_size)
            ocr_tokens = norm_line.split()
            base_size = len(ocr_tokens)
            window_sizes = [s for s in (base_size-1, base_size, base_size+1) if s > 0]
            candidates = []
            for w in window_sizes:
                candidates.extend(build_windows(ref_norm, w))
            candidates = list(dict.fromkeys(candidates))

            match, score, idx = process.extractOne(norm_line, candidates, scorer=fuzz.ratio)
            start_index = ref_norm.find(match)

            # Track confusions
            diff_strings(line, match, confusion_log)

            final_match = match
            results.append((line, match, score, start_index, final_match))
            writer.writerow([line, match, score, start_index, final_match])

    # Sort by Torah position
    #results.sort(key=lambda x: x[3])

    # Save matched text
    with open(txt_path, "w", encoding="utf-8") as f:
        for _, _, _, _, final_match in results:
            f.write(final_match + "\n")

    # Save confusion stats
    confusion_counts = Counter(confusion_log)
    with open(confusion_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Confused Char", "Confused With", "Count"])
        for (c, cw), count in confusion_counts.most_common():
            writer.writerow([c, cw, count])

    # --- Summary Report ---
    scores = [s for _, _, s, _, _ in results]
    avg_score = sum(scores) / len(scores) if scores else 0
    low_conf = sum(1 for s in scores if s < threshold)
    low_conf_pct = (low_conf / len(scores) * 100) if scores else 0

    print("\n📊 Summary Report")
    print(f"- Lines processed: {len(results)}")
    print(f"- Average score: {avg_score:.2f}")
    print(f"- Low-confidence (<{threshold}): {low_conf} lines ({low_conf_pct:.1f}%)")

    print("\n🔝 Top 5 Confusions:")
    for (c, cw), count in confusion_counts.most_common(5):
        print(f"  {c or '∅'} → {cw or '∅'} : {count} times")

    return results, csv_path, txt_path, confusion_path

# --- CLI entrypoint ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Align OCR text against Hebrew reference")
    parser.add_argument("--ocr", required=True, help="Path to OCR text file")
    parser.add_argument("--ref", required=True, help="Path to reference text file")
    parser.add_argument("--out", default="aligned", help="Output directory (default: aligned/)")
    parser.add_argument("--threshold", type=int, default=70, help="Low-score threshold (default: 70)")
    args = parser.parse_args()

    with open(args.ocr, encoding="utf-8") as f:
        ocr_lines = [line.strip() for line in f if line.strip()]

    with open(args.ref, encoding="utf-8") as f:
        reference_text = f.read()

    results, csv_path, txt_path, confusion_path = align_ocr_lines(
        ocr_lines, reference_text, args.out, args.threshold
    )

    print(f"\n✅ Alignment complete!")
    print(f"- Alignment CSV: {csv_path}")
    print(f"- Matched text TXT: {txt_path}")
    print(f"- Confusion log CSV: {confusion_path}")

