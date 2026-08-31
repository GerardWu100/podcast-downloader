# Podcast Downloader — Goal and Intent

This file is the anchor for every AI session in this repository. Judge all
suggestions, features, and refactors against the goal below. If work does not
serve it, say so instead of recommending it.

## Ultimate goal

Reliably turn selected online video sources (mostly YouTube channels and
playlists) into a clean, sponsor-free MP3 podcast library in Audiobookshelf,
self-hosted, with as little ongoing manual attention as possible.

The two words that matter most are "reliably" and "little attention". The
purpose of this project is listening to podcasts, not maintaining a
downloader. Work that makes the system more trustworthy or lower-touch serves
the goal; work that adds surface area without doing either does not.

## What "done" means

The build phase is complete. The pipeline, web UI, JSON API, browser
extensions, and Docker deployment all work and are tested. Remaining work is
operational: the system should be able to tell its operator when it has
quietly stopped working (heartbeat or digest notifications, cookie freshness,
detection of YouTube 403/PO-token breakage) rather than gain new features.

## In scope

- Download correctness and failure visibility.
- Keeping up with YouTube countermeasures (player clients, PO tokens,
  cookies) with the least possible manual intervention.
- Small listening-quality improvements that ride the existing pipeline, such
  as chapter markers.

## Out of scope

- Multi-user or multi-tenant operation. This is a personal tool; the three
  accounts that exist are enough.
- Transcripts, search, or research features.
- A public RSS feed. Audiobookshelf already handles distribution.
- Support for sites yt-dlp does not already handle incidentally.

## Standing invariants

- Success is defined by the filesystem, never by a subprocess exit code: an
  MP3 must appear or change in the active source folder.
- The MP3 `date` and `comment` tags are the retention database. Nothing may
  rewrite MP3 metadata without preserving both tags and the inode-preserving
  copy behavior, or retention and Audiobookshelf tracking break.
- One host, one instance. State files use advisory locks that assume a local
  filesystem; never run replicas or mount the data directory over a network
  filesystem.
- Queue and archive state changes only after verification, tagging, and
  publication all succeed, in that order.
