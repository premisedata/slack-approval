import json
import os
import logging

from slack_sdk.signature import SignatureVerifier
from slack_sdk import WebhookClient, WebClient, errors

logger = logging.getLogger("slack_provision")
logger.setLevel(logging.DEBUG)


class SlackProvision:
    def __init__(self, request, requesters_channel=None):
        self.exception = None
        self.message_ts = None
        self.token = os.environ.get("SLACK_BOT_TOKEN")
        self.data = request.get_data()
        self.headers = request.headers
        self.payload = json.loads(request.form["payload"])

        # Comes from the reject response modal view (data comes in private metadata)
        if self.is_reject_reason_view():
            # Some vars need to be defined so IDE dont complain
            self.channel_id = None
            self.reason = None
            self.get_private_metadata()
            return

        self.user_payload = self.payload["user"]
        self.action = self.payload["actions"][0]
        self.inputs = json.loads(self.action["value"])
        self.name = self.inputs["provision_class"]
        self.response_url = self.payload["response_url"]
        self.action_id = self.action["action_id"]
        self.ts = self.inputs.pop("ts")
        self.requesters_channel = self.inputs.pop("requesters_channel")
        self.approvers_channel = self.inputs.pop("approvers_channel", None)
        self.user = self.parse_user()
        self.requester = self.inputs.get("requester", "")

        """ Requester can response depending on flag for prevent self approval and user-requester values
            Backward compatibility: prevent_self_approval deactivated """
        self.prevent_self_approval = self.inputs.get("prevent_self_approval", False)
        if not self.is_allowed():
            self.action_id = "Not allowed"

    def is_valid_signature(self, signing_secret):
        """Validates the request from the Slack integration"""
        timestamp = self.headers["x-slack-request-timestamp"]
        signature = self.headers["x-slack-signature"]
        verifier = SignatureVerifier(signing_secret)
        return verifier.is_valid(self.data, timestamp, signature)

    @staticmethod
    def approved():
        logger.info("request approved")

    @staticmethod
    def rejected():
        logger.info("request rejected")

    def __call__(self):
        status = None
        try:
            if self.action_id == "Approved":
                self.approved()
                status = "Approved"
            elif self.action_id == "Rejected":
                self.open_reject_reason_view()
                return
            elif self.action_id == "Not allowed":
                message = f"Same request/response user {self.user} not allowed. Prevent self approval is on."
                self.open_dialog(title="Warning", message=message)
                return
            elif self.action_id == "Reject Response":
                self.rejected()
                message = f"Reason for rejection: {self.reason}"
                # Message to approver same request message thread
                self.send_message_to_thread(
                    message=message, thread_ts=self.message_ts, channel=self.channel_id
                )
                # Message to requester same request message
                self.send_message_to_thread(
                    message=message,
                    thread_ts=self.ts,
                    channel=self.requesters_channel,
                )
                # Update status on messages
                status = "Rejected"


        except Exception as e:
            self.exception = e
            logger.error(e)
            status = "Error"

        self.send_status_message(status)


    def send_status_message(self, status):
        hide = self.inputs.get("hide")
        if hide:
            for field in hide:
                self.inputs.pop(field, None)
            self.inputs.pop("hide")
        blocks = self.get_base_blocks(status)
        try:
            # Message to approver
            slack_client = WebhookClient(self.response_url)
            response = slack_client.send(text="fallback", blocks=blocks)
        except errors.SlackApiError as e:
            self.exception = e
            logger.error(e)
        try:
            # Message to requester
            slack_web_client = WebClient(self.token)
            response = slack_web_client.chat_update(
                channel=self.requesters_channel,
                ts=self.ts,
                text="fallback",
                blocks=blocks,
            )
        except errors.SlackApiError as e:
            self.exception = e
            logger.error(e)

    def is_allowed(self):
        if not self.prevent_self_approval:
            return True
        try:
            slack_web_client = WebClient(self.token)
            user_info = slack_web_client.users_info(user=self.user_payload["id"])
            user_email = user_info["user"]["profile"]["email"]
            if user_email == self.requester and self.action_id == "Approved":
                return False
            else:
                return True
        except errors.SlackApiError as e:
            self.exception = e
            logger.error(e)

    def open_reject_reason_view(self):
        private_metadata = {
            "channel_id": self.payload["channel"]["id"],
            "message_ts": self.payload["message"]["ts"],
            "name": self.inputs["provision_class"],
            "inputs": self.inputs,
            "user": self.user,
            "response_url": self.response_url,
            "requesters_channel": self.requesters_channel,
            "token": self.token,
            "ts": self.ts,
        }
        try:
            client = WebClient(self.token)
            client.views_open(
                trigger_id=self.payload["trigger_id"],
                view={
                    "type": "modal",
                    "callback_id": "reject_reason_modal",
                    "private_metadata": json.dumps(private_metadata),
                    "title": {"type": "plain_text", "text": "Reject Reason"},
                    "blocks": [
                        {
                            "type": "input",
                            "block_id": "reason_block",
                            "label": {
                                "type": "plain_text",
                                "text": "Please provide a reason for rejection:",
                            },
                            "element": {
                                "type": "plain_text_input",
                                "action_id": "reject_reason_input",
                            },
                        }
                    ],
                    "submit": {"type": "plain_text", "text": "Submit"},
                },
            )
        except errors.SlackApiError as e:
            self.exception = e
            logger.error(e)

    def send_message_to_thread(self, message, thread_ts, channel):
        try:
            client = WebClient(self.token)
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=message,
            )
        except errors.SlackApiError as e:
            self.exception = e
            logger.error(e)

    def is_reject_reason_view(self):
        return (
            self.payload.get("type", "") == "view_submission"
            and self.payload.get("view", False)
            and self.payload["view"].get("callback_id", "") == "reject_reason_modal"
        )

    def parse_user(self):
        return " ".join(
            [s.capitalize() for s in self.payload["user"]["name"].split(".")]
        )

    def get_private_metadata(self):
        metadata = json.loads(self.payload["view"]["private_metadata"])
        self.channel_id = metadata["channel_id"]
        self.ts = metadata["ts"]
        self.message_ts = metadata["message_ts"]
        self.inputs = metadata["inputs"]
        self.name = self.inputs["provision_class"]
        self.user = metadata["user"]
        self.response_url = metadata["response_url"]
        self.requesters_channel = metadata["requesters_channel"]
        self.token = metadata["token"]
        self.reason = self.payload["view"]["state"]["values"]["reason_block"][
            "reject_reason_input"
        ]["value"]
        self.action_id = "Reject Response"
        self.exception = None

    def get_base_blocks(self, status):
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": self.name,
                    "emoji": True,
                },
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
        if status:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Status: {status} by {self.user}*",
                    },
                }
            )

        if self.exception:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Error while provisioning: {self.exception}",
                    },
                }
            )
        return blocks

    def open_dialog(self, title, message):
        try:
            client = WebClient(self.token)
            client.views_open(
                trigger_id=self.payload["trigger_id"],
                view={
                    "type": "modal",
                    "title": {"type": "plain_text", "text": title},
                    "close": {"type": "plain_text", "text": "Close"},
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": message,
                            },
                        },
                    ],
                },
            )
        except errors.SlackApiError as e:
            logger.error(e)
