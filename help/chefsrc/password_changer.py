from primp import Client
from output import Output


class PasswordChanger:
    @staticmethod
    def change_password_request(session: Client, new_password: str, old_password: str, sec_auth_intent: dict) -> str:
        payload = {
            "currentPassword": old_password,
            "newPassword": new_password,
            "secureAuthenticationIntent": sec_auth_intent
        }

        response = session.post(
            "https://auth.roblox.com/v2/user/passwords/change",
            json=payload
        )

        csrf = response.headers.get("x-csrf-token")

        if csrf:
            session.headers = {
                **session.headers,
                "x-csrf-token": csrf
            }

            response = session.post(
                "https://auth.roblox.com/v2/user/passwords/change",
                json=payload
            )

        if response.status_code != 200 or ".ROBLOSECURITY" not in response.cookies:
            raise ValueError(f"Failed to change password {response.status_code}, {response.text}")

        return response.cookies.get(".ROBLOSECURITY")

    @staticmethod
    def change_password(session: Client, new_password: str, old_password: str, sec_auth_intent: dict) -> str:
        if not sec_auth_intent:
            raise ValueError("Missing secureAuthenticationIntent for password change")

        Output("INFO").log("Attempting password change")
        new_cookie = PasswordChanger.change_password_request(
            session,
            new_password,
            old_password,
            sec_auth_intent
        )
        Output("SUCCESS").log("Password changed successfully")
        return new_cookie