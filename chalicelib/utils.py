import csv
import os
from functools import wraps
import json
import pickle
import uuid
import boto3
from telegram import ParseMode, Bot, ChatAction
from langchain import PromptTemplate
from langchain.chains import LLMChain
import traceback
from langchain.chat_models import ChatOpenAI
from chalice import Chalice
from io import StringIO
from langchain.agents import Tool, LLMSingleActionAgent
from langchain import LLMMathChain
from langchain.agents.structured_chat.base import StructuredChatAgent
from langchain.utilities import GoogleSerperAPIWrapper
import pinecone 
from langchain.embeddings.openai import OpenAIEmbeddings
from chalicelib.custom_objects import CustomOutputParser, CustomPromptTemplate
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate
from langchain.schema import SystemMessage
from langchain.chains import LLMChain
from langchain.experimental.plan_and_execute.planners.base import LLMPlanner
from chalicelib.custom_objects import PlanningOutputParser
from langchain.vectorstores import Pinecone
from langchain.chains import RetrievalQA
from langchain.llms import OpenAI

from chalicelib.credentials import APP_NAME, BUCKET, PRIVATE_BUCKET, PINECONE_API_KEY, PINECONE_ENV, MESSAGE_HANDLER_LAMBDA

app = Chalice(app_name=APP_NAME)
app.debug = True
s3 = boto3.client("s3")


def send_typing_action(func):
    """Sends typing action while processing func command."""

    @wraps(func)
    def command_func(update, context, *args, **kwargs):
        context.bot.send_chat_action(
            chat_id=update.effective_message.chat_id, action=ChatAction.TYPING
        )
        return func(update, context, *args, **kwargs)

    return command_func


def create_database(bot_username):
    users_dict = get_users(bot_username)
    users_info = [(userid, list(user_dict["strings"].values())) for userid, user_dict in users_dict.items()]
    # get data extraction prompt
    data_extraction_prompt = get_data_extraction_prompt(bot_username)

    # extract input variables from data_extraction prompt
    input_variables_list = extract_variables_from_template(data_extraction_prompt)
    input_variables_values = [users_info]
    input_variables_dict = dict(zip(input_variables_list, input_variables_values))

    # extract data
    csv_string = extract_data(data_extraction_prompt, input_variables_dict)

    # write csv string to file
    csv_reader = csv.reader(StringIO(csv_string))
    csv_rows = [row for row in csv_reader]
    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerows(csv_rows)
    csv_buffer.seek(0)

    return csv_buffer


def extract_variables_from_template(string):
    variables = []
    while True:
        start = string.find('{')
        end = string.find('}')
        if start == -1 or end == -1:
            break
        variables.append(string[start+1:end])
        string = string[end+1:]
    return variables

# Returns list with all moderators of the community
def get_moderators(bot_username):
    moderators_key =f"{bot_username}/moderators.json"
    try: 
        response = s3.get_object(Bucket=BUCKET, Key=moderators_key)
        moderators = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        raise IndexError(f"No {moderators_key} in {BUCKET}.")
    return moderators['moderators']

def store_match(bot_username, user1, user2):
    # get match dictionary
    match_dict = get_match_dict(bot_username)
    # add each user to the list of matched users of the other
    if user1 not in match_dict:
        match_dict[user1] = [user2]
    if user2 not in match_dict:
        match_dict[user2] = [user1]
    if user2 not in match_dict[user1]:
        match_dict[user1].append(user2)
    if user1 not in match_dict[user2]:
        match_dict[user2].append(user1)
    # store match dictionary in s3
    store_match_dict(bot_username, match_dict)
    
def get_match_dict(bot_username):
    # match dict key
    match_dict_key = f"{bot_username}/match_dict.json"
    try:
        match_dict = s3.get_object(Bucket=BUCKET, Key=match_dict_key)
        match_dict = json.loads(match_dict["Body"].read().decode("utf-8"))
    except:
        match_dict = {}
    return match_dict

def check_match(bot_username, user1, user2):
    # convert ids to strings
    user1 = str(user1)
    user2 = str(user2)

    # get match dictionary
    match_dict = get_match_dict(bot_username)
    # check if user1 and user2 were matched
    if user1 in match_dict:
        if user2 in match_dict[user1]:
            return True
    return False

def store_match_dict(bot_username, match_dict):
    # match dict key
    match_dict_key = f"{bot_username}/match_dict.json"
    s3.put_object(Bucket=BUCKET, Key=match_dict_key, Body=json.dumps(match_dict))

def update_user(new_info, bot_username, user_id, username):
    object_key = f"{bot_username}/{user_id}.json"

    # Retrieve the existing content (if any)
    existing_content = get_user(bot_username=bot_username, user_id=user_id)

    # Add metadata (after new content is added the previous summary is no longer up to date)
    metadata = {
        'user_id': str(user_id),
        'user_name': username,
        'updated': 'false'
    }

    # Determine the next index for the new info
    next_index = len(existing_content["strings"]) + 1

    # Add the new sentence to the existing content
    existing_content["strings"][next_index] = new_info

    # Store the updated content in the object
    s3.put_object(Bucket=BUCKET, Key=object_key, Body=json.dumps(existing_content), Metadata=metadata)

    # change the metadata of the database to reflect that it is not updated anymore
    database_metadata = {
        'updated': 'false'
    }
    database_key = f"{bot_username}/database.csv"
    s3.copy_object(Bucket=BUCKET, Key=database_key, CopySource=f"{BUCKET}/{database_key}", MetadataDirective="REPLACE", Metadata=database_metadata)

    # # store the username and user_id in the name_to_id dictionary
    # name_to_id_dict = get_name_to_id_dict(bot_username)
    # if username not in name_to_id_dict:
    #     name_to_id_dict[username] = user_id
    #     store_name_to_id_dict(bot_username, name_to_id_dict)

