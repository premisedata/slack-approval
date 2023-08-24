
def get_header_block(name):
    return [{
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": name,
            "emoji": True,
        },
    },
    {"type": "divider"}]


def get_inputs_blocks(inputs):
    input_block : list = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{' '.join([s.capitalize() for s in key.split('_')])}:* {value}",
            },
        }
        for key, value in inputs.items()
        if key != "provision_class" and key != "modifiables_fields" and key != "modified" and key != "requester_info"
    ]
    input_block.append({"type": "divider"})
    return input_block


def get_status_block(status, user, mention_requester=False, user_id=None):
    mention = f"<@{user_id}>" if mention_requester and user_id is not None else ""
    return [{
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Status: {status} by {user}* {mention}"
            }
        }]

def get_exception_block(exception):
    return [
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Error while provisioning: {exception}",
            },
        }
    ]

def get_accepted_button(value):
    return {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "emoji": True,
                            "text": "Approve",
                        },
                        "style": "primary",
                        "action_id": "Approved",
                        "value": value,
                        "confirm": {
                            "title": {
                                "type": "plain_text",
                                "text": "Confirm",
                            },
                            "text": {
                                "type": "mrkdwn",
                                "text": "Are you sure?",
                            },
                            "confirm": {"type": "plain_text", "text": "Do it"},
                            "deny": {
                                "type": "plain_text",
                                "text": "Stop, I've changed my mind!",
                            },
                        },
                    }

def get_rejected_button(value):
    return {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "emoji": True,
                            "text": "Reject",
                        },
                        "value": value,
                        "style": "danger",
                        "action_id": "Rejected",
                    }

def get_edit_button(value):
    return {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "emoji": True,
                            "text": "Edit",
                        },
                        "value": value,
                        "action_id": "Edit",
                    }
def get_buttons_blocks(value, edit_button = False):
    buttons = [get_accepted_button(value), get_rejected_button(value)]
    if edit_button:
        buttons.append(get_edit_button(value))
    return [{
                "type": "actions",
                "elements": buttons,
            }]
