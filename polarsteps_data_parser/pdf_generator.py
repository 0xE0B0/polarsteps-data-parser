from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from polarsteps_data_parser.model import Trip, Step
from tqdm import tqdm


class PDFGenerator:
    """Generates a PDF for Polarsteps Trip objects."""

    MAIN_FONT = ("Helvetica", 12)
    BOLD_FONT = ("Helvetica-Bold", 12)
    HEADING_FONT = ("Helvetica-Bold", 16)
    TITLE_HEADING_FONT = ("Helvetica-Bold", 36)

    def __init__(self, output: str, emoji_font_path: Path | str | None = None, portrait_height: int = 330, landscape_width: int = 250, side_by_side_gap: int = 20, photo_padding: float = 3.0, photo_border_width: float = 0.5) -> None:
        self.filename = output
        self.canvas = None
        self.width, self.height = letter
        self.y_position = self.height - 30
        # Configurable image sizing (in points): portraits specify height, landscapes specify width
        self.portrait_height = float(portrait_height)
        self.landscape_width = float(landscape_width)
        # Global default gap for side-by-side photos
        self.side_by_side_gap = int(side_by_side_gap)
        # Global defaults for image borders/padding
        self.photo_padding = float(photo_padding)
        self.photo_border_width = float(photo_border_width)
        # If an emoji-capable TTF is provided, register it and use it as the main font
        if emoji_font_path is not None:
            self.register_font(emoji_font_path)

    def generate_pdf(self, trip: Trip) -> None:
        """Generate a PDF for a given trip."""
        self.canvas = Canvas(self.filename, pagesize=letter)

        # Track page numbers, trip name and step counts for footer
        self.page_number = 1
        self.current_trip_name = trip.name
        self.total_steps = len(trip.steps)
        self.current_step = 0

        self.canvas.setTitle(trip.name)

        self.generate_title_page(trip)

        for i, step in enumerate(trip.steps, start=1):
            self.current_step = i
            self.generate_step_pages(step)

        # Draw footer on the final page then save
        self._draw_footer()
        self.canvas.save()

    def generate_title_page(self, trip: Trip) -> None:
        """Generate title page."""
        self.title_heading(trip.name)
        self.y_position -= 20
        self.short_text(
            f"{trip.start_date.strftime('%d-%m-%Y')} - {trip.end_date.strftime('%d-%m-%Y')}", bold=True, centered=True
        )
        self.photo(trip.cover_photo_path, centered=True, photo_width=500)

    def generate_step_pages(self, step: Step) -> None:
        """Add a step to the canvas."""
        self.new_page()

        self.heading(step.name)

        # Show location and right-aligned weather info if available
        left = f"Ort: {step.location.name}, {step.location.country}"
        weather_text = self._format_weather(step.weather_condition, step.weather_temperature)
        if weather_text:
            self.short_text_with_right(left, weather_text)
        else:
            self.short_text(left)

        self.short_text(f"Datum: {step.date.strftime('%d-%m-%Y')}")

        self.long_text(step.description)

        for comment in step.comments:
            self.short_text(comment.follower.name, bold=True)
            self.long_text(comment.text)

        # Layout photos: if two consecutive photos are both portrait, place side-by-side
        photos = step.photos
        i = 0
        while i < len(photos):
            if i + 1 < len(photos):
                try:
                    img1 = ImageReader(photos[i])
                    img2 = ImageReader(photos[i + 1])
                    w1, h1 = img1.getSize()
                    w2, h2 = img2.getSize()
                    if h1 > w1 and h2 > w2:
                        self.photo_side_by_side(photos[i], photos[i + 1])
                        i += 2
                        continue
                except Exception:
                    # If ImageReader fails, fall back to drawing sequentially
                    pass
            # Single image: center it on the page
            self.photo(photos[i], centered=True)
            i += 1

    def _draw_footer(self) -> None:
        """Draw a footer with left trip name, center current_step/total_steps, and right 'Seite #'"""
        if getattr(self, "canvas", None) is None or not getattr(self, "current_trip_name", None):
            return
        margin = 30
        y = 15

        # Draw a thin black separator line above the footer
        line_y = y + 12
        self.canvas.setStrokeColorRGB(0, 0, 0)
        self.canvas.setLineWidth(0.5)
        self.canvas.line(margin, line_y, self.width - margin, line_y)

        # Left: trip name (use MAIN_FONT if contains non-ASCII)
        left_text = self.current_trip_name
        left_font = ("Helvetica", 8)
        if any(ord(ch) > 127 for ch in left_text):
            left_font = (self.MAIN_FONT[0], 8)
        self.canvas.setFont(*left_font)
        self.canvas.drawString(margin, y, left_text)

        # Center: step_counter (n/m)
        total = getattr(self, "total_steps", None)
        cur = getattr(self, "current_step", 0)
        center_text = f"{cur}/{total}" if total is not None else ""
        center_font = ("Helvetica", 8)
        self.canvas.setFont(*center_font)
        cx = self.calc_width_centered(center_text, center_font)
        self.canvas.drawString(cx, y, center_text)

        # Right: page number in German
        right_text = f"Seite {self.page_number}"
        right_font = ("Helvetica", 8)
        self.canvas.setFont(*right_font)
        right_x = self.width - margin - self.canvas.stringWidth(right_text, right_font[0], right_font[1])
        self.canvas.drawString(right_x, y, right_text)

    def new_page(self) -> None:
        """Add a new page to the canvas (draw footer for the current page)."""
        # Draw footer for the current page, then show a new page
        try:
            self._draw_footer()
        except Exception:
            # Footer drawing must not break PDF generation
            pass
        self.canvas.showPage()
        # increase page counter for the new page
        if hasattr(self, "page_number"):
            self.page_number += 1
        self.width, self.height = letter
        self.y_position = self.height - 30

    def register_font(self, font_path: Path | str, font_name: str | None = None) -> None:
        """Register a TTF font and set it as MAIN_FONT.

        Args:
            font_path: Path to a .ttf font file that includes emoji glyphs.
            font_name: Optional internal name for the registered font.
        Raises:
            FileNotFoundError: If the font file is not found.
        """
        font_path = Path(font_path)
        if not font_path.exists():
            raise FileNotFoundError(f"Font file not found: {font_path}")
        name = font_name or f"TTF-{font_path.stem}"
        pdfmetrics.registerFont(TTFont(name, str(font_path)))
        # Preserve the configured size from MAIN_FONT
        size = self.MAIN_FONT[1] if isinstance(self.MAIN_FONT, tuple) else 12
        self.MAIN_FONT = (name, size)

    def heading(self, text: str) -> None:
        """Add heading to canvas."""
        if self.y_position < 50:
            self.new_page()
        # If text contains non-ASCII (emoji or other glyphs), use the registered MAIN_FONT at heading size
        font_to_use = self.HEADING_FONT
        if any(ord(ch) > 127 for ch in text):
            font_to_use = (self.MAIN_FONT[0], self.HEADING_FONT[1])
        self.canvas.setFont(*font_to_use)
        self.canvas.drawString(30, self.y_position, text)
        self.y_position -= 30

    def title_heading(self, text: str) -> None:
        """Add heading to canvas."""
        self.y_position -= 100
        font_to_use = self.TITLE_HEADING_FONT
        if any(ord(ch) > 127 for ch in text):
            font_to_use = (self.MAIN_FONT[0], self.TITLE_HEADING_FONT[1])
        self.canvas.setFont(*font_to_use)
        self.canvas.drawString(self.calc_width_centered(text, font_to_use), self.y_position, text)
        self.y_position -= 30

    def calc_width_centered(self, text: str, font: tuple) -> float:
        """Calculate the width location to center the text."""
        return (self.width - stringWidth(text, *font)) / 2.0

    def short_text(self, text: str, bold: bool = False, centered: bool = False) -> None:
        """Add short text to canvas."""
        if self.y_position < 50:
            self.new_page()
        if bold:
            font = self.BOLD_FONT
            # If bold font may not contain emojis, fall back to main registered TTF
            if any(ord(ch) > 127 for ch in text):
                font = (self.MAIN_FONT[0], self.BOLD_FONT[1])
        else:
            font = self.MAIN_FONT
        self.canvas.setFont(*font)
        width = self.calc_width_centered(text, font) if centered else 30
        self.canvas.drawString(width, self.y_position, text)
        self.y_position -= 20

    def short_text_with_right(self, left_text: str, right_text: str, bold_left: bool = False, bold_right: bool = False) -> None:
        """Draw left-aligned `left_text` at margin and right-aligned `right_text` on the same line.

        If both pieces of text would overlap, the right_text is pushed to the next line (right aligned).
        """
        if self.y_position < 50:
            self.new_page()

        # Fonts
        left_font = self.BOLD_FONT if bold_left else self.MAIN_FONT
        if any(ord(ch) > 127 for ch in left_text) and bold_left:
            left_font = (self.MAIN_FONT[0], self.BOLD_FONT[1])
        right_font = self.BOLD_FONT if bold_right else self.MAIN_FONT
        if any(ord(ch) > 127 for ch in right_text) and bold_right:
            right_font = (self.MAIN_FONT[0], self.BOLD_FONT[1])

        # Draw left text
        self.canvas.setFont(*left_font)
        left_x = 30
        self.canvas.drawString(left_x, self.y_position, left_text)
        left_end = left_x + stringWidth(left_text, *left_font)

        # Compute right position
        right_w = stringWidth(right_text, *right_font)
        right_x = self.width - 30 - right_w

        # If overlap, push right text to next line
        if right_x <= left_end + 8:
            # next line: decrement y then draw right-aligned text
            self.y_position -= 20
            self.canvas.setFont(*right_font)
            right_w = stringWidth(right_text, *right_font)
            right_x = self.width - 30 - right_w
            self.canvas.drawString(right_x, self.y_position, right_text)
            self.y_position -= 20
            return

        # Draw right text on same line
        self.canvas.setFont(*right_font)
        self.canvas.drawString(right_x, self.y_position, right_text)
        self.y_position -= 20

    def long_text(self, text: str) -> None:
        """Add long text to canvas."""
        if text is None:
            return

        self.y_position -= 10
        lines = self.wrap_text(text, self.width - 60)
        for line in lines:
            if self.y_position < 50:
                self.new_page()
                self.canvas.setFont(*self.MAIN_FONT)
            self.canvas.drawString(30, self.y_position, line)
            self.y_position -= 20
        self.y_position -= 20

    def photo(self, photo_path: Path | str, centered: bool = False, photo_width: int | None = None, photo_height: int | None = None) -> None:
        """Add photo to canvas.

        Uses configurable sizing depending on orientation (constructor defaults):
        - Portrait images: height = self.portrait_height (override via `photo_height`)
        - Landscape images: width = self.landscape_width (override via `photo_width`)
        Pass `photo_width` or `photo_height` to override the target size for a specific image.
        """
        image = ImageReader(photo_path)
        img_width, img_height = image.getSize()
        aspect = img_height / float(img_width)

        # Decide draw size based on orientation and overrides
        if img_height > img_width:
            # Portrait: use photo_height override or configured portrait_height
            if photo_height is not None:
                draw_height = float(photo_height)
            else:
                draw_height = float(self.portrait_height)
            draw_width = draw_height / aspect
        else:
            # Landscape or square: use photo_width override or configured landscape_width
            if photo_width is not None:
                draw_width = float(photo_width)
            else:
                draw_width = float(self.landscape_width)
            draw_height = draw_width * aspect

        # Cap the width to available page width (margins: 30 on both sides -> width - 60)
        max_width = self.width - 60
        if draw_width > max_width:
            scale = max_width / draw_width
            draw_width *= scale
            draw_height *= scale

        if self.y_position - draw_height < 50:
            self.new_page()

        x = (self.width - draw_width) / 2.0 if centered else 30
        y_bottom = self.y_position - draw_height
        self._draw_image_with_border(image, x, y_bottom, draw_width, draw_height)
        self.y_position = self.y_position - draw_height - 20

    def _draw_image_with_border(self, image, x: float, y: float, width: float, height: float, padding: float | None = None, border_width: float | None = None) -> None:
        """Draw an image with a small white padding and a thin black border.

        Defaults for padding and border width come from instance configuration (`photo_padding`, `photo_border_width`) when None is provided.

        Args:
            image: ImageReader or image-like accepted by drawImage.
            x, y: bottom-left coordinates where image will be placed.
            width, height: size of the image in points.
            padding: white padding around the image in points (defaults to self.photo_padding).
            border_width: stroke width of the outer black border (defaults to self.photo_border_width).
        """
        if padding is None:
            padding = float(getattr(self, "photo_padding", 4.0))
        if border_width is None:
            border_width = float(getattr(self, "photo_border_width", 0.5))

        border_x = x - padding
        border_y = y - padding
        border_w = width + (padding * 2)
        border_h = height + (padding * 2)

        # Use save/restore to avoid changing colors globally
        self.canvas.saveState()
        # white background rectangle (padding)
        self.canvas.setFillColorRGB(1, 1, 1)
        self.canvas.rect(border_x, border_y, border_w, border_h, stroke=0, fill=1)
        # draw image on top
        self.canvas.drawImage(image, x, y, width=width, height=height)
        # thin black border
        self.canvas.setLineWidth(border_width)
        self.canvas.setStrokeColorRGB(0, 0, 0)
        self.canvas.rect(border_x, border_y, border_w, border_h, stroke=1, fill=0)
        self.canvas.restoreState()

    def photo_side_by_side(
        self,
        photo_path1: Path | str,
        photo_path2: Path | str,
        centered: bool = True,
        photo_height: int | None = None,
        gap: int | None = None,
    ) -> None:
        """Layout two images side-by-side.

        Uses `photo_height` if provided; otherwise each portrait image uses the configured `portrait_height`.
        Gap between images defaults to the instance's `side_by_side_gap` if not provided. If combined width exceeds page margins, both images are scaled down uniformly.
        """
        image1 = ImageReader(photo_path1)
        img1_w, img1_h = image1.getSize()
        aspect1 = img1_h / float(img1_w)

        image2 = ImageReader(photo_path2)
        img2_w, img2_h = image2.getSize()
        aspect2 = img2_h / float(img2_w)

        # Only do side-by-side if both images are portrait; otherwise fall back to stacked
        if not (img1_h > img1_w and img2_h > img2_w):
            self.photo(photo_path1, centered=centered, photo_height=photo_height)
            self.photo(photo_path2, centered=centered, photo_height=photo_height)
            return

        # If gap not provided, use global default
        if gap is None:
            gap = int(self.side_by_side_gap)

        # Both images are portrait here (caller checks), determine target height
        target_height = float(photo_height) if photo_height is not None else float(self.portrait_height)
        h1 = target_height
        w1 = target_height / aspect1
        h2 = target_height
        w2 = target_height / aspect2

        total_width = w1 + gap + w2
        max_width = self.width - 60
        if total_width > max_width:
            scale = max_width / total_width
            w1 *= scale
            h1 *= scale
            w2 *= scale
            h2 *= scale
            total_width = max_width

        pair_height = max(h1, h2)

        if self.y_position - pair_height < 50:
            self.new_page()

        x_left = (self.width - total_width) / 2.0 if centered else 30
        x1 = x_left
        x2 = x_left + w1 + gap

        # Draw images (aligned to top of current y_position) with border
        self._draw_image_with_border(image1, x1, self.y_position - h1, w1, h1)
        self._draw_image_with_border(image2, x2, self.y_position - h2, w2, h2)

        self.y_position = self.y_position - pair_height - 20

    def _format_weather(self, condition: str | None, temp: float | None) -> str:
        """Format weather info as a short string with an emoji (when known) and temperature.

        Examples: '⛅ 19°C' or 'Partly Cloudy 19°C' if emoji not mapped.
        """
        if not condition and temp is None:
            return ""
        # Map known conditions to compact emoji
        mapping = {
            "partly-cloudy-day": "⛅",
            "partly-cloudy-night": "☁️",
            "cloudy": "☁️",
            "rain": "🌧️",
            "clear-day": "☀️",
            "clear-night": "🌙",
            "snow": "❄️",
            "fog": "🌫️",
            "wind": "💨",
        }
        emoji = mapping.get(condition, "")
        if not emoji:
            # fallback to readable label
            emoji = (condition.replace("-", " ").title() if condition else "")
        temp_text = f"{int(round(temp))}°C" if temp is not None else ""
        return f"{emoji} {temp_text}".strip()

    def wrap_text(self, text: str, max_width: int) -> list:
        """Wrap text to fit within max_width."""
        self.canvas.setFont(*self.MAIN_FONT)
        lines = []
        words = text.replace("\n", " <newline> ").split()
        current_line = ""
        for word in words:
            if word == "<newline>":
                lines.append(current_line)
                current_line = ""
                continue

            test_line = f"{current_line} {word}".strip()
            if self.canvas.stringWidth(test_line) <= max_width:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word
        lines.append(current_line)
        return lines
