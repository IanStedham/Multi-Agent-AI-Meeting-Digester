###
Instructions to run software
 
When opening the software, please run it using the command: python start.py
This will start the software and start the workflow.
A window will open on local host with dropboxes available for transcript and employee information.
Next upload your transcript and employee information to the designated fields.
Once you have uploaded the files, please click the "Run Workflow" button.
###
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
###
Project Description:

Front-end:
- Website.html is the frontend of the software. It is a simple HTML file that allows for the user to upload their transcript and employee information.
- api.py is the backend of the software. It is a FastAPI application that allows for the user to upload their transcript and employee information.
- start.py is the script used to start the software and start the workflow.

Back-end:
- agents_layer contains all the context engineering files for our 5 agents
- data_lay contains all the data needed for testing the model
  - employee_json contains the relevant sythetic emplyoee information for testing
  - extractive_es_txt contains the ES subset of the extractive dataset from the AMI Meeting Corpus
  - abstractive_action_items_json contains the ES subset of the abstractive dataset from the AMI Meeting Corpus, this was filtered to only contain items identified as "actions"
- scripts
  - main.py is the main script used to call the workflow and structure the data for the MCP server
  - memory_management.py is the script used to control all interactions done within the MCP server
  - workflow.py is the script used to orchestrate our agents and call them with their respective context engineering and prompting
  - evaluation.py is the script used to evaluate the system using LLM as a judge
###
###
Code Contributions:

Code was written by us with assistance from Claude and Cursor.
Code fully AI generated:
- compare_single_task, compare_single_system_task functions in src/scripts/evaluation.py were made by Claude to help with LLM Evaluation
- force_kill_ruflo function in src/scripts/memory_management.py was made by Claude to help with Windows vs Linus configuration
- save_cache(), load_cache(), get_graph_token(), and create_outlook_draft() were created by Claude to interact with Outlook via the Microsoft Graph API
- start.py and api.py were made with the help of Cursor
- Website.html was made by Claude
- .claude folder was structured and formatted by Claude
###