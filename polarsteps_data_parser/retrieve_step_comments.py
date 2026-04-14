import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from polarsteps_data_parser.utils import log
from polarsteps_data_parser.model import Trip, StepComment

# Define the headers used for the request to polarsteps.com
headers = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "en-NL,en;q=0.9,nl-NL;q=0.8,nl;q=0.7,en-US;q=0.6",
    "Connection": "keep-alive",
    "Cookie": "",  # Will be retrieved from environment variables
    "Host": "www.polarsteps.com",
    "Polarsteps-Api-Version": "13",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 "
    "Safari/537.36",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


@dataclass
class FetchResponse:
    status_code: int
    text: str
    headers: dict

    def json(self):
        return json.loads(self.text)


class StepCommentsEnricher:
    """Enriches steps with comments retrieved using the Polarsteps API."""

    def __init__(self, path: Path) -> None:
        self.comment_data_path = path / "comments.json"
        headers["Cookie"] = os.getenv("COOKIE")

    def enrich(self, trip: Trip) -> None:
        """Enrich trip data with comments.

        Args:
        ----
            trip: trip data

        """
        comment_data = self.retrieve_comments(trip)
        self.add_comments_to_steps(trip, comment_data)

    def retrieve_comments(self, trip: Trip) -> dict:
        """Retrieve comments from Polarsteps API or local file storage.

        Args:
        ----
            trip: data of the trip

        Returns:
        -------
            dict: comment data

        """
        # Check if there is comment data and give the option to download/use existing data
        if self.comment_data_path.exists():
            comment_data = self.load_comments_from_file()
            return comment_data

        # Retrieve data from the API
        comment_data = {"steps": []}
        for step in trip.steps:
            comments = self.get_comments_for_step(step.step_id)
            comment_data["steps"].append({"id": step.step_id, "comments": comments["comments"]})

        self.write_comments_to_file(comment_data)

        return comment_data

    def write_comments_to_file(self, comment_data: dict) -> None:
        """Write comments data to file.

        Args:
        ----
            comment_data: comment data retrieved from the API

        """
        with open(self.comment_data_path, "w") as file:
            json.dump(comment_data, file, indent=4)

    def load_comments_from_file(self) -> dict:
        """Load comments from data file.

        Returns:
        -------
            dict: comment data

        """
        with open(self.comment_data_path, "r") as file:
            return json.load(file)

    @staticmethod
    def get_comments_for_step(step_id: str) -> dict:
        """Retrieve all comments for a step.

        Args:
        ----
            step_id: id of the step (e.g. 82089888)

        Returns:
        -------
            dict: response parsed to JSON

        """
        url = f"https://www.polarsteps.com/api/social/steps/{step_id}/comments"
        response = StepPhotoOrderEnricher._fetch_url_static(url)

        if response is None:
            raise ConnectionError(f"Could not retrieve comments for step {step_id}")

        if response.status_code == 401:
            log(
                "Error: Unauthorized request to Polarsteps API. "
                "Temporarily set the trip to public or set a valid COOKIE environment variable.",
                color="red",
            )
            exit(1)

        return response.json()

    @staticmethod
    def add_comments_to_steps(trip: Trip, comment_data: dict) -> Trip:
        """Parse the comment data to the model.

        Args:
        ----
            trip: trip data
            comment_data: comment data

        Returns:
        -------
            trip: trip data including comments

        """
        for step, comments in zip(trip.steps, comment_data["steps"]):
            if step.step_id != comments["id"]:
                raise ValueError("Steps in trip and comment data are not in the same order.")
            step.comments = [StepComment.from_json(c) for c in comments["comments"]]

        return trip


