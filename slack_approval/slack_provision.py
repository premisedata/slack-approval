import json
import logging
from slack_sdk.signature import SignatureVerifier
from slack_sdk import WebhookClient, errors

logger = logging.getLogger("slack_provision")
logger.setLevel(logging.DEBUG)


class SlackProvision:
    def __init__(self, request, requesters_channel=None):
        self.data = request.get_data()
        self.headers = request.headers
        payload = json.loads(request.form["payload"])
        action = payload["actions"][0]
        self.action_id = action["action_id"]
        self.inputs = json.loads(action["value"])
        self.name = self.inputs["provision_class"]
        self.user = " ".join(
            [s.capitalize() for s in payload["user"]["name"].split(".")]
        )
        self.response_url = payload["response_url"]
        self.requesters_channel = requesters_channel
        self.exception = None

    def is_valid_signature(self, signing_secret):
        """Validates the request from the Slack integration
        """
        logger.info(self.data)
        timestamp = self.headers["x-slack-request-timestamp"]
        signature = self.headers["x-slack-signature"]
        verifier = SignatureVerifier(signing_secret)
        return verifier.is_valid(self.data, timestamp, signature)

    def approved(self):
        raise NotImplementedError

    def rejected(self):
        raise NotImplementedError

    def __call__(self):
        try:
            if self.action_id == "Approved":
                self.approved()
            elif self.action_id == "Rejected":
                self.rejected()
        except Exception as e:
            self.exception = e
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
                "text": {"type": "mrkdwn", "text": f"*{key}:* {value}",},
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
        if self.requesters_channel:
            try:
                slack_client = WebhookClient(self.requesters_channel)
                response = slack_client.send(text="fallback", blocks=blocks)
                logger.info(response.status_code)
            except errors.SlackApiError as e:
                logger.error(e)
