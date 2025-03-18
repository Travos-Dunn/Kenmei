# kenmei.py
import os
import json
import requests
import uuid
from datetime import datetime
from typing import Any

session = requests.Session()

def get_config() -> dict[str, str]:
    """Returns API keys and URL for Kenmei and Pushover."""
    return {
        "kenmei_login_url": "https://api.kenmei.co/auth/sessions",
        "kenmei_manga_url": "https://api.kenmei.co/api/v2/manga_entries?page=1&status=1",
        "kenmei_auth_key": "",
        "pushover_acc_key": "",
        "pushover_app_key": "",
    }

def generate_headers() -> dict[str, str]:
    """Generates the necessary headers for requests."""
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Content-Type": "application/json",
        "Origin": "https://www.kenmei.co",
        "Referer": "https://www.kenmei.co/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "X-Forwarded-For": "149.106.126.96",
        "sentry-trace": f"{uuid.uuid4().hex}-{uuid.uuid4().hex}-1"
    }

def fetch_auth_key(login_url: str, email: str, password: str) -> str:
    """Fetches the authentication key from the login API."""
    headers = generate_headers()
    data = {"user": {"login": email, "password": password, "remember_me": False}}
    response = session.post(login_url, headers=headers, json=data)

    if response.status_code == 200:
        return response.json().get("access")
    else:
        print(f"Login failed: {response.status_code}")
        return None

def fetch_kenmei_data(kenmei_url: str, kenmei_key: str) -> Any:
    """Fetches manga data from Kenmei API."""
    session.headers.update({"Authorization": f"Bearer {kenmei_key}"})
    
    try:
        response = session.get(kenmei_url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Failed to fetch Kenmei data: {e}")
        return None

def save_data(filename: str, data: Any) -> None:
    """Saves data to a file in JSON format to same directory as script."""
    try:
        directory = os.path.dirname(os.path.abspath(__file__))
        filepath = os.path.join(directory, filename)
        with open(filepath, "w") as file:
            json.dump(data, file, indent=4)
    except IOError as e:
        print(f"Failed to save {filename}: {e}")

def load_unread_data(filename: str = "unread.json") -> dict[str, str]:
    """Loads unread manga data from a file, returning an empty dictionary if the file is missing or invalid."""
    try:
        with open(filename, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def push_notification(pushover_data: dict[str, str], title: str, latest: str) -> None:
    """Sends a notification using Pushover."""
    pushover_data["message"] = f"{title} | Ch. {latest} released!"
    requests.post("https://api.pushover.net/1/messages.json", data=pushover_data)
    
    # DEBUG
    # print(f"{title} | Ch. {latest} released!")

def process_manga_entries(kenmei_data: dict[str, Any], unread_data: dict[str, str], pushover_data: dict[str, str]) -> None:
    """Process manga entires, updating unread data and sending notifications if needed."""
    entries = kenmei_data.get("entries", [])
    for entry in entries:
        attributes = entry.get("attributes", {})
        if not attributes:
            print(f"Failed to retrieve attributes for {entry.get('id')}")
            continue

        title = attributes.get("title")
        unread = attributes.get("unread")
        latest = attributes.get("latestChapter", {}).get("chapter")
        latest = int(latest) if isinstance(latest, (float, int)) and latest == round(latest) else latest

        if not (title or latest):
            print(f"Missing title or latest chapter info for {entry.get('id')}")
            continue
        
        if unread:
            if unread_data.get(title) != latest:
                unread_data[title] = latest
                push_notification(pushover_data, title, latest)
        else:
            unread_data.pop(title, None)

def main():
    """Main execution function."""
    print(f"Script last ran at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    email = os.getenv("KENMEI_EMAIL")
    password = os.getenv("KENMEI_PASSWORD")
    pushover_acc_key = os.getenv("PUSHOVER_ACC_KEY")
    pushover_app_key = os.getenv("PUSHOVER_APP_KEY")

    if not all([email, password, pushover_acc_key, pushover_app_key]):
        print("Missing environment variables.")
        return

    config = get_config()
    config["pushover_acc_key"] = pushover_acc_key
    config["pushover_app_key"] = pushover_app_key

    pushover_data = {
        "token": config["pushover_app_key"],
        "user": config["pushover_acc_key"],
        "message": ""
    }

    auth_key = fetch_auth_key(config["kenmei_login_url"], email, password)
    if not auth_key:
        print("Failed to collect authentication key.")
        return
    config["kenmei_auth_key"] = auth_key

    kenmei_data = fetch_kenmei_data(config["kenmei_manga_url"], config["kenmei_auth_key"])
    if not kenmei_data:
        print(f"Failed to load Kenmei data.")
        return

    unread_data = load_unread_data()
    process_manga_entries(kenmei_data, unread_data, pushover_data)

    save_data("unread.json", unread_data)

if __name__ == "__main__":
    main()
