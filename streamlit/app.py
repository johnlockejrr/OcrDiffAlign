import streamlit as st
import re
import os
import uuid
import csv
from rapidfuzz import process, fuzz
import difflib
from collections import Counter

# --- Normalization ---
def normalize_hebrew(text):
    text = re.sub(r"[^\u0590-\u05FF\s]", "", text)
    return text.strip()

# --- Build candidate windows ---
def build_windows(reference_text, window_size):
    words = reference_text.split()
    return [" ".join(words[i:i+window_size]) for i in range(len(words)-window_size+1)]

# --- Character-level diff + confusion tracking ---
def diff_strings(ocr, ref, confusion_log):
    diff = list(difflib.ndiff(ocr, ref))
    out = []
    i = 0
    while i < len(diff):
        d = diff[i]
        if d.startswith(" "):
            out.append(d[-1])
        elif d.startswith("-"):
            # check if next is a "+"
            if i+1 < len(diff) and diff[i+1].startswith("+"):
                ocr_char = d[-1]
                ref_char = diff[i+1][-1]
                out.append(f":red[{ocr_char}]")
                out.append(f":green[{ref_char}]")
                confusion_log.append((ocr, ref, ocr_char, ref_char))
                i += 1  # skip the paired "+"
            else:
                out.append(f":red[{d[-1]}]")
                confusion_log.append((ocr, ref, d[-1], ""))  # deletion only
        elif d.startswith("+"):
            out.append(f":green[{d[-1]}]")
            confusion_log.append((ocr, ref, "", d[-1]))  # insertion only
        i += 1
    return "".join(out)

def diff_strings_html(ocr, ref, confusion_log):
    diff = list(difflib.ndiff(ocr, ref))
    out = []
    i = 0
    while i < len(diff):
        d = diff[i]
        if d.startswith(" "):
            out.append(d[-1])
        elif d.startswith("-"):
            # check if next is a "+"
            if i+1 < len(diff) and diff[i+1].startswith("+"):
                ocr_char = d[-1]
                ref_char = diff[i+1][-1]
                out.append(f'<span style="color:red;font-weight:bold">{ocr_char}</span>')
                out.append(f'<span style="color:green;font-weight:bold">{ref_char}</span>')
                confusion_log.append((ocr, ref, ocr_char, ref_char))
                i += 1  # skip the paired "+"
            else:
                out.append(f'<span style="color:red;font-weight:bold">{d[-1]}</span>')
                confusion_log.append((ocr, ref, d[-1], ""))  # deletion only
        elif d.startswith("+"):
            out.append(f'<span style="color:green;font-weight:bold">{d[-1]}</span>')
            confusion_log.append((ocr, ref, "", d[-1]))  # insertion only
        i += 1
    return "".join(out)

# --- Align OCR lines ---
def align_ocr_lines(ocr_lines, reference_text, threshold):
    ref_norm = normalize_hebrew(reference_text)
    results = []
    confusion_log = []

    for line_num, line in enumerate(ocr_lines, start=1):
        norm_line = normalize_hebrew(line)
        ocr_tokens = norm_line.split()
        base_size = len(ocr_tokens)

        # Flexible window sizes: allow ±1
        window_sizes = [s for s in (base_size - 1, base_size, base_size + 1) if s > 0]
        candidates = []
        for w in window_sizes:
            candidates.extend(build_windows(ref_norm, w))

        # remove duplicates
        candidates = list(dict.fromkeys(candidates))
        match, score, idx = process.extractOne(norm_line, candidates, scorer=fuzz.ratio)
        start_index = ref_norm.find(match)

        diff_str = diff_strings_html(line, match, confusion_log)
        results.append({
            "line_num": line_num,
            "ocr": line,
            "match": match,
            "score": score,
            "index": start_index,
            "final_match": match,  # <-- initialize final_match
            "diff": diff_str
        })

    #results.sort(key=lambda x: x["index"])
    return results, confusion_log

# --- App state ---
if "page" not in st.session_state:
    st.session_state.page = 0
if "results" not in st.session_state:
    st.session_state.results = []