def register_user(bot_username, user_id, username):
    object_key = f"{bot_username}/{user_id}.json"

    # Retrieve the existing content (if any)
    existing_content = get_user(bot_username=bot_username, user_id=user_id)

    # Add metadata (after new content is added the previous summary is no longer up to date)
    metadata = {
        'user_id': str(user_id),
        'user_name': username,
        'updated': 'false'
    }

    # Store the updated content in the object
    s3.put_object(Bucket=BUCKET, Key=object_key, Body=json.dumps(existing_content), Metadata=metadata)

    # store the username and user_id in the name_to_id dictionary
    name_to_id_dict = get_name_to_id_dict(bot_username)
    if username not in name_to_id_dict:
        name_to_id_dict[username] = user_id
        store_name_to_id_dict(bot_username, name_to_id_dict)

    
def get_name_to_id_dict(bot_username):
    name_to_id_key = f"{bot_username}/name_to_id.json"
    try:
        name_to_id_dict = s3.get_object(Bucket=BUCKET, Key=name_to_id_key)
        name_to_id_dict = json.loads(name_to_id_dict["Body"].read().decode("utf-8"))
    except:
        name_to_id_dict = {}
    return name_to_id_dict

def get_community_members(bot_username):
    name_to_id_dict = get_name_to_id_dict(bot_username)
    return name_to_id_dict.keys()

def store_name_to_id_dict(bot_username, name_to_id_dict):
    name_to_id_key = f"{bot_username}/name_to_id.json"
    s3.put_object(Bucket=BUCKET, Key=name_to_id_key, Body=json.dumps(name_to_id_dict))

# stores review string in user state
def store_review(bot_username, reviewer_userid, reviewed_userid, review_text):
    object_key = f"{bot_username}/{reviewed_userid}.json"

    # Retrieve the existing content (if any)
    user_obj = get_user(bot_username=bot_username, user_id=reviewed_userid, get_object=True)

    # get metadata and update the updated field
    metadata = user_obj["Metadata"]
    metadata["updated"] = "false"

    # Add the new sentence to the existing content
    existing_content = json.loads(user_obj["Body"].read().decode("utf-8"))
    if reviewer_userid not in existing_content["reviews"]:
        existing_content["reviews"][reviewer_userid] = [review_text]
    else:
        existing_content["reviews"][reviewer_userid].append(review_text)

    # Store the updated content in the object
    s3.put_object(Bucket=BUCKET, Key=object_key, Body=json.dumps(existing_content), Metadata=metadata)

def set_bot_webhook(lambda_url, bot):
    webhook_url = f"{lambda_url}?community_id={bot.token}"
    success = bot.setWebhook(url=webhook_url)
    if success:
        app.log.info("Webhook set successfully.")
    else:
        app.log.info("Failed to set webhook.")
        return -1
    return 0

# get default methods from s3 PRIVATE_BUCKET
def get_default_methods():
    default_methods_key = "default_methods.json"
    try:
        response = s3.get_object(Bucket=PRIVATE_BUCKET, Key=default_methods_key)
        default_methods = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        raise IndexError(f"No {default_methods_key} in {PRIVATE_BUCKET}.")
    return default_methods


# get default experts from s3 PRIVATE_BUCKET
def get_default_experts():
    default_experts_key = "default_experts.json"
    try:
        response = s3.get_object(Bucket=PRIVATE_BUCKET, Key=default_experts_key)
        default_experts = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        raise IndexError(f"No {default_experts_key} in {PRIVATE_BUCKET}.")
    return default_experts

def get_default_tools():
    default_tools_key = "default_tools.json"
    try:
        response = s3.get_object(Bucket=PRIVATE_BUCKET, Key=default_tools_key)
        default_tools = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        raise IndexError(f"No {default_tools_key} in {PRIVATE_BUCKET}.")
    return default_tools

def get_default_config():
    default_config_key = "default_config.json"
    try:
        response = s3.get_object(Bucket=PRIVATE_BUCKET, Key=default_config_key)
        default_config = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        raise IndexError(f"No {default_config_key} in {PRIVATE_BUCKET}.")
    return default_config

# get default database from s3 PRIVATE_BUCKET
def get_default_database():
    default_database_key = "default_database.csv"
    try:
        response = s3.get_object(Bucket=PRIVATE_BUCKET, Key=default_database_key)
        csv_content = response['Body'].read().decode('utf-8')
    except s3.exceptions.NoSuchKey:
        raise IndexError(f"No {default_database_key} in {PRIVATE_BUCKET}.")
    return csv_content

def get_database_object(bot_username):
    database_key = f"{bot_username}/database.csv"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=database_key)
    except s3.exceptions.NoSuchKey:
        raise IndexError(f"No {database_key} in {BUCKET}.")
    return response

def read_csv_string(csv_string):
    csv_reader = csv.reader(csv_string.splitlines(), delimiter=',')
    csv_list = list(csv_reader)
    return csv_list

