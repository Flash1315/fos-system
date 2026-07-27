import pickle
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive"]

flow = InstalledAppFlow.from_client_secrets_file("oauth_credentials.json", SCOPES)
creds = flow.run_local_server(port=8080)

with open("token.pickle", "wb") as f:
    pickle.dump(creds, f)
print("token.pickle saved!")
