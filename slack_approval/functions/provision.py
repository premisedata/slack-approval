import os
from goblet import Goblet, goblet_entrypoint, Response
from google.cloud import secretmanager
from slack_approval.slack_provision import SlackProvision

app = Goblet(function_name="provision")
goblet_entrypoint(app)


@app.http()
def main(request):
    """
    """
    # get slack signature secret from secret manager
    slack_provision = SlackProvision(request, requesters_channel)
    secret_client = secretmanager.SecretManagerServiceClient()
    signing_secret = secret_client.access_secret_version(
        request={"name": os.environ.get("SIGNATURE_SECRET_ID")}
    ).payload.data.decode("UTF-8")
    # validate request using the signature secret
    if not slack_provision.is_valid_signature(signing_secret):
        return Response("Forbidden", status_code=403)