import time
import uuid
from time import sleep

from curl_cffi import requests
from util import Util


def _get_config_values():
    config = Util.get_config()
    public_key = config.get("publicKey")
    solver_provider = config.get("solverProvider", "rosolve")
    solvers_keys = config.get("Solvers_Keys", {})

    rosolve_config = solvers_keys.get("RoSolve", {})
    devious_config = solvers_keys.get("Devious", {})
    funbypass_config = solvers_keys.get("FunBypass", {})

    rosolve_key = rosolve_config.get("RoSolve")
    devious_key = devious_config.get("Devious")
    funbypass_key = funbypass_config.get("FunBypass")

    if solver_provider is None:
        solver_provider = "rosolve"

    if solver_provider.lower() == "devious":
        solver_key = devious_key or config.get("solverKey")
    elif solver_provider.lower() == "funbypass":
        solver_key = funbypass_key or config.get("solverKey")
    else:
        solver_key = rosolve_key or config.get("solverKey")

    return solver_key, public_key, solver_provider.lower()


def _get_token_rosolve(roblox_session: requests.Session, blob, proxy):
    session = requests.Session()

    challengeInfo = {
        "publicKey": "476068BF-9607-4799-B53D-966BE98E2B81",
        "site": "https://www.roblox.com/",
        "surl": "https://arkoselabs.roblox.com",
        "capiMode": "inline",
        "styleTheme": "default",
        "languageEnabled": False,
        "jsfEnabled": False,
        "extraData": {"blob": blob},
        "ancestorOrigins": ["https://www.roblox.com"],
        "treeIndex": [1],
        "treeStructure": "[[],[]]",
        "locationHref": "https://www.roblox.com/arkose/iframe",
        "documentReferrer": "https://www.roblox.com/login",
    }

    browserInfo = {
        "Sec-Ch-Ua": roblox_session.headers.get("sec-ch-ua", ""),
        "User-Agent": roblox_session.headers.get("user-agent", ""),
        "Mobile": False,
    }

    solver_key, _, _ = _get_config_values()

    payload = {
        "key": solver_key,
        "challengeInfo": challengeInfo,
        "browserInfo": browserInfo,
        "proxy": proxy,
    }

    response = session.post(
        "https://rosolve.pro/createTask", json=payload, timeout=120
    ).json()

    task_id = response.get("taskId")
    if task_id is None:
        raise ValueError(f"Failed to get taskId, reason: {response.get('error')}")

    counter = 0
    while counter < 60:
        sleep(1)

        result = session.post(
            "https://rosolve.pro/taskResult",
            json={"key": solver_key, "taskId": task_id},
        ).json()

        if result["status"] == "completed":
            return result["result"]["solution"]
        if result["status"] == "failed":
            return None

        counter += 1

    return None


def _get_token_devious(roblox_session: requests.Session, blob, proxy, cookies):
    solver_key, public_key, _ = _get_config_values()

    payload = {
        "api_key": solver_key,
        "proxy": proxy,
        "blob_exchange": blob,
        "public_key": public_key,
        "cookies": (
            f"{cookies}; RBXPaymentsFlowContext={uuid.uuid4()},; "
            "RBXcb=RBXViralAcquisition%3Dtrue%26RBXSource%3Dtrue%26GoogleAnalytics%3Dtrue"
        ),
    }

    while True:
        response = requests.post(
            "https://api.devioussolver.com/solve", json=payload, timeout=120
        )
        response_text = response.text

        if "Currently On Maintenance" in response_text or "error code" in response_text:
            time.sleep(30)
            continue
        if "Request timeout" in response_text or "Couldn't respond after 30s" in response_text:
            continue
        if "Server Error" in response_text:
            continue

        if any(
            err in response_text
            for err in [
                "Invalid API key",
                "Max solves reached",
                "Add Proxy",
                "Add Public Key",
                "Please use the new version",
                "Currently not supported",
                "Low quality IP score",
                "Do not use rotating",
                "Voltproxy",
            ]
        ):
            return None

        break

    solution = response.json()
    return solution.get("token")


def _get_token_funbypass(roblox_session: requests.Session, blob, proxy, cookies):
    solver_key, _, _ = _get_config_values()
    session = requests.Session()
    user_agent = roblox_session.headers.get("user-agent")

    task = {
        "type": "FunCaptchaTask" if proxy else "FunCaptchaTaskProxyless",
        "websiteURL": "https://www.roblox.com/",
        "websitePublicKey": "476068BF-9607-4799-B53D-966BE98E2B81",
        "websiteSubdomain": "roblox.com",
        "data": {"blob": blob},
        "headers": {"cookie": cookies},
    }

    if user_agent:
        task["userAgent"] = user_agent

    if proxy:
        task["proxy"] = proxy

    response = session.post(
        "https://api.funbypass.com/createTask",
        json={"clientKey": solver_key, "task": task},
        timeout=60,
    ).json()

    if response.get("errorId", 0) != 0:
        return None

    task_id = response.get("taskId")
    if task_id is None:
        return None

    counter = 0
    while counter < 120:
        sleep(1)

        result = session.post(
            "https://api.funbypass.com/getTaskResult",
            json={"clientKey": solver_key, "taskId": task_id},
            timeout=30,
        ).json()

        if "status" not in result:
            result = session.get(
                f"https://api.funbypass.com/getTaskResult/{task_id}",
                timeout=30,
            ).json()

        if result.get("status") == "ready":
            solution = result.get("solution")
            if isinstance(solution, dict) and "token" in solution:
                return solution["token"]
            if isinstance(solution, str):
                return solution
            return None

        if result.get("status") == "failure":
            return None

        counter += 1

    return None


def get_token(roblox_session: requests.Session, blob, proxy, cookies=""):
    _, _, solver_provider = _get_config_values()

    if solver_provider == "devious":
        return _get_token_devious(roblox_session, blob, proxy, cookies)
    if solver_provider == "rosolve":
        return _get_token_rosolve(roblox_session, blob, proxy)
    if solver_provider == "funbypass":
        return _get_token_funbypass(roblox_session, blob, proxy, cookies)

    raise ValueError(f"Unknown solverProvider: {solver_provider}")
