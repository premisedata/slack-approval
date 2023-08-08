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
        self.token = os.environ.get("SLACK_BOT_TOKEN")
        self.data = request.get_data()
        self.headers = request.headers
        self.payload = json.loads(request.form["payload"])

        # Comes from the reject response modal view (data comes in private metadata)
        if self.is_reject_reason_view():
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

        # Requester can response depending on flag for prevent self approval and user-requester values
        self.prevent_self_approval = self.inputs.get("prevent_self_approval", False)
        if not self.is_allowed():
            self.action_id = "Not allowed"

    def is_valid_signature(self, signing_secret):
        """Validates the request from the Slack integration"""
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
                self.send_status_message(
                    requester_status="Approved", approver_status="Approved"
                )
            elif self.action_id == "Rejected":
                self.open_reason_modal()
            elif self.action_id == "Not allowed":
                # Send "Not allowed" message to approvers channel
                self.send_thread_message(
                    message=f"{self.user} not allowed. Prevent self approval active.",
                    thread=self.channel_id,
                )
                self.send_status_message(
                    requester_status="Pending", approver_status="Pending"
                )
            elif self.action_id == "Reject Response":
                self.rejected()
                self.send_thread_message(message=self.reason, thread=self.response_url)
                self.send_thread_message(
                    message=self.reason, thread=self.channel_id
                )
                self.send_status_message(
                    requester_status="Rejected", approver_status="Rejected"
                )

        except Exception as e:
            self.exception = e
            logger.error(e)

    def send_status_message(self, requester_status=None, approver_status=None):
        hide = self.inputs.get("hide")
        if hide:
            for field in hide:
                self.inputs.pop(field, None)
            self.inputs.pop("hide")
        blocks = self.get_base_blocks(status=approver_status)
        try:
            # Message for approver
            slack_client = WebhookClient(self.response_url)
            response = slack_client.send(text="fallback", blocks=blocks)
            logger.info(f"Message sent to response_url {self.response_url} status code {response.status_code}")
        except errors.SlackApiError as e:
            logger.error(f"Error sending status message to {self.response_url} error: {e}")
        try:
            # Message for requester
            blocks = self.get_base_blocks(status=requester_status)
            slack_web_client = WebClient(self.token)
            response = slack_web_client.chat_update(
                channel=self.requesters_channel,
                ts=self.ts,
                text="fallback",
                blocks=blocks,
            )
            logger.info(f"Message sent to requesters channel {self.requesters_channel} status code {response.status_code}")
        except errors.SlackApiError as e:
            logger.error(f"Error sending status message to {self.requesters_channel} error: {e}")

    def is_allowed(self):
        if not self.prevent_self_approval:
            return True
        try:
            slack_web_client = WebClient(self.token)
            user_info = slack_web_client.users_info(user=self.user_payload["id"])
            user_email = user_info["user"]["profile"]["email"]
            if user_email == self.requester:
                return False
            else:
                return True
        except errors.SlackApiError as e:
            logger.error(e)

    def send_not_allowed_message(self):
        blocks = self.get_base_blocks()
        try:
            client = WebClient(self.token)
            client.chat_update(
                channel=self.requesters_channel,
                ts=self.ts,
                text="fallback",
                blocks=blocks,
            )
        except errors.SlackApiError as e:
            logger.error(e)

    def open_reason_modal(self):
        private_metadata = {
            "channel_id": self.payload["channel"]["id"],
            "message_ts": self.payload["message"]["ts"],
            "name": self.inputs["provision_class"],
            "inputs": self.inputs,
            "user": self.user,
            "response_url": self.response_url,
            "requesters_channel": self.requesters_channel,
            "token": self.token,
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
            logger.error(e)

    # Reply reject reason in thread
    def send_thread_message(self, message, thread):
        try:
            client = WebClient(self.token)
            client.chat_postMessage(channel=thread, thread_ts=self.ts, text=message)
        except errors.SlackApiError as e:
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
        self.ts = metadata["message_ts"]
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
        blocks = []
        header_block = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": self.name,
                    "emoji": True,
                },
            }
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
        status_block = {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Status: {status} by {self.user}*",
                }
            }

        blocks.append(header_block)
        blocks.append({"type": "divider"})
        blocks.append(input_blocks)
        blocks.append({"type": "divider"})
        blocks.append(status_block)

        if self.exception:
            exception_block = {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Error while provisioning: {self.exception}",
                    },
                }
            blocks.append({"type": "divider"})
            blocks.append(exception_block)

        return blocks
