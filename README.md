# 📜 Hebrew OCR Alignment Toolkit

This project provides tools to **align noisy OCR output** (e.g., Hebrew Torah passages) against a **reference text**.  
It includes both a **command-line interface (CLI)** and an **interactive Streamlit app**, plus specialized tools for **PAGE-XML file processing**.

---

## ✨ Features

### Core Alignment Engine
- **Normalization**: Strip non-Hebrew characters, preserve final forms (no unification).
- **Fuzzy alignment**: Uses `rapidfuzz` (Levenshtein distance) to align OCR lines with reference text.
- **Diagnostics**:
  - Character-level diffs (red = OCR-only, green = reference-only).
  - Confusion log: tracks substitutions (e.g., ת → ש).

### Text File Processing (`align.py`)
- **Outputs**:
  - Alignment CSV (OCR line, match, score, index, final match).
  - Matched text TXT (aligned reference text in same order as OCR input).
  - Confusion CSV (confusion statistics with `Confused Char` and `Confused With`).

### PAGE-XML Processing (`align-pagexml.py`) 🆕
- **PAGE-XML Support**: Processes PAGE-XML files with automatic namespace detection (2009-2019 schemas).
- **OCR Extraction**: Extracts text from `<Unicode>` tags under `<TextLine>` elements.
- **Smart Updates**: Replaces incorrect OCR lines with aligned reference text.
- **Clean Output**: Saves aligned PAGE-XML files without namespace prefixes.
- **Progress Tracking**: Rich progress bar for multiple files, detailed output for single files.
- **Batch Processing**: Handles both single files and entire directories.

### Streamlit App
- **Interactive Interface**:
  - Paste or upload OCR text.
  - Select reference text dynamically from `ref/*.txt`.
  - Set low-score threshold for editable matches.
  - Paginated results with inline editing.
  - Download buttons for CSV, TXT, and confusion logs.

---

## 📂 Project Structure
```
OcrDiffAlign/
├── align.py              # CLI script for text file alignment
├── align-pagexml.py      # CLI script for PAGE-XML file alignment 🆕
├── streamlit/
│   └── app.py            # Streamlit interactive app
├── ref/                  # Reference texts (*.txt)
├── samples/              # Sample PAGE-XML files for testing 🆕
└── aligned/              # Output directory for results
```
---

## ⚙️ Installation

git clone <your-repo-url>
cd OcrDiffAlign
pip install -r requirements.txt

### Requirements
- Python 3.9+
- rapidfuzz
- streamlit
- lxml (for PAGE-XML processing)
- rich (for progress bars)

Install with:

```bash
pip install rapidfuzz streamlit lxml rich
```

Or use conda:

```bash
conda create -n OcrDiffAlign-py3.11 python=3.11
conda activate OcrDiffAlign-py3.11
pip install rapidfuzz streamlit lxml rich
```

---

## 🖥️ CLI Usage

### Text File Alignment (`align.py`)

The CLI script aligns OCR lines against a reference text and saves results.

```bash
python align.py --ocr my_ocr.txt --ref ref/torah.txt --out aligned/
```

**Arguments:**
- `--ocr`: Path to OCR text file (line-separated).
- `--ref`: Path to reference text file.
- `--out`: Output directory (default: aligned/).
- `--threshold`: Low-score threshold (default: 70).

**Output:**
- `alignment_<uuid>.csv` → Alignment log.
- `alignment_<uuid>.txt` → Final matched text.
- `confusions_<uuid>.csv` → Confusion statistics.

### PAGE-XML File Alignment (`align-pagexml.py`) 🆕

The PAGE-XML script processes PAGE-XML files, extracts OCR text, aligns it with reference text, and updates the XML files with corrected text.

#### Single File Processing
```bash
python align-pagexml.py --pagexml document.xml --ref ref/torah.txt --out aligned/
```

**Output for single file:**
```
🚀 Starting PAGE-XML OCR Alignment
📁 Input: document.xml
📖 Reference: ref/torah.txt
📤 Output: aligned/

🔄 Processing: document.xml
📝 Found 39 OCR lines
🏷️  Detected namespace: http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15

📊 Summary Report
- Lines processed: 39
- Average score: 99.03
- Low-confidence (<70): 0 lines (0.0%)

🔝 Top 5 Confusions:
  ש → ∅ : 2 times
  ל → ∅ : 2 times
  ן → ף : 1 times
  ∅ → ו : 1 times
  ∅ → ע : 1 times
💾 Saved aligned PAGE-XML: aligned/xml/document.xml

✅ Alignment complete! Processed 1 file(s)

📄 File 1:
  - Aligned PAGE-XML: aligned/xml/document.xml
  - Alignment CSV: aligned/alignment_abc123.csv
  - Matched text TXT: aligned/alignment_abc123.txt
  - Confusion log CSV: aligned/confusions_abc123.csv
```

