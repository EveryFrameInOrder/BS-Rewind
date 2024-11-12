import asyncio
import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass

import httpx
import undetected_chromedriver as uc
import orjson
from atproto import AsyncClient, models

from PySide6.QtCore import QObject, Signal, Slot, QTimer, QThread, QMutex, QMutexLocker
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QLabel,
    QHeaderView,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
)
from PySide6.QtGui import QPixmap, Qt
import sys
from io import BytesIO

import qasync
from qasync import asyncSlot


@dataclass
class UserMapping:
    twitter_username: str
    atproto_username: str
    description: str
    avatar_url: Optional[str]
    did: str


class TwitterBlueskyMapper(QObject):
    new_mapping = Signal(UserMapping)
    error_occurred = Signal(str)

    def __init__(self, cache_dir: str = 'cache'):
        super().__init__()
        self.client = AsyncClient()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.twitter_cache_file = self.cache_dir / 'twitter_cache.json'
        self.bluesky_cache_file = self.cache_dir / 'bluesky_cache.json'
        self.twitter_cache: Dict[str, str] = self._load_cache(self.twitter_cache_file)
        self.bluesky_cache: Dict[str, dict] = self._load_cache(self.bluesky_cache_file)
        self.twitter_mutex = QMutex()
        self.bluesky_mutex = QMutex()

    def _load_cache(self, cache_file: Path) -> dict:
        """Load cache from file."""
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text())
            except json.JSONDecodeError:
                print(f'Warning: Cache file {cache_file} is corrupted. Starting fresh.')
        return {}

    def _save_cache(self, cache_file: Path, data: dict) -> None:
        """Save cache to file."""
        cache_file.write_text(json.dumps(data, indent=2))

    @staticmethod
    def load_user_entries(file_path: str) -> List[Dict]:
        """Load user entries from JSON file."""
        with open(file_path, 'r') as file:
            return orjson.loads(file.read())

    def get_twitter_username(self, driver: uc.Chrome, user_link: str) -> Optional[str]:
        """Get Twitter username from user link with caching."""
        # Check cache first
        with QMutexLocker(self.twitter_mutex):
            if user_link in self.twitter_cache:
                return self.twitter_cache[user_link]

        try:
            driver.get(user_link)
            time.sleep(2)
            logs = driver.get_log('performance')
            username = None

            for entry in logs:
                message = json.loads(entry['message'])
                method = message['message']['method']

                if method != 'Page.navigatedWithinDocument':
                    continue

                message_params = message['message']['params']

                if 'url' not in message_params:
                    continue

                current_url = message_params['url']
                parsed_url = urlparse(current_url)
                query_params = parse_qs(parsed_url.query)

                if 'screen_name' in query_params:
                    username = query_params['screen_name'][0]
                    if username:
                        # Cache the result
                        with QMutexLocker(self.twitter_mutex):
                            self.twitter_cache[user_link] = username
                            self._save_cache(self.twitter_cache_file, self.twitter_cache)
                        return username

            if username:
                # Cache the result
                with QMutexLocker(self.twitter_mutex):
                    self.twitter_cache[user_link] = username
                    self._save_cache(self.twitter_cache_file, self.twitter_cache)
                return username
        except Exception as e:
            print(f'Error fetching Twitter username: {e}')
            self.error_occurred.emit(f'Error fetching Twitter username: {e}')
        return None

    async def get_atproto_user_info(self, twitter_username: str) -> Optional[dict]:
        """Get ATProto user information with caching."""
        # Check cache first
        with QMutexLocker(self.bluesky_mutex):
            if twitter_username in self.bluesky_cache:
                return self.bluesky_cache[twitter_username]

        
        try:
            handle = f'{twitter_username}'
            print(f'Fetching ATProto info for {twitter_username}...')
            profile = await self.client.app.bsky.actor.search_actors(
                params={'q': handle, 'limit': 1}
            )

            if not profile['actors']:
                return None

            actor = profile['actors'][0]
            data = {
                'did': actor.did,
                'handle': actor.handle,
                'avatar': actor.avatar,
                'description': actor.description,
                'screen_name': actor.display_name,
            }
            # Cache the result
            with QMutexLocker(self.bluesky_mutex):
                self.bluesky_cache[twitter_username] = data
                self._save_cache(self.bluesky_cache_file, self.bluesky_cache)
            return data
        except Exception as e:
            print(f'Error fetching ATProto info for {twitter_username}: {e}')
            self.error_occurred.emit(f'Error fetching ATProto info for {twitter_username}: {e}')
            return None

    async def process_users(self, input_file: str) -> None:
        """Main processing function."""
        try:
            # Login to Bluesky
            await self.client.login(
                login=os.getenv('BLUESKY_LOGIN'),
                password=os.getenv('BLUESKY_PASSWORD'),
            )

            user_entries = self.load_user_entries(input_file)

            # Configure ChromeOptions
            options = uc.ChromeOptions()
            options.headless = True
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--disable-extensions')

            # Enable performance logging
            options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

            with uc.Chrome(options=options, use_subprocess=True) as driver:
                for entry in user_entries:
                    user_link = entry.get('following', {}).get('userLink')
                    if not user_link:
                        continue

                    twitter_username = self.get_twitter_username(
                        driver, user_link
                    )
                    if not twitter_username:
                        continue

                    data = await self.get_atproto_user_info(twitter_username)

                    if not data:
                        continue

                    atproto_username = data.get('handle')
                    description = data.get('description')
                    avatar_url = data.get('avatar')
                    did = data.get('did')
                    if not atproto_username:
                        continue

                    mapping = UserMapping(
                        twitter_username=twitter_username,
                        atproto_username=atproto_username,
                        description=description,
                        avatar_url=avatar_url,
                        did=did,
                    )
                    # Emit the mapping
                    self.new_mapping.emit(mapping)

        except Exception as e:
            print(f'Error in main processing: {e}')
            self.error_occurred.emit(f'Error in main processing: {e}')
        finally:
            del self.client


