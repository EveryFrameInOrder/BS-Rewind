# BS-Rewind
Rewind the BS, and maintain your social connections on BlueSky Social.

## What is this?
This is a collection of tools to help you move from Twitter to BlueSky Social. It is a work in progress and will be updated as needed.

It utilizes your Twitter Archive, publicly available data from Twitter, and the ATProto BlueSky Social API.

![gui.png](assets%2Fgui.png)

## Setup

### Step 1: Download your Twitter Archive
1. Go to [Twitter](https://twitter.com) and log in.
2. Click on your profile picture in the top right corner and select "Settings and privacy".
3. Scroll down to the bottom of the page and click on "Request your archive".
  <details>
  <summary>Click here to see a screenshot</summary>
  
  ![request-archive.png](assets%2Frequest-archive.png)
  </details>

4. Fill out your password
5. Wait for an email from Twitter with your 2FA code (if you have 2FA enabled)
6. Enter the 2FA code
7. It may take a bit for Twitter to prepare your archive. You should receive an email when it is ready, but don't rely on it. Check back in a few hours.
8. Download the archive when it is ready.

### Step 2: Extract your Twitter Archive
1. Unzip the archive you downloaded from Twitter.
2. There will be a folder called `data`.
3. Copy the `data` folder to the same directory as this README. We specifically need the `following.js` file in the `data` folder.

<details>
<summary>Build or Install</summary>

This project utilizes the [uv](https://github.com/astral-sh/uv) package manager.

1. Install `uv` by following the instructions [here](https://docs.astral.sh/uv/getting-started/installation/).\
2. You'll need Python 3.11.6, which you can download using uv:
```sh
uv python install 3.11.6
```

3. Install the dependencies:
```sh
uv pip install --requirement .\pyproject.toml
```

### Step 3: Run the tools, or build

#### AutoFollowGui
```sh
pyinstaller --onefile --noconsole .\AutoFollowGui.py
```

(There may be some issues with the build process, so you may need to troubleshoot, I'll be working to improve this if needed.)

</details>

**~ or ~**
### Download the latest release as a ZIP file
[AutoFollowGui](assets%2FBS-Rewind-Refollower-v0.1.zip)


## FAQ
<details>
<summary>Why do I need to download my Twitter Archive?</summary>
This allows us to programmatically grab accounts based on the Accounts ID.

We do NOT use the Twitter API to grab this information, as it is against the Twitter API TOS to use the API to grab account information for the purpose of following accounts.

Instead, we simply load the page, and attempt to grab the screen name from the page. This is why we need the Twitter Archive, as it contains the Account ID, which we can use to grab the screen name.
</details>

<details>
<summary>Why do I need to put in my Username and Password?</summary>
This is so we can log in to BlueSky and follow accounts for you. We do not store your username or password, and we do not have access to your account. This is all done locally on your machine.

It is recommended to use an [App Password](https://bsky.app/settings/app-passwords) to allow access to your account, rather than your main password.

In any case - your password is never stored, and is only used to log in to BlueSky. 

If you want to easily log in you can set `BLUESKY_LOGIN` and `BLUESKY_PASSWORD` as environment variables.

</details>

<details>
<summary>How can I make sure this is the same person I followed on Twitter?</summary>
This is a good question, and one that is difficult to answer. We are working on ways to verify this, but for now, you will have to manually verify this.

We recommend you only follow accounts you are sure are the same person you followed on Twitter. Very commonly, people will have the same username on BlueSky as they did on Twitter, so this is a good way to verify.

</details>
