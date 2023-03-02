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
        self.approving_team = self.inputs.get("approving_team", None)
        self.value = self.inputs # save inputs before hiding anything
        hide = self.inputs.get("hide")
        if hide:
            logger.info(f"Hidden fields: {hide}")
            for field in hide:
                self.inputs.pop(field)
            self.inputs.pop("hide")
        self.token = os.environ.get("SLACK_BOT_TOKEN")
        self.approvers_channel, self.requesters_channel = self.get_slack_channels(self.approving_team)

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
        # First send to requesters channel
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
            # Save timestamp and requesters channel to be updated after provision
            self.value["ts"] = response.get("ts")
            self.value["requesters_channel"] = self.requesters_channel
        except errors.SlackApiError as e:
            logger.error(e)
        value = json.dumps(self.value)
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
                        "value": value,
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
                        "value": value,
                        "style": "danger",
                        "action_id": "Rejected",
                    },
                ],
            }
        )
        # Send to approvers channel with `approve` and `reject` buttons
        try:
            response = slack_web_client.chat_postMessage(
                channel=self.approvers_channel, text="fallback", blocks=blocks
            )
            logger.info(response.status_code)
        except errors.SlackApiError as e:
            logger.error(e)

    def get_slack_channels(self, approving_team):
        """Get approvers and requesters channels from environment variables."""
        # try:
        if approving_team is None:
            approvers_channel = os.environ["APPROVERS_CHANNEL"]
            requesters_channel = os.environ["REQUESTERS_CHANNEL"]
        else:
            approvers_channel = os.environ[f"{approving_team.upper()}_APPROVERS_CHANNEL"]
            requesters_channel = os.environ[f"{approving_team.upper()}_REQUESTERS_CHANNEL"]
        return approvers_channel, requesters_channel
        # except KeyError as e:
        #     logger.error(f"Slack channel(s) not found: {e}")
        #     raise e