class Worker(QObject):
    new_mapping = Signal(UserMapping)
    error_occurred = Signal(str)

    def __init__(self, input_file: str):
        super().__init__()
        self.mapper = TwitterBlueskyMapper()
        self.input_file = input_file
        self.mapper.new_mapping.connect(self.handle_new_mapping)
        self.mapper.error_occurred.connect(self.error_occurred.emit)

    async def mapper_process(self):
        await self.mapper.process_users(self.input_file)

    @Slot(UserMapping)
    def handle_new_mapping(self, mapping: UserMapping):
        self.new_mapping.emit(mapping)


import qasync


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Twitter to Bluesky Mapper")
        self.resize(800, 600)
        self.setMaximumSize(800, 600)

        # Initialize member variables
        self.followed_dids: Set[str] = set()
        self.avatar_cache: dict = {}
        self.client: Optional[AsyncClient] = None
        self.mapping_queue: asyncio.Queue = asyncio.Queue()
        self.follow_queue: asyncio.Queue = asyncio.Queue()  # New follow queue

        # Setup UI
        self.setup_ui()

        data_path = Path("data")
        if not data_path.exists():
            raise FileNotFoundError("Please copy the `data` folder from your Twitter data export to the current directory.")

        following_js = data_path / "following.js"
        following_json = data_path / "following.json"
        if not following_json.exists() and not following_js.exists():
            raise FileNotFoundError("Please copy the `following.js` file from your Twitter data export to the `data` folder.")

        if following_js.exists():
            # make a backup of the original file
            following_js_backup = data_path / "following.js.bak"
            following_js_backup.touch(exist_ok=True)
            with following_js.open("r") as f:
                with following_js_backup.open("w") as f_backup:
                    f_backup.write(f.read())

            with following_js.open("r+") as f:
                with following_json.open("w") as json_f:
                    current_value = f.read()
                    if not current_value:
                        raise ValueError("Please copy the `following.json` file from your Twitter data export to the `data` folder.")

                    current_value = current_value.strip().replace('window.YTD.following.part0 = ', '')
                    json_f.seek(0)
                    json_f.write(current_value)


        # Initialize the worker
        self.worker = Worker(input_file="./data/following.json")
        self.worker.new_mapping.connect(self.queue_mapping)
        self.worker.error_occurred.connect(self.show_error_message)

        # Progress tracking
        self.progress_bar = QProgressBar()
        self.layout.addWidget(self.progress_bar)
        self.progress_bar.hide()


    def setup_ui(self):
        """Initialize and setup all UI components"""
        # Start processing after event loop starts
        QTimer.singleShot(0, self.start_mapper_process)
        # Create main widget and layout
        self.central_widget = QWidget()
        self.layout = QVBoxLayout(self.central_widget)
        self.setCentralWidget(self.central_widget)

        # Setupz table
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(5)
        self.table_widget.setHorizontalHeaderLabels(
            ["Avatar", "Twitter Username", "Bluesky Username", "Description", "Follow"]
        )

        # Configure table properties
        header = self.table_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        # Ensure the rows will be resized to fit the content and at least the size of the Avatar
        self.table_widget.setSizeAdjustPolicy(QTableWidget.SizeAdjustPolicy.AdjustToContents)
        self.table_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table_widget.setMaximumSize(800, 600)

        # Scroll bar policy
        self.table_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.layout.addWidget(self.table_widget)

    async def get_client(self) -> AsyncClient:
        """Get an authenticated Bluesky client"""

        if self.client is None or not hasattr(self.client, 'me'):
            self.client = AsyncClient()
            await self.client.login(
                login=os.getenv("BLUESKY_LOGIN"),
                password=os.getenv("BLUESKY_PASSWORD"),
            )
            while not self.client.me:
                await asyncio.sleep(1)

        return self.client

    @qasync.asyncSlot()
    async def start_mapper_process(self):
        """Initialize the mapping process"""
        try:
            self.progress_bar.setRange(0, 0)  # Indeterminate progress
            self.progress_bar.show()

            # Start the mapper process and the mapping consumer
            asyncio.create_task(self.worker.mapper_process())
            asyncio.create_task(self.process_mapping_queue())
            asyncio.create_task(self.process_follow_queue())  # Moved here
            asyncio.create_task(self.get_followed_users())

        except Exception as e:
            self.show_error_message(f"Failed to start mapping process: {str(e)}")
        finally:
            self.progress_bar.hide()

    async def get_followed_users(self):
        """Fetch list of users already being followed"""
        try:
            client = AsyncClient()
            await client.login(
                login=os.getenv("BLUESKY_LOGIN"),
                password=os.getenv("BLUESKY_PASSWORD"),
            )

            followed = []
            cursor = None

            last_cursor = None
            while True:
                response = await client.app.bsky.graph.follow.list(
                    repo=client.me.did, cursor=cursor, limit=100
                )
                followed.extend(response.records)
                cursor = response.cursor

                if not cursor or cursor == last_cursor:
                    break

                last_cursor = cursor
                # Process events to keep UI responsive
                QApplication.processEvents()

            self.followed_dids = {user for user in followed}

        except Exception as e:
            self.show_error_message(f"Error retrieving followed users: {str(e)}")

    async def process_follow_queue(self):
        """Process the follow queue and follow users sequentially."""
        while True:
            did, button = await self.follow_queue.get()
            await self.follow_user(did, button)
            self.follow_queue.task_done()

    def queue_follow(self, did: str, button: QPushButton):
        """Queue a follow request."""
        self.follow_queue.put_nowait((did, button))

    async def fetch_avatar(self, url: str) -> Optional[QPixmap]:
        """Asynchronously fetch and cache avatar images"""
        if url in self.avatar_cache:
            return self.avatar_cache[url]

        try:
            async with httpx.AsyncClient() as session:
                response = await session.get(url, timeout=10)
                if response.status_code == 200 and response.headers['Content-Type'].startswith('image/'):
                    data = response.content
                    pixmap = QPixmap()
                    if pixmap.loadFromData(data):
                        scaled_pixmap = pixmap.scaled(
                            50,
                            50,
                            aspectMode=Qt.AspectRatioMode.KeepAspectRatio,
                            mode=Qt.TransformationMode.SmoothTransformation,
                        )
                        self.avatar_cache[url] = scaled_pixmap
                        return scaled_pixmap
        except Exception as e:
            print(f"Error fetching avatar: {e}")
        return None

    @Slot(UserMapping)
    def queue_mapping(self, mapping: UserMapping):
        """Queue mappings to be added to the UI"""
        self.mapping_queue.put_nowait(mapping)

    async def process_mapping_queue(self):
        """Process the mapping queue and add entries to the table"""
        while True:
            mapping = await self.mapping_queue.get()
            await self.add_mapping(mapping)
            self.mapping_queue.task_done()

    async def add_mapping(self, mapping: UserMapping):
        """Add a new mapping entry to the table."""
        try:
            if not mapping.atproto_username:
                return

            row = self.table_widget.rowCount()
            self.table_widget.insertRow(row)

            # Avatar
            avatar_label = QLabel()
            avatar_label.setFixedSize(50, 50)
            avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if mapping.avatar_url:
                pixmap = await self.fetch_avatar(mapping.avatar_url)
                if pixmap:
                    avatar_label.setPixmap(pixmap)
            self.table_widget.setCellWidget(row, 0, avatar_label)
            self.table_widget.resizeRowsToContents()

            # Text fields
            self.table_widget.setItem(
                row, 1, QTableWidgetItem(mapping.twitter_username)
            )
            self.table_widget.setItem(
                row, 2, QTableWidgetItem(mapping.atproto_username)
            )
            if mapping.atproto_username.lower().startswith(mapping.twitter_username.lower()):
                self.table_widget.item(row, 2).setBackground(Qt.GlobalColor.green)
            self.table_widget.setItem(row, 3, QTableWidgetItem(mapping.description))

            # Follow button
            follow_button = QPushButton("Follow")
            if mapping.did in self.followed_dids:
                follow_button.setText("Following")
                follow_button.setEnabled(False)
            else:
                follow_button.clicked.connect(
                    lambda _, did=mapping.did, btn=follow_button: self.queue_follow(
                        did, btn
                    )
                )
            self.table_widget.setCellWidget(row, 4, follow_button)

            # Process events to keep UI responsive
            QApplication.processEvents()

        except Exception as e:
            self.show_error_message(f"Error adding mapping: {str(e)}")

    async def follow_user(self, did: str, button: QPushButton):
        """Follow a user with retry logic for rate limits."""
        try:
            client = await self.get_client()
            max_retries = 5
            retry_delay = 1  # Initial delay in seconds

            button.setEnabled(False)
            button.setText("Following...")

            for attempt in range(max_retries):
                try:
                    await client.app.bsky.graph.follow.create(
                        record=models.AppBskyGraphFollow.Record(
                            subject=did,
                            created_at=datetime.now(tz=timezone.utc).strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            ),
                        ),
                        repo=client.me.did,
                    )
                    self.followed_dids.add(did)
                    button.setText("Following")
                    return

                except Exception as e:
                    if "429" in str(e):  # Rate limit error
                        if attempt < max_retries - 1:
                            button.setText(f"Retrying ({attempt + 1}/{max_retries})")
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                            continue
                    raise e

        except Exception as e:
            button.setEnabled(True)
            button.setText("Follow")
            self.show_error_message(f"Error following user: {str(e)}")

    @Slot(str)
    def show_error_message(self, message: str):
        """Display error message to user"""
        QMessageBox.critical(self, "Error", message)

    def closeEvent(self, event):
        """Clean up resources when window is closed"""
        if self.client:
            del self.client
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = MainWindow()
    window.show()
    with loop:
        loop.run_forever()
