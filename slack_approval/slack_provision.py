import json
import os
import logging

from slack_sdk.signature import SignatureVerifier
from slack_sdk import WebhookClient, WebClient, errors

from slack_approval.utils import get_header_block, get_inputs_blocks, get_status_block, get_exception_block, \
    get_buttons_blocks

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
        if self.is_callback_view(callback_id="reject_reason_modal"):
            # Some vars need to be defined so IDE dont complain
            self.channel_id = None
            self.reason = None
            self.get_private_metadata()
            self.action_id = "Reject Response"
            self.reason = self.payload["view"]["state"]["values"]["reason_block"][
                "reject_reason_input"
            ]["value"]
            return
        elif self.is_callback_view(callback_id="edit_view_modal"):
            self.channel_id = None
            self.reason = None
            self.get_private_metadata()
            self.action_id = "Modified"
            self.get_modified_fields()
            self.send_status_message(status="Pending (modified) ")
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
        self.modifiables_fields = self.capture_modifiable_fields()
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
        try:
            if self.action_id == "Approved":
                self.approved()
                self.send_status_message(status="Approved")
            elif self.action_id == "Rejected":
                self.open_reject_reason_view()
            elif self.action_id == "Not allowed":
                message = f"Same request/response user {self.user} not allowed. Prevent self approval is on."
                self.open_dialog(title="Warning", message=message)
            elif self.action_id == "Reject Response":
                self.rejected()
                message = f"Reason for rejection: {self.reason}"
                # Message to approver same request message thread
                self.send_message_to_thread(
                    message=message, thread_ts=self.ts, channel=self.channel_id
                )
                # Message to requester same request message
                self.send_message_to_thread(
                    message=message,
                    thread_ts=self.message_ts,
                    channel=self.requesters_channel,
                )
                # Update status on messages
                self.send_status_message(status="Rejected")
            elif self.action_id == "Edit":
                logger.info(f"Initial inputs = {self.inputs}")
                self.open_edit_view()
            elif self.action_id == "Modified":
                self.open_dialog("Modification", "Success")
                logger.info(f"Modified inputs = {self.inputs}")

        except Exception as e:
            self.exception = e
            logger.error(e)

    def send_message_approver(self, blocks):
        hide = self.inputs.get("hide")
        if hide:
            for field in hide:
                self.inputs.pop(field, None)
            self.inputs.pop("hide")
        try:
            # Message to approver
            slack_client = WebhookClient(self.response_url)
            response = slack_client.send(text="fallback", blocks=blocks)
            logger.info(response.status_code)
        except errors.SlackApiError as e:
            self.exception = e
            logger.error(e)
    def send_message_requester(self, blocks):
        try:
            # Message to requester
            slack_web_client = WebClient(self.token)
            response = slack_web_client.chat_update(
                channel=self.requesters_channel,
                ts=self.ts,
                text="fallback",
                blocks=blocks,
            )
            logger.info(response.status_code)
        except errors.SlackApiError as e:
            self.exception = e
            logger.error(e)
    
    def send_modified_message(self):
        hide = self.inputs.get("hide")
        if hide:
            for field in hide:
                self.inputs.pop(field, None)
            self.inputs.pop("hide")
        blocks = []
        blocks.extend(get_header_block(name=self.name))
        blocks.extend(get_inputs_blocks(inputs=self.inputs))
        blocks.extend(get_buttons_blocks(value=self.inputs.copy()))
        self.send_message_approver(blocks)
        self.send_message_requester(blocks)
    def send_status_message(self, status):
        hide = self.inputs.get("hide")
        if hide:
            for field in hide:
                self.inputs.pop(field, None)
            self.inputs.pop("hide")
        blocks = self.get_status_blocks(status)
        self.send_message_approver(blocks)
        self.send_message_requester(blocks)
        # try:
        #     # Message to approver
        #     slack_client = WebhookClient(self.response_url)
        #     response = slack_client.send(text="fallback", blocks=blocks)
        #     logger.info(response.status_code)
        # except errors.SlackApiError as e:
        #     self.exception = e
        #     logger.error(e)
        # try:
        #     # Message to requester
        #     slack_web_client = WebClient(self.token)
        #     response = slack_web_client.chat_update(
        #         channel=self.requesters_channel,
        #         ts=self.ts,
        #         text="fallback",
        #         blocks=blocks,
        #     )
        #     logger.info(response.status_code)
        # except errors.SlackApiError as e:
        #     self.exception = e
        #     logger.error(e)

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

    def is_callback_view(self, callback_id):
        return (
            self.payload.get("type", "") == "view_submission"
            and self.payload.get("view", False)
            and self.payload["view"].get("callback_id", "") == callback_id
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
        self.exception = None

    def get_status_blocks(self, status):
        blocks = []

        # blocks = [
        #     {
        #         "type": "header",
        #         "text": {
        #             "type": "plain_text",
        #             "text": self.name,
        #             "emoji": True,
        #         },
        #     },
        #     {"type": "divider"},
        # ]

        blocks.extend(get_header_block(name=self.name))

        # input_blocks = [
        #     {
        #         "type": "section",
        #         "text": {
        #             "type": "mrkdwn",
        #             "text": f"*{' '.join([s.capitalize() for s in key.split('_')])}:* {value}",
        #         },
        #     }
        #     for key, value in self.inputs.items()
        #     if key != "provision_class"
        # ]
        # blocks.extend(input_blocks)
        # blocks.append({"type": "divider"})

        blocks.extend(get_inputs_blocks(self.inputs))

        # blocks.append(
        #     {
        #         "type": "section",
        #         "text": {
        #             "type": "mrkdwn",
        #             "text": f"*Status: {status} by {self.user}*",
        #         },
        #     }
        # )

        blocks.extend(get_status_block(status=status, user=self.user))

        if self.exception:
            blocks.extend(get_exception_block(self.exception))

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

    def open_edit_view(self):
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
            "modifiables_fields": self.modifiables_fields
        }
        try:
            modal_view = {
                    "type": "modal",
                    "callback_id": "edit_view_modal",
                    "private_metadata": json.dumps(private_metadata),
                    "title": {"type": "plain_text", "text": "Edit view"},
                    "blocks": self.construct_modifiable_fields_blocks(),
                    "submit": {"type": "plain_text", "text": "Save"},
                }
            client = WebClient(self.token)
            client.views_open(
                trigger_id=self.payload["trigger_id"],
                view=modal_view
            )
            logger.info(f"modal view =   {modal_view}")
        except errors.SlackApiError as e:
            self.exception = e
            logger.error(e)

    def construct_modifiable_fields_blocks(self):
        blocks = [{
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Modifiable fields"
                    }
                }
        ]
        for modifiable_field_name, modifiable_field_value in self.modifiables_fields.items():
            field = {
                    "type": "input",
                    "block_id": f"block_id_{modifiable_field_name}",
                    "label": {
                        "type": "plain_text",
                        "text": modifiable_field_name
                    },
                    "element": {
                        "type": "plain_text_input",
                        "action_id": f"action_id_{modifiable_field_name}",
                        "placeholder": {
                            "type": "plain_text",
                            "text": modifiable_field_value
                        },
                        "initial_value":modifiable_field_value,
                        "multiline": False
                    },
                    "optional": True
                }
            blocks.append(field)
        return blocks

    def capture_modifiable_fields(self):
        modifiables_fields_names = self.inputs.get("modifiables_fields", "")
        fields = modifiables_fields_names.split(";")
        modifiables_fields = {}
        for field in fields:
            if field in self.inputs:
                modifiables_fields[field] = self.inputs[field]
        return modifiables_fields

    def get_modified_fields(self):
        available_blocks = self.payload["view"]["state"]["values"]
        for block_name, block_values in available_blocks.items():
            if "block_id_" in block_name:
                modifiable_field_name = block_name.replace("block_id_", "")
                if f"action_id_{modifiable_field_name}" in block_values:
                    self.inputs[modifiable_field_name] = block_values[f"action_id_{modifiable_field_name}"]["value"]
        # self.reason = self.payload["view"]["state"]["values"]["block_id_{modifiable_field_name}"][
        #     "action_id_{modifiable_field_name}"
        # ]["value"]

