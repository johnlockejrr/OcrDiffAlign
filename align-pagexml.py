#!/usr/bin/env python3
"""
PAGE-XML OCR Alignment Tool

This script processes PAGE-XML files to align OCR text lines with reference text,
replacing incorrect OCR lines with their best matches from the reference.
"""

import re
import csv
import argparse
import uuid
import os
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from rapidfuzz import process, fuzz
import difflib
from collections import Counter
from lxml import etree
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.console import Console

# --- Normalization ---
def normalize_hebrew(text):
    """Normalize Hebrew text by keeping only Hebrew letters and spaces."""
    text = re.sub(r"[^\u0590-\u05FF\s]", "", text)  # keep only Hebrew letters + spaces
    return text.strip()

# --- Build candidate windows ---
def build_windows(reference_text, window_size):
    """Build sliding windows of words from reference text."""
    words = reference_text.split()
    return [" ".join(words[i:i+window_size]) for i in range(len(words)-window_size+1)]

# --- Character-level diff + confusion tracking ---
def diff_strings(ocr, ref, confusion_log):
    """Track character-level differences between OCR and reference text."""
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

# PAGE-XML namespace schemas
PAGE_NAMESPACES = {
    '2009-03-16': 'http://schema.primaresearch.org/PAGE/gts/pagecontent/2009-03-16',
    '2010-01-12': 'http://schema.primaresearch.org/PAGE/gts/pagecontent/2010-01-12', 
    '2010-03-19': 'http://schema.primaresearch.org/PAGE/gts/pagecontent/2010-03-19',
    '2013-07-15': 'http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15',
    '2014-08-26': 'http://schema.primaresearch.org/PAGE/gts/pagecontent/2014-08-26',
    '2016-07-15': 'http://schema.primaresearch.org/PAGE/gts/pagecontent/2016-07-15',
    '2017-07-15': 'http://schema.primaresearch.org/PAGE/gts/pagecontent/2017-07-15',
    '2018-07-15': 'http://schema.primaresearch.org/PAGE/gts/pagecontent/2018-07-15',
    '2019-07-15': 'http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15'
}

def detect_page_namespace(xml_path):
    """Detect the PAGE-XML namespace from the XML file."""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        # Extract namespace from the root tag
        if root.tag.startswith('{'):
            # Extract namespace from {namespace}tag format
            namespace = root.tag.split('}')[0][1:]
            return namespace
        
        # Check the xmlns attribute
        xmlns = root.get('{http://www.w3.org/2000/xmlns/}xmlns')
        if xmlns:
            for version, namespace in PAGE_NAMESPACES.items():
                if namespace in xmlns:
                    return namespace
                
        # Default to most recent namespace
        return PAGE_NAMESPACES['2019-07-15']
        
    except Exception as e:
        print(f"Warning: Could not detect namespace for {xml_path}: {e}")
        return PAGE_NAMESPACES['2019-07-15']

# --- PAGE-XML Processing ---
def extract_ocr_lines_from_pagexml(xml_path):
    """Extract OCR lines from PAGE-XML file."""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        # Detect namespace
        namespace = detect_page_namespace(xml_path)
        
        ocr_lines = []
        # Use the detected namespace to find TextLine elements
        textline_elements = root.findall(f'.//{{{namespace}}}TextLine')
        
        for textline in textline_elements:
            # Look for TextEquiv first, then Unicode inside it
            textequiv_elem = textline.find(f'{{{namespace}}}TextEquiv')
            
            unicode_elem = None
            if textequiv_elem is not None:
                # Try both with and without namespace for Unicode
                unicode_elem = textequiv_elem.find(f'{{{namespace}}}Unicode')
                if unicode_elem is None:
                    unicode_elem = textequiv_elem.find('Unicode')
            else:
                # Fallback: try to find Unicode directly with and without namespace
                unicode_elem = textline.find(f'{{{namespace}}}Unicode')
                if unicode_elem is None:
                    unicode_elem = textline.find('Unicode')
            
            if unicode_elem is not None and unicode_elem.text:
                ocr_lines.append(unicode_elem.text.strip())
        return ocr_lines, tree, root, namespace
    except ET.ParseError as e:
        print(f"Error parsing XML file {xml_path}: {e}")
        return [], None, None, None
    except Exception as e:
        print(f"Error processing {xml_path}: {e}")
        return [], None, None, None

