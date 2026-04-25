import anthropic
import json
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv
from pathlib import Path
import anthropic
from workflow import start_workflow
from memory_management import store_memory, clear_workflow_memory

client = anthropic.Anthropic()


@dataclass
class RecallResult:
    ground_truth_id: str
    ground_truth_text: str
    matched_task_id: str | None
    matched_task_description: str | None
    verdict: str
    reasoning: str
    score: float

@dataclass
class PrecisionResult:
    task_id:   str
    verdict:   str
    reasoning: str
    score:     float

def compare_single_task(ground_truth_task: dict, system_tasks: list[dict], client: anthropic.Anthropic) -> RecallResult:
    prompt = f"""
        You are evaluating a meeting task extraction system.

        Below is one action item identified by a human annotator (ground truth):
        "{ground_truth_task['text']}"

        Below are the tasks extracted by the system for the same meeting:
        {json.dumps([{"task_id": t["task_id"], "description": t["description"]} for t in system_tasks], indent=2)}

        Determine whether any system task matches the ground truth action item.

        Definitions:
        - "match": A system task covers the same action as the ground truth item, even if worded differently
        - "partial": A system task is related but misses part of the scope 
        - "miss": No system task corresponds to this ground truth item

        Respond with only raw JSON in this format:
        {{
        "verdict": "match | partial | miss",
        "matched_task_id": "T001 or null if miss",
        "matched_task_description": "the matching task description or null if miss",
        "reasoning": "one sentence explaining your decision"
        }}
    """

    response = client.messages.create(
        model="claude-sonnet-4-20250514",  # use a stronger model for evaluation
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    result = json.loads(text)

    score_map = {"match": 1.0, "partial": 0.5, "miss": 0.0}

    return RecallResult(
        ground_truth_id=ground_truth_task["id"],
        ground_truth_text=ground_truth_task["text"],
        matched_task_id=result.get("matched_task_id"),
        matched_task_description=result.get("matched_task_description"),
        verdict=result["verdict"],
        reasoning=result["reasoning"],
        score=score_map.get(result["verdict"], 0.0)
    )

def compare_single_system_task(system_task: dict, ground_truth_tasks: list[dict], client: anthropic.Anthropic) -> dict:
    prompt = f"""
        You are evaluating whether a system-extracted task corresponds to any real action item from a meeting.

        System task:
        "{system_task['description']}"

        Ground truth action items identified by a human annotator:
        {json.dumps([t["text"] for t in ground_truth_tasks], indent=2)}

        Does this system task correspond to a real action item, or is it an invention not supported by the ground truth?

        Definitions:
        - "match": This system task clearly corresponds to one of the ground truth items
        - "partial": This system task is loosely related to a ground truth item
        - "miss": This system task does not correspond to any ground truth item

        Respond with only raw JSON:
        {{
            "verdict": "match | partial | miss",
            "reasoning": "one sentence explaining your decision"
        }}
    """
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=128,
        messages=[{"role": "user", "content": prompt}]
    )
    text = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    result_json = json.loads(text)
    score = {"match": 1.0, "partial": 0.5, "miss": 0.0}.get(result_json["verdict"], 0.0)
    return PrecisionResult(
        task_id=system_task["task_id"],
        verdict=result_json["verdict"],
        reasoning=result_json["reasoning"],
        score=score
    )

def evaluate_meeting(meeting_id, ground_truth_tasks, system_tasks, client):
    print(f"\nEvaluating {meeting_id}...")
    print(f"  Ground truth tasks: {len(ground_truth_tasks)}")
    print(f"  System tasks:       {len(system_tasks)}")

    # Recall — ground truth perspective
    # print("Recall Results:")
    recall_results = []
    for gt_task in ground_truth_tasks:
        result = compare_single_task(gt_task, system_tasks, client)
        recall_results.append(result)
        # print(f"  [{result.verdict.upper()}] GT: \"{gt_task['text'][:60]}...\"")
        # print(f"         Reason: {result.reasoning}")

    recall_score = sum(r.score for r in recall_results) / len(recall_results) if recall_results else 0.0

    # Precision — system perspective
    # print("\nPrecision Results:")
    precision_results = []
    for sys_task in system_tasks:
        result = compare_single_system_task(sys_task, ground_truth_tasks, client)
        precision_results.append(result)
        # print(f"  [{result.verdict.upper()}] SYS: \"{sys_task['description'][:60]}...\"")
        # print(f"         Reason: {result.reasoning}")

    precision_score = sum(r.score for r in precision_results) / len(precision_results) if precision_results else 0.0

    f1 = (2 * precision_score * recall_score) / (precision_score + recall_score) if (precision_score + recall_score) > 0 else 0.0

    return {
        "meeting_id":          meeting_id,
        "ground_truth_count":  len(ground_truth_tasks),
        "system_count":        len(system_tasks),
        "quantity_delta":      len(system_tasks) - len(ground_truth_tasks),
        "recall":              round(recall_score, 3),
        "precision":           round(precision_score, 3),
        "f1":                  round(f1, 3),
        "recall_breakdown": [
            {
                "ground_truth_id":   r.ground_truth_id,
                "ground_truth_text": r.ground_truth_text,
                "verdict":           r.verdict,
                "matched_task_id":   r.matched_task_id,
                "reasoning":         r.reasoning,
                "score":             r.score
            }
            for r in recall_results
        ],
        "precision_breakdown": [
            {
                "task_id":   r.task_id,
                "verdict":   r.verdict,
                "reasoning": r.reasoning,
                "score":     r.score
            }
            for r in precision_results
        ]
    }

def run_evaluator(meeting_id, ground_truth, model_response, client: anthropic.Anthropic):
    result = evaluate_meeting(
        meeting_id=meeting_id,
        ground_truth_tasks=ground_truth,
        system_tasks=model_response,
        client=client
    )

    Path("eval_results").mkdir(exist_ok=True)
    file_location = "eval_results/" + meeting_id + ".json"
    with open(file_location, "w") as f:
        json.dump(result, f, indent=2)

    return result
    