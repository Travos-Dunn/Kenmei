# kenmei.py
import os
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import uuid
import logging
from typing import Any

logging.basicConfig(level=logging.INFO)

BASE_DIR = os.path.dirname(__file__)
UNREAD_FILE = os.path.join(BASE_DIR, "unread.json")

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
        "manga": "https://api.kenmei.co/api/v2/manga_entries?page={}&status=1"
    }

    def __init__(self, email: str, password: str, pushover_app_key: str, pushover_acc_key: str):
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.email = email
        self.password = password
        self.pushover_data = {
            "token": pushover_app_key,
            "user": pushover_acc_key,
            "message": ""
        }
        self.sentry_trace = f"{uuid.uuid4().hex}-{uuid.uuid4().hex}-1"
        self.auth_key = self.authenticate()

    def generate_headers(self) -> dict[str, str]:
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
            "sentry-trace": self.sentry_trace
        }

    def authenticate(self) -> str | None:
        """
        Authenticates the user and retrieves an access token.

        :return: The authentication token if successful, otherwise None.
        :rtype: str | None
        """
        try:
            response = self.session.post(
                self.BASE_URLS["login"],
                headers=self.generate_headers(),
                json={"user": {"login": self.email, "password": self.password, "remember_me": False}},
                timeout=10
            )
            response.raise_for_status()
            logging.debug("Authentication successful")
            return response.json().get("access")
        except requests.RequestException as e:
            logging.error(f"Login failed: {e}")
            return None

    def fetch_manga_data(self) -> dict[str, Any]:
        """
        Fetch manga entries across multiple pages (if available) from Kenmei API.

        :return: A dictionary containing all manga data.
        :rtype: dict[str, Any]
        """
        if not self.auth_key:
            logging.error("Authentication key is missing.")
            return {}
        
        self.session.headers.update({"Authorization": f"Bearer {self.auth_key}"})
        all_entries = []

        try:
            response = self.session.get(self.BASE_URLS["manga"].format(1), timeout=10)
            response.raise_for_status()
            
            try:
                data = response.json()
            except ValueError:
                logging.error("Invalid JSON response from Kenmei API")
                return {"entries": []}

            pages = data.get("pagy", {}).get("pages", 0) or 1
            logging.debug(f"Found {pages} page(s) of manga entries")

            for page in range(1, pages + 1):
                try:
                    response = self.session.get(self.BASE_URLS["manga"].format(page), timeout=10)
                    response.raise_for_status()
                    page_entries = response.json().get("entries", [])
                    if page_entries:
                        all_entries.extend(page_entries)
                        logging.debug(f"Fetched {len(page_entries)} entries from page {page}")
                    else:
                        logging.debug(f"No entries found on page {page}")
                except requests.RequestException as e:
                    logging.error(f"Failed to fetch data on page {page}: {e}")
        except requests.RequestException as e:
            logging.error(f"Initial data request failed: {e}")
        
        return {"entries": all_entries}

    def process_manga_entries(self, kenmei_data: dict[str, Any]) -> dict[str, str]:
        """
        Processes manga entries and sends notifications for new chapters.

        :param kenmei_data: The retrieved manga data.
        :type kenmei_data: dict[str, Any]

        :return: A dictionary of unread manga data
        :rtype: dict[str, str]
        """
        try:
            unread_data = load_unread_data()
        except Exception as e:
            logging.error(f"Failed to load unread data: {e}")
            unread_data = {}
        
        updated_data: dict[str, str] = {}

        for entry in kenmei_data.get("entries", []):
            try:
                attributes = entry.get("attributes", {})
                title = attributes.get("title")
                unread = attributes.get("unread", False)
                latest = attributes.get("latestChapter", {})

                if not title:
                    logging.warning(f"Skipping entry with missing title: {entry}")
                    continue
                
                if isinstance(latest, dict):
                    latest = latest.get("chapter")

                if latest is None:
                    logging.warning(f"Skipping entry with no chapter info: {title}")
                    continue
                
                if isinstance(latest, (int, float)):
                    if isinstance(latest, float) and latest.is_integer():
                        latest = int(latest)

                latest_str = str(latest).strip()

                if latest_str in ("", "0"):
                    logging.warning(f"Skipping entry with empty or zero chapter: {title}")
                    continue
                
                if "." in latest_str:
                    latest_str = latest_str.rstrip("0").rstrip(".")
                
                if bool(unread):
                    prev = unread_data.get(title)
                    if prev != latest_str:
                        try:
                            self.push_notification(title, latest_str)
                        except Exception as e:
                            logging.error(f"Failed to send notification for {title}: {e}")
                    updated_data[title] = latest_str
            except Exception as e:
                logging.error(f"Error processing entry {entry}: {e}")
                continue
        
        removed_titles = set(unread_data) - set(updated_data)
        if removed_titles:
            logging.debug(f"Removed stale titles: {', '.join(removed_titles)}")

        return updated_data
    
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
            response = self.session.post("https://api.pushover.net/1/messages.json", data=self.pushover_data, timeout=10)
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
    
    return {var: os.environ[var] for var in required_vars}

def save_data(data: dict[str, str]) -> None:
    """
    Saves data to a `unread.json`.

    :param data: Data to write to JSON file.
    :type data: dict[str, Any]
    """
    with open(UNREAD_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)

def load_unread_data() -> dict[str, str]:
    """
    Loads unread manga data from `unread.json`.

    :return: Dictionary of unread manga entries.
    :rtype: dict[str, str]
    """
    if os.path.exists(UNREAD_FILE):
        try:
            with open(UNREAD_FILE, "r", encoding="utf-8") as file:
                return json.load(file)
        except json.JSONDecodeError as e:
            logging.error(f"Failed to open {UNREAD_FILE}: {e}")
    return {}

def main():
    """Main execution function."""
    private = get_env_variables()
    if not private:
        return
    
    client = KenmeiClient(
        email=private["KENMEI_EMAIL"],
        password=private["KENMEI_PASSWORD"],
        pushover_app_key=private["PUSHOVER_APP_KEY"],
        pushover_acc_key=private["PUSHOVER_ACC_KEY"]
    )
    kenmei_data = client.fetch_manga_data()
    if not kenmei_data:
        return
    
    new_data = client.process_manga_entries(kenmei_data)
    save_data(new_data)

if __name__ == "__main__":
    main()