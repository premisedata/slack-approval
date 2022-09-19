import logging
import json
from slack_sdk import WebhookClient, errors

logger = logging.getLogger("slack_request")
logger.setLevel(logging.DEBUG)


class SlackRequest:
    def __init__(self, request, approvers_channel, requesters_channel=None):
        """requesters_channel only necessary for `pending` messages
        """
        self.inputs = request.json
        self.name = self.inputs["provision_class"]
        self.value = json.dumps(self.inputs)
        hide = self.inputs.get("hide")
        if hide:
            for field in hide:
                self.inputs.pop(field)
            self.inputs.pop("hide")
        self.approvers_channel = approvers_channel
        self.requesters_channel = requesters_channel

    def send_request_message(self):
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": self.name, "emoji": True,},
            },
            {"type": "divider"},
        ]
        input_blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{' '.join([s.capitalize() for s in key.split('_')])}:* {value}",
                },
            }
            for key, value in self.inputs.items()
            if key != "provision_class"
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
                            "text": {"type": "mrkdwn", "text": "*Request Pending*",},
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
