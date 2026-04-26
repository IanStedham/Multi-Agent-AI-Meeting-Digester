import argparse
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import anthropic
from workflow import start_workflow, run_transcript_only
from memory_management import store_memory, clear_workflow_memory
from evaluation import run_evaluator
import json

NAMESPACE = "meeting-digester"

def validate_environment() -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("\nANTHROPIC_API_KEY not found\n")
        print("Make sure your .env file contains your API key\n")
        sys.exit(1)
    return api_key
  
def load_inputs_to_memory(transcript_path: Path, employee_path: Path):
    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = f.read().strip()

    with open(employee_path, "r", encoding="utf-8") as f:
        employees = f.read().strip()

    if not store_memory("meeting:transcript", transcript, NAMESPACE):
        print("Failed to store transcript in mcp server")
        sys.exit(1)
    if not store_memory("meeting:employees", employees, NAMESPACE):
        print("Failed to store employee data in mcp server")
        sys.exit(1)

def main(
    transcript_path: str = "src/data_layer/extractive_txt/ES2002a.txt",
    employee_path: str = "src/data_layer/employee_json/employee_es.json",
    evaluate: bool = False
):
    load_dotenv()
    api_key = validate_environment()
    client = anthropic.Anthropic(api_key=api_key)

    if not evaluate: 
        if not Path(transcript_path).exists():
            raise FileNotFoundError(f"Transcript file not found: {transcript_path}")
        if not Path(employee_path).exists():
            raise FileNotFoundError(f"Employee file not found: {employee_path}")

        clear_workflow_memory()
        load_inputs_to_memory(transcript_path, employee_path)

        summary, tasks, assignments, emails = start_workflow(client=client)

        return summary, tasks, assignments, emails
    else:
        scripts_dir      = Path(__file__).parent
        data_dir         = scripts_dir.parent / "data_layer"

        transcript_dir   = data_dir / "extractive_es_txt"
        employee_path    = data_dir / "employee_json" / "employee_es.json"
        ground_truth_dir = data_dir / "abstractive_es_json"

        # Validate all directories exist before starting
        for path in [transcript_dir, employee_path, ground_truth_dir]:
            if not path.exists():
                raise FileNotFoundError(f"Required path not found: {path}")

        transcript_files = sorted(transcript_dir.glob("*.txt"))

        if not transcript_files:
            raise FileNotFoundError(f"No transcript files found in {transcript_dir}")
        
        print(f"Found {len(transcript_files)} meetings to evaluate\n")

        corpus_results  = []
        failed_meetings = []

        for transcript_file in transcript_files:
            meeting_id = transcript_file.stem
            ground_truth_file = ground_truth_dir / f"{meeting_id}.json"

            if not ground_truth_file.exists():
                print(f"[SKIP] {meeting_id} — no ground truth file at {ground_truth_file}")
                continue

            try:
                with open(ground_truth_file, "r") as f:
                    raw_ground_truth = json.load(f)

                ground_truth = [
                    item for item in raw_ground_truth
                    if item.get("type") == "actions" 
                    and item.get("text", "").strip() not in ("*NA*", "NA", "")
                ]

                if not ground_truth:
                    print(f"[SKIP] {meeting_id} — no action items in ground truth (NA meeting)")
                    # But still run the system and check it returns empty tasks
                    # to measure false positive rate separately
                    continue

                clear_workflow_memory()
                load_inputs_to_memory(str(transcript_file), str(employee_path))
                tasks = run_transcript_only(client=client)

                if isinstance(tasks, str):
                    system_tasks = json.loads(tasks)
                elif isinstance(tasks, list):
                    system_tasks = tasks
                else:raise ValueError(f"Unexpected tasks type: {type(tasks)}")

                result = run_evaluator(
                    meeting_id=meeting_id,
                    ground_truth=ground_truth,
                    model_response=system_tasks,
                    client=client 
                )

                corpus_results.append(result)
                print(f"  Recall: {result['recall']}  Precision: {result['precision']}  F1: {result['f1']}")

            except Exception as e:
                print(f"[ERROR] {meeting_id} failed: {e}")
                failed_meetings.append({"meeting_id": meeting_id, "error": str(e)})
                continue

        if not corpus_results:
            print("No meetings were successfully evaluated.")
            return None

        avg_recall              = sum(r["recall"]              for r in corpus_results) / len(corpus_results)
        avg_precision           = sum(r["precision"]           for r in corpus_results) / len(corpus_results)
        avg_f1                  = sum(r["f1"]                  for r in corpus_results) / len(corpus_results)
        avg_delta               = sum(r["quantity_delta"]      for r in corpus_results) / len(corpus_results)
        avg_recall_accuracy     = sum(r["recall_accuracy"]     for r in corpus_results) / len(corpus_results)
        avg_precision_accuracy  = sum(r["precision_accuracy"]  for r in corpus_results) / len(corpus_results)
        avg_overall_accuracy    = sum(r["overall_accuracy"]    for r in corpus_results) / len(corpus_results)

        print(f"\n{'='*60}")
        print("CORPUS EVALUATION COMPLETE")
        print(f"{'='*60}")
        print(f"Meetings evaluated:       {len(corpus_results)}")
        print(f"Meetings failed:          {len(failed_meetings)}")
        print(f"{'─'*40}")
        print(f"Avg Recall:               {avg_recall:.3f}")
        print(f"Avg Precision:            {avg_precision:.3f}")
        print(f"Avg F1:                   {avg_f1:.3f}")
        print(f"{'─'*40}")
        print(f"Avg Recall Accuracy:      {avg_recall_accuracy:.3f}")
        print(f"Avg Precision Accuracy:   {avg_precision_accuracy:.3f}")
        print(f"Avg Overall Accuracy:     {avg_overall_accuracy:.3f}")
        print(f"{'─'*40}")
        print(f"Avg Quantity Delta:       {avg_delta:+.2f}")
        print(f"\nFull report saved to eval_results/corpus_report.json")

        corpus_report = {
            "total_meetings":          len(corpus_results),
            "failed_meetings":         failed_meetings,
            "avg_recall":              round(avg_recall,             3),
            "avg_precision":           round(avg_precision,          3),
            "avg_f1":                  round(avg_f1,                 3),
            "avg_quantity_delta":      round(avg_delta,              2),
            "avg_recall_accuracy":     round(avg_recall_accuracy,    3),
            "avg_precision_accuracy":  round(avg_precision_accuracy, 3),
            "avg_overall_accuracy":    round(avg_overall_accuracy,   3),
            "per_meeting_results":     corpus_results
        }

        Path("eval_results").mkdir(exist_ok=True)
        with open("eval_results/corpus_report.json", "w") as f:
            json.dump(corpus_report, f, indent=2)

        print(f"\n{'='*60}")
        print("CORPUS EVALUATION COMPLETE")
        print(f"{'='*60}")
        print(f"Meetings evaluated:   {len(corpus_results)}")
        print(f"Meetings failed:      {len(failed_meetings)}")
        print(f"Avg Recall:           {avg_recall:.3f}")
        print(f"Avg Precision:        {avg_precision:.3f}")
        print(f"Avg F1:               {avg_f1:.3f}")
        print(f"Avg Quantity Delta:   {avg_delta:+.2f}")
        print(f"\nFull report saved to eval_results/corpus_report.json")

        return corpus_report

if __name__ == "__main__":
    evaluate = "--evaluate" in sys.argv
    main(evaluate=evaluate)