#### Multiple Files Processing
```bash
python align-pagexml.py --pagexml samples/ --ref ref/torah.txt --out aligned/
```

**Output for multiple files:**
```
  Processing BL_Or_1443_285.xml ━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:14 0:00:00

✅ Alignment complete! Processed 3/3 files successfully
📤 Aligned files saved to: aligned/xml/
```

**Arguments:**
- `--pagexml`: Path to PAGE-XML file or directory containing PAGE-XML files.
- `--ref`: Path to reference text file.
- `--out`: Output directory (default: aligned/).
- `--threshold`: Low-score threshold (default: 70).

**Features:**
- **Automatic namespace detection**: Supports PAGE-XML schemas from 2009-2019.
- **Smart text extraction**: Finds OCR text in `<Unicode>` tags under `<TextLine>` elements.
- **Intelligent updates**: Only replaces text that differs significantly (score > 50).
- **Clean XML output**: Removes namespace prefixes while preserving structure.
- **Progress tracking**: Rich progress bar for multiple files, detailed output for single files.
- **Timestamp updates**: Updates `<LastChange>` element with current timestamp.

**Output Structure:**
```
aligned/
├── xml/                          # Aligned PAGE-XML files
│   ├── document1.xml
│   └── document2.xml
├── alignment_<uuid>.csv          # Alignment details
├── alignment_<uuid>.txt          # Matched reference text
└── confusions_<uuid>.csv         # Character confusion statistics
```

---

## 🌐 Streamlit App

Run the interactive app:

streamlit run streamlit/app.py

### Workflow
1. Select a reference text from ref/.
2. Paste OCR text or upload a .txt file.
3. Adjust low-score threshold.
4. Click Run Alignment.
5. Review results:
   - Character-level diffs.
   - Editable low-confidence matches.
   - Paginated navigation.
6. Download outputs:
   - Alignment CSV
   - Matched text TXT
   - Confusion log CSV

---

## 📊 Confusion Log

The confusion log captures systematic OCR errors. Example:

OCR Line,Reference Line,Confused Char,Confused With,Count
ברתשית ברא תלהים,בראשית ברא אלהים,ת,ש,1
ברתשית ברא תלהים,בראשית ברא אלהים,ל,א,1

This helps quantify common OCR mistakes and improve preprocessing.

---

## 📝 Examples

### Processing a Single PAGE-XML File
```bash
# Process one PAGE-XML file with detailed output
python align-pagexml.py --pagexml samples/BL_Or_1443_285.xml --ref ref/schorch_verses.txt --out results/
```

### Processing Multiple PAGE-XML Files
```bash
# Process all PAGE-XML files in a directory with progress bar
python align-pagexml.py --pagexml samples/ --ref ref/schorch_verses.txt --out results/
```

### Text File Alignment
```bash
# Process plain text OCR file
python align.py --ocr ocr.txt --ref ref/schorch_verses.txt --out results/
```

### Using the Streamlit App
```bash
# Launch interactive web interface
streamlit run streamlit/app.py
```

## 🔧 Technical Details

### PAGE-XML Namespace Support
The `align-pagexml.py` script automatically detects and supports all major PAGE-XML namespace versions:
- 2009-03-16
- 2010-01-12, 2010-03-19
- 2013-07-15
- 2014-08-26
- 2016-07-15, 2017-07-15, 2018-07-15, 2019-07-15

### Text Correction Logic
- Only replaces OCR text when alignment score > 50%
- Preserves original XML structure and attributes
- Updates `<LastChange>` timestamp automatically
- Removes namespace prefixes for cleaner output

### Progress Tracking
- **Single file**: Detailed verbose output with statistics
- **Multiple files**: Rich progress bar with file names and timing
- **Error handling**: Graceful handling of malformed XML files

## 🚀 Future Enhancements

- Regex-based pre-cleaning toggle
- Error frequency dashboard in Streamlit
- Search bar for OCR lines
- Batch processing of multiple OCR files
- Support for additional XML formats (ALTO, hOCR)
- Confidence score visualization
- Automated quality assessment metrics

---

## 📜 License

Copyright 2025 johnlockejrr

MIT License — free to use, modify, and distribute.

