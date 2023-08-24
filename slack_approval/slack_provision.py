import json
import os
import logging
import re
import asyncio

from slack_sdk.signature import SignatureVerifier
from slack_sdk import WebhookClient, WebClient, errors
from slack_sdk.web.async_client import AsyncWebClient

from slack_approval.utils import (
    get_header_block,
    get_inputs_blocks,
    get_status_block,
    get_exception_block,
    get_buttons_blocks,
)

logger = logging.getLogger("slack_provision")
logger.setLevel(logging.DEBUG)


class SlackProvision:
    def __init__(self, request):
        self.exception = None
        self.channel_id = None
        self.reason = None
        self.user_payload = None
        self.user = None
        self.user_id = None
        self.token = os.environ.get("SLACK_BOT_TOKEN")
        self.data = request.get_data()
        self.headers = request.headers
        self.payload = json.loads(request.form["payload"])
        # Comes from the reject response modal view (data comes in private metadata)
        if self.is_callback_view(callback_id="reject_reason_modal"):
            self.action_id = "Reject Response"
            self.get_private_metadata()
            self.reason = self.payload["view"]["state"]["values"]["reason_block"][
                "reject_reason_input"
            ]["value"]
            return
        elif self.is_callback_view(callback_id="edit_view_modal"):
            self.action_id = "Modified"
            self.get_private_metadata()
            self.get_modifications()
            return

        self.action = self.payload["actions"][0]
        self.inputs = json.loads(self.action["value"])
        self.response_url = self.payload["response_url"]
        self.action_id = self.action["action_id"]
        self.get_user_info()

        self.name = self.inputs["provision_class"]
        self.requesters_ts = self.inputs.pop("requesters_ts")
        self.approvers_ts = self.payload["container"]["message_ts"]
        self.requesters_channel = self.inputs.pop("requesters_channel")
        self.approvers_channel = self.inputs.pop("approvers_channel")
        self.requester_info = json.loads(self.inputs.get("requester_info", {}))

        self.requester = self.inputs.get("requester", "")
        self.modifiables_fields = self.get_modifiable_fields()
        """ Requester can response depending on flag for prevent self approval and user-requester values
            Backward compatibility: prevent_self_approval deactivated """
        self.prevent_self_approval = self.inputs.get("prevent_self_approval", False)
        self.inputs["modified"] = self.inputs.get("modified", False)
        if not self.is_allowed():
            self.action_id = "Not allowed"

    def __call__(self):
        mention_requester = True
        try:
            if self.action_id == "Approved":
                mention_requester = True
                self.approved()
            elif self.action_id == "Rejected":
                self.open_reject_reason_view()
                return
            elif self.action_id == "Not allowed":
                message = f"Same request/response user {self.user} not allowed. Prevent self approval is on."
                self.open_message_dialog(title="Warning", message=message)
                return
            elif self.action_id == "Reject Response":
                self.rejected()
                message = f"reason for rejection: {self.reason}"
                asyncio.run(self.send_notifications(message=message, mention_requester=True))

            elif self.action_id == "Edit":
                self.open_edit_view()
                return
            elif self.action_id == "Modified":
                self.send_modified_message()
                return

        except Exception as e:
            self.exception = e
            logger.error(e, stack_info=True, exc_info=True)
        self.send_status_message(status=self.action_id, mention_requester=mention_requester)

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


    def send_message_approver(self, blocks):
        try:
            hide = self.inputs.get("hide")
            if hide:
                for field in hide:
                    self.inputs.pop(field, None)
                self.inputs.pop("hide")

            # Message to requester
            slack_web_client = WebClient(self.token)
            response = slack_web_client.chat_update(
                channel=self.approvers_channel,
                ts=self.approvers_ts,
                blocks=blocks,
                as_user=True,
                text="fallback",
            )

        except errors.SlackApiError as e:
            self.exception = e
            logger.error(e, stack_info=True, exc_info=True)

    def send_message_requester(self, blocks):
        try:
            # Message to requester
            slack_web_client = WebClient(self.token)
            response = slack_web_client.chat_update(
                channel=self.requesters_channel,
                ts=self.requesters_ts,
                blocks=blocks,
                text="fallback",
            )
        except errors.SlackApiError as e:
            self.exception = e
            logger.error(e, stack_info=True, exc_info=True)

    def send_status_message(self, status, mention_requester=False):
        hide = self.inputs.get("hide")
        if hide:
            for field in hide:
                self.inputs.pop(field, None)
            self.inputs.pop("hide")
        blocks = self.get_message_status(status, mention_requester)
        # asyncio.run(self.send_message_approver(blocks))
        # asyncio.run(self.send_message_requester(blocks))
        asyncio.run(self.send_message_requester_approver(blocks, blocks))

    def send_message_to_thread(self, message, thread_ts, channel, mention_requester=False):
        try:
            if getattr(self, "requester_info", None) is None or "id" not in \
                    self.requester_info:
                mention_requester = False
                requester_info = None
            else:
                requester_info = self.requester_info["id"]

            if mention_requester and requester_info:
                message = f"<@{requester_info}> {message}"
            client = WebClient(self.token)
            response = client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=message,
            )
        except errors.SlackApiError as e:
            self.exception = e
            logger.error(e, stack_info=True, exc_info=True)

    def send_modified_message(self):
        hide = self.inputs.get("hide")
        if hide:
            for field in hide:
                self.inputs.pop(field, None)
            self.inputs.pop("hide")
        inputs = self.inputs.copy()
        inputs.pop("requesters_channel", None)
        inputs.pop("approvers_channel", None)
        inputs.pop("modifiables_fields", None)
        requesters_blocks = []
        requesters_blocks.extend(get_header_block(name=self.name))
        requesters_blocks.extend(get_inputs_blocks(self.inputs))
        requesters_blocks.extend(get_status_block(status="Pending. Modified ", user=self.user))


        approvers_blocks = []
        approvers_blocks.extend(get_header_block(name=self.name))
        approvers_blocks.extend(get_inputs_blocks(self.inputs))

        values = self.inputs.copy()
        values["requesters_ts"] = self.requesters_ts
        values["requesters_channel"] = self.requesters_channel
        values["approvers_channel"] = self.approvers_channel
        values["modifiables_fields"] = ";".join(list(self.modifiables_fields.keys()))
        edit_button = values.get("modifiables_fields", None) is not None and values["modifiables_fields"] != ""
        approvers_blocks.extend(get_buttons_blocks(value=json.dumps(values), edit_button=edit_button))
        asyncio.run(self.send_message_requester_approver(requesters_blocks, approvers_blocks))

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
            logger.error(e, stack_info=True, exc_info=True)

    def is_callback_view(self, callback_id):
        return (
                self.payload.get("type", "") == "view_submission"
                and self.payload.get("view", False)
                and self.payload["view"].get("callback_id", "") == callback_id
        )

    def get_user_info(self):
        self.user_payload = self.payload["user"]
        self.user = " ".join(
            [s.capitalize() for s in self.user_payload["name"].split(".")]
        )
        self.user_id = self.user_payload["id"]

    def get_private_metadata(self):
        metadata = json.loads(self.payload["view"]["private_metadata"])
        self.channel_id = metadata["channel_id"]
        self.requesters_ts = metadata["requesters_ts"]
        self.approvers_ts = metadata["approvers_ts"]
        self.inputs = metadata["inputs"]
        self.name = self.inputs["provision_class"]
        self.response_url = metadata["response_url"]
        self.requesters_channel = metadata["requesters_channel"]
        self.approvers_channel = metadata["approvers_channel"]
        self.token = metadata["token"]
        self.exception = None
        self.requester = metadata["requester"]
        self.prevent_self_approval = metadata["prevent_self_approval"]
        self.modifiables_fields = metadata["modifiables_fields"]
        self.user_payload = metadata["user_payload"]
        self.user = metadata["user"]
        self.user_payload = metadata["user_payload"]
        self.user_id = metadata["user_id"]
        self.requester_info = metadata["requester_info"]

    def get_message_status(self, status, mention_requester=False):
        blocks = []
        blocks.extend(get_header_block(name=self.name))
        blocks.extend(get_inputs_blocks(self.inputs))
        if getattr(self, "requester_info", None) is None or "id" not in \
                self.requester_info:
            mention_requester = False
            requester_info = None
        else:
            requester_info = self.requester_info["id"]
        blocks.extend(
            get_status_block(status=status, user=self.user, mention_requester=mention_requester, user_id=requester_info))
        if self.exception:
            blocks.extend(get_exception_block(self.exception))


        return blocks

    def open_message_dialog(self, title, message):
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
            logger.error(e, stack_info=True, exc_info=True)

    def open_reject_reason_view(self):
        private_metadata = self.construct_private_metadata()
        try:
            client = WebClient(self.token)
            client.views_open(
                trigger_id=self.payload["trigger_id"],
                view=self.construct_reason_modal(
                    private_metadata=json.dumps(private_metadata)
                ),
            )
        except errors.SlackApiError as e:
            self.exception = e
            logger.error(e, stack_info=True, exc_info=True)

    def open_edit_view(self):
        self.inputs["modifiables_fields"] = ";".join(
            list(self.modifiables_fields.keys())
        )
        private_metadata = self.construct_private_metadata()

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
            client.views_open(trigger_id=self.payload["trigger_id"], view=modal_view)
        except errors.SlackApiError as e:
            self.exception = e
            logger.error(e, stack_info=True, exc_info=True)

    def construct_modifiable_fields_blocks(self):
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Modify fields (empty text to remove)"}}
        ]
        for (
                modifiable_field_name,
                modifiable_field_value,
        ) in self.modifiables_fields.items():
            if isinstance(modifiable_field_value, list):
                item_number = 0
                if len(modifiable_field_value) == 0:
                    field = {
                        "type": "input",
                        "block_id": f"multivalue_block_id_{modifiable_field_name}_{item_number}",
                        "label": {"type": "plain_text", "text": modifiable_field_name},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": f"action_id_{modifiable_field_name}_{item_number}",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "Insert value (empty to remove)",
                            },
                            "initial_value": "no value",
                            "multiline": False,
                        },
                        "optional": True,
                    }
                    blocks.append(field)
                    blocks.append({"type": "divider"})
                    continue
                for valid_value in modifiable_field_value:
                    valid_value = valid_value if valid_value != "" and valid_value is not None else "no value"
                    field = {
                        "type": "input",
                        "block_id": f"multivalue_block_id_{modifiable_field_name}_{item_number}",
                        "label": {"type": "plain_text", "text": modifiable_field_name},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": f"action_id_{modifiable_field_name}_{item_number}",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "Insert value (empty to remove)",
                            },
                            "initial_value": valid_value,
                            "multiline": False,
                        },
                        "optional": True,
                    }
                    blocks.append(field)
                    item_number += 1
                blocks.append({"type": "divider"})
                continue
            valid_value = modifiable_field_value if modifiable_field_value != "" and modifiable_field_value is not None else "no value"

            field = {
                "type": "input",
                "block_id": f"block_id_{modifiable_field_name}",
                "label": {"type": "plain_text", "text": modifiable_field_name},
                "element": {
                    "type": "plain_text_input",
                    "action_id": f"action_id_{modifiable_field_name}",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Insert value (empty to remove)",
                    },
                    "initial_value": valid_value,
                    "multiline": False,
                },
                "optional": True,
            }
            blocks.append(field)
            blocks.append({"type": "divider"})
        return blocks

    def get_modifiable_fields(self):
        modifiables_fields_names = self.inputs.pop("modifiables_fields", "")
        fields = modifiables_fields_names.split(";")
        modifiables_fields = {}
        for field in fields:
            if field in self.inputs:
                modifiables_fields[field] = self.inputs[field]
        return modifiables_fields

    def get_modifications(self):
        available_blocks = self.payload["view"]["state"]["values"]
        blocks = {
            block_name.replace("block_id_", ""): block_values
            for block_name, block_values in available_blocks.items()
            if "block_id_" in block_name and not "multivalue_block_id_" in block_name
        }
        blocks = {
            block_name: block_values
            for block_name, block_values in blocks.items()
            if f"action_id_{block_name}" in block_values
        }
        for block_name, block_values in blocks.items():
            actual_value = self.inputs[block_name]
            new_value = block_values[f"action_id_{block_name}"]["value"]
            if actual_value != new_value:
                self.inputs["modified"] = True
                self.inputs[block_name] = new_value

        blocks = {
            block_name.replace("multivalue_block_id_", ""): block_values
            for block_name, block_values in available_blocks.items()
            if "multivalue_block_id_" in block_name
        }

        for block_name, block_values in blocks.items():
            self.inputs[re.sub(r"_\d+$", '', block_name)] = []

        blocks = {
            block_name: block_values
            for block_name, block_values in blocks.items()
            if f"action_id_{block_name}" in block_values
        }

        for block_name, block_values in blocks.items():
            new_value = block_values[f"action_id_{block_name}"]["value"]
            if new_value is None or new_value == "":
                continue
            self.inputs["modified"] = True
            self.inputs[re.sub(r"_\d+$", '', block_name)].append(new_value)

    @staticmethod
    def construct_reason_modal(private_metadata):
        return {
            "type": "modal",
            "callback_id": "reject_reason_modal",
            "private_metadata": private_metadata,
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
        }

    def construct_private_metadata(self):
        return {
            "channel_id": self.payload["channel"]["id"],
            "approvers_ts": self.payload["message"]["ts"],
            "name": self.inputs["provision_class"],
            "inputs": self.inputs,
            "user_payload": self.user_payload,
            "user": self.user,
            "user_id": self.user_id,
            "response_url": self.response_url,
            "requesters_channel": self.requesters_channel,
            "token": self.token,
            "requesters_ts": self.requesters_ts,
            "approvers_channel": self.approvers_channel,
            "requester": self.requester,
            "prevent_self_approval": self.prevent_self_approval,
            "modifiables_fields": self.modifiables_fields,
            "requester_info": self.requester_info
        }

    async def send_notifications(self, message, mention_requester):
        self.send_message_to_thread(message=message,
                                                thread_ts=self.requesters_ts,
                                                channel=self.requesters_channel,
                                                mention_requester=True)

        self.send_message_to_thread(message=message,
                                                thread_ts=self.approvers_ts,
                                                channel=self.channel_id,
                                                mention_requester=True)

    async def send_message_requester_approver(self, requesters_blocks, approvers_blocks):
        self.send_message_requester(requesters_blocks)
        self.send_message_approver(approvers_blocks)
