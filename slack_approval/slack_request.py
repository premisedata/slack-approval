import os
import logging
import json
from slack_sdk import WebClient, errors

from slack_approval.utils import get_buttons_blocks, get_header_block, get_inputs_blocks

logger = logging.getLogger("slack_request")
logger.setLevel(logging.DEBUG)


class SlackRequest:
    def __init__(self, request):
        """requesters_channel only necessary for `pending` messages"""
        self.inputs = request.json
        self.name = self.inputs["provision_class"]
        self.value = self.inputs.copy()  # save inputs before hiding anything
        hide = self.inputs.get("hide")
        if hide:
            logger.info(f"Hidden fields: {hide}")
            for field in hide:
                self.inputs.pop(field, None)
            self.inputs.pop("hide")
        self.token = os.environ.get("SLACK_BOT_TOKEN")
        self.approvers_channel = os.environ[
            self.inputs.get("approvers_channel", "APPROVERS_CHANNEL")
        ]
        self.requesters_channel = os.environ[
            self.inputs.get("requesters_channel", "REQUESTERS_CHANNEL")
        ]

        if self.inputs.get("requesters_channel"):
            self.inputs.pop("requesters_channel")

        if self.inputs.get("approvers_channel"):
            self.inputs.pop("approvers_channel")

    def send_request_message(self):
        slack_web_client = WebClient(self.token)
        blocks = []
        blocks.extend(get_header_block(self.name))
        blocks.extend(get_inputs_blocks(self.inputs))

        # First send to requesters channel
        try:
            response = slack_web_client.chat_postMessage(
                channel=self.requesters_channel,
                text="fallback",
                blocks=blocks
                + [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Request Pending*",
                        },
                    }
                ],
            )
            # Save timestamp and requesters channel to be updated after provision
            self.value["ts"] = response.get("ts")
            self.value["requesters_channel"] = self.requesters_channel
            self.value["approvers_channel"] = self.approvers_channel
        except errors.SlackApiError as e:
            logger.error(e)
        value = json.dumps(self.value)

        blocks.extend(get_buttons_blocks(value))

        # Send to approvers channel with `approve` and `reject` buttons
        try:
            response = slack_web_client.chat_postMessage(
                channel=self.approvers_channel, text="fallback", blocks=blocks
            )
        except errors.SlackApiError as e:
            logger.error(e)