def format_pretty_table(data):
    col_widths = [max(len(str(cell)) for cell in col) for col in zip(*data)]
    table = ""
    for row in data:
        table += "| " + " | ".join("{:<{}}".format(cell, width) for cell, width in zip(row, col_widths)) + " |\n"
    return table

# get default prompts from s3 PRIVATE_BUCKET
def get_default_prompts():
    default_prompts_key = "default_prompts.json"
    try:
        response = s3.get_object(Bucket=PRIVATE_BUCKET, Key=default_prompts_key)
        default_prompts = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        raise IndexError(f"No {default_prompts_key} in {PRIVATE_BUCKET}.")
    return default_prompts

# get default memory prompt
def get_default_memory_prompt():
    default_prompts = get_default_prompts()
    return default_prompts["memory"]
        
def add_bot_token_to_db(bot_token, bot_username):
    bots_db_key = "bots_id_to_token.json"
    try:
        response = s3.get_object(Bucket=PRIVATE_BUCKET, Key=bots_db_key)
        bots_db = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        raise IndexError(f"No {bots_db_key} in {PRIVATE_BUCKET}.")

    bots_db[bot_username] = bot_token
    s3.put_object(Bucket=PRIVATE_BUCKET, Key=bots_db_key, Body=json.dumps(bots_db))

def get_lambda_url(lambda_name):
    lambdas_db_key = "lambdas.json"
    try:
        response = s3.get_object(Bucket=PRIVATE_BUCKET, Key=lambdas_db_key)
        lambdas_db = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        raise IndexError(f"No {lambdas_db_key} in {PRIVATE_BUCKET}.")
    try:
        url = lambdas_db[lambda_name]
    except KeyError:
        print(f"Lambda {lambda_name} not found in {lambdas_db_key}.")
        raise KeyError(f"Lambda {lambda_name} not found in {lambdas_db_key}.")
    return url

def register_bot(bot_token, moderator, main_chat_id):
    bot = Bot(token=bot_token)
    bot_username = bot.username

    lamdba_name = f'{APP_NAME}-dev-{MESSAGE_HANDLER_LAMBDA}'
    print(lamdba_name)
    lambda_url = get_lambda_url(lamdba_name)
    print('got lambda url')

    # bind bot to lambda
    set_bot_webhook(lambda_url, bot)

    # add bot token to db
    add_bot_token_to_db(bot_token, bot_username)

    # get default prompts from s3 PRIVATE_BUCKET
    prompts = get_default_prompts()

    # get default methods from s3 PRIVATE_BUCKET
    methods = get_default_methods()

    # get default database from s3 PRIVATE_BUCKET
    csv_content = get_default_database()
    csv_buffer = StringIO(csv_content)

    # get default experts from s3 PRIVATE_BUCKET
    experts = get_default_experts()

    # get default tools from s3 PRIVATE_BUCKET
    tools = get_default_tools()

    # moderators
    moderators = {'main_chat_id': main_chat_id, 'moderators': [moderator]}

    # config
    default_config = get_default_config()

    # set default settings
    s3.put_object(Bucket=BUCKET, Key=f"{bot_username}/moderators.json", Body=json.dumps(moderators))
    s3.put_object(Bucket=BUCKET, Key=f"{bot_username}/methods.json", Body=json.dumps(methods))
    s3.put_object(Bucket=BUCKET, Key=f"{bot_username}/prompts.json", Body=json.dumps(prompts))
    s3.put_object(Bucket=BUCKET, Key=f"{bot_username}/database.csv", Body=csv_buffer.getvalue())
    s3.put_object(Bucket=BUCKET, Key=f"{bot_username}/experts.json", Body=json.dumps(experts))
    s3.put_object(Bucket=BUCKET, Key=f"{bot_username}/tools.json", Body=json.dumps(tools))
    s3.put_object(Bucket=BUCKET, Key=f"{bot_username}/config.json", Body=json.dumps(default_config))

    return bot_username

def get_global_mods():
    global_mods_key = "global_moderators.json"
    try:
        response = s3.get_object(Bucket=PRIVATE_BUCKET, Key=global_mods_key)
        global_mods = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        global_mods = []
    return global_mods

def add_global_mod(moderator):
    global_mods = get_global_mods()
    global_mods.append(moderator)
    s3.put_object(Bucket=PRIVATE_BUCKET, Key="global_moderators.json", Body=json.dumps(global_mods))

def remove_global_mod(moderator):
    global_mods = get_global_mods()
    try:
        global_mods.remove(moderator)
    except ValueError:
        print(f"Moderator {moderator} not found in global moderators.")
    s3.put_object(Bucket=PRIVATE_BUCKET, Key="global_moderators.json", Body=json.dumps(global_mods))

# get id of global moderator from s3 PRIVATE_BUCKET
def get_main_mod_id():
    global_mods = get_global_mods()
    return global_mods['main_mod']['id']

def get_main_chat_id(bot_username):
    moderators_key = f"{bot_username}/moderators.json"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=moderators_key)
        moderators = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        raise IndexError(f"No {moderators_key} in {BUCKET}.")
    return moderators['main_chat_id']

def set_main_chat_id(bot_username, chat_id):
    moderators_key = f"{bot_username}/moderators.json"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=moderators_key)
        moderators = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        raise IndexError(f"No {moderators_key} in {BUCKET}.")

    moderators['main_chat_id'] = chat_id
    s3.put_object(Bucket=BUCKET, Key=moderators_key, Body=json.dumps(moderators))