class StepPhotoOrderEnricher:
    """Enriches steps with photo ordering retrieved from Polarsteps web view."""

    def __init__(self, path: Path) -> None:
        self.photo_order_data_path = path / "photo_order.json"
        headers["Cookie"] = os.getenv("COOKIE", "")

    def enrich(self, trip: Trip) -> None:
        """Enrich trip data with the step photo order."""
        if not headers["Cookie"]:
            log("Error: COOKIE environment variable must be set for photo order enrichment.", color="red")
            log(
                "Set COOKIE from a logged-in Polarsteps browser session with access to the trip.",
                color="red",
            )
            log(
                "Example (PowerShell): $env:COOKIE='name=value; name2=value2'",
                color="red",
            )
            exit(1)

        photo_order_data = self.retrieve_photo_order(trip)
        self.add_photo_order_to_steps(trip, photo_order_data)

    def retrieve_photo_order(self, trip: Trip) -> dict:
        """Retrieve photo order data from cache or from the Polarsteps web API."""
        if self.photo_order_data_path.exists():
            return self.load_photo_order_from_file()

        photo_order_data = {"steps": []}
        for step in trip.steps:
            photo_order = self.get_photo_order_for_step(step.step_id)
            photo_order_data["steps"].append({"id": step.step_id, "photo_order": photo_order})

        self.write_photo_order_to_file(photo_order_data)
        return photo_order_data

    def write_photo_order_to_file(self, photo_order_data: dict) -> None:
        with open(self.photo_order_data_path, "w", encoding="utf-8") as file:
            json.dump(photo_order_data, file, indent=4)

    def load_photo_order_from_file(self) -> dict:
        with open(self.photo_order_data_path, "r", encoding="utf-8") as file:
            return json.load(file)

    def get_photo_order_for_step(self, step_id: str) -> list[str]:
        """Retrieve the ordered list of photo identifiers for a step."""
        candidate_urls = [
            f"https://www.polarsteps.com/api/social/steps/{step_id}",
            f"https://www.polarsteps.com/api/social/steps/{step_id}/media",
            f"https://www.polarsteps.com/api/social/steps/{step_id}/photos",
            f"https://www.polarsteps.com/api/steps/{step_id}",
            f"https://www.polarsteps.com/api/steps/{step_id}/media",
            f"https://www.polarsteps.com/api/steps/{step_id}/photos",
            f"https://www.polarsteps.com/steps/{step_id}",
        ]

        for url in candidate_urls:
            response = self._fetch_url(url)
            if response is None:
                continue
            if response.status_code == 401:
                log(
                    "Error: Unauthorized request to Polarsteps web API. "
                    "Set a valid COOKIE environment variable from a logged-in session.",
                    color="red",
                )
                exit(1)

            photo_order = self._parse_photo_order_response(response)
            if photo_order:
                return photo_order

        log(
            f"Warning: Could not retrieve photo order for step {step_id}. "
            "Photos will remain in local export order.",
            color="yellow",
        )
        return []

    @staticmethod
    def _fetch_url_static(url: str):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read()
                try:
                    text = body.decode("utf-8")
                except UnicodeDecodeError:
                    text = body.decode("utf-8", errors="replace")
                headers_dict = {k: v for k, v in response.getheaders()}
                return FetchResponse(status_code=response.getcode(), text=text, headers=headers_dict)
        except urllib.error.HTTPError as err:
            try:
                body = err.read()
                text = body.decode("utf-8", errors="replace")
            except Exception:
                text = ""
            headers_dict = {k: v for k, v in err.headers.items()} if err.headers else {}
            return FetchResponse(status_code=err.code, text=text, headers=headers_dict)
        except urllib.error.URLError as err:
            log(f"Warning: Failed to fetch {url}: {err}", color="yellow")
            return None

    def _fetch_url(self, url: str):
        return self._fetch_url_static(url)

    def _parse_photo_order_response(self, response: FetchResponse) -> list[str]:
        try:
            data = response.json()
        except ValueError:
            data = None

        if data:
            photo_order = self._parse_photo_order_from_json(data)
            if photo_order:
                return photo_order

        return self._parse_photo_order_from_html(response.text)

    def _parse_photo_order_from_json(self, data: dict) -> list[str]:
        if not isinstance(data, dict):
            return []

        order = []

        list_keys = [
            "photo_order",
            "photos",
            "media",
            "items",
            "attachments",
            "images",
        ]

        for key in list_keys:
            if key in data and isinstance(data[key], list):
                order = self._extract_photo_names(data[key])
                if order:
                    return order

        for value in data.values():
            if isinstance(value, list):
                order = self._extract_photo_names(value)
                if order:
                    return order

        return []

    def _extract_photo_names(self, values: list) -> list[str]:
        names = []
        for item in values:
            if isinstance(item, str):
                names.append(Path(urlparse(item).path).name)
                continue

            if not isinstance(item, dict):
                continue

            for key in [
                "filename",
                "fileName",
                "name",
                "url",
                "path",
                "image_url",
                "original_file_name",
                "originalFilename",
                "thumbnail",
            ]:
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    names.append(Path(urlparse(value).path).name)
                    break

        return [name for name in names if name]

    def _parse_photo_order_from_html(self, html: str) -> list[str]:
        if not isinstance(html, str):
            return []

        names = []
        seen = set()

        patterns = [
            r'src=["\']([^"\']+\.(?:jpe?g|jpeg|png|webp))["\']',
            r'data-src=["\']([^"\']+\.(?:jpe?g|jpeg|png|webp))["\']',
            r'srcset=["\']([^"\']+\.(?:jpe?g|jpeg|png|webp))',
            r'url\(([^)]+\.(?:jpe?g|jpeg|png|webp))\)',
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, html, re.IGNORECASE):
                raw_value = match.group(1).strip().strip('"\'')
                name = Path(urlparse(raw_value).path).name
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)

        return names

    def add_photo_order_to_steps(self, trip: Trip, photo_order_data: dict) -> None:
        total_matched = 0
        total_unmatched = 0

        for step, order_info in zip(trip.steps, photo_order_data.get("steps", [])):
            if step.step_id != order_info.get("id"):
                raise ValueError("Steps in trip and photo order data are not in the same order.")

            order = order_info.get("photo_order", [])
            local_photo_names = [photo.name for photo in step.photos]
            matched, unmatched, unmatched_names = step.apply_photo_order(order)

            total_matched += matched
            total_unmatched += unmatched

            log(f"Photo order debug for step {step.step_id}:", color="cyan")
            log(f"  ordered/local names:{len(order)}/{len(local_photo_names)}", color="blue")
            #log(f"  local photo filenames ({len(local_photo_names)})", color="blue")
            #log(f"  ordered names ({len(order)}): {order}", color="cyan")
            #log(f"  local photo filenames ({len(local_photo_names)}): {local_photo_names}", color="cyan")
            if unmatched_names:
                log(
                    f"  unmatched ordered names ({len(unmatched_names)}): {unmatched_names}",
                    color="yellow",
                )
            else:
                log("  all ordered names matched locally", color="green")

        log(
            f"Photo order enrichment: {total_matched} ordered photo names matched locally, "
            f"{total_unmatched} ordered photo names had no local match.",
            color="green",
        )
