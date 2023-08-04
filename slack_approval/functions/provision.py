import os
from goblet import Goblet, goblet_entrypoint, Response
from slack_approval.slack_provision import SlackProvision

app = Goblet(function_name="provision")
goblet_entrypoint(app)
import logging

logger = logging.getLogger("slack_provision")
logger.setLevel(logging.DEBUG)
@app.http()
def main(request):
    """
    """
    slack_provision = SlackProvision(request)
    # validate request using the signature secret
    # if not slack_provision.is_valid_signature(os.environ.get("SIGNING_SECRET")):
    #     return Response("Forbidden", status_code=403)

    if hasattr(slack_provision, "name"):
        try:
            slack_provision.__class__ = globals()[slack_provision.name.replace(" ", "")]
            slack_provision()
        except Exception as e:
            logger.info(f"Error {e}")
            return Response("OK", status_code=200)
    return Response("OK", status_code=200)

