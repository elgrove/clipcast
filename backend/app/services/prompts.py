TRANSCRIBE_AUDIO_PROMPT = """Transcribe this audio file with precise timestamps.
Return ONLY a JSON array of segments, each with start_time (seconds), end_time (seconds), and text.
Example format: [{"start_time": 0.0, "end_time": 5.5, "text": "Hello world"}]
Be precise with timestamps. Include all spoken content."""


ANALYSE_ADS_PROMPT = """You are an expert at analysing podcast transcripts to find advertising.

{context}

What counts as an advertisement (flag it):
- A paid promotion for an external company, product, or service — whether pre-recorded (a radio-style spot or a programmatic/network-inserted ad) or host-read (voiced by the hosts in their own words, woven into the show).
- Sponsorship cues: "sponsor", "brought to you by", "advertisement", "partner", "our friends at", a discount code, a vanity URL like brand.com/show, "go to X and use code Y".
- Watch for brand/product/company names and calls to action to visit or buy from a third party — but don't confuse a person's name with a company, or a passing brand mention in conversation with a paid plug.

What does NOT count (never flag it):
- The show's own promotion of itself: Patreon, memberships, merch, "subscribe/rate/review", "follow us on social", live-show tickets, or cross-promotion of other shows by the same hosts/network.
- Ordinary conversation, banter, news, interviews, or editorial content.
- A brand or product mentioned as part of the discussion that is not a paid plug.

Idents (short branding jingles) near an ad break need care — they fall into two categories:
- **Distributor / ad-break idents** (e.g. Acast's "This podcast is supported by...", or any network sting that announces or closes an ad break) are PART of the ad break. Extend the break to include them: start at the opening ident, end at the closing ident.
- **Show idents** (the podcast's own intro/outro stings, its regular branding) are CONTENT. Never include them in a break. If a show ident sits between the host's last words and the first ad, the break starts AFTER it.
- When unsure about an unfamiliar jingle, prefer keeping it as content (tighter break).

An "ad break" is one contiguous block of one or more back-to-back adverts; a single advert typically spans 10 to 60 seconds. For each break you identify, return:
- start_time and end_time of the whole break (the outer bounds covering every advert inside).
- adverts: the list of individual adverts within it. For each, give its own start_time, end_time, and advert_for (the company/product being advertised). This breakdown is required — naming who is advertised forces you to ground each break in real transcript content rather than guessing at boundaries.
Very rarely will two back-to-back adverts in one break be for the same company/brand/product. Use timestamps consistent with the transcript segments you are given. If there is no advertising, return an empty list of breaks. If any further instructions are appended below, they take precedence.

Transcript:
{transcript}"""


# Per-block priors fed into ANALYSE_ADS_PROMPT's {context} slot. They calibrate
# the model to the base rate of advertising in the block it's shown, without
# forking the shared definition of what an advert is.

ADS_CONTEXT_FULL_EPISODE = (
    "This transcript is a full podcast episode, or a large contiguous portion of one. "
    "Most episodes have between one and four breaks (a pre-roll, one or two mid-rolls, "
    "sometimes a post-roll). Once a break ends it is extremely rare for another to begin "
    "within the next 10 minutes — use this to avoid splitting one break into several or "
    "inventing breaks in editorial content."
)

ADS_CONTEXT_OPENING = (
    "This transcript is only the OPENING few minutes of an episode — the most ad-dense "
    "region. Episodes here typically begin with a pre-roll stack: one or more adverts "
    "back-to-back, often mixing pre-recorded/programmatic spots with a host-read "
    "sponsorship, before the show's editorial content begins. Do not assume the episode "
    "opens with content — it usually opens with ads. Scan from the very start and flag "
    "every advert up to the point the show proper begins."
)

ADS_CONTEXT_POST_BREAK_WINDOW = (
    "This transcript is a short window of content immediately adjacent to a distributor "
    "(Acast) ad break — either just after its closing jingle or just before the next "
    "opening jingle. It is mostly ordinary show content, but a baked-in host-read sponsor "
    "sometimes sits here, outside the jingle bracket. Flag only a genuine advert; be "
    "conservative and do not mistake brand-heavy show talk for an ad."
)

ADS_CONTEXT_CONFIRMED_BREAK = (
    "This entire transcript window has ALREADY been confirmed to be a single advertising "
    "break — it was bracketed by distributor ad-break idents, so all of it is advertising. "
    "Itemise every distinct advert within it (a change of advertiser, product, or offer "
    "marks a new advert), and return a single break spanning the window. Do not flag the "
    "network ident/jingle itself or silence."
)


