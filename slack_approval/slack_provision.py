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
        self.payload = json.loads(request.form["payload"])
        if self.from_reject_response():
            logger.info(f"Reject response. Payload = {self.payload}")
            self.reject_with_reason()
            # self.reject_with_reason()
            return
        self.user_payload = self.payload["user"]
        self.action = self.payload["actions"][0]
        self.inputs = json.loads(self.action["value"])
        self.name = self.inputs["provision_class"]
        self.response_url = self.payload["response_url"]
        self.action_id = self.action["action_id"]
        self.ts = self.inputs.pop("ts")
        self.requesters_channel = self.inputs.pop("requesters_channel")
        logger.info(f"Approve or Reject or Not Allowd action_id payload = {self.payload}")
        self.approvers_channel = self.inputs.pop("approvers_channel", None)
        self.user = " ".join(
            [s.capitalize() for s in self.payload["user"]["name"].split(".")]
        )

        self.exception = None
        self.prevent_self_approval = self.inputs.get("prevent_self_approval", False)
        self.requester = self.inputs["requester"] if "requester" in self.inputs else ""

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
                self.open_reject_reason_modal()
                return
                # self.rejected()
            elif self.action_id == "Not allowed":
                self.send_not_allowed_message()
                logger.info(f"Response not allowed for user {self.user}")
                return
            else:
                logger.info(f"Action not found called by {self.user}")
                return

        except Exception as e:
            self.exception = e
            logger.error(e)

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

    def send_not_allowed_message(self):
        try:
            client = WebClient(self.token)
            client.chat_postMessage(
                channel=self.requesters_channel,
                thread_ts=self.ts,
                text=f"User {self.user} not allowed to response (same user as requester). Prevent self approval activated."
            )
        except errors.SlackApiError as e:
            logger.error(e)

    def open_reject_reason_modal(self):
        client = WebClient(self.token)
        client.views_open(
            trigger_id=self.payload['trigger_id'],
            view={
                "type": "modal",
                "callback_id": "reject_reason_modal",
                "private_metadata": json.dumps({"channel_id": self.payload['channel']['id'], "message_ts": self.payload['message']['ts']}),
                "title": {
                    "type": "plain_text",
                    "text": "Deny Reason"
                },
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "reason_block",
                        "label": {
                            "type": "plain_text",
                            "text": "Please provide a reason for deny:"
                        },
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "reject_reason_input"
                        }
                    }
                ],
                "submit": {
                    "type": "plain_text",
                    "text": "Submit"
                }
            }
        )

    def reject_with_reason(self):
        logger.info("reject_with_reason")
        try:
            metadata = json.loads(self.payload['view']['private_metadata'])
            channel_id = metadata["channel_id"]
            ts = metadata["message_ts"]
            reason = self.payload['view']['state']['values']['reason_block']['reject_reason_input']['value']
            client = WebClient(self.token)
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=ts,
                text=f"Reason for denial: {reason}"
            )
        except errors.SlackApiError as e:
            logger.error(e)
        self.action_id = "Rejected with reason"
        self.send_status_message()
        self.rejected()

    def from_reject_response(self):
        return self.payload["type"] == "view_submission" and "view" in self.payload and "callback_id" in self.payload["view"] and self.payload["view"]["callback_id"] == "reject_reason_modal"

    def load_payload(self):
        self.name = self.inputs["provision_class"]
