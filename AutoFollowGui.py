import json
import os
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import parse_qs, urlparse

import httpx
import orjson
import undetected_chromedriver as uc
from atproto import Client, models
from auto_download_undetected_chromedriver import (
    download_undetected_chromedriver,
)
from PySide6.QtCore import (
    QMutex,
    QMutexLocker,
    QObject,
    Qt,
    QThread,
    Signal,
    Slot,
)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from rapidfuzz import fuzz

# Download the driver right next to the script
chromedriver_path = download_undetected_chromedriver(
    folder_path_for_exe=os.path.dirname(os.path.abspath(__file__))
)


@dataclass
class UserMapping:
    twitter_username: str
    atproto_username: str
    description: str
    avatar_url: Optional[str]
    did: str


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Bluesky Login')
        self.setModal(True)
        # Create layout and widgets
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.addWidget(
            QLabel('Please enter your Bluesky login credentials:')
        )
        self.username_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        login_button = QPushButton('Login')
        cancel_button = QPushButton('Cancel')
        # Connect buttons
        login_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        # Add widgets to layout
        layout.addWidget(QLabel('Email:'))
        layout.addWidget(self.username_input)
        layout.addWidget(QLabel('Password:'))
        layout.addWidget(self.password_input)
        button_layout = QHBoxLayout()
        button_layout.addWidget(login_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        self.setLayout(layout)

        self.username_input.setText(os.getenv('BLUESKY_LOGIN', ''))
        self.password_input.setText(os.getenv('BLUESKY_PASSWORD', ''))


class TwitterBlueskyMapper(QObject):
    new_mapping = Signal(UserMapping)
    error_occurred = Signal(str, str)  # message, level
    progress_update = Signal(int, int)  # current, total
    mapping_complete = Signal()
    critical_error_occurred = Signal(str)

    def __init__(
        self,
        cache_dir: str = 'cache',
        login: str = '',
        password: str = '',
        input_file: str = '',
    ):
        super().__init__()
        self.client = None
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.twitter_cache_file = self.cache_dir / 'twitter_cache.json'
        self.bluesky_cache_file = self.cache_dir / 'bluesky_cache.json'
        self.twitter_cache: Dict[str, str] = self._load_cache(
            self.twitter_cache_file
        )
        self.bluesky_cache: Dict[str, dict] = self._load_cache(
            self.bluesky_cache_file
        )
        self.twitter_mutex = QMutex()
        self.bluesky_mutex = QMutex()
        self.login = login
        self.password = password
        self.input_file = input_file

    def _load_cache(self, cache_file: Path) -> dict:
        """Load cache from file."""
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text())
            except json.JSONDecodeError:
                print(
                    f'Warning: Cache file {cache_file} is corrupted. Starting fresh.'
                )
        return {}

    def _save_cache(self, cache_file: Path, data: dict) -> None:
        """Save cache to file."""
        cache_file.write_text(json.dumps(data, indent=2))

    @staticmethod
    def load_user_entries(file_path: str) -> List[Dict]:
        """Load user entries from JSON file."""
        with open(file_path, 'r') as file:
            return orjson.loads(file.read())

    def get_twitter_username(
        self, driver: uc.Chrome, user_link: str
    ) -> Optional[str]:
        """Get Twitter username from user link with caching."""
        # Check cache first
        with QMutexLocker(self.twitter_mutex):
            if user_link in self.twitter_cache:
                return self.twitter_cache[user_link]

        try:
            driver.get(user_link)
            time.sleep(0.8)
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
                            self._save_cache(
                                self.twitter_cache_file, self.twitter_cache
                            )
                        return username

            with QMutexLocker(self.twitter_mutex):
                self.twitter_cache[user_link] = username
                self._save_cache(self.twitter_cache_file, self.twitter_cache)
            return username
        except Exception as e:
            error_message = f"Error fetching Twitter username for {user_link}: {e}\n{traceback.format_exc()}"
            print(error_message)  # Print for debugging
            self.error_occurred.emit(error_message, 'error')
            return None
        return None

    def get_atproto_user_info(self, twitter_username: str) -> Optional[dict]:
        """Get ATProto user information with caching."""
        # Check cache first
        with QMutexLocker(self.bluesky_mutex):
            if twitter_username in self.bluesky_cache:
                return self.bluesky_cache[twitter_username]

        try:
            handle = f'{twitter_username}'
            print(f'Fetching ATProto info for {twitter_username}...')
            profile = self.client.app.bsky.actor.search_actors(
                params={'q': handle, 'limit': 1}
            )

            data = {}
            if profile['actors']:
                actor = profile['actors'][0]

                # compare handles
                if actor.handle != handle:
                    bsky_handle = actor.handle.split('.')[0] if '.bsky' in actor.handle else actor.handle

                    threshold = 75 if '.bsky' in actor.handle else 55 # Lower threshold for custom domains

                    match_percent = fuzz.ratio(bsky_handle, handle)
                    if match_percent < threshold:
                        # Not a good match
                        return None


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
            error_message = f"Error fetching ATProto info for {twitter_username}: {e}\n{traceback.format_exc()}"
            print(error_message)
            self.error_occurred.emit(error_message, 'error')
            return None

    def current_followed(self) -> Set[str]:
        """Get the set of currently followed users."""
        try:
            followed = self.client.app.bsky.graph.follow.list(
                repo=self.client.me.did,
                params={'limit': 1000},
            )
            return {record for record in followed.records}
        except Exception as e:
            error_message = f"Error fetching followed users: {e}\n{traceback.format_exc()}"
            print(error_message)
            self.error_occurred.emit(error_message, 'error')
            return set()  # Return an empty set to avoid further issues

    @Slot()
    def process_users(self) -> None:
        """Main processing function."""
        try:
            # Load user entries
            try:
                user_entries = self.load_user_entries(self.input_file)
            except Exception as e:
                error_message = f"Error loading user entries: {e}\n{traceback.format_exc()}"
                print(error_message)
                self.critical_error_occurred.emit(error_message)
                return  # Halt processing

            user_links = [
                entry.get('following', {}).get('userLink')
                for entry in user_entries
                if entry.get('following', {}).get('userLink')
            ]
            total_users = len(user_links)
            self.progress_update.emit(0, total_users)
            current_user = 0

            twitter_usernames = {}

            # Initialize Chrome driver
            options = uc.ChromeOptions()
            options.headless = True
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--disable-extensions')
            # Enable performance logging
            options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
            try:
                driver = uc.Chrome(
                    driver_executable_path=chromedriver_path,
                    options=options,
                    use_subprocess=True,
                    version_main=130,
                )
            except Exception as e:
                error_message = f"Error initializing Chrome driver: {e}\n{traceback.format_exc()}"
                print(error_message)
                self.critical_error_occurred.emit(error_message)
                return  # Halt processing

            for user_link in user_links:
                QApplication.processEvents()
                twitter_username = self.get_twitter_username(
                    driver, user_link
                )
                if twitter_username:
                    twitter_usernames[user_link] = twitter_username

                    # Emit mapping with Twitter username and any cached atproto data
                    with QMutexLocker(self.bluesky_mutex):
                        bluesky_info = self.bluesky_cache.get(
                            twitter_username
                        )
                    if bluesky_info:
                        mapping = UserMapping(
                            twitter_username=twitter_username,
                            atproto_username=bluesky_info.get('handle'),
                            description=bluesky_info.get('description'),
                            avatar_url=bluesky_info.get('avatar'),
                            did=bluesky_info.get('did'),
                        )
                    else:
                        mapping = UserMapping(
                            twitter_username=twitter_username,
                            atproto_username='',
                            description='',
                            avatar_url=None,
                            did='',
                        )
                    self.new_mapping.emit(mapping)

                current_user += 1
                self.progress_update.emit(current_user, total_users)
                QApplication.processEvents()
            driver.quit()
            # Now we have twitter_usernames mapping user_link -> twitter_username

            # Collect Twitter usernames and see which ones we have Bluesky info for
            twitter_usernames_set = set(twitter_usernames.values())

            missing_twitter_usernames = []
            with QMutexLocker(self.bluesky_mutex):
                for twitter_username in twitter_usernames_set:
                    if twitter_username not in self.bluesky_cache:
                        missing_twitter_usernames.append(twitter_username)

            # Now login to Bluesky
            self.error_occurred.emit('Logging into Bluesky...', 'info')
            try:
                self.client = Client()
                self.client.login(
                    login=self.login,
                    password=self.password,
                )
            except Exception as e:
                error_message = f"Error logging into Bluesky: {e}\n{traceback.format_exc()}"
                print(error_message)
                self.critical_error_occurred.emit(error_message)
                return  # Halt processing

            self.error_occurred.emit('Logged into Bluesky.', 'info')

            # Now process missing Twitter usernames
            total_missing = len(missing_twitter_usernames)
            for idx, twitter_username in enumerate(
                missing_twitter_usernames, 1
            ):
                data = self.get_atproto_user_info(twitter_username)
                if data:
                    mapping = UserMapping(
                        twitter_username=twitter_username,
                        atproto_username=data.get('handle'),
                        description=data.get('description'),
                        avatar_url=data.get('avatar'),
                        did=data.get('did'),
                    )
                    # Update the mapping
                    self.new_mapping.emit(mapping)
                self.progress_update.emit(idx, total_missing)

            # Emit mapping_complete signal
            self.mapping_complete.emit()

        except Exception as e:
            error_message = f"Critical error in main processing: {e}\n{traceback.format_exc()}"
            print(error_message)
            self.critical_error_occurred.emit(error_message)
        finally:
            if self.client:
                del self.client


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Twitter to Bluesky Mapper')
        self.resize(800, 600)
        self.setMaximumSize(1200, 600)

        # Initialize member variables
        self.followed_dids: Set[str] = set()
        self.avatar_cache: dict = {}
        self.client: Optional[Client] = None
        self.logged_in_user: str = ''
        self.twitter_username_to_row: Dict[str, int] = {}
        self.row_to_mapping: Dict[int, UserMapping] = {}

        # Setup UI and login
        login_dialog = LoginDialog()
        if login_dialog.exec() == QDialog.DialogCode.Accepted:
            self.bluesky_login = login_dialog.username_input.text()
            self.bluesky_password = login_dialog.password_input.text()
        else:
            sys.exit()  # User canceled login

        # Attempt to login to Bluesky
        try:
            self.client = Client()
            self.client.login(login=self.bluesky_login, password=self.bluesky_password)
            self.logged_in_user = self.client.me.handle
        except Exception as e:
            self.show_error_message(f'Login failed: {str(e)}')
            sys.exit()  # Halt processing due to critical error

        self.convert_file()

        # Proceed with setting up the UI
        self.setup_ui()

        # Initialize the worker
        self.worker_thread = QThread()
        self.worker = TwitterBlueskyMapper(
            login=self.bluesky_login,
            password=self.bluesky_password,
            input_file='./data/following.json',
        )
        self.worker.moveToThread(self.worker_thread)
        self.worker.new_mapping.connect(self.add_mapping_to_table)
        self.worker.error_occurred.connect(self.update_status_message)
        self.worker.progress_update.connect(self.update_progress)
        self.worker.mapping_complete.connect(self.enable_checkboxes)
        self.worker.critical_error_occurred.connect(self.handle_critical_error)

        # Handle unexpected thread termination
        self.worker_thread.finished.connect(self.handle_worker_finished)
        self.worker_thread.destroyed.connect(self.handle_worker_terminated)

        self.worker_thread.started.connect(self.worker.process_users)
        self.worker_thread.start()

        # Progress tracking
        self.progress_bar = QProgressBar()
        self.layout.addWidget(self.progress_bar)
        self.progress_bar.hide()

    def convert_file(self):
        data_path = Path("data")
        if not data_path.exists():
            # Show error message and exit
            self.show_error_message(
                "Please copy the `data` folder from your Twitter data export to the same directory as this script."
            )
            sys.exit()

        following_js = data_path / "following.js"
        following_json = data_path / "following.json"
        if not following_json.exists() and not following_js.exists():
            # Show error message and exit
            self.show_error_message(
                "Please ensure the `following.js` or `following.json` file is present in the `data` folder."
            )
            sys.exit()
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
                        # Show error message and exit
                        self.show_error_message(
                            "Please copy the `data` folder from your Twitter data export to the same directory as this script."
                        )
                        sys.exit()

                    current_value = current_value.strip().replace(
                        "window.YTD.following.part0 = ", ""
                    )
                    json_f.seek(0)
                    json_f.write(current_value)

    def setup_ui(self):
        """Initialize and setup all UI components"""
        # Create main widget and layout
        self.central_widget = QWidget()
        self.layout = QVBoxLayout(self.central_widget)
        self.setCentralWidget(self.central_widget)

        # Logged-in user label
        self.logged_in_user_label = QLabel(f'Logged in as: {self.logged_in_user}')
        self.layout.addWidget(self.logged_in_user_label)

        # Create table
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(5)
        self.table_widget.setHorizontalHeaderLabels(
            [
                'Avatar',
                'Twitter Username',
                'Bluesky Username',
                'Description',
                'Select',
            ]
        )

        # Configure table properties
        header = self.table_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table_widget.setColumnWidth(0, 60)
        self.table_widget.setColumnWidth(4, 60)

        # Minimum row size to fit the avatar
        self.table_widget.verticalHeader().setDefaultSectionSize(60)

        # Ensure the rows will be resized to fit the content and at least the size of the Avatar
        self.table_widget.setSizeAdjustPolicy(
            QTableWidget.SizeAdjustPolicy.AdjustToContents
        )
        self.table_widget.setMinimumSize(1200, 600)

        # Add "Check All" button
        self.check_all_button = QPushButton('Check All')
        self.check_all_button.clicked.connect(self.check_all_users)
        self.layout.addWidget(self.check_all_button)

        # Follow Selected Users button
        self.follow_selected_button = QPushButton('Follow Selected Users')
        self.follow_selected_button.clicked.connect(self.follow_selected_users)
        self.follow_selected_button.setEnabled(False)

        self.layout.addWidget(self.follow_selected_button)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Enable row-click for check/uncheck
        self.table_widget.cellClicked.connect(self.toggle_row_check)
        self.layout.addWidget(self.table_widget)

    @Slot(UserMapping)
    def add_mapping_to_table(self, mapping: UserMapping):
        """Add a new mapping entry to the table with auto-check for 95% matches"""
        try:
            row = self.table_widget.rowCount()
            self.table_widget.insertRow(row)
            self.twitter_username_to_row[mapping.twitter_username] = row

            # Create widgets
            avatar_label = QLabel()
            avatar_label.setFixedSize(50, 50)
            avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            # Set widgets and items
            self.table_widget.setCellWidget(row, 0, avatar_label)
            self.table_widget.setItem(
                row, 1, QTableWidgetItem(mapping.twitter_username)
            )
            self.table_widget.setItem(
                row, 2, QTableWidgetItem(mapping.atproto_username)
            )
            self.table_widget.setItem(
                row, 3, QTableWidgetItem(mapping.description)
            )

            checkbox = QCheckBox()
            # Automatically check based on match percentage or already followed users
            is_followed = mapping.did in self.followed_dids
            if (
                is_followed
                or fuzz.ratio(
                    mapping.twitter_username, mapping.atproto_username
                )
                >= 95
            ):
                checkbox.setChecked(True)
            checkbox.setEnabled(False)
            checkbox_layout = QHBoxLayout()
            checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            checkbox_layout.addWidget(checkbox)
            checkbox_widget = QWidget()
            checkbox_widget.setLayout(checkbox_layout)
            self.table_widget.setCellWidget(row, 4, checkbox_widget)

            # Store mapping
            self.row_to_mapping[row] = mapping

            # Schedule avatar fetch if needed
            if mapping.avatar_url:
                self.fetch_avatar(mapping.avatar_url, avatar_label)

            # Ensure table updates
            self.table_widget.viewport().update()

        except Exception as e:
            self.show_error_message(f'Error updating table: {str(e)}')

    @Slot(int, int)
    def toggle_row_check(self, row: int, column: int):
        """Toggle the checkbox in a row when the row is clicked"""
        if (
            column != 4
        ):  # Ensure it doesn't conflict with the checkbox column itself
            checkbox_widget = self.table_widget.cellWidget(row, 4)
            checkbox = checkbox_widget.findChild(QCheckBox) if checkbox_widget else None
            if checkbox and checkbox.isEnabled():
                checkbox.setChecked(not checkbox.isChecked())

    @Slot()
    def check_all_users(self):
        """Check all checkboxes in the table"""
        for row in range(self.table_widget.rowCount()):
            checkbox_widget = self.table_widget.cellWidget(row, 4)
            checkbox = checkbox_widget.findChild(QCheckBox) if checkbox_widget else None
            if checkbox:
                checkbox.setChecked(True)

    def get_client(self) -> Client:
        """Get an authenticated Bluesky client"""
        if self.client is None or not hasattr(self.client, 'me'):
            self.client = Client()
            self.client.login(
                login=self.bluesky_login,
                password=self.bluesky_password,
            )
            self.logged_in_user = self.client.me.handle
            self.logged_in_user_label.setText(
                f'Logged in as: {self.logged_in_user}'
            )

        return self.client

    def fetch_avatar(self, url: str, avatar_label: QLabel) -> None:
        """Fetch and cache avatar images"""
        if url in self.avatar_cache:
            pixmap = self.avatar_cache[url]
            avatar_label.setPixmap(pixmap)
            return

        try:
            response = httpx.get(url, timeout=10)
            response.raise_for_status()
            if response.headers.get('Content-Type', '').startswith('image/'):
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
                    avatar_label.setPixmap(scaled_pixmap)
        except httpx.RequestError as e:
            print(f'Network error fetching avatar: {e}')
        except Exception as e:
            print(f'Error fetching avatar: {e}')

    def follow_selected_users(self):
        """Follow the selected users"""
        try:
            for row in range(self.table_widget.rowCount()):
                checkbox_widget = self.table_widget.cellWidget(row, 4)
                checkbox = checkbox_widget.findChild(QCheckBox) if checkbox_widget else None
                if checkbox and checkbox.isChecked():
                    mapping = self.row_to_mapping.get(row)
                    if (
                        mapping
                        and mapping.did
                        and mapping.did not in self.followed_dids
                    ):
                        # Disable the checkbox to prevent multiple follows
                        checkbox.setEnabled(False)
                        self.follow_user(mapping.did, row)
        except Exception as e:
            self.show_error_message(f'Error following selected users: {str(e)}')

    def follow_user(self, did: str, row: int):
        """Follow a user with retry logic for rate limits."""
        try:
            client = self.get_client()
            max_retries = 5
            retry_delay = 1  # Initial delay in seconds

            self.status_bar.showMessage(f'Attempting to follow user {did}')

            for attempt in range(max_retries):
                try:
                    client.app.bsky.graph.follow.create(
                        record=models.AppBskyGraphFollow.Record(
                            subject=did,
                            created_at=datetime.now(tz=timezone.utc).strftime(
                                '%Y-%m-%dT%H:%M:%SZ'
                            ),
                        ),
                        repo=client.me.did,
                    )
                    self.followed_dids.add(did)
                    self.status_bar.showMessage(
                        f'Successfully followed user {did}'
                    )
                    # Update UI to reflect that the user is followed
                    checkbox_widget = self.table_widget.cellWidget(row, 4)
                    checkbox = checkbox_widget.findChild(QCheckBox) if checkbox_widget else None
                    if checkbox:
                        checkbox.setText('Followed')
                        checkbox.setEnabled(False)
                    return

                except Exception as e:
                    if '429' in str(e):  # Rate limit error
                        if attempt < max_retries - 1:
                            self.status_bar.showMessage(
                                f'Rate limited. Retrying in {retry_delay} seconds...'
                            )
                            for _ in range(retry_delay):
                                QApplication.processEvents()
                                time.sleep(1)
                            retry_delay *= 2  # Exponential backoff
                            continue
                    raise e

        except Exception as e:
            self.show_error_message(f'Error following user: {str(e)}')
            self.status_bar.showMessage(f'Error following user {did}')

    @Slot()
    def enable_checkboxes(self):
        """Enable the checkboxes after mapping is complete."""
        for row in range(self.table_widget.rowCount()):
            QApplication.processEvents()
            checkbox_widget = self.table_widget.cellWidget(row, 4)
            checkbox = checkbox_widget.findChild(QCheckBox) if checkbox_widget else None
            if checkbox:
                mapping = self.row_to_mapping.get(row)
                if mapping and mapping.did:
                    checkbox.setEnabled(True)
        self.follow_selected_button.setEnabled(True)
        self.status_bar.showMessage('Mapping complete.')

    @Slot(str)
    def show_error_message(self, message: str):
        """Display error message to user with detailed traceback"""
        QMessageBox.critical(self, 'Error', message)

    @Slot(int, int)
    def update_progress(self, current: int, total: int):
        """Update the progress bar"""
        if total == 0:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
            self.status_bar.showMessage(f'Processing {current}/{total} - The UI may be unresponsive during this time.')
            self.progress_bar.show()

    @Slot(str, str)
    def update_status_message(self, message: str, level: str = 'info'):
        """Update the status bar message."""
        if level == 'error':
            self.status_bar.showMessage(f'Error: {message}')
        else:
            self.status_bar.showMessage(message)

    @Slot(str)
    def handle_critical_error(self, message: str):
        """Handle critical errors from the worker."""
        self.show_error_message(message)
        self.worker_thread.quit()
        self.worker_thread.wait()

    @Slot()
    def handle_worker_finished(self):
        """Handle normal worker thread completion."""
        # You can add any cleanup or UI updates here
        pass

    @Slot()
    def handle_worker_terminated(self):
        """Handle unexpected worker thread termination."""
        self.show_error_message("The processing thread was terminated unexpectedly.")
        # Perform any necessary cleanup

    def closeEvent(self, event):
        """Clean up resources when window is closed"""
        try:
            if self.client:
                del self.client
            if self.worker_thread.isRunning():
                self.worker_thread.quit()
                self.worker_thread.wait()
            event.accept()
        except Exception as e:
            print(f'Error during cleanup: {e}')
            event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    if 'driver' in locals():
        driver.quit()   # noqa

    sys.exit(app.exec())