def delete_bot_data_from_s3(bot_id):
    s3 = boto3.resource('s3')
    bucket_name = BUCKET
    prefix = f'{bot_id}/'
    bucket = s3.Bucket(bucket_name)
    bucket.objects.filter(Prefix=prefix).delete()

def get_bot_username(bot_token):
    bot = Bot(token=bot_token)
    bot_username = bot.username
    return bot_username

def deregister_bot(bot_username):
    # delete bot from db
    bots_db_key = "bots_id_to_token.json"
    try:
        response = s3.get_object(Bucket=PRIVATE_BUCKET, Key=bots_db_key)
        bots_db = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        raise IndexError(f"No {bots_db_key} in {PRIVATE_BUCKET}.")
    del bots_db[bot_username]
    s3.put_object(Bucket=PRIVATE_BUCKET, Key=bots_db_key, Body=json.dumps(bots_db))

    # delete all bot data from s3
    delete_bot_data_from_s3(bot_username)

# Returns list with all previous users of the community
def get_users(bot_username):
    users_raw = s3.list_objects_v2(Bucket=BUCKET, Prefix=f"{bot_username}/")
    users_dict = {}
    if "Contents" in users_raw:
        for user in users_raw["Contents"]:
            key = user["Key"]
            # skip special objects
            if not key.split('/', 1)[1][0].isdigit():
                continue
            data = s3.get_object(Bucket=BUCKET, Key=key)
            user_id = data["Metadata"]["user_id"]
            try:
                body_str = data["Body"].read().decode("utf-8")
                body_dict = json.loads(body_str)
                users_dict[user_id] = body_dict
            except UnicodeDecodeError:
                print(f"Skipping non-UTF-8 encoded object: {key}")
    return users_dict
    
# Returns the state_update_method of this community
def get_state_update_method(bot_username):
    state_update_method_key = f"{bot_username}/methods.json"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=state_update_method_key)
        existing_content = json.loads(response['Body'].read().decode('utf-8'))
        state_update_method = existing_content["state_update"]
    except s3.exceptions.NoSuchKey:
        app.log.error("There is no state update method for this community!")
        state_update_method = ''
    return state_update_method

def get_match_method(bot_username):
    match_method_key = f"{bot_username}/methods.json"
    # get the match_method of this community
    try:
        response = s3.get_object(Bucket=BUCKET, Key=match_method_key)
        existing_content = json.loads(response['Body'].read().decode('utf-8'))
        match_method = existing_content["match"]
    except s3.exceptions.NoSuchKey:
        app.log.error("There is no match method for this community!")
        match_method = ''
    return match_method

def get_match_prompt(bot_username):
    prompts_key = f"{bot_username}/prompts.json"
    # get the llm_prompt of this community
    try:
        response = s3.get_object(Bucket=BUCKET, Key=prompts_key)
        existing_content = json.loads(response['Body'].read().decode('utf-8'))
        match_prompt = existing_content["match"]
    except s3.exceptions.NoSuchKey:
        app.log.error("There is no match prompt for this community!")
        match_prompt = ''
    return match_prompt


def get_global_match_prompt(bot_username):
    prompts_key = f"{bot_username}/prompts.json"
    # get the global_match_prompt of this community
    try:
        response = s3.get_object(Bucket=BUCKET, Key=prompts_key)
        existing_content = json.loads(response['Body'].read().decode('utf-8'))
        global_match_prompt = existing_content["global_match"]
    except s3.exceptions.NoSuchKey:
        app.log.error("There is no global match prompt for this community!")
        global_match_prompt = ''
    return global_match_prompt

def get_user_prompt(bot_username):
    prompts_key = f"{bot_username}/prompts.json"
    # get the user_prompt of this community
    try:
        response = s3.get_object(Bucket=BUCKET, Key=prompts_key)
        existing_content = json.loads(response['Body'].read().decode('utf-8'))
        user_prompt = existing_content["user"]
    except s3.exceptions.NoSuchKey:
        app.log.error("There is no user prompt for this community!")
        user_prompt = ''
    return user_prompt

def get_summary_prompt(bot_username):
    prompts_key = f"{bot_username}/prompts.json"
    # get the summary_prompt of this community
    try:
        response = s3.get_object(Bucket=BUCKET, Key=prompts_key)
        existing_content = json.loads(response['Body'].read().decode('utf-8'))
        summary_prompt = existing_content["summary"]
    except s3.exceptions.NoSuchKey:
        app.log.error("There is no summary prompt for this community!")
        summary_prompt = ''
    return summary_prompt

def get_query_prompt(bot_username):
    prompts_key = f"{bot_username}/prompts.json"
    # get the query_prompt of this community
    try:
        response = s3.get_object(Bucket=BUCKET, Key=prompts_key)
        existing_content = json.loads(response['Body'].read().decode('utf-8'))
        query_prompt = existing_content["query"]
    except s3.exceptions.NoSuchKey:
        app.log.error("There is no query prompt for this community!")
        query_prompt = ''
    return query_prompt

def get_data_extraction_prompt(bot_username):
    prompts_key = f"{bot_username}/prompts.json"
    # get the data_extraction_prompt of this community
    try:
        response = s3.get_object(Bucket=BUCKET, Key=prompts_key)
        existing_content = json.loads(response['Body'].read().decode('utf-8'))
        data_extraction_prompt = existing_content["data_extraction"]
    except s3.exceptions.NoSuchKey:
        app.log.error("There is no data extraction prompt for this community!")
        data_extraction_prompt = ''
    return data_extraction_prompt

