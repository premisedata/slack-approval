import os
import logging
import json
from slack_sdk import WebClient, errors

logger = logging.getLogger("slack_request")
logger.setLevel(logging.DEBUG)


class SlackRequest:
    def __init__(self, request):
        """requesters_channel only necessary for `pending` messages
        """
        self.inputs = request.json
        self.name = self.inputs["provision_class"]
        self.value = json.dumps(self.inputs)
        hide = self.inputs.get("hide")
        if hide:
            logger.info(f"Hidden fields: {hide}")
            for field in hide:
                self.inputs.pop(field)
            self.inputs.pop("hide")
        self.token = os.environ.get("SLACK_BOT_TOKEN")
        self.approvers_channel = os.environ["APPROVERS_CHANNEL"]
        self.requesters_channel = os.environ.get("REQUESTERS_CHANNEL")

    def send_request_message(self):
        slack_web_client = WebClient(self.token)
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
                response = slack_web_client.chat_postMessage(
                    channel=self.requesters_channel,
                    text="fallback",
                    blocks=blocks
                    + [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": "*Request Pending*",},
                        }
                    ],
                )
                self.value["ts"] = response.get("ts")
                self.value["requesters_channel"] = self.requesters_channel
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
            response = slack_web_client.chat_postMessage(
                channel=self.approvers_channel, text="fallback", blocks=blocks
            )
            logger.info(response.status_code)
        except errors.SlackApiError as e:
            logger.error(e)
