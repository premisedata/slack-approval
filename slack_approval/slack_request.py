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

        if "requester" in self.inputs:
            try:
                slack_web_client = WebClient(self.token)
                user_response = slack_web_client.users_lookupByEmail(email=self.inputs.get("requester"))

                if user_response and user_response.status_code == 200:
                    self.value["requester_info"] = json.dumps({"id":user_response["user"]["id"]})
                    logger.info(self.value["requester_info"])
            except errors.SlackApiError as e:
                logger.error(e, stack_info=True, exc_info=True)




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
            self.value["requesters_ts"] = response.get("ts")
            self.value["requesters_channel"] = self.requesters_channel
            self.value["approvers_channel"] = self.approvers_channel
        except errors.SlackApiError as e:
            logger.error(e, stack_info=True, exc_info=True)
        value = json.dumps(self.value)

        edit_button = self.inputs.get("modifiables_fields", None) is not None and self.inputs.get("modifiables_fields") != ""
        blocks.extend(get_buttons_blocks(value, edit_button = edit_button))

        # Send to approvers channel with `approve` and `reject` buttons
        try:
            slack_web_client.chat_postMessage(
                channel=self.approvers_channel, text="fallback", blocks=blocks
            )
        except errors.SlackApiError as e:
            logger.error(e, stack_info=True, exc_info=True)
