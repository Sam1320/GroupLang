import os

os.environ["AWS_ACCESS_KEY_ID"] = "test"
os.environ["AWS_SECRET_ACCESS_KEY"] = "test"
os.environ["AWS_SESSION_TOKEN"] = "test"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["DEFAULT_REGION"] = "us-east-1"

# S3 buckets
PRIVATE_BUCKET = os.environ["S3_PRIVATE_BUCKET"] = ""
BUCKET = os.environ["S3_BUCKET"] = ""

# api keys
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"] = ""
PINECONE_API_KEY = os.environ["PINECONE_API_KEY"] = ""
PINECONE_ENV = os.environ["PINECONE_ENVIRONMENT"] = ""

# bots
MAIN_BOT_NAME = os.environ["MAIN_BOT_NAME"] = ''
MAIN_MOD_ID = os.environ["MAIN_MOD_ID"] = ""
MAIN_MOD_USERNAME = os.environ["MAIN_MOD_USERNAME"] = ""

# Chalice Lambda app
APP_NAME = "grouplang"
MESSAGE_HANDLER_LAMBDA = "message-handler"
