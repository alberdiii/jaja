import sys, os
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
    os.mkdir("output/account_creation")
except:
    pass

try:
    os.mkdir("output/items")
except:
    pass

try:
    os.mkdir("output/items/offsales")
except:
    pass

try:
    os.mkdir("output/items/onsale")
except:
    pass



threading_lock = lock

config = Util.get_config()

THREAD_AMOUNT = config["threads"]
ACCOUNTS = Util.get_accounts()

def choose_solver() -> None:
    prompt = (
        "What solver do you want to use?\n"
        "[1] RoSolve\n"
        "[2] Devious\n"
        "[3] FunBypass\n"
        "Enter 1, 2, or 3: "
    )

    while True:
        choice = input(prompt).strip()
        if choice == "":
            return
        if choice == "1":
            config["solverProvider"] = "rosolve"
            return
        if choice == "2":
            config["solverProvider"] = "devious"
            return
        if choice == "3":
            config["solverProvider"] = "funbypass"
            return
        print("Invalid choice. Please enter 1, 2, or 3.")

def main() -> None:
    choose_solver()
    threads = []

    if len(ACCOUNTS) <= THREAD_AMOUNT:
        for _ in range(len(ACCOUNTS)):
            thread = Thread(target=Roblox(threading_lock, counter, ACCOUNTS).check)
            thread.start()
            threads.append(thread)
    else:
        for _ in range(THREAD_AMOUNT):
            thread = Thread(target=Roblox(threading_lock, counter, ACCOUNTS).check)
            thread.start()
            threads.append(thread)

    for thread in threads:
        thread.join()

    Output("SUCCESS").log("Finished checking all accounts")

if __name__ == "__main__":
    main()
