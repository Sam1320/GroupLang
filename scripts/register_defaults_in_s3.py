import boto3, json
import os

USER_DATABASE_PROMPT = """Also, I am collecting information about symptoms and other data from people who have bathed in the rivers and lakes of the city recently.,
I am trying to find out if there is a correlation between the symptoms and the water quality.,
If you have bathed in the rivers or lakes of the city recently and have felt or noticed something odd, please tell me about it!,
If you can include the place and also date and time of day you bathed, that would be great."""

DATA_EXTRACTION_PROMPT = """The following are the reports of a set of users which bathed on a specific river. Parse the report to look for the following information:,
1. Symptoms of potential disease. 2. Time. 3. Location., 
For each symptom found you compress it into a compact description and then create an internal list of all the unique symptoms found.,
You then create a csv file with: 1. One row per single report (each user can have multiple reports/rows), 2. Once column for the userid, 3. One column for time,  4. One column for location, and 5. One additional column per each unique symptom.,
So if in 6 reports you find 3 unique symptoms, you will have 6 report rows, 1 userid, 1 time column, 1 location column and 3 symptom columns.,
the format of the csv file should be: userid, time, location, symptom1, symptom2, symptom3, ...,
If no information is found for a specific column, you should write N/A.,
where each symptom column name is a short description of the symptom and the value is a binary value (1 or 0) indicating if the symptom was found in the report or not.,
You output exclusively the csv file.
This is the report: {report}.
"""
PAIRWISE_MATCH_PROMPT = """You are a helpful facilitator attempting to match those who are open to offering help, and those who are seeking it, 
in a context where both only wish for the joint "task" to take place if they are both expected to be happy with it after the fact. 
You try to reach a definite conclusion with the information you have without asking or needing more context or information from the users.
The information for each user is composed of a self description and a list of reviews from other users.
This is are all the offerings of person 1: {user_1}. This are all the offerings of person 2: {user_2}.
You think step by step if they are likely to have enjoyed the exchange.
After thinking step by step you output a conclusion of the format 'yes' or 'no'.
"""

GLOBAL_MATCH_PROMPT = """You are a helpful facilitator attempting to match compatible people,
in a context where both only wish for the joint 'task' to take place if they are both expected to be happy with it after the fact.
You try to reach a definite conclusion with the information you have without asking or needing more context or information from the users.
the information for each user is composed of a self description and a list of reviews from other users.
this are all the users:
{users}
You think step by step if they are likely to have enjoyed the exchange.
After thinking step by step you about the best possible matches you output a conclusion of the format:
[(n, m), (o, p), ... , (q, r)]
which correponds to the matched pairs and where the letters are placeholders for the index of the user on the list.
Note that some users might not be matched with anyone, in which case they are not included in the output.
Also note that some users might be matched with more than one other user, in which case they are included multiple times in the output.
You provide exclusively the list of matched pairs. No other output.
"""

SUMMARY_PROMPT = """You generate a very compressed description of persons based on the self reported information about themselves and also on the reviews of other people who have interacted with them, 
you generate the summary while still capturing the previous essence of the person. 
You compress step by step each information in a compact representation before trying to integrate it with the previous and so gradually create the summary. 
If a string is not contributing any new information to the previous state you don't bother integrating it.  
Here is the self reported information of the person to summarize:
{info}
and this are the reviews of others: 
{reviews}
You provide exclusively the summary for that person. No other output."""

QUERY_AGENT_PROMPT = """Answer the following questions as best you can. You have access only to the following tools:

{tools}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, has to be one of [{tool_names}]
Action Input: the input to the action (make sure it is not 'None')
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {input}
{agent_scratchpad}"""

QUERY_DOC_PROMPT = """Answer the following questions as best you can. You have access only to the following tools:

{tools}

Current document: {document}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, has to be one of [{tool_names}]
Action Input: the input to the action (make sure it is not 'None')
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {input}
{agent_scratchpad}"""

ROUTER_PROMPT = """ You are a helpful assistant who is in charge of mapping user messages to the correct callback function. 

This are the available callbacks:

{callbacks}

The cmd_message callback has a special function: when no other callback is adecuate, then this should be the one chosen.

Use the following format:

User Input: the user input
Action: the action to take, should be the name of one of [{callbacks}]
Action Input: Either "None" or the input to the action, which should be a json object with the arguments to the callback function.

Begin!
User Input: {input}
"""

MEMORY_PROMPT = """Use the following pieces of memories of information you have had which are similar to the new question, try to answer the question based on these memories. 
If there is no relevant info in your memories, just say that you don't know, don't try to make up an answer.

{context}

Question: {question}
Helpful Answer:"""

PLANNER_PROMPT = (
    "Let's first understand the problem and devise a plan to solve the problem."
    " Please output the plan starting with the header 'Plan:' "
    "and then followed by a numbered list of steps. "
    "Please make the plan the minimum number of steps required "
    "to accurately complete the task. If the task is a question, "
    "the final step should almost always be 'Given the above steps taken, "
    "please respond to the users original question'. "
    "At the end of your plan, say '<END_OF_PLAN>'"
)

TEMP_USER_PROMPT = """Hey.  You can send me .txt or a .pdf documents and then ask me questions about them using the /query command.
You can also add experts which I will ask for help when I don't know the answer to a question. You can either add other users as experts telling me their username and a description of their expertise or each expert can simply introduce themselves directly to me by describing their expertise e.g. "I am an expert in X".
If you want to see which commands you can use, just ask me :). 
"""

FEEDBACK_PROMPT = """You provide a final answer to a query given a 1. A draft answer and 2. Feedback on how to improve the draft answer.

Here is the original query:
{query}

Here is the draft answer:
{answer}

Here is the feedback:
{feedback}

Please provide the final answer. No other output.
"""

MAIN_MOD_ID = os.environ.get("MAIN_MOD_ID")
MAIN_MOD_USERNAME = os.environ.get("MAIN_MOD_USERNAME")

default_prompts = {
    'user': TEMP_USER_PROMPT,
    'query': QUERY_AGENT_PROMPT,
    'router': ROUTER_PROMPT,
    'user_database': USER_DATABASE_PROMPT,
    'match': PAIRWISE_MATCH_PROMPT,
    'global_match': GLOBAL_MATCH_PROMPT,
    'summary': SUMMARY_PROMPT,
    'query_doc': QUERY_DOC_PROMPT,
    'data_extraction':DATA_EXTRACTION_PROMPT,
    'memory': MEMORY_PROMPT,
    'planner': PLANNER_PROMPT,
    'feedback': FEEDBACK_PROMPT
}

config = {
    'prompts' : default_prompts,
    'moderators' : {'main_mod': {'username': MAIN_MOD_USERNAME, 'id': MAIN_MOD_ID}},
    'experts' : [],
    'tools' : [{'name': 'clarification', 'description': 'ask for clarification'}],
    'llm' : "gpt-3.5-turbo",
    'max_iterations' : 6,
    'debug' : 'yes',
    'feedback_mode' : 'yes'
}

def register_defaults_in_s3(BUCKET):
    s3 = boto3.resource('s3')
    s3.Object(BUCKET, 'default_config.json').put(Body=json.dumps(config))
    
if __name__ == "__main__":
    BUCKET = os.environ.get("S3_PRIVATE_BUCKET")
    register_defaults_in_s3(BUCKET)
    print("Done")