from goblet import Goblet, goblet_entrypoint
from slack_approval.slack_request import SlackRequest

app = Goblet(function_name="request")
goblet_entrypoint(app)


@app.http()
def main(request):
    """
    """
    slack_request = SlackRequest(request, approvers_channel)
    slack_request.send_request_message()



