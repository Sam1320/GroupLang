import json
from chalice import Chalice
from telegram.ext import Dispatcher, MessageHandler, Filters, CommandHandler
import boto3
AWS_PROFILE = 'localstack'
boto3.setup_default_session(profile_name=AWS_PROFILE)

from telegram import MessageEntity, ParseMode, Update, Bot
from langchain.chat_models import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain
from chalicelib.utils import get_chat_state, get_config, get_main_chat_id, get_prompts, send_typing_action, parse_router_output
from chalicelib.callbacks import (
    cmd_add_global_moderator, cmd_ask, cmd_deregister_bot, cmd_disable_debug, cmd_disable_feedback, cmd_enable_debug, 
    cmd_enable_feedback, cmd_help, cmd_remove_global_moderator, cmd_reset_index, cmd_show_experts, cmd_show_global_moderators, cmd_start, cmd_token, 
    cmd_reset_defaults, cmd_introduce, cmd_show_tools, cmd_add_tool, cmd_remove_tool, cmd_answer, 
    cmd_query, cmd_delete_pending_queries, cmd_show_pending_queries, cmd_add_expert, 
    cmd_add_moderator, handle_document, new_member, handle_url)
from chalicelib.credentials import BUCKET, PRIVATE_BUCKET, MAIN_BOT_NAME, APP_NAME, MESSAGE_HANDLER_LAMBDA

# s3 = boto3.client("s3")
AWS_REGION = "eu-west-1"
ENDPOINT_URL = "http://localhost:4566"
s3 = boto3.client("s3", region_name=AWS_REGION, endpoint_url=ENDPOINT_URL)
app = Chalice(app_name=APP_NAME)
app.debug = True

CALLBACKS = [
    {"name": "cmd_message", "args": None}, 
    {"name": "cmd_start", "args": None}, 
    {"name": "cmd_reset_defaults", "args": None}, 
    {"name": "cmd_reset_index", "args": None},
    {"name": "cmd_show_tools", "args": None}, 
    {"name": "cmd_show_pending_queries", "args": None}, 
    {"name": "cmd_delete_pending_queries", "args": None}, 
    {"name": "cmd_enable_feedback", "args": None}, 
    {"name": "cmd_disable_feedback", "args": None},
    {"name": "cmd_enable_debug", "args": None},
    {"name": "cmd_disable_debug", "args": None}, 
    {"name": "cmd_help", "args": None, "hint": "Whenever the user seems to be asking for how the bot works"}, 
    {"name": "cmd_deregister_bot", "args": None},
    {"name": "cmd_token", "args": ["token"]}, 
    {"name": "cmd_set_user_prompt", "args": ["prompt"]},
    {"name": "cmd_add_moderator", "args": ["moderator"]}, 
    {"name": "cmd_add_tool", "args": ["name", "description"]}, 
    {"name": "cmd_add_expert", "args": ["username", "description"], "hint": "When a user wants to add another one as an expert"}, 
    {"name": "cmd_introduce", "args": ["description"], "hint": "When user is introducing themselves and stating what they know."}, 
    {"name": "cmd_answer", "args": ["answer"], "hint": "When user answers a question"},     
    {"name": "cmd_query", "args": ["query"], "hint": "When user asks a question or orders a task"}, 
    {"name": "cmd_remove_tool", "args": ["tool_name"], "hint": "When user asks to remove a tool"}
]



@send_typing_action
def process_message(update, context):
    # extract relevant info
    chat_id = update.message.chat_id
    chat_text = update.message.text
    username = update.message.from_user.username
    name = update.message.from_user.name
    bot_username = context.bot.get_me().username
    user_id = update.message.from_user.id

    print(f"Received message from {username} ({user_id}) in chat {chat_id} . message: ({chat_text})")

    # ignore text if main bot
    if bot_username == MAIN_BOT_NAME or chat_text.startswith("/"):
        context.bot.send_message(chat_id=chat_id, text=f"Sorry, I'm just meant to receive /start and /token commands.")
        return
    
    # get chat state and check if there is a pending answer from this chat. If so then map directly to cmd_answer
    chat_state = get_chat_state(bot_username, chat_id)
    if chat_state == "waiting_for_answer":
        context.bot.send_message(chat_id=chat_id, text=f"Thanks for your help {name} :).")
        cmd_answer(update, context, chat_text)
        return
    elif chat_state == "waiting_for_clarification":
        context.bot.send_message(chat_id=chat_id, text=f"Thank you for clarifying that {name} :). I'll send you a message when I have an answer.")
        cmd_answer(update, context, chat_text)
        return
    elif chat_state == "waiting_for_feedback":
        context.bot.send_message(chat_id=chat_id, text=f"Thank you for your feedback {name} :).")
        cmd_answer(update, context, chat_text)
        return

    prompts = get_prompts(bot_username)
    ROUTER_PROMPT = prompts["router"]

    router_llm = ChatOpenAI(temperature=0, model_name="gpt-3.5-turbo")
    prompt = PromptTemplate(
        input_variables=["input", "callbacks"],
        template=ROUTER_PROMPT
    )
    router_chain = LLMChain(llm=router_llm, prompt=prompt)

    try:
        llm_opinion = router_chain.run({"input": chat_text, "callbacks": CALLBACKS})
    except Exception as e:
        # show error to user
        context.bot.send_message(chat_id=chat_id, text=f"Error: {e}")
        return
    

    try:
        # parse output
        callback_name, callback_args  = parse_router_output(llm_opinion)
    except Exception as e:
        # show error to user
        app.log.error(e)
        context.bot.send_message(chat_id=chat_id, text=f"Error: {e}", parse_mode=ParseMode.MARKDOWN,)
        return
    
    # if message is not mapped to any other callback, it is mapped to cmd_message. for now we just ignore it
    if callback_name == 'cmd_message':
        return
    
    #show llm opinion to mods
    debug = True if get_config(bot_username)['debug'] == 'yes' else False
    if debug:
        main_chat_id = get_main_chat_id(bot_username)
        context.bot.send_message(chat_id=main_chat_id, text=f"Hi, router agent here. I got the message: \n'''{chat_text}'''\n  and I matched it to the command: \n{callback_name} \n with args: \n{callback_args}")

    try:
        # get callback function
        command = globals()[callback_name]
    except Exception as e:
        # show error to user
        app.log.error(e)
        context.bot.send_message(chat_id=chat_id, text=f"Error trying to fetch the mapped command: {e}")
        return
    
    # execute callback function
    if callback_args is None:
        command(update, context)
    else:
        try:
            command(update, context, **callback_args)
        except Exception as e:
            # show error to user
            app.log.error(e)
            context.bot.send_message(chat_id=chat_id, text=f"Error trying to execute the mapped command. \n Error: {e}")


