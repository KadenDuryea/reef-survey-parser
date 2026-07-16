"""
REEF Survey Log Parser
-----------------------
Converts freeform dive/snorkel survey notes into structured data matching
REEF's Volunteer Fish Survey Project (VFSP) format: species name, abundance
category (Single / Few / Many / Abundant), and a confidence flag for any
sighting the model wasn't sure how to categorize.

Why this exists: REEF volunteers often jot loose notes underwater or right
after a dive ("saw a few blue tangs, one nurse shark, tons of sergeant
majors") rather than filling out the structured survey form in the moment.
This script uses the Claude API to turn those notes into a clean CSV ready
for review/submission, cutting out manual re-typing.

Usage:
    export ANTHROPIC_API_KEY=your_key_here
    python reef_survey_parser.py --input sample_notes.txt --output survey_output.csv

    Or dry-run without an API key (uses a canned example response) to see
    the expected output shape:
    python reef_survey_parser.py --input sample_notes.txt --dry-run
"""

import argparse
import csv
import json
import os
import sys
import urllib.request

REEF_ABUNDANCE_CATEGORIES = ["Single", "Few", "Many", "Abundant"]

# A sample of common species from REEF's Tropical Western Atlantic survey
# slate, used to sanity-check extracted names against real REEF ID list
# naming conventions. Not exhaustive -- a full build would pull REEF's
# complete species list from their site/API.
REEF_KNOWN_SPECIES = {
    "blue tang", "sergeant major", "nurse shark", "yellowtail damselfish",
    "spotted eagle ray", "french angelfish", "queen angelfish",
    "stoplight parrotfish", "yellowtail snapper", "southern stingray",
    "green moray", "barracuda", "foureye butterflyfish", "trumpetfish",
    "bluehead wrasse", "spotted moray", "porkfish", "gray angelfish",
}

SYSTEM_PROMPT = f"""You are helping a volunteer diver convert freeform notes \
from a fish survey into REEF Volunteer Fish Survey Project (VFSP) format.

For each species mentioned, extract:
- common_name: the fish/marine species common name, standardized (capitalize properly)
- abundance_category: one of {REEF_ABUNDANCE_CATEGORIES} based on REEF's scale
  (Single = 1, Few = 2-10, Many = 11-100, Abundant = 100+)
- confidence: "high" if the species and abundance are clearly stated,
  "low" if you had to infer or guess

Respond with ONLY a JSON array of objects with keys:
common_name, abundance_category, confidence. No other text.
"""

def call_claude(notes_text, api_key, model="claude-sonnet-4-5"):
    url = "https://api.anthropic.com/v1/messages"
    payload = {
        "model": model,
        "max_tokens": 1000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": notes_text}],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    raw_text = "\n".join(text_blocks).strip()

    # Strip markdown fences if the model added them despite instructions
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        raw_text = raw_text.replace("json\n", "", 1)

    return json.loads(raw_text)


def dry_run_example():
    """Canned output so the pipeline/CSV formatting can be demoed without an API key."""
    return [
        {"common_name": "Blue Tang", "abundance_category": "Few", "confidence": "high"},
        {"common_name": "Nurse Shark", "abundance_category": "Single", "confidence": "high"},
        {"common_name": "Sergeant Major", "abundance_category": "Abundant", "confidence": "high"},
        {"common_name": "Yellowtail Damselfish", "abundance_category": "Many", "confidence": "low"},
    ]


def check_against_reef_list(records):
    """Flag species names that don't match REEF's known naming conventions,
    so a volunteer can catch typos or non-standard common names before submitting."""
    for r in records:
        r["in_reef_id_list"] = "yes" if r["common_name"].lower() in REEF_KNOWN_SPECIES else "unverified"
    return records


def write_csv(records, output_path):
    fieldnames = ["common_name", "abundance_category", "confidence", "in_reef_id_list"]
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow(r)


def main():
    parser = argparse.ArgumentParser(description="Parse freeform dive survey notes into REEF VFSP-style CSV.")
    parser.add_argument("--input", required=True, help="Path to a text file with freeform survey notes")
    parser.add_argument("--output", default="survey_output.csv", help="Path to write the structured CSV")
    parser.add_argument("--dry-run", action="store_true", help="Skip the API call and use a canned example")
    args = parser.parse_args()

    with open(args.input) as f:
        notes_text = f.read().strip()

    if args.dry_run:
        print("[dry-run] Skipping API call, using example output.")
        records = dry_run_example()
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("No ANTHROPIC_API_KEY set. Run with --dry-run to preview output, "
                  "or set the key and re-run.", file=sys.stderr)
            sys.exit(1)
        records = call_claude(notes_text, api_key)

    records = check_against_reef_list(records)
    write_csv(records, args.output)

    low_confidence = [r for r in records if r.get("confidence") == "low"]
    print(f"Wrote {len(records)} species entries to {args.output}")
    if low_confidence:
        print(f"⚠ {len(low_confidence)} entries flagged low-confidence — worth a manual double-check:")
        for r in low_confidence:
            print(f"   - {r['common_name']} ({r['abundance_category']})")


if __name__ == "__main__":
    main()