def update_pagexml_with_aligned_text(tree, root, namespace, alignment_results, xml_path, verbose=True):
    """Update PAGE-XML with aligned text, replacing incorrect OCR lines."""
    try:
        # Use the detected namespace to find TextLine elements
        textline_elements = root.findall(f'.//{{{namespace}}}TextLine')
        
        alignment_idx = 0
        
        for textline in textline_elements:
            # Look for Unicode element using the same namespace
            unicode_elem = textline.find(f'{{{namespace}}}Unicode')
            
            if unicode_elem is not None and alignment_idx < len(alignment_results):
                original_text, matched_text, score, _, _ = alignment_results[alignment_idx]
                
                # Only update if the text is different and score is reasonable
                if original_text != matched_text and score > 50:
                    unicode_elem.text = matched_text
                    if verbose:
                        print(f"Updated line {alignment_idx + 1}: '{original_text}' -> '{matched_text}' (score: {score})")
                else:
                    if verbose:
                        print(f"Kept line {alignment_idx + 1}: '{original_text}' (score: {score})")
                
                alignment_idx += 1
        
        # Update LastChange timestamp
        lastchange_elem = root.find(f'{{{namespace}}}LastChange')
        if lastchange_elem is not None:
            lastchange_elem.text = datetime.now().isoformat()
        
        return tree
    except Exception as e:
        print(f"Error updating PAGE-XML: {e}")
        return tree

def write_xml_without_namespace_prefixes(tree, output_path):
    """Write XML without namespace prefixes using lxml."""
    # Convert ElementTree to lxml
    root = tree.getroot()
    
    # Create a new lxml element with the same tag name but without namespace
    new_root = etree.Element(root.tag.split('}')[-1] if '}' in root.tag else root.tag)
    
    # Copy all attributes
    for key, value in root.attrib.items():
        if '}' in key:
            # Remove namespace from attribute names
            new_key = key.split('}')[-1]
        else:
            new_key = key
        new_root.set(new_key, value)
    
    # Copy all children recursively
    def copy_element(src, dest):
        for child in src:
            if '}' in child.tag:
                new_tag = child.tag.split('}')[-1]
            else:
                new_tag = child.tag
            
            new_child = etree.SubElement(dest, new_tag)
            
            # Copy attributes
            for key, value in child.attrib.items():
                if '}' in key:
                    new_key = key.split('}')[-1]
                else:
                    new_key = key
                new_child.set(new_key, value)
            
            # Copy text content
            if child.text:
                new_child.text = child.text
            if child.tail:
                new_child.tail = child.tail
            
            # Recursively copy children
            copy_element(child, new_child)
    
    copy_element(root, new_root)
    
    # Write to file with proper formatting
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n')
        f.write(etree.tostring(new_root, encoding='unicode', pretty_print=True))

# --- Align OCR lines ---
def align_ocr_lines(ocr_lines, reference_text, outdir, threshold=70, verbose=True):
    """Align OCR lines with reference text using fuzzy matching."""
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

    if verbose:
        print("\n📊 Summary Report")
        print(f"- Lines processed: {len(results)}")
        print(f"- Average score: {avg_score:.2f}")
        print(f"- Low-confidence (<{threshold}): {low_conf} lines ({low_conf_pct:.1f}%)")

        print("\n🔝 Top 5 Confusions:")
        for (c, cw), count in confusion_counts.most_common(5):
            print(f"  {c or '∅'} → {cw or '∅'} : {count} times")

    return results, csv_path, txt_path, confusion_path

