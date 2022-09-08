import os
from goblet import Goblet, goblet_entrypoint, Response
from slack_approval.slack_provision import SlackProvision

app = Goblet(function_name="provision")
goblet_entrypoint(app)

@app.http()
def main(request):
    """
    """
    slack_provision = SlackProvision(request, os.environ.get("REQUESTER_CHANNEL_HOOK"))
    # validate request using the signature secret
    if not slack_provision.is_valid_signature(os.environ.get("SIGNING_SECRET")):
        return Response("Forbidden", status_code=403)
    
    slack_provision.__class__ = globals()[slack_provision.name.replace(" ", "")]
    slack_provision()