TRIM_BBC_PROMPT = """You analyse BBC podcast transcripts to find where an episode's actual \
show content starts and ends, so the BBC's wrapper audio can be trimmed off. BBC podcasts \
carry no third-party adverts, but episodes are wrapped in non-show audio at the head and tail.

You are given two timestamped transcript windows from one episode, plus the episode's title \
and description:
- HEAD: the first {head_window_s:.0f} seconds of the file. Timestamps are seconds from the \
start of the file.
- TAIL: the last {tail_window_s:.0f} seconds of the file, which begins {tail_offset_s:.1f} \
seconds into the episode. Timestamps are seconds from the start of the TAIL window itself, \
NOT from the start of the file.

CUT (this is not show content):
- BBC Sounds ident/jingle ("BBC Sounds, music, radio, podcasts")
- Podcast preamble ("Thanks for downloading this episode...", "There's a reading list...")
- Continuity announcer ("Now on BBC Radio 4...", "...here's X with Y", announcer intros for \
special series)
- News bulletin fragments from the preceding broadcast
- Trailers for OTHER BBC programmes — the signal is a new voice saying "Hi, I'm X...", \
"BBC Radio 4 presents...", "To subscribe, just search for..." or similar. If a trailer is \
present, the content end must be BEFORE the trailer starts, never inside it.
- Producer credits ("X is produced by...")
- BBC Sounds app / subscribe promos ("download the free BBC Sounds app", "bbc.co.uk/sounds")

KEEP (this is show content):
- The host's cold open or "Hello" — content starts at the first word of the show itself
- The host's signoff, thanks to guests, and next-episode preview
- Post-signoff bonus discussion (e.g. a producer interrupting with "tea or coffee?" followed \
by substantive extra conversation about the episode topic). This is part of the show — \
content ends AFTER it, just before any trailer or credit. But if the exchange has no \
substantive discussion after it (just "tea please" and then a trailer), cut it too.

Return:
- content_start_s: seconds into the HEAD window of the first word of show content. 0 if the \
show starts immediately with no wrapper audio.
- content_end_s: seconds into the TAIL window at which show content ends — the END of the \
last in-show line, just before any trailer, credit, or promo. {tail_window_s:.0f} (the full \
window) if the episode ends with show content and there is nothing to trim.
- head_reason / tail_reason: a few words naming what is being cut at each end (e.g. \
"BBC Sounds ident + continuity intro", "trailer for Intrigue + Sounds promo"). Empty string \
if nothing is cut at that end.

Episode title: {title}
Episode description: {description}

HEAD transcript:
{head_transcript}

TAIL transcript:
{tail_transcript}"""


REFINE_AD_START_PROMPT = """You are listening to a short audio clip from a podcast.

Somewhere in this clip, regular podcast content transitions into an advertisement. Your
job is to pinpoint the exact moment the cut should begin — i.e. the first millisecond of
audio that should be removed.

The transition is often signalled by a change in tone, a music sting, a sponsorship cue
("brought to you by", "this episode is sponsored by", a brand mention), or a clean cut
in the audio.

Two kinds of short jingles ("idents") commonly sit near this boundary and must be
handled differently:
- **Show idents** — the podcast's own branding sting, played at the same point in every
  episode (often a show-outro before going to break). These ARE content — keep them.
  The cut should begin AFTER any show ident.
- **Ad-break / distributor idents** — a podcast network's bracket sting (e.g. Acast's
  signature voice/sound that announces the start of an ad break). These are NOT content
  — they should be cut along with the ads. The cut should begin AT the START of this
  sting, not at the start of the first ad inside the break.

When in doubt about an unfamiliar jingle, prefer keeping it as content (start the cut
later rather than earlier).

Return ONLY a single integer: the offset in milliseconds from the start of this clip
where the cut should begin. If you genuinely cannot determine the transition with
confidence, return -1.

Do not include any other text, units, JSON, or explanation. Just the integer."""


REFINE_AD_END_PROMPT = """You are listening to a short audio clip from a podcast.

Somewhere in this clip, an advertisement ends and regular podcast content resumes. Your
job is to pinpoint the exact moment content should resume — i.e. the first millisecond
of audio that should NOT be cut.

The transition is often signalled by a return to the host's regular voice/cadence, the
end of advert music, or a clean cut back to the show.

Two kinds of short jingles ("idents") commonly sit near this boundary and must be
handled differently:
- **Ad-break / distributor idents** — a podcast network's closing sting (e.g. Acast's
  signature voice/sound that closes an ad break). These are NOT content — they should
  be cut along with the ads. The cut should end AFTER this sting.
- **Show idents** — the podcast's own branding sting, played at the same point in every
  episode (often a show-intro as content resumes). These ARE content — keep them. The
  cut should end AT the START of the show ident, not at the host's first spoken words.

When in doubt about an unfamiliar jingle, prefer keeping it as content (end the cut
earlier rather than later).

Return ONLY a single integer: the offset in milliseconds from the start of this clip
where the cut should end. If you genuinely cannot determine the transition with
confidence, return -1.

Do not include any other text, units, JSON, or explanation. Just the integer."""