def process_pagexml_file(xml_path, reference_text, output_dir, threshold=70, verbose=True):
    """Process a single PAGE-XML file."""
    if verbose:
        print(f"\n🔄 Processing: {xml_path}")
    
    # Extract OCR lines
    ocr_lines, tree, root, namespace = extract_ocr_lines_from_pagexml(xml_path)
    
    if not ocr_lines:
        if verbose:
            print(f"⚠️  No OCR lines found in {xml_path}")
        return None
    
    if verbose:
        print(f"📝 Found {len(ocr_lines)} OCR lines")
        print(f"🏷️  Detected namespace: {namespace}")
    
    # Align OCR lines
    alignment_results, csv_path, txt_path, confusion_path = align_ocr_lines(
        ocr_lines, reference_text, output_dir, threshold, verbose
    )
    
    # Update PAGE-XML with aligned text
    if tree is not None and namespace is not None:
        updated_tree = update_pagexml_with_aligned_text(tree, root, namespace, alignment_results, xml_path, verbose)
        
        # Save updated PAGE-XML
        xml_filename = Path(xml_path).name
        aligned_xml_dir = os.path.join(output_dir, "xml")
        os.makedirs(aligned_xml_dir, exist_ok=True)
        aligned_xml_path = os.path.join(aligned_xml_dir, xml_filename)
        
        # Write XML without namespace prefixes
        write_xml_without_namespace_prefixes(updated_tree, aligned_xml_path)
        if verbose:
            print(f"💾 Saved aligned PAGE-XML: {aligned_xml_path}")
        
        return {
            'xml_path': aligned_xml_path,
            'csv_path': csv_path,
            'txt_path': txt_path,
            'confusion_path': confusion_path,
            'alignment_results': alignment_results
        }
    
    return None

def process_pagexml_directory(input_path, reference_text, output_dir, threshold=70):
    """Process a directory of PAGE-XML files."""
    input_path = Path(input_path)
    console = Console()
    
    if input_path.is_file():
        # Single file - use verbose output
        return [process_pagexml_file(str(input_path), reference_text, output_dir, threshold, verbose=True)]
    
    xml_files = list(input_path.glob("*.xml"))
    if not xml_files:
        print(f"⚠️  No XML files found in {input_path}")
        return []
    
    # Multiple files - use progress bar
    results = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Processing PAGE-XML files...", total=len(xml_files))
        
        for xml_file in xml_files:
            progress.update(task, description=f"Processing {xml_file.name}")
            result = process_pagexml_file(str(xml_file), reference_text, output_dir, threshold, verbose=False)
            if result:
                results.append(result)
            progress.advance(task)
    
    return results

# --- CLI entrypoint ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Align OCR text in PAGE-XML files against Hebrew reference")
    parser.add_argument("--pagexml", required=True, help="Path to PAGE-XML file or directory containing PAGE-XML files")
    parser.add_argument("--ref", required=True, help="Path to reference text file")
    parser.add_argument("--out", default="aligned", help="Output directory (default: aligned/)")
    parser.add_argument("--threshold", type=int, default=70, help="Low-score threshold (default: 70)")
    args = parser.parse_args()

    # Read reference text
    with open(args.ref, encoding="utf-8") as f:
        reference_text = f.read()

    # Check if input is single file or directory
    input_path = Path(args.pagexml)
    is_single_file = input_path.is_file()
    
    if is_single_file:
        print("🚀 Starting PAGE-XML OCR Alignment")
        print(f"📁 Input: {args.pagexml}")
        print(f"📖 Reference: {args.ref}")
        print(f"📤 Output: {args.out}")
    
    # Process PAGE-XML file(s)
    results = process_pagexml_directory(args.pagexml, reference_text, args.out, args.threshold)

    if results:
        if is_single_file:
            print(f"\n✅ Alignment complete! Processed {len(results)} file(s)")
            for i, result in enumerate(results, 1):
                if result is not None:
                    print(f"\n📄 File {i}:")
                    print(f"  - Aligned PAGE-XML: {result['xml_path']}")
                    print(f"  - Alignment CSV: {result['csv_path']}")
                    print(f"  - Matched text TXT: {result['txt_path']}")
                    print(f"  - Confusion log CSV: {result['confusion_path']}")
        else:
            # For multiple files, show summary
            successful_files = len([r for r in results if r is not None])
            print(f"\n✅ Alignment complete! Processed {successful_files}/{len(results)} files successfully")
            print(f"📤 Aligned files saved to: {args.out}/xml/")
    else:
        print("❌ No files were processed successfully")
