import os
from goblet import Goblet, goblet_entrypoint
from slack_approval.slack_request import SlackRequest

app = Goblet(function_name="request")
goblet_entrypoint(app)


@app.http()
def main(request):
    """Forwards requests to slack
    """
    slack_request = SlackRequest(request, os.environ.get("APPROVERS_CHANNEL_HOOK"), os.environ.get("REQUESTER_CHANNEL_HOOK"))
    slack_request.send_request_message()
