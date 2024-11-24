import hashlib
import hmac
import json
import logging
import os
import re
import sys
import uuid
from copy import deepcopy as copy
from pprint import pprint

import requests
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from taiga import TaigaAPI
from waitress import serve
from werkzeug.middleware.proxy_fix import ProxyFix

from util import blocks, slack, slack_formatters, taigalink, tidyhq


def verify_signature(key, data, signature):
    mac = hmac.new(key.encode("utf-8"), msg=data, digestmod=hashlib.sha1)
    return mac.hexdigest() == signature


# Set up logging
logging.basicConfig(level=logging.INFO)
# Set urllib3 logging level to INFO to reduce noise when individual modules are set to debug
urllib3_logger = logging.getLogger("urllib3")
urllib3_logger.setLevel(logging.INFO)
# Set slack bolt logging level to INFO to reduce noise when individual modules are set to debug
slack_logger = logging.getLogger("slack")
slack_logger.setLevel(logging.INFO)
setup_logger = logging.getLogger("setup")
logger = logging.getLogger("issue_sync")

# Load config
try:
    with open("config.json") as f:
        config: dict = json.load(f)
except FileNotFoundError:
    setup_logger.error(
        "config.json not found. Create it using example.config.json as a template"
    )
    sys.exit(1)

if not config["taiga"].get("auth_token"):
    # Get auth token for Taiga
    # This is used instead of python-taiga's inbuilt user/pass login method since we also need to interact with the api directly
    auth_url = f"{config['taiga']['url']}/api/v1/auth"
    auth_data = {
        "password": config["taiga"]["password"],
        "type": "normal",
        "username": config["taiga"]["username"],
    }
    response = requests.post(
        auth_url,
        headers={"Content-Type": "application/json"},
        data=json.dumps(auth_data),
    )

    if response.status_code == 200:
        taiga_auth_token = response.json().get("auth_token")
    else:
        setup_logger.error(f"Failed to get auth token: {response.status_code}")
        sys.exit(1)

else:
    taiga_auth_token = config["taiga"]["auth_token"]

taigacon = TaigaAPI(host=config["taiga"]["url"], token=taiga_auth_token)

# Map project names to IDs
projects = taigacon.projects.list()
project_ids = {project.name.lower(): project.id for project in projects}
actual_ids = {project.name.lower(): project.id for project in projects}

# Duplicate similar board names for QoL
project_ids["infra"] = project_ids["infrastructure"]
project_ids["laser"] = project_ids["lasers"]
project_ids["printer"] = project_ids["3d"]
project_ids["printers"] = project_ids["3d"]

# Set up TidyHQ cache
tidyhq_cache = tidyhq.fresh_cache(config=config)
setup_logger.info(
    f"TidyHQ cache set up: {len(tidyhq_cache['contacts'])} contacts, {len(tidyhq_cache['groups'])} groups"
)

# Initialize the app with your bot token and signing secret
slack_app = App(token=config["slack"]["bot_token"], logger=slack_logger)

flask_app = Flask(__name__)


