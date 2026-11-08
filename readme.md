# Kimi Usage Monitor

A lightweight menu bar application that tracks your [Kimi Code](https://www.kimi.ai/) CLI usage quota, ensuring you never get caught off guard by hitting session limits mid-task.


## Setup & Run

1. **Prerequisite:** Ensure the Kimi Code CLI is installed and available in your `PATH` (the `kimi-code-usage` command must be executable). I preferred to install it via `pipx`.
2. **Download:** Grab the latest version from the Releases, or build it from source.
3. **Configuration:** Launch the app, open **Settings**, and paste your API key (`sk-kimi-...`). 
4. **macOS Gatekeeper Note:** Since the app is currently unsigned, macOS may block it on the first launch. To allow it, right-click the app icon and select **Open**, or navigate to **System Settings → Privacy & Security** and click **Open Anyway**.
5. **Customize:** Adjust the background refresh interval and alert threshold to your preference.

## Features

* **Live Quota Tracking** — Polls the `kimi-code-usage` CLI in the background, displaying your 5-hour/6-hour session limits via a clean ring gauge alongside the remaining percentage and reset countdown.
* **Menu Bar Integration** — Sits quietly in your system tray with a handy tooltip showing current usage. Click to open the dashboard; closing the window keeps the utility running smoothly in the background.
* **Smart Alerts** — Receive a system notification (with optional sound) whenever your usage crosses your custom threshold, allowing you to space out requests before hitting the cap.
* **Color-Coded Status** — Dynamically shifts from green to yellow and red as usage climbs, complete with an "On pace / Over threshold" status badge.
* **Highly Configurable** — Easily tweak refresh intervals (1–1440 min), alert thresholds (1–100%), and toggle notification sounds directly from the in-app Settings dialog.

## Technical Details

* Built with **PySide6** (Qt for Python).
* Compiled and packaged using **Nuitka** for standalone performance.

## Security Attention

Your API key is stored in `~/Library/Application Support/Kimi Usage Monitor/config.json` in macOS and in `%APPDATA%\Kimi Usage Monitor\config.json
` in Windows.

## License

This project is licensed under the **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)** License. 

You are free to share, copy, and modify this software for personal and educational purposes. **Commercial use of this software is strictly prohibited.**

## Acknowledgments

This project is built on top of the excellent [kimi-code-usage](https://github.com/Golden0Voyager/kimi-code-usage) CLI utility developed by [Haining Yu](https://github.com/Golden0Voyager). Special thanks to the author for creating the foundational toolchain that makes this monitor possible.