def get_prompts(bot_username):
    prompts_key = f"{bot_username}/prompts.json"
    # get the data_extraction_prompt of this community
    try:
        response = s3.get_object(Bucket=BUCKET, Key=prompts_key)
        prompts = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        app.log.error("There is no data extraction prompt for this community!")
        prompts = ''
    return prompts

def get_config(bot_username):
    config_key = f"{bot_username}/config.json"
    # get the config of this community
    try:
        response = s3.get_object(Bucket=BUCKET, Key=config_key)
        config = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        app.log.error("There is no config for this community!")
        raise Exception("There is no config for this community!")
    return config
    

def get_query_prompt(bot_username):
    prompts = get_prompts(bot_username)
    try:
        query_prompt = prompts["query"]
    except KeyError:
        app.log.error("There is no query prompt for this community!")
        query_prompt = ''
    return query_prompt

def get_router_prompt(bot_username):
    prompts = get_prompts(bot_username)
    try:
        router_prompt = prompts["router"]
    except KeyError:
        app.log.error("There is no router prompt for this community!")
        router_prompt = ''
    return router_prompt

def get_memory_prompt(bot_username):
    prompts = get_prompts(bot_username)
    try:
        memory_prompt = prompts["memory"]
    except KeyError:
        app.log.error("There is no memory prompt for this community!")
        memory_prompt = ''
    return memory_prompt

def get_planner_prompt(bot_username):
    prompts = get_prompts(bot_username)
    try:
        planner_prompt = prompts["planner"]
    except KeyError:
        app.log.error("There is no planner prompt for this community!")
        planner_prompt = ''
    return planner_prompt

def update_chat_state(bot_username, chat_id, chat_state):
    chat_states_key = f"{bot_username}/chat_states.json"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=chat_states_key)
        existing_content = json.loads(response['Body'].read().decode('utf-8'))
        existing_content[str(chat_id)] = chat_state
        s3.put_object(Bucket=BUCKET, Key=chat_states_key, Body=json.dumps(existing_content))
    except s3.exceptions.NoSuchKey:
        s3.put_object(Bucket=BUCKET, Key=chat_states_key, Body=json.dumps({str(chat_id): chat_state}))

def get_chat_state(bot_username, chat_id):
    chat_states_key = f"{bot_username}/chat_states.json"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=chat_states_key)
        existing_content = json.loads(response['Body'].read().decode('utf-8'))
        if str(chat_id) not in existing_content:
            chat_state = None
        else:
            chat_state = existing_content[str(chat_id)]
    except s3.exceptions.NoSuchKey:
        app.log.error("There is no chat state for this user!")
        chat_state = None
    return chat_state


# Parses the output of the LLM to extract the list of matched pairs
def parse_global_match_output(llm_opinion):
    # extract the string containing list of tuples
    start = llm_opinion.find("[")
    end = llm_opinion.find("]")
    llm_opinion = llm_opinion[start:end+1]
    # convert the string into a list of tuples
    try:
        llm_opinion = eval(llm_opinion)
    except SyntaxError or NameError:
        return -1
    return llm_opinion

def add_moderator(bot_username, moderator):
    moderators_key = f"{bot_username}/moderators.json"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=moderators_key)
        existing_content = json.loads(response['Body'].read().decode('utf-8'))
        existing_content['moderators'].append(moderator)
        existing_content['moderators'] = list(set(existing_content['moderators']))
    except s3.exceptions.NoSuchKey:
        raise Exception("There is no moderators.json file for this community!")
    s3.put_object(Bucket=BUCKET, Key=moderators_key, Body=json.dumps(existing_content))

def add_expert(name, description, community):
    experts_key = f"{community}/experts.json"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=experts_key)
        existing_content = json.loads(response['Body'].read().decode('utf-8'))
        existing_content.append({"name": name, "description": description})
        experts = existing_content
    except s3.exceptions.NoSuchKey:
        experts = [{"name": name, "description": description}]
    s3.put_object(Bucket=BUCKET, Key=experts_key, Body=json.dumps(experts))

def add_tool(name, description, community):
    tools_key = f"{community}/tools.json"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=tools_key)
        existing_content = json.loads(response['Body'].read().decode('utf-8'))
        existing_content.append({"name": name, "description": description})
        tools = existing_content
    except s3.exceptions.NoSuchKey:
        tools = [{"name": name, "description": description}]
    s3.put_object(Bucket=BUCKET, Key=tools_key, Body=json.dumps(tools))

def evaluate_potential_match(match_prompt, input_variables):
    llm = ChatOpenAI(temperature=0.9, model_name="gpt-3.5-turbo")

    try:
        template = PromptTemplate(input_variables=list(input_variables.keys()), template=match_prompt)
        reasoning_chain = LLMChain(llm=llm, prompt=template)
        llm_opinion = reasoning_chain.run(input_variables)
    except Exception as e:
        app.log.error(e)
        app.log.error(traceback.format_exc())
        return None, "There was an exception handling your message :("
    is_match = True if "yes" in llm_opinion.lower() else False
    return is_match, llm_opinion

def get_matched_pairs(global_match_prompt, input_variables):
    llm = ChatOpenAI(temperature=0.9, model_name="gpt-3.5-turbo")

    try:
        template = PromptTemplate(input_variables=list(input_variables.keys()), template=global_match_prompt)
        reasoning_chain = LLMChain(llm=llm, prompt=template)
        llm_opinion = reasoning_chain.run(input_variables)
    except Exception as e:
        app.log.error(e)
        app.log.error(traceback.format_exc())
        return None, "There was an exception handling your message :("
    matched_pairs = parse_global_match_output(llm_opinion)
    return matched_pairs, llm_opinion

