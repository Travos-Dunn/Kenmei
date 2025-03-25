# kenmei.py
import os
import json
import requests
import uuid
import logging
from typing import Any

logging.basicConfig(level=logging.INFO)

class KenmeiClient:
    """
    A client for interacting with the Kenmei API to retrieve manga entries and send notifications via Pushover.

    :param email: The email address used for Kenmei login.
    :type email: str

    :param password: The password for Kenmei login.
    :type password: str

    :param pushover_app_key: The application key for Pushover notifications.
    :type pushover_app_key: str

    :param pushover_acc_key: The user key for Pushover notifications.
    :type pushover_acc_key: str
    """
    BASE_URLS = {
        "login": "https://api.kenmei.co/auth/sessions",
        "manga": "https://api.kenmei.co/api/v2/manga_entries?page=1&status=1"
    }

    def __init__(self, email: str, password: str, pushover_app_key: str, pushover_acc_key: str):
        self.session = requests.Session()
        self.email = email
        self.password = password
        self.pushover_data = {
            "token": pushover_app_key,
            "user": pushover_acc_key,
            "message": ""
        }
        self.auth_key = self.authenticate()

    @staticmethod
    def generate_headers() -> dict[str, str]:
        """
        Generates HTTP headers for making requests to the Kenmei API.
        
        :return: A dictionary of HTTP headers.
        :rtype: dict[str, str]
        """
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

    def authenticate(self) -> str | None:
        """
        Authenticates the user and retrieves an access token.

        :return: The authentication token if successful, otherwise None.
        :rtype: str | None
        """
        response = self.session.post(
            self.BASE_URLS["login"],
            headers=self.generate_headers(),
            json={"user": {"login": self.email, "password": self.password, "remember_me": False}}
        )

        if response.status_code == 200:
            return response.json().get("access")

        logging.error(f"Login failed: {response.status_code}")
        return None

    def fetch_manga_data(self) -> dict[str, Any]:
        """
        Fetch manga entries from Kenmei API.

        :return: A dictionary containing manga data.
        :rtype: dict[str, Any]
        """
        if not self.auth_key:
            logging.error("Authentication key is missing.")
            return {}
        
        self.session.headers.update({"Authorization": f"Bearer {self.auth_key}"})
        
        try:
            response = self.session.get(self.BASE_URLS["manga"])
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"Failed to fetch Kenmei data: {e}")
            return {}

    def process_manga_entries(self, kenmei_data: dict[str, Any], unread_data: dict[str, str]) -> None:
        """
        Processes manga entries and sends notifications for new chapters.

        :param kenmei_data: The retrieved manga data.
        :type kenmei_data: dict[str, Any]

        :param unread_data: A dictionary tracking unread chapters.
        :type unread_data: dict[str, str]
        """
        for entry in kenmei_data.get("entries", []):
            attributes = entry.get("attributes", {})
            if not attributes:
                logging.warning(f"Missing attributes for entry {entry.get('id')}")
                continue

            title = attributes.get("title")
            unread = attributes.get("unread")
            latest = attributes.get("latestChapter", {})
            
            if isinstance(latest, dict):
                latest = latest.get("chapter")

            if isinstance(latest, (str, float, int)) and str(latest).replace(".", "", 1).isdigit():
                latest = float(latest)

            if not title or latest is None:
                logging.warning(f"Missing title/latest chapter for {entry.get('id')}")
                continue

            latest_str = str(latest) if not latest.is_integer() else str(int(latest))

            if unread and unread_data.get(title) != latest_str:
                unread_data[title] = latest_str
                self.push_notification(title, latest)
            elif not unread:
                unread_data.pop(title, None)
    
    def push_notification(self, title: str, latest: str) -> None:
        """
        Sends a Pushover notification.

        :param title: The title of the manga.
        :type title: str

        :param latest: The latest chapter number.
        :type latest: str
        """
        self.pushover_data["message"] = f"{title} | Ch. {latest} released!"
        try:
            response = requests.post("https://api.pushover.net/1/messages.json", data=self.pushover_data)
            response.raise_for_status()
        except requests.RequestException as e:
            logging.error(f"Failed to send Pushover notification: {e}")

def get_env_variables() -> dict[str, str]:
    """
    Retrieves required environment variables for authentication.

    :return: A dictionary containing the required environment variables.
    :rtype: dict[str, str]
    """
    required_vars = ["KENMEI_EMAIL", "KENMEI_PASSWORD", "PUSHOVER_APP_KEY", "PUSHOVER_ACC_KEY"]
    missing_vars = [var for var in required_vars if var not in os.environ]
    if missing_vars:
        logging.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return {}
    
    return {var.lower(): os.environ[var] for var in required_vars}

def save_data(filename: str, data: dict[str, Any]) -> None:
    """
    Saves data to a JSON file.

    :param filename: The name of the file.
    :type filename: str

    :param data: Data to write to JSON file.
    :type data: dict[str, Any]
    """
    try:
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        with open(filepath, "w") as file:
            json.dump(data, file, indent=4)
    except IOError as e:
        logging.error(f"Failed to save {filename}: {e}")

def load_unread_data(filename: str = "unread.json") -> dict[str, str]:
    """
    Loads unread manga data from a file.

    :param filename: The name of the file.
    :type filename: str

    :return: Dictionary of unread manga entries.
    :rtype: dict[str, str]
    """
    try:
        with open(filename, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def main():
    """Main execution function."""
    private = get_env_variables()
    if not private:
        return
    
    client = KenmeiClient(
        email=private["kenmei_email"],
        password=private["kenmei_password"],
        pushover_app_key=private["pushover_app_key"],
        pushover_acc_key=private["pushover_acc_key"]
    )
    kenmei_data = client.fetch_manga_data()
    if not kenmei_data:
        return
    
    unread_data = load_unread_data()
    client.process_manga_entries(kenmei_data, unread_data)
    save_data("unread.json", unread_data)

if __name__ == "__main__":
    main()
