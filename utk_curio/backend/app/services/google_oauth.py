import requests as internal_requests
from google.oauth2 import id_token
from google.auth.transport import requests
import os
from dotenv import load_dotenv

load_dotenv()

REDIRECT_URI = os.getenv('REDIRECT_URI', 'http://localhost:8080')

if 'CLIENT_ID' in os.environ:
    CLIENT_ID = os.environ['CLIENT_ID']

if 'CLIENT_SECRET' in os.environ:
    CLIENT_SECRET = os.environ['CLIENT_SECRET']
class GoogleOAuth:
    def verify_token(self, auth_code):
        token_data = {
            'code': auth_code,
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'redirect_uri': [REDIRECT_URI],
            'grant_type': 'authorization_code',
        }
        token_url = 'https://oauth2.googleapis.com/token'
        
        token = None
        try:
            token_response = internal_requests.post(token_url, data=token_data)
            token_response_json = token_response.json()
            
            token = token_response_json.get('id_token')
        except Exception as e:
            print(e)
            return None
        
        try:
            idinfo = id_token.verify_oauth2_token(token, requests.Request(), CLIENT_ID)

            user_data = {
                'email': idinfo.get('email'),
                'name': idinfo.get('name'),
                'picture': idinfo.get('picture'),
                'uid': idinfo.get('sub'),
                'provider': 'google'
            }

            return user_data
        except ValueError as e:
            print(e)
            return None