if "confusions" not in st.session_state:
    st.session_state.confusions = []
if "uuid" not in st.session_state:
    st.session_state.uuid = uuid.uuid4().hex[:8]

# --- UI ---
st.title("📜 Hebrew OCR Alignment Tool")

ref_files = [f for f in os.listdir("ref") if f.endswith(".txt")]
selected_ref = st.selectbox("Select reference text", ref_files)

with open(os.path.join("ref", selected_ref), encoding="utf-8") as f:
    reference_text = f.read()

ocr_input = st.text_area("Paste OCR text (line-separated)", height=200)
uploaded_file = st.file_uploader("Or upload OCR text file", type=["txt"])
if uploaded_file:
    ocr_input = uploaded_file.read().decode("utf-8")

ocr_lines = [line.strip() for line in ocr_input.splitlines() if line.strip()]
threshold = st.slider("Low-score threshold (highlight for manual edit)", 0, 100, 70)

if st.button("Run Alignment"):
    if not ocr_lines:
        st.warning("Please paste or upload OCR text first.")
    else:
        results, confusion_log = align_ocr_lines(ocr_lines, reference_text, threshold)
        st.session_state.results = results
        st.session_state.confusions = confusion_log
        st.session_state.page = 0
        #st.rerun() # Remove st.rerun() here - let Streamlit naturally rerender

# --- Pagination ---
results = st.session_state.results
page_size = 10
total_pages = (len(results) - 1) // page_size + 1 if results else 1
start = st.session_state.page * page_size
end = start + page_size
current_page_results = results[start:end]

if results:
    st.subheader(f"Results (Page {st.session_state.page + 1} of {total_pages})")

    for i, r in enumerate(current_page_results):
        st.markdown("---")
        st.markdown(f"**Line {r['line_num']}**")
        st.markdown(f"OCR: {r['ocr']}")
        #st.markdown(f"Diff: {diff_strings(r['ocr'], r['match'], st.session_state.confusions)}")
        st.markdown(f"Diff: {r['diff']}", unsafe_allow_html=True)
        st.markdown(f"Match: {r['match']} (score {r['score']})")

        # no editing, so just persist match as final_match
        r["final_match"] = r["match"]
        st.session_state.results[start + i] = r

    # Navigation
    col1, col2, col3 = st.columns([1,2,1])
    with col1:
        if st.session_state.page > 0:
            if st.button("⬅️ Previous"):
                st.session_state.page -= 1
                st.rerun()
    with col3:
        if st.session_state.page < total_pages - 1:
            if st.button("Next ➡️"):
                st.session_state.page += 1
                st.rerun()

    # Save outputs
    # make sure the directory exists
    os.makedirs("aligned", exist_ok=True)
    base = os.path.join("aligned", f"alignment_{st.session_state.uuid}")
    csv_path = f"{base}.csv"
    txt_path = f"{base}.txt"
    confusion_path = os.path.join("aligned", f"confusions_{st.session_state.uuid}.csv")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["OCR Line", "Best Match", "Score", "Index", "Final Match"])
        for r in results:
            writer.writerow([
                r["ocr"],
                r["match"],
                r["score"],
                r["index"],
                r.get("final_match", r["match"])  # <-- safe fallback
            ])

    with open(txt_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(r.get("final_match", r["match"]) + "\n")

    # Confusion stats
    confusion_counts = Counter((o, r, c, cw) for o, r, c, cw in st.session_state.confusions)
    with open(confusion_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["OCR Line", "Reference Line", "Confused Char", "Confused With", "Count"])
        for (o, r, c, cw), count in confusion_counts.items():
            writer.writerow([o, r, c, cw, count])

    # Downloads
    with open(csv_path, "rb") as f:
        st.download_button("⬇️ Download Alignment CSV", f, file_name=csv_path, mime="text/csv")
    with open(txt_path, "rb") as f:
        st.download_button("⬇️ Download Matched Text", f, file_name=txt_path, mime="text/plain")
    with open(confusion_path, "rb") as f:
        st.download_button("⬇️ Download Confusion Log", f, file_name=confusion_path, mime="text/csv")

    st.success("Alignment complete!")

