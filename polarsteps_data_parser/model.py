from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Self

from polarsteps_data_parser.utils import parse_date, find_folder_by_id, list_files_in_folder


@dataclass
class Location:
    """Location as tracked by the travel tracker."""

    lat: float
    lon: float
    time: datetime

    @classmethod
    def from_json(cls, data: dict) -> Self:
        """Parse object from JSON data."""
        return Location(lat=data["lat"], lon=data["lon"], time=parse_date(data["time"]))


@dataclass
class StepLocation:
    """Location as provided by a step."""

    lat: float
    lon: float
    name: str
    country: str

    @classmethod
    def from_json(cls, data: dict) -> Self:
        """Parse object from JSON data."""
        return StepLocation(
            lat=data["lat"],
            lon=data["lon"],
            name=data["name"],
            country=data["detail"],
        )


@dataclass
class Follower:
    """Follower (can leave comments)."""

    user_id: str
    username: str
    first_name: str
    last_name: str

    @classmethod
    def from_json(cls, data: dict) -> Self:
        """Parse object from JSON data."""
        return Follower(
            user_id=data["id"],
            username=data["username"],
            first_name=data["first_name"],
            last_name=data["last_name"],
        )

    @property
    def name(self) -> str:
        """Name of the follower."""
        return f"{self.first_name} {self.last_name}"


@dataclass
class StepComment:
    """Comment connected to a step."""

    comment_id: str
    text: str
    date: datetime
    follower: Follower

    @classmethod
    def from_json(cls, data: dict) -> Self:
        """Parse object from JSON data."""
        return StepComment(
            comment_id=data["id"],
            text=data["text"],
            date=parse_date(data["creation_time"]),
            follower=Follower.from_json(data["user"]),
        )


@dataclass
class Step:
    """Polarsteps Step object."""

    step_id: str
    name: str
    description: str
    location: StepLocation
    date: date
    photos: list[Path]
    videos: list[Path]
    comments: list[StepComment]
    # Optional weather info (may not be present in older exports)
    weather_condition: str | None = None
    weather_temperature: float | None = None

    @classmethod
    def from_json(cls, data: dict, input_folder: Path | None = None) -> Self:
        """Parse object from JSON data."""
        s = Step(
            step_id=data["id"],
            name=data["name"] or data["display_name"],
            description=data["description"],
            location=StepLocation.from_json(data["location"]),
            date=parse_date(data["start_time"]),
            photos=[],
            videos=[],
            comments=[],
            weather_condition=data.get("weather_condition"),
            weather_temperature=data.get("weather_temperature"),
        )
        s.load_media(input_folder)
        return s

    def load_media(self, input_folder: Path | None = None) -> None:
        """Load photos and videos for the step."""
        step_dir = find_folder_by_id(self.step_id)
        if step_dir is None:
            self.photos = []
            self.videos = []
        else:
            photos_dir = step_dir / "photos"
            self.photos = list_files_in_folder(photos_dir, dir_has_to_exist=False)
            self.videos = list_files_in_folder(step_dir / "videos", dir_has_to_exist=False)

    def apply_photo_order(self, order: list[str]) -> tuple[int, int, list[str]]:
        """Reorder loaded photos according to the provided ordered filenames.

        Returns:
            tuple[int, int, list[str]]: Number of ordered filenames matched locally, number of ordered filenames without a local match, and list of unmatched ordered names.
        """
        if not order or not self.photos:
            return 0, 0, []

        def normalize_name(name: str) -> str:
            normalized = name.lower()
            duplicate_extensions = [".jpg", ".jpeg", ".png", ".webp"]
            for ext in duplicate_extensions:
                while normalized.endswith(ext + ext):
                    normalized = normalized[: -len(ext)]
            return normalized

        def extract_prefix(name: str) -> str:
            normalized = normalize_name(name)
            return normalized.split("_", 1)[0]

        ordered_photos: list[Path] = []
        remaining_photos = {photo.name: photo for photo in self.photos}
        normalized_photo_map = {normalize_name(name): photo for name, photo in remaining_photos.items()}
        prefix_photo_map = {extract_prefix(name): photo for name, photo in remaining_photos.items()}
        seen = set()
        matched = 0
        unmatched = 0
        unmatched_names: list[str] = []

        for item in order:
            name = Path(item).name
            if not name:
                continue

            normalized_name = normalize_name(name)
            prefix_name = extract_prefix(name)
            photo = None

            if normalized_name in normalized_photo_map:
                photo = normalized_photo_map[normalized_name]
            elif prefix_name in prefix_photo_map:
                photo = prefix_photo_map[prefix_name]
            else:
                for photo_name, local_photo in remaining_photos.items():
                    if photo_name in seen:
                        continue
                    normalized_local = normalize_name(photo_name)
                    if normalized_name == normalized_local or normalized_name in normalized_local or normalized_local in normalized_name:
                        photo = local_photo
                        break

            if photo is not None and photo.name not in seen:
                ordered_photos.append(photo)
                seen.add(photo.name)
                matched += 1
            else:
                unmatched += 1
                unmatched_names.append(name)

        for photo in self.photos:
            if photo.name not in seen:
                ordered_photos.append(photo)

        self.photos = ordered_photos
        return matched, unmatched, unmatched_names


@dataclass
class Trip:
    """Polarsteps trip object."""

    name: str
    start_date: datetime
    end_date: datetime
    cover_photo_path: str
    steps: list[Step]

    @classmethod
    def from_json(cls, data: dict, input_folder: Path | None = None) -> Self:
        """Parse object from JSON data."""
        return Trip(
            name=data["name"],
            start_date=parse_date(data.get("start_date")),
            end_date=parse_date(data.get("end_date")),
            cover_photo_path=data["cover_photo_path"],
            steps=[Step.from_json(step, input_folder) for step in data.get("all_steps")],
        )
