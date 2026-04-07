import json
import re
import sys
from pathlib import Path

# --- Config -----------------------------------------------------------

ROLE_MAP = {
    "PM": "ProjectManager",
    "ME": "MarketingExpert",
    "UI": "UserInterface",
    "ID": "IndustrialDesigner",
    # ICSI roles (if you process those too)
    "Grad": "Grad",
    "Prof": "Professor",
    "Obs":  "Observer",
}

# Dialogue act labels to EXCLUDE entirely (backchannels, non-content)
# 'bc' = backchannel ("mm", "yeah", "uh-huh")
# 'be' = be-positive/negative (short affirmations)
EXCLUDE_LABELS = {"bc", "be"}

# Minimum word count for a turn to be kept
MIN_WORDS = 3

# ----------------------------------------------------------------------


def clean_text(text: str) -> str:
    """Remove XML-style tags, fillers, and clean up whitespace."""
    # Remove any <tag> including <vocalsound>, <disfmarker>, etc.
    text = re.sub(r"<[^>]+>", "", text)

    # Convert acronym tokens like D_V_D_ or V_C_R_ or T_V_ -> DVD, VCR, TV
    text = re.sub(r"\b([A-Z]_)+[A-Z]?_?\b", lambda m: m.group().replace("_", ""), text)

    # Remove cut-off words ending in hyphen e.g. "basi-" or "th-"
    text = re.sub(r"\b\w{1,4}-(?=\s|$)", "", text)

    # Remove filler words (standalone only, not inside real words)
    fillers = r"\b(um|uh|uhm|er|hmm|mm|hm)\b"
    text = re.sub(fillers, "", text, flags=re.IGNORECASE)

    # Remove stray single consonant letters from cut-offs (e.g. "W ", "S ", "M ")
    # Preserve "I" (first-person pronoun) and "a" / "A" (article)
    text = re.sub(r"\s+[b-hj-z]\s+", " ", text, flags=re.IGNORECASE)

    # Collapse multiple spaces
    text = re.sub(r" {2,}", " ", text)

    # Fix space before punctuation: " ." -> "."
    text = re.sub(r" ([.,?!])", r"\1", text)

    # Remove leading punctuation/commas left after stripping
    text = re.sub(r"^[,.\s]+", "", text)

    return text.strip()


def get_role_label(entry: dict) -> str:
    """Return display name: role if available, else speaker letter."""
    role_code = entry.get("attributes", {}).get("role", "")
    return ROLE_MAP.get(role_code, f"Speaker_{entry['speaker']}")


def process_file(input_path: Path, output_path: Path):
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. Filter out excluded dialogue act labels
    data = [e for e in data if e.get("label", "") not in EXCLUDE_LABELS]

    # 2. Sort chronologically by start time
    data.sort(key=lambda e: float(e["starttime"]))

    # 3. Clean text and filter short turns
    cleaned = []
    for entry in data:
        text = clean_text(entry["text"])
        words = text.split()
        if len(words) < MIN_WORDS:
            continue
        cleaned.append({
            "role":      get_role_label(entry),
            "speaker":   entry["speaker"],
            "starttime": float(entry["starttime"]),
            "text":      text,
        })

    # 4. Merge consecutive same-speaker turns
    merged = []
    for turn in cleaned:
        if merged and merged[-1]["role"] == turn["role"]:
            prev_text = merged[-1]["text"]
            # Ensure the previous turn ends with sentence-ending punctuation
            if prev_text and prev_text[-1] not in ".?!":
                prev_text = prev_text + "."
            merged[-1]["text"] = prev_text + " " + turn["text"]
        else:
            merged.append(dict(turn))

    # 5. Write to txt
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        meeting_id = input_path.stem  # e.g. "ES2002a"
        f.write(f"Meeting: {meeting_id}\n")
        f.write("=" * 60 + "\n\n")
        for turn in merged:
            # Capitalise first letter
            text = turn["text"]
            if text:
                text = text[0].upper() + text[1:]
            f.write(f"{turn['role']}: {text}\n\n")

    print(f"Done: {output_path}  ({len(merged)} turns)")


def main():
    # Usage:
    #   python ami_to_transcript.py input.json output.txt
    #   python ami_to_transcript.py input_dir/ output_dir/   (batch)

    if len(sys.argv) < 3:
        print("Usage: python ami_to_transcript.py <input.json|input_dir> <output.txt|output_dir>")
        sys.exit(1)

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])

    if src.is_dir():
        # Batch mode: process every .json in the directory
        json_files = list(src.glob("*.json"))
        if not json_files:
            print(f"No .json files found in {src}")
            sys.exit(1)
        dst.mkdir(parents=True, exist_ok=True)
        for jf in sorted(json_files):
            out_file = dst / (jf.stem + ".txt")
            process_file(jf, out_file)
    else:
        # Single file mode
        process_file(src, dst)


if __name__ == "__main__":
    main()