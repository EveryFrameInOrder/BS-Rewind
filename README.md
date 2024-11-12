# BS-Rewind
Tools to help you move from Twitter to BlueSky Social.

## What is this?
This is a collection of tools to help you move from Twitter to BlueSky Social. It is a work in progress and will be updated as needed.

It utilizes your Twitter Archive, publicly available data from Twitter, and the ATProto BlueSky Social API.

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
3. Copy the `data` folder to the same directory as this README.

### Step 3: Install Python

This project utilizes the [uv](https://github.com/astral-sh/uv) package manager.

1. Install `uv` by following the instructions [here](https://docs.astral.sh/uv/getting-started/installation/).\
2. You'll need Python 3.12, which you can download using uv:
```sh
uv python install 3.12
```

3. Install the dependencies:
```sh
uv pip install --requirement .\pyproject.toml
```



