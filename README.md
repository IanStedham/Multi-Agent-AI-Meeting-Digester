###
Instructions to run software
 
When opening the software, please run it using the command: python start.py
This will start the software and start the workflow.
A window will open on local host with dropboxes available for transcript and employee information. 
Next upload your transcript and employee information to the designated fields.
Once you have uploaded the files, please click the "Run Workflow" button.
###
Expectations

While the workflow is running, you will see the progress in the terminal as it will traversing through the five different agents.
Once the workflow is complete, you will see the results in the terminal.
Our agents will perform the following tasks for you:
- The transcript agent will create a summary of the meeting as well as identify relevant action items.
- The task agent will assign the identified action items to relevant employees with appropriate deadlines based on role and skills.
- The email and tool agent will create follow-up emails and add them to the designated outlook draft box. 
The results will be displayed in the terminal in a JSON format.
The JSON format will contain the following:
- The summary of the transcript
- The tasks that were assigned to the employees
- The emails that were sent to the employees
- The follow up emails that were sent to the employees
The designated outlook draft box will be updated with the draft emails created by our system.
###