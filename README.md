# clipcast

Clipcast is a podcast server that uses AI to clip the adverts out of your favourite podcasts and serves a separate RSS feed to add to your usual podcast player.

## Features

- Search iTunes API for podcasts to import
- Use AI to identify adverts in the episodes and clip them out
- Serve RSS feed for the clipped episodes to add to your normal podcast player
- Supports Gemini for transcription/analysis on a BYOK basis and Whisper.cpp for local transcription
- Deploy with Docker Compose including optional container for local transcription

## Stack

- Python/Django web app
- SQLite database
- DjangoQ2 for background tasks, backed by SQLite
- HTMX for minimal web interactivity
- Deployed with Docker Compose

## Getting started

The app can be deployed with Docker Compose for ease, there is a compose file in the repo that can be used as an example.

The Django server and DjangoQ2 workers run in the same container, managed by supervisord.

On first run, you will be guided through configuring transcription and analysis models, adding a podcast and sending an episode to be clipped.

Once a podcast is added, a scheduled task will check for new episodes and send them through the ad-clipping process. One or all episodes can be clipped manually in the web UI.

The app offers an RSS feed for each podcast containing only the clipped episodes.

#### Local transcription

The app allows you to configure local transcription using a Whisper transcription server that is (or offers the same interface as) the one included in the Whisper.cpp repo [here](https://github.com/ggml-org/whisper.cpp/tree/master/examples/server).

I run the local transcription container on CPU, limited to 2 CPUs and one episode at a time. It takes about 15 mins per hour of audio which is fine for my library. However, if you listen to a large number of podcasts with frequent release schedules, you may want consider GPU acceleration or else the transcription server might get behind on its work.