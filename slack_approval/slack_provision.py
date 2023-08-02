import json
import os
import logging
from slack_sdk.signature import SignatureVerifier
from slack_sdk import WebhookClient, WebClient, errors

logger = logging.getLogger("slack_provision")
logger.setLevel(logging.DEBUG)


class SlackProvision:
    def __init__(self, request, requesters_channel=None):
        self.token = os.environ.get("SLACK_BOT_TOKEN")
        self.data = request.get_data()
        self.headers = request.headers
        payload = json.loads(request.form["payload"])
        action = payload["actions"][0]
        self.action_id = action["action_id"]
        self.inputs = json.loads(action["value"])
        self.ts = self.inputs.pop("ts")
        self.requesters_channel = self.inputs.pop("requesters_channel")
        self.approvers_channel = self.inputs.pop("approvers_channel", None)
        self.name = self.inputs["provision_class"]
        self.user = " ".join(
            [s.capitalize() for s in payload["user"]["name"].split(".")]
        )
        self.response_url = payload["response_url"]
        self.exception = None
        self.prevent_self_approval = self.inputs.get("prevent_self_approval", False)

        self.user_payload = payload["user"]
        self.requester = self.inputs["requester"] if "requester" in self.inputs else ""

        logger.info(payload)
        # Requester can response depending on flag for prevent self approval and user-requester values
        if not self.can_response():
            self.action_id = "Not allowed"

    def is_valid_signature(self, signing_secret):
        """Validates the request from the Slack integration
        """
        timestamp = self.headers["x-slack-request-timestamp"]
        signature = self.headers["x-slack-signature"]
        verifier = SignatureVerifier(signing_secret)
        return verifier.is_valid(self.data, timestamp, signature)

    def approved(self):
        logger.info("request approved")

    def rejected(self):
        logger.info("request rejected")

    def __call__(self):

        try:
            if self.action_id == "Approved":
                self.approved()
            elif self.action_id == "Rejected":
                self.rejected()
            elif self.action_id == "Not allowed":
                client = WebClient(self.token)
                response = client.chat_postMessage(
                    channel=self.requesters_channel,
                    thread_ts=self.ts,
                    text="Hello from your app! :tada:"
                )
                logger.info(f"Response not allowed for user {self.user}")
                return

        except Exception as e:
            self.exception = e

        hide = self.inputs.get("hide")
        if hide:
            for field in hide:
                self.inputs.pop(field, None)
            self.inputs.pop("hide")
        self.send_status_message()

    def send_status_message(self):
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
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Status: {self.action_id} by {self.user}*",
                },
            }
        )
        if self.exception:
            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Error while provisioning: {self.exception}",
                    },
                }
            )
        try:
            slack_client = WebhookClient(self.response_url)
            response = slack_client.send(text="fallback", blocks=blocks)
            logger.info(response.status_code)
        except errors.SlackApiError as e:
            logger.error(e)
        try:
            slack_web_client = WebClient(self.token)
            response = slack_web_client.chat_update(
                channel=self.requesters_channel,
                ts=self.ts,
                text="fallback",
                blocks=blocks,
            )
            logger.info(response.status_code)
        except errors.SlackApiError as e:
            logger.error(e)

    def can_response(self):
        if not self.prevent_self_approval:
            return True
        try:
            slack_web_client = WebClient(self.token)
            logger.info(self.user_payload["id"])
            user_info = slack_web_client.users_info(user=self.user_payload["id"])
            logger.info(user_info)
            user_email = user_info["user"]["profile"]["email"]
            logger.info(f"user_info = {user_info}")
            logger.info(f"user_email = {user_email} requester = {self.requester}")
            if user_email == self.requester:
                return False
            else:
                return True
        except errors.SlackApiError as e:
            logger.error(e)
