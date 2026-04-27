from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import tempfile
import anthropic
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src" / "scripts"))

import main

app = FastAPI(title="Meeting Digester API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "Meeting Digester API is running"}


@app.post("/run")
async def run_workflow(
    transcript: UploadFile = File(...),
    employees: UploadFile = File(...)
):
    # api_key = os.getenv("ANTHROPIC_API_KEY")
    # if not api_key:
    #     raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    # Read uploaded files
    transcript_text = (await transcript.read()).decode("utf-8")
    employees_text = (await employees.read()).decode("utf-8")

    # Save to temp files so start_workflow can use them
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as t:
        t.write(transcript_text)
        transcript_path = Path(t.name)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as e:
        e.write(employees_text)
        employee_path = Path(e.name)

    try:
        # Clear old memory and load new inputs
        summary, tasks, assignments, emails = main.main(
            transcript_path=transcript_path, 
            employee_path=employee_path
        )

        return {
            "status": "complete",
            "tasks": tasks,
            "summary": summary,
            "assignments": assignments,
            "emails": emails
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        transcript_path.unlink(missing_ok=True)
        employee_path.unlink(missing_ok=True)