# lamdba handler function
@app.lambda_function(name=MESSAGE_HANDLER_LAMBDA)
def message_handler(event, context):
    # initialize the bot and dispatcher using the extracted community id
    community_id = event['queryStringParameters']['community_id']
    print(f"got event: {event}")

    # verify that the community_id/bot_token is registered in the bots database
    bots_db_key = "bots_id_to_token.json"
    response = s3.get_object(Bucket=PRIVATE_BUCKET, Key=bots_db_key)
    bots_db = json.loads(response['Body'].read().decode('utf-8'))

    if community_id not in bots_db.values():
        print(f"Unauthorized Bot Token: {community_id}")
        return {
            "statusCode": 401,
            "body": json.dumps({
                "message": "Unauthorized Bot Token",
            }),
        }

    bot = Bot(token=community_id)
    
    # check update id to avoid processing the same message twice
    # TODO: reset processed messages every 24 hours (otherwise it will grow indefinitely!)
    PROCESSED_MESSAGES_KEY = f"{bot.username}/processed_messages.json"
    try:
        response = s3.get_object(Bucket=BUCKET, Key=PROCESSED_MESSAGES_KEY)
        processed_messages = set(json.loads(response['Body'].read().decode('utf-8')))
    except Exception as e:
        app.log.error(e)
        processed_messages = set()        

    event_body = json.loads(event['body'])
    update_id = event_body['update_id']

    if update_id in processed_messages:
        app.log.info(f"Message already processed: {update_id}")
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Message already processed",
            }),
        }
    else:
        app.log.info(f"Processing message: {update_id}")
        processed_messages.add(update_id)
        s3.put_object(Bucket=BUCKET, Key=PROCESSED_MESSAGES_KEY, Body=json.dumps(list(processed_messages)))
        

    dispatcher = Dispatcher(bot, None, use_context=True)

    # add handlers
    dispatcher.add_handler(CommandHandler('start', cmd_start))
    dispatcher.add_handler(CommandHandler('token', cmd_token))
    dispatcher.add_handler(CommandHandler('reset_defaults', cmd_reset_defaults))
    dispatcher.add_handler(CommandHandler('help', cmd_help))
    dispatcher.add_handler(CommandHandler('show_tools', cmd_show_tools))
    dispatcher.add_handler(CommandHandler('add_tool', cmd_add_tool))
    dispatcher.add_handler(CommandHandler('remove_tool', cmd_remove_tool))
    dispatcher.add_handler(CommandHandler('query', cmd_query))
    dispatcher.add_handler(CommandHandler('answer', cmd_answer))
    dispatcher.add_handler(CommandHandler('add_expert', cmd_add_expert))
    dispatcher.add_handler(CommandHandler('show_experts', cmd_show_experts))
    dispatcher.add_handler(CommandHandler('show_pending_queries', cmd_show_pending_queries))
    dispatcher.add_handler(CommandHandler('delete_pending_queries', cmd_delete_pending_queries))
    dispatcher.add_handler(CommandHandler('add_moderator', cmd_add_moderator))
    dispatcher.add_handler(CommandHandler("ask", cmd_ask))
    dispatcher.add_handler(CommandHandler('enable_feedback', cmd_enable_feedback))
    dispatcher.add_handler(CommandHandler('disable_feedback', cmd_disable_feedback))
    dispatcher.add_handler(CommandHandler('enable_debug', cmd_enable_debug))
    dispatcher.add_handler(CommandHandler('disable_debug', cmd_disable_debug))
    dispatcher.add_handler(CommandHandler('reset_index', cmd_reset_index))
    dispatcher.add_handler(CommandHandler('introduce', cmd_introduce))
    dispatcher.add_handler(CommandHandler('deregister_bot', cmd_deregister_bot))
    dispatcher.add_handler(CommandHandler('add_global_mod', cmd_add_global_moderator))
    dispatcher.add_handler(CommandHandler('remove_global_mod', cmd_remove_global_moderator))
    dispatcher.add_handler(CommandHandler('show_global_mods', cmd_show_global_moderators))
    dispatcher.add_handler(MessageHandler(Filters.entity(MessageEntity.URL), handle_url))
    dispatcher.add_handler(MessageHandler(Filters.document, handle_document))
    dispatcher.add_handler(MessageHandler(Filters.status_update.new_chat_members, new_member))
    dispatcher.add_handler(MessageHandler(Filters.text, process_message))

    # process update
    try:
        dispatcher.process_update(Update.de_json(json.loads(event["body"]), bot))
    except Exception as e:
        print(e)
        return {"statusCode": 500}
    return {"statusCode": 200}