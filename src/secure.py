from util import Util
from output import Output

config = Util.get_config()
DEBUG = config.get("debug", False)

class Secure:
    @staticmethod
    def change_password(session, new_password, old_password, sec_auth_intent):
        DEBUG and Output("INFO").log("Change_Password")
        payload = {
            "currentPassword": old_password,
            "newPassword": new_password,
            "secureAuthenticationIntent": sec_auth_intent
        }

        response = session.post("https://auth.roblox.com/v2/user/passwords/change", json=payload)

        if response.status_code != 200 or ".ROBLOSECURITY" not in response.cookies:
            raise Exception(f"Failed to change password {response.status_code}, {response.text}")

        return True, response.cookies.get(".ROBLOSECURITY")
