import json
import logging
from slack_sdk.signature import SignatureVerifier
from slack_sdk import WebhookClient, errors

logger = logging.getLogger("slack_provision")
logger.setLevel(logging.DEBUG)

class SlackProvision:
    def __init__(self, request, requesters_channel=None):
        self.request = request
        payload = json.loads(request.form["payload"])
        logger.info(vars(request))
        logger.info(request.form)
        logger.info(payload)
        logger.info(request.data)
        logger.info(request.json)
        action = payload["actions"][0]
        self.action_id = action["action_id"]
        self.inputs = json.loads(action["value"])
        self.name = self.inputs["provision_class"]
        self.user = ' '.join(payload["user"]["name"].split('.'))
        self.response_url = payload["response_url"]
        self.requesters_channel = requesters_channel

    def is_valid_signature(self, signing_secret):
        """Validates the request from the Slack integration
        """
        headers = self.request.headers
        data = self.request.get_data()
        logger.info(data)
        timestamp = headers["x-slack-request-timestamp"]
        signature = headers["x-slack-signature"]
        logger.info(timestamp, signature)
        verifier = SignatureVerifier(signing_secret)
        return verifier.is_valid(data, timestamp, signature)

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
            }
        ]
        input_blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"{key}: {value}",},}
            for key, value in self.inputs.items() if key != "provision_class"
        ]
        blocks.extend(input_blocks)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"Status: {self.action_id} by {self.user}",},})
        if self.exception:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"Error while provisioning: {self.exception}",},})
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