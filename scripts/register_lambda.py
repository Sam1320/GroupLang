import boto3, json
import os
from telegram import Bot

def register_lambda(lambda_name, url):
    s3 = boto3.client("s3")

    # get s3 private bucket name from env   
    BUCKET = os.environ['S3_PRIVATE_BUCKET']
    lambdas_db_key = "lambdas.json"

    try:
        response = s3.get_object(Bucket=BUCKET, Key=lambdas_db_key)
        lambdas_db = json.loads(response['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        lambdas_db = {}

    # Add the new sentence to the existing content
    lambdas_db[lambda_name] = url
    
    # Store the updated content in the object
    s3.put_object(Bucket=BUCKET, Key=lambdas_db_key, Body=json.dumps(lambdas_db))
    print(f"Registered lambda {lambda_name} with url {url}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python register_lambda.py LAMBDA_NAME URL")
        exit(1)
    lambda_name = sys.argv[1]
    url = sys.argv[2]
    register_lambda(lambda_name, url)
    print("done")