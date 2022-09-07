import logging
import json
from slack_sdk import WebhookClient, errors

logger = logging.getLogger("slack_request")
logger.setLevel(logging.DEBUG)


class SlackRequest:
    def __init__(self, request, approvers_channel, requesters_channel=None):
        self.inputs = request.json
        self.name = self.inputs["name"]
        self.value = json.dumps(self.inputs)
        self.approvers_channel = approvers_channel
        self.requesters_channel = requesters_channel

    def send_request_message(self):
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": self.name, "emoji": True,},
            }
        ]
        input_blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"{key}: {value}",},}
            for key, value in self.inputs.items()
        ]
        blocks.extend(input_blocks)
        if self.requesters_channel:
            try:
                slack_client = WebhookClient(self.requesters_channel)
                response = slack_client.send(
                    text="fallback",
                    blocks=blocks
                    + [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": "Request Pending",},
                        }
                    ],
                )
                logger.info(response.status_code)
            except errors.SlackApiError as e:
                logger.error(e)
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "emoji": True,
                            "text": "Approve",
                        },
                        "style": "primary",
                        "action_id": "Approved",
                        "value": self.value,
                        "confirm": {
                            "title": {"type": "plain_text", "text": "Confirm",},
                            "text": {"type": "mrkdwn", "text": "Are you sure?",},
                            "confirm": {"type": "plain_text", "text": "Do it"},
                            "deny": {
                                "type": "plain_text",
                                "text": "Stop, I've changed my mind!",
                            },
                        },
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "emoji": True,
                            "text": "Reject",
                        },
                        "value": self.value,
                        "style": "danger",
                        "action_id": "Rejected",
                    },
                ],
            }
        )
        try:
            slack_client = WebhookClient(self.approvers_channel)
            response = slack_client.send(text="fallback", blocks=blocks)
            logger.info(response.status_code)
        except errors.SlackApiError as e:
            logger.error(e)
