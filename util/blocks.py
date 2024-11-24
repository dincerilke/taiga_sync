divider = [{"type": "divider"}]
text = [{"type": "section", "text": {"type": "mrkdwn", "text": ""}}]
context = [
    {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": ""}],
    }
]
quote = [
    {
        "type": "rich_text",
        "elements": [
            {
                "type": "rich_text_quote",
                "elements": [
                    {
                        "type": "text",
                        "text": "",
                    }
                ],
            }
        ],
    }
]
header = [{"type": "header", "text": {"type": "plain_text", "text": "", "emoji": True}}]

accessory_image = {"type": "image", "image_url": "", "alt_text": ""}

button = {"type": "button", "text": {"type": "plain_text", "text": ""}}

actions = [{"type": "actions", "block_id": "button_actions", "elements": []}]

text_question = {
    "type": "input",
    "element": {
        "type": "plain_text_input",
        "action_id": "",
        "placeholder": {"type": "plain_text", "text": "", "emoji": True},
    },
    "label": {"type": "plain_text", "text": "", "emoji": True},
}

option = {
    "text": {"type": "plain_text", "text": "", "emoji": True},
    "value": "",
}

radio_buttons = {
    "type": "input",
    "element": {
        "type": "radio_buttons",
        "options": [],
        "action_id": "",
    },
    "label": {"type": "plain_text", "text": "", "emoji": True},
}

static_dropdown = {
    "type": "input",
    "element": {
        "type": "static_select",
        "placeholder": {"type": "plain_text", "text": "", "emoji": True},
        "options": [],
        "action_id": "",
    },
    "label": {"type": "plain_text", "text": "", "emoji": True},
}

multi_users_select = {
    "type": "input",
    "element": {
        "type": "multi_users_select",
        "placeholder": {"type": "plain_text", "text": "", "emoji": True},
        "action_id": "",
    },
    "label": {"type": "plain_text", "text": "", "emoji": True},
}

date_select = {
    "type": "actions",
    "elements": [
        {
            "type": "datepicker",
            "placeholder": {
                "type": "plain_text",
                "text": "",
                "emoji": True,
            },
            "action_id": "",
        },
    ],
}
