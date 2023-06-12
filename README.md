# GroupLang
LLM-powered telegram bot that can interact with groups of humans for varied collaborative activities. The current example use case is an agent that can rely on humans as experts in addition to using documents when answering user queries. 

The running version of the bot is currently deployed in AWS Lambda and is built using [LangChain](https://python.langchain.com/en/latest/index.html) as an LLM-framework. But we are [migrating](#migration)

## Features
- [x] Index and answer questions using .txt and .pdf documents, and urls from github repositories.
- [x] Ask domain experts for information.
- [x] Ask original user for clarification on a question.
- [x] Stream Chain of Thought and sends feedback requests to a dedicated moderator channel (user only sees relevant info).
- [x] Moderators can confirm or correct agent's final answer giving it feedback before sending it to the user.
- [x] Asks new group members of the moderator group for their expertise and adds user as expert when receiving the user's self-description.
- [x] Moderators can toggle feedback mode to increase bots autonomy.
- [x] Moderators can toggle debug mode to hide thoghts and logs.

### Setting up Group, Uploading Docs & Adding Experts
https://github.com/Sam1320/GroupLang/assets/33493647/ccae2fef-9a21-442c-93d7-2c1ceec396f9

### Asking Domain Experts for Help
https://github.com/Sam1320/GroupLang/assets/33493647/f2d65de4-49a1-4f66-bc14-ac3232cc6fc5

### Asking Questions Regarding docs, Toggling Feedback/Debug Modes, Adding Tools
https://github.com/Sam1320/GroupLang/assets/33493647/716ede83-357c-4b1e-ad7a-36b3edabeca1

# Getting Started (WIP)
## Initial Setup 

1. Create an [OpenAI account](https://openai.com/api/) and [get an API Key](https://platform.openai.com/account/api-keys).
2. Create an [AWS account](https://aws.amazon.com/es/).
3. Setup your Telegram bot. You can follow [this instructions](https://core.telegram.org/bots/tutorial#obtain-your-bot-token) to get your token.
4. Create 2 S3 buckets in your AWS account, one public and one private.
5. Create a Pinecone account and get an API key.
6. Create a Serper account and get an API key.
7. Go to `.chalice/config.json` and stablish the configurations:
- `TELEGRAM_TOKEN` with your Telegram token. 
- `MAIN_BOT_NAME` with the *username* of your main bot.
- `OPENAI_API_KEY` with the value of your Open AI API Token.
- `S3_BUCKET`: with the bucket name you created previously.
- `S3_PRIVATE_BUCKET`: with the other bucket name,
- `SERPER_API_KEY`: with your Serper API key,
- `PINECONE_API_KEY`: with your Pinecone API key,
- `PINECONE_ENVIRONMENT` with your Pinecone environment.
8. as an alternative to step 7, you can set the environment variables in github secrets and uncomment the code in `.github/workflows/main.yml` this will automatically setup and deploy your bot in AWS Lambda when you push to the main branch.

## Installation
1. Install Python using [pyenv](https://github.com/pyenv/pyenv-installer) or your prefered Python installation.
2. Create a virtual environment: `python3 -m venv .venv`.
3. Activate you virtual environment: `source .venv/bin/activate`.
3. Install dependencies: `pip install -r requirements.txt`.
4. [Install the AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) and [configure your credentials](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-quickstart.html).

## Deployment
1. Run `chalice deploy`.
2. Go to the AWS Console -> Lambda -> grouplang-dev-message-handler -> Configuration -> Function URL.
3. Click Create Function URL and set Auth type to NONE.
4. [Add layer](https://github.com/lambci/git-lambda-layer) to lambda function to allow the usage of `git` binaries. This is needed to index github repositories. (Currently needs to be done manually in the AWS console after `chalice deploy`). 
5. Copy the created function URL.
6. run `python scripts/set_bot_webhook.py <YOUR_FUNCTION_URL> <YOUR_TELEGRAM_TOKEN>` to stablish your Telegram webhook to point to you AWS Lambda.
7. run `python scripts/register_bot.py <YOUR_TELEGRAM_TOKEN>` to register your main bot in the private S3 bucket. 
8. run `python scripts/register_lambda.py <YOUR_FUNCTION_NAME> <YOUR_FUNCTION_URL>` to register your lambda function in s3 (will be used to set the webhooks of community bots programatically.

Now you can go an setup your bot & group in telegram!.

# Migration
We are currently migrating the hosting to [Modal](https://modal.com/) and replacing LangChain with [Guidance](https://github.com/microsoft/guidance). The main reasons are the following:

1. Although LangChain is nice to get started quickly, it is not [well suited](https://github.com/hwchase17/langchain/issues/1364#issuecomment-1560895510) for a serverless framework. Also due to its extremely nested design it is not easy to keep an intuitive overview of the prompts and parsers used by each agent. [Guidance](https://github.com/microsoft/guidance) solves this by representing programs as simple strings which allows to see all prompts at once.
2. Modal is built explicitly for ML applications in mind, is very easy to setup and manage compared to AWS Lambda, and offersthe same instant feedback loop you have when you develop locally. 
3. [Guidance](https://github.com/microsoft/guidance)'s [token healing](https://github.com/microsoft/guidance/blob/main/notebooks/art_of_prompt_design/prompt_boundaries_and_token_healing.ipynb) automatically deals with the uninteded consequences of greedy tokenizations used by most language models. 

The migration process is taking place in the [switch_to_guidance](https://github.com/Sam1320/GroupLang/tree/switch_to_guidance) branch.

# Next Steps
- [x] Handle urls of repositories to load information in the knowledge base.
- [ ] Create summary of documents before indexing and add list of summaries to the query agent prompt so it knows what it knows.
- [ ] Use single config.json (or other format) to store the community parameters
- [ ] Use one namespace per community when indexing in vector store.
- [ ] Index (bad answer, feedback) tuples to improve quality of answers overtime.
- [ ] Use google api for search directly instead of serper api
- [ ] Add timeout + exponential backoff when waiting for expert/moderator feedback.
- [ ] Finish Guidance/Modal migration
There is also a lot of additional functionality *already implemented* but currently not integrated. The corresponging code is currently commented out.
### WIP:
- [ ] Creating tabular data from collections of free-form user messages.
- [ ] Matching users based of self description
- [ ] Create & summarize user description based on messages.
- [ ] Use Plan & Execute framework to solve more complicated tasks.


## Other Notes & Information

## License
GroupLang is licensed under the MIT License. For more information, see the [LICENSE](LICENSE) file.