def parse_csv(csv_string):
    csv_reader = csv.DictReader(StringIO(csv_string))
    return [row for row in csv_reader]


def extract_data(data_extraction_prompt, input_variables):
    llm = ChatOpenAI(temperature=0.9, model_name="gpt-3.5-turbo")

    try:
        template = PromptTemplate(input_variables=list(input_variables.keys()), template=data_extraction_prompt)
        reasoning_chain = LLMChain(llm=llm, prompt=template)
        llm_output = reasoning_chain.run(input_variables)
    except Exception as e:
        app.log.error(e)
        app.log.error(traceback.format_exc())
        return None, "There was an exception handling your message :("
    return llm_output

# returns summary if available otherwise generates summary from llm
def get_user_summary(bot_username, user_id):
    current_user_object = get_user(bot_username, user_id, get_object=True)
    updated = check_if_object_updated(current_user_object)
    current_user_dict = json.loads(current_user_object["Body"].read().decode('utf-8'))
    # if updated, then get summary
    if updated:
        print(f"summary for {user_id} is updated")
        summary = current_user_dict["summary"]
    # if not updated, then get summary from prompt
    else:
        print(f"summary for {user_id} is not updated, updating now...")
        # get summary prompt
        summary_prompt = get_summary_prompt(bot_username)
        input_variables_list = extract_variables_from_template(summary_prompt)
        input_variables_values = [list(current_user_dict["strings"].values()), list(current_user_dict['reviews'].values())]
        input_variables_dict = dict(zip(input_variables_list, input_variables_values))
        # get summary
        summary = get_summary(summary_prompt, input_variables_dict)
        # if summary is None, then there was an error
        if summary[0] == None:
            return None
        # update summary
        current_user_dict["summary"] = summary
        # update the object's metadata and put it back in s3
        metadata = current_user_object.get("Metadata", {})
        metadata["updated"] = "true"
        user_key = f"{bot_username}/{user_id}.json"

        s3.put_object(Bucket=BUCKET, Key=user_key, Body=json.dumps(current_user_dict), Metadata=metadata)
    return summary

# get the users summary from the llm
def get_summary(summary_prompt, input_variables):
    llm = ChatOpenAI(temperature=0.9, model_name="gpt-3.5-turbo")

    try:
        template = PromptTemplate(input_variables=list(input_variables.keys()), template=summary_prompt)
        reasoning_chain = LLMChain(llm=llm, prompt=template)
        llm_output = reasoning_chain.run(input_variables)
    except Exception as e:
        app.log.error(e)
        app.log.error(traceback.format_exc())
        return None, "There was an exception handling your message :("
    return llm_output


def check_if_object_updated(object):
    # get database metadata
    metadata = object.get("Metadata", {})
    # check if it is updated    
    return metadata.get("updated", "false") == "true" 

def get_user(bot_username, user_id, get_object=False):
    user_key = f"{bot_username}/{user_id}.json"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=user_key)
        if get_object:
            return response
        existing_content = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey as e:
        app.log.error("Tried to get sentences from non-exisiting user.")
        existing_content = {"strings": {}, "summary": '', 'reviews': {}}
    return existing_content

def get_pending_queries(bot_username):
    pending_queries_key = f"{bot_username}/pending_queries.pkl"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=pending_queries_key)
        existing_content = pickle.loads(response['Body'].read())
    except s3.exceptions.NoSuchKey as e:
        app.log.error("There are no pending queries.")
        existing_content = {}
    return existing_content

def get_task(bot_username):
    task_key = f"{bot_username}/task.pkl"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=task_key)
        existing_content = pickle.loads(response['Body'].read())
    except s3.exceptions.NoSuchKey as e:
        app.log.error("There is no task.")
        existing_content = None
    return existing_content 

def get_object(community, obj_name):
    key = f"{community}/{obj_name}.pkl"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=key)
        existing_content = pickle.loads(response['Body'].read())
    except s3.exceptions.NoSuchKey as e:
        app.log.error(f"There is no object with name {obj_name}.")
        existing_content = None
    return existing_content

def delete_pending_queries(bot_username):
    pending_queries_key = f"{bot_username}/pending_queries.pkl"
    try:
        s3.delete_object(Bucket=BUCKET, Key=pending_queries_key)
    except s3.exceptions.NoSuchKey as e:
        app.log.error("There are no pending queries.")

def store_object(obj, community, name):
    serialized_object = pickle.dumps(obj)
    key = f"{community}/{name}.pkl"
    s3.put_object(Bucket=BUCKET, Key=key, Body=serialized_object)

def get_experts(bot_username):
    experts_key = f"{bot_username}/experts.json"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=experts_key)
        existing_content = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey as e:
        app.log.error("There are no experts.")
        existing_content = []
    return existing_content


def get_memory_tool(bot_username=None):
    if bot_username is None:
        MEMORY_PROMPT = get_default_memory_prompt()
    else:
        MEMORY_PROMPT = get_memory_prompt(bot_username)
    memory_tool = Tool(
        name = 'Memory',
        func=lambda x: answer_from_memory(query=x, memory_prompt=MEMORY_PROMPT),
        description="Useful for information you have learned in the past. Input should be a fully formed question."
    )
    return memory_tool