@flask_app.route("/taiga/incoming", methods=["POST"])
def incoming():
    # Get the verification header
    signature = request.headers.get("X-Taiga-Webhook-Signature")

    if not signature:
        return "No signature", 401

    if not verify_signature(
        key=config["taiga"]["webhook_secret"], data=request.data, signature=signature
    ):
        return "Invalid signature", 401

    logger.debug("Data received from taiga and verified")

    data = request.get_json()

    # We only perform actions in three scenarios:
    # 1. The webhook is for a new issue or user story
    new_thing = False
    # 2. The webhook is for a user story tagged with "important"
    important = False
    # 3. The webhook is for a user story that is watched by someone other than the user who initiated the action
    watched = False

    send_to = []
    project_id = str(data["data"]["project"]["id"])
    # Map the project ID to a slack channel
    slack_channel = None
    if project_id in config["taiga-channel"]:
        slack_channel = config["taiga-channel"][project_id]
    from_slack_id = None

    if data["action"] == "create":
        # If the created thing is an issue it must be created by Giant Robot for us to send a notification
        # It's assumed that issues created by people directly in Taiga are already being handled appropriately
        if data["type"] == "issue" and data["by"]["full_name"] != "Giant Robot":
            logger.debug("Issue created by non-Giant Robot user, no action required")
            return "No action required", 200
        elif data["type"] == "issue":
            # Giant Robot only raises issues based on Slack interactions.
            # We can find the user who initiated the action by looking at the description
            pattern = re.compile(r"Added to Taiga by: .* \((\w+)\)")
            match = pattern.search(data["data"]["description"])
            if match:
                from_slack_id = match.group(1)
        new_thing = True
        assigned_to = data["data"]["assigned_to"]
        if assigned_to:
            watchers = [assigned_to["id"]]
        # Add the corresponding slack channel as a recipient if it exists
        if slack_channel:
            # Don't send notifications to slack channels for new tasks
            if data["type"] != "task":
                send_to.append(slack_channel)

    elif "important" in data["data"]["tags"]:
        important = True
        # Add the corresponding slack channel as a recipient if it exists
        if slack_channel:
            send_to.append(slack_channel)
        else:
            logger.error(
                f"No slack channel found for project {project_id} and it's marked as important"
            )

    if data["action"] == "change":
        by = data["by"]["id"]
        watchers = data["data"]["watchers"]
        # Check if the user who's assigned the issue is watching it (and pretend they are if they aren't)
        assigned_to = data["data"]["assigned_to"]
        if assigned_to:
            if assigned_to["id"] not in watchers:
                watchers.append(assigned_to["id"])

        # Remove the user who initiated the action from the list of watchers if present
        if by in watchers:
            watchers.remove(by)

        if len(watchers) > 0:
            watched = True
            send_to += [str(watcher) for watcher in watchers]

    logger.info(f"New: {new_thing}, Important: {important}, Watched: {watched}")

    if not new_thing and not important and not watched:
        return "No action required", 200

    # Construction the message
    message = taigalink.parse_webhook_action_into_str(
        data=data,
        tidyhq_cache=tidyhq_cache,
        config=config,
        taiga_auth_token=taiga_auth_token,
    )

    block_list = []
    block_list += blocks.text
    block_list = slack_formatters.inject_text(block_list, message)

    # Check if there's a url to attach
    # This is also where we add a watch button
    url = data["data"].get("permalink", None)
    if url:
        # Construct the "View in Taiga" button
        visit_button = copy(blocks.button)
        visit_button["text"]["text"] = "View in Taiga"
        visit_button["url"] = url
        visit_button["action_id"] = f"tlink{uuid.uuid4().hex}"

        # Construct the "Watch" button
        watch_button = copy(blocks.button)
        watch_button["text"]["text"] = "Watch"
        watch_button["action_id"] = f"twatch{uuid.uuid4().hex}"
        # Create a value that will let us identify the issue later
        item_data = {
            "project_id": project_id,
            "item_id": data["data"]["id"],
            "type": data["type"],
            "permalink": url,
        }
        watch_button["value"] = json.dumps(item_data)

        # Create an action block and add the buttons
        block_list += copy(blocks.actions)
        block_list[-1]["elements"].append(visit_button)
        block_list[-1]["elements"].append(watch_button)

    # map recipients to slack IDs
    recipients = slack.map_recipients(
        list_of_recipients=send_to, tidyhq_cache=tidyhq_cache, config=config
    )

    # Decide who we're sending as
    sender_image = None
    sender_name = None

    if data["by"]["full_name"] != "Giant Robot":
        sender_image = data["by"].get("photo", None)
        sender_name = f"{data['by']['full_name'].split(' ')[0]} | Taiga"

    # If we know the slack ID of the user who initiated the action, send the message as them
    if from_slack_id:
        # Get the Slack user's details
        user = slack_app.client.users_info(user=from_slack_id)
        sender_image = user["user"]["profile"]["image_72"]
        sender_name = f"{user['user']['profile']['display_name_normalized']} | Taiga"

    for user in recipients["user"]:
        slack.send_dm(
            slack_id=user,
            message=message,
            slack_app=slack_app,
            blocks=block_list,
            photo=sender_image,
            username=sender_name,
        )

    for channel in recipients["channel"]:
        try:
            slack_app.client.chat_postMessage(
                channel=channel,
                text=message,
                blocks=block_list,
                icon_url=sender_image,
                username=sender_name,
            )
        except SlackApiError as e:
            logger.error(f"Failed to send message to channel {channel}")
            logger.error(e.response["error"])
            pprint(block_list)

    return "Actioned!", 200


@flask_app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def catch_all(path):
    print(f"Route: /{path}")
    return "", 404


flask_app.wsgi_app = ProxyFix(flask_app.wsgi_app, x_for=1, x_proto=1, x_host=1)

if __name__ == "__main__":
    serve(flask_app, host="0.0.0.0", port=32000)