def get_tools(bot_username):
    # load tools.json from s3
    tools_key = f"{bot_username}/tools.json"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=tools_key)
        existing_content = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey as e:
        app.log.error("There are no tools.")
        existing_content = []
    return existing_content
    

def get_all_tools(bot_username, client_username=None, include_experts=True):
    tools_list = [tool['name'].strip().lower() for tool in get_tools(bot_username)]
    tools_list.append("knowledge base")  #TODO: should the kb tool always be available?
    tools = []
    tools.append(get_clarification_tool(client_username)) #TODO: should the clarification tool always be available?
    if 'knowledge base' in tools_list:
        tools.append(get_kb_tool(bot_username))
    if include_experts:
        tools.extend(get_tools_from_experts(bot_username))
    if 'search' in tools_list:
        tools.append(get_search_tool(bot_username))
    # if 'memory' in tools_list:
    #     tools.append(get_memory_tool(bot_username)) 
    if 'math_llm' in tools_list:
        tools.append(get_math_tool(bot_username))
    if 'python' in tools_list:
        tools.append(get_python_tool(bot_username))
    return tools

def get_python_tool(bot_username):
    from langchain.utilities import PythonREPL
    python_repl = PythonREPL()
    repl_tool = Tool(
        name="python_repl",
        description="A Python shell. Use this to execute python commands. Input should be a valid python command. If you want to see the output of a value, you should print it out with `print(...)`.",
        func=python_repl.run
    )
    return repl_tool

def get_kb_tool(bot_username):
    pinecone.init(
        api_key=PINECONE_API_KEY,  # find at app.pinecone.io
        environment=PINECONE_ENV  # next to api key in console
    )
    embeddings = OpenAIEmbeddings()

    index_name = "grouplang"
    docsearch = Pinecone.from_existing_index(index_name, embeddings)

    retriever = docsearch.as_retriever()

    llm = OpenAI(temperature=0.9, model_name="text-davinci-003")
    # send typing action
    qa = RetrievalQA.from_chain_type(llm=llm, chain_type="stuff", retriever=retriever)  

    kb_tool = Tool(
        name="knowledge base",
        description="Knowledge base with the information you have acquired so far. Use this first before using other tools. Input should be a question.",
        func=qa.run
    )
    return kb_tool

def get_tools_from_experts(bot_username):
    experts = get_experts(bot_username)
    tools = []
    for expert in experts:
        tools.append(
            Tool(
            name=expert["name"], 
            func=lambda x: None, # for now not used
            description=expert["description"])
            )
    return tools

def get_search_tool(bot_username):
    # search = GoogleSearchAPIWrapper(k=1)
    search = GoogleSerperAPIWrapper()
    search_tool = Tool(
        name = "Search",
        description="A low-cost Google Search API. Useful for when you need to answer questions about current events. Input should be a search query.",
        func=search.run
    )
    return search_tool

def get_clarification_tool(username=None, bot_username=None):
    if username == None:
        username = "<username>"
    clarification_tool = Tool(
        name = username,
        func=lambda x: x,
        description="Original user who asked the question, useful for when you need clarification on the meaning of the question."
    )
    return clarification_tool

def get_math_tool(bot_username):
    math_llm = ChatOpenAI(temperature=0, model_name='gpt-3.5-turbo')
    llm_math_chain = LLMMathChain.from_llm(llm=math_llm, verbose=True)
    math_tool = Tool(
            name="Calculator",
            func=llm_math_chain.run,
            description="useful for when you need to answer questions about math"
        )
    return math_tool

def get_plan(bot_username, query_text, username, intermediate_steps=list()):
    query_llm = ChatOpenAI(temperature=0, model_name="gpt-4")
    tools = get_all_tools(bot_username, client_username=username)
    tool_names = [tool.name for tool in tools]

    # TODO: remove or update old document logic
    if 'document' not in tool_names:
        template = get_prompts(bot_username)['query']
        input_variables = ["input", "intermediate_steps"]
        input = {'input': query_text, 'intermediate_steps': intermediate_steps}
    else:
        template = get_prompts(bot_username)['query_doc']
        input_variables = ["input", "intermediate_steps", "document"]
        try:
            s3_response = s3.get_object(Bucket=BUCKET, Key=f"{bot_username}/current_document_name")
        except s3.exceptions.NoSuchKey as e:
            raise Exception("There is no current document.")
        current_doc_name = s3_response['Body'].read().decode('utf-8')
        input = {'input': query_text, 'intermediate_steps': intermediate_steps, 'document': current_doc_name}

    prompt = CustomPromptTemplate(
        template=template,
        tools=tools,
        # This omits the `agent_scratchpad`, `tools`, and `tool_names` variables because those are generated dynamically
        # This includes the `intermediate_steps` variable because that is needed
        input_variables=input_variables
    )
    output_parser = CustomOutputParser()
    llm_chain = LLMChain(llm=query_llm, prompt=prompt)
    agent = LLMSingleActionAgent(
        llm_chain=llm_chain, 
        output_parser=output_parser,
        stop=["\nObservation:"],
        allowed_tools=tool_names
    )
    return agent.plan(**input)

def get_next_action(bot_username, task):
    task_llm = ChatOpenAI(temperature=0, model_name='gpt-4')

    HUMAN_MESSAGE_TEMPLATE = """Previous steps: {previous_steps}

    Current objective: {current_step}

    {agent_scratchpad}"""

    tools = get_all_tools(bot_username, include_experts=False) 

    agent = StructuredChatAgent.from_llm_and_tools(
        task_llm,
        tools,
        human_message_template=HUMAN_MESSAGE_TEMPLATE,
        input_variables=["previous_steps", "current_step", "agent_scratchpad"],
    )
    objective = task.objective
    plan = task.plan

    current_step = plan.steps[int(task.current_step_n)]


    all_inputs = {"input": objective, "previous_steps": task.step_container, "current_step": current_step, 'intermediate_steps':task.intermediate_steps}
    action = agent.plan(**all_inputs)
    return action

def update_action_with_feedback(bot_username, query, answer, feedback):
    llm = ChatOpenAI(temperature=0.9, model_name="gpt-3.5-turbo")
    feedback_prompt = get_prompts(bot_username)['feedback']

    prompt = PromptTemplate(
        input_variables=["answer", "feedback", "query"],
        template=feedback_prompt
    )
    reasoning_chain = LLMChain(llm=llm, prompt=prompt)
    llm_opinion = reasoning_chain.run({'answer': answer, 'feedback': feedback, 'query': query})
    return  llm_opinion


def get_steps(bot_username, query):
    planner_llm = ChatOpenAI(temperature=0, model_name='gpt-4')

    PLANNER_PROMPT = get_planner_prompt(bot_username)
    prompt_template = ChatPromptTemplate.from_messages(
        [
            SystemMessage(content=PLANNER_PROMPT),
            HumanMessagePromptTemplate.from_template("{input}"),
        ]
    )
    llm_chain = LLMChain(llm=planner_llm, prompt=prompt_template)
    planner = LLMPlanner(
        llm_chain=llm_chain,
        output_parser=PlanningOutputParser(),
        stop=["<END_OF_PLAN>"],
    )
    # query = "What is the age difference between Brad Pitt and Angelina Jolie?"

    plan = planner.plan({'input' : query})
    return plan


def parse_router_output(llm_output):
    """Parse the output from the router chain to a callback function name."""
    callback_name = llm_output.split('Action: ')[1].split('\n')[0]
    callback_args = llm_output.split('Action Input: ')[1].split('\n')[0]
    callback_args = callback_args.replace("'", '"')
    if callback_args == "None":
        callback_args = None
    else:
        callback_args = json.loads(callback_args)
    return callback_name, callback_args


def insert_in_index(index_name, namespace, text):
    pinecone.init(api_key=PINECONE_API_KEY, environment=PINECONE_ENV)
    embeddings = OpenAIEmbeddings()
    index = pinecone.Index(index_name)
    vectors = [{'id': uuid.uuid4().hex, 'text': text}]

    # embed vectors
    for v in vectors:
        v['embedding'] = embeddings.embed_query(v['text'])
    
    batch_size = 1
    for i in range(0, len(vectors), batch_size):
        # find end of batch
        i_end = min(len(vectors), i+batch_size)
        meta_batch = vectors[i: i_end]
        # get ids
        ids_batch = [x['id'] for x in meta_batch]
        # add embeddings
        embeds = [x['embedding'] for x in meta_batch]
        # cleanup metadata
        meta_batch = [{
            'text': x['text']
        } for x in meta_batch]
        to_upsert = list(zip(ids_batch, embeds, meta_batch))
        # # upsert to Pinecone
        # print(to_upsert[0][0])
        index.upsert(vectors=to_upsert, namespace=namespace)
        print(f'batch {i} upserted')


def get_relevant_docs(index_name, query, n=3, namespace='test'):
    pinecone.init(api_key=PINECONE_API_KEY, environment=PINECONE_ENV)
    embeddings = OpenAIEmbeddings()
    index = pinecone.Index(index_name)

    embedding = embeddings.embed_query(query)
    result = index.query(
        vector=embedding,
        top_k=n,
        include_distances=True,
        include_metadata=True,
        namespace=namespace
    )
    relevant_docs = [doc for doc in result['matches']]
    return relevant_docs

def get_relevant_texts(index_name, query, n=3, namespace='test'):    
    docs = get_relevant_docs(index_name, query, n, namespace)
    relevant_texts = [doc['metadata']['text'] for doc in docs]
    return relevant_texts


def get_all_docs(index_name='grouplang', namespace='test'):
    index = pinecone.Index(index_name)
    stats = index.describe_index_stats()
    size = stats["total_vector_count"]
    query = 'dummy'
    return get_relevant_docs(index_name=index_name, query=query, n= int(size), namespace=namespace)

def get_all_texts(index_name, namespace='test'):
    docs = get_all_docs(index_name, namespace)
    all_texts = [doc['metadata']['text'] for doc in docs]
    return all_texts

def delete_index(index_name):
    pinecone.delete_index(index_name)

def delete_all_entries(index_name, namespace='test'):
    index = pinecone.Index(index_name)
    index.delete(delete_all=True, namespace=namespace)

def answer_from_memory(query, memory_prompt, index_name='grouplang', namespace='test'):
    llm_mem = ChatOpenAI(temperature=0)
    relevant_texts = get_relevant_texts(index_name, query, n=3, namespace=namespace)
    prompt = PromptTemplate(template=memory_prompt, input_variables=["context", "question"])
    llm_chain_test = LLMChain(llm=llm_mem, prompt=prompt)
    llm_opinion = llm_chain_test.run({"context": relevant_texts, "question": query})
    return llm_opinion