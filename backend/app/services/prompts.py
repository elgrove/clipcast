TRANSCRIBE_AUDIO_PROMPT = """Transcribe this audio file with precise timestamps.
Return ONLY a JSON array of segments, each with start_time (seconds), end_time (seconds), and text.
Example format: [{"start_time": 0.0, "end_time": 5.5, "text": "Hello world"}]
Be precise with timestamps. Include all spoken content."""


ANALYSE_AD_BREAKS_PROMPT = """You are an AI assistant specialised in analysing podcast transcripts to identify advertisement breaks.

An "ad break" is one contiguous block of one or more back-to-back adverts. Most podcasts have between one and four breaks per episode (a pre-roll, one or two mid-rolls, sometimes a post-roll). Each break typically contains 1-4 individual adverts.

Guidelines for identifying ad breaks:
- Analyse dialogue many lines at a time to understand the full context
- Determine the start of a break from where the host pivots into sponsored content, and the end from where they pivot back to the show
- Adverts can be pre-recorded (like radio ads) or host-read (common in podcasts)
- A single advert typically spans 10 to 60 seconds; back-to-back adverts within one break form a single contiguous span
- Very rarely will two adverts back-to-back inside the same break be for the same company/brand/product
- Once a break ends, it's extremely rare for another break within the next 10 minutes
- Look for sponsorship keywords: "sponsor," "brought to you by," "advertisement," "partner," "our friends at"
- Watch for known brand/product/company names, but be careful not to confuse person names with companies
- If any further instructions are appended to this prompt, they take precedence

Treat idents (short branding jingles) on either side of an ad break carefully — they fall into two distinct categories:
- **Distributor / ad-break idents** (e.g. Acast's "This podcast is supported by...", or any network sting that announces or closes an ad break) are PART of the ad break. Extend the break span to include them: the start_time should be the start of the opening ident, and the end_time should be the end of the closing ident.
- **Show idents** (the podcast's own intro/outro stings played at the same point each episode — the show's regular branding) are PART OF THE CONTENT. They must NOT be included in any break span. If a show ident sits between the host's last words and the first ad, the break starts AFTER the show ident, not before it.
- When in doubt about an unfamiliar jingle, prefer keeping it as content (tighter break span).

For each ad break you identify, return:
- start_time and end_time of the whole break (the outer bounds covering every advert inside)
- adverts: the list of individual adverts within the break. For each advert, give its own start_time, end_time, and advert_for (the company/product being advertised). This breakdown is required — identifying who is being advertised forces you to ground each break in real transcript content rather than guessing at boundaries.

Transcript:
{transcript}"""


ANALYSE_HOST_READ_PROMPT = """You are analysing a short transcript window taken from a podcast.

This window is the regular show content that comes immediately AFTER a distributor ad break has finished. Hosts sometimes read a baked-in advert here — a paid third-party sponsorship voiced by the hosts in their own words, woven into the show. Your job is to find ONLY such host-read third-party adverts in this window.

What counts as a host-read advert (flag it):
- A paid promotion for an external company, product, or service ("this episode is supported by", "brought to you by", a discount code, a vanity URL like brand.com/show, "go to X and use code Y")
- Look for sponsorship cues, brand names, offer codes, and calls to action to visit/buy from a third party

What does NOT count (do NOT flag it):
- The show's own promotion of itself: Patreon, memberships, merch, "subscribe/rate/review", "follow us on social", live-show tickets, or cross-promotion of other shows by the same hosts/network
- Ordinary conversation, banter, news, interviews, or editorial content
- A mention of a brand or product as part of the discussion that is not a paid plug

If there is no host-read third-party advert in this window, return an empty list of breaks.

Timestamps in the transcript are in seconds, relative to the START of this window. Return any advert you find using those same window-relative timestamps.

For each host-read advert, return one break with:
- start_time and end_time of the advert (where the host pivots into the plug, and where they pivot back to the show)
- adverts: the individual advert(s) within it. For each, give its own start_time, end_time, and advert_for (the company/product). This breakdown is required — naming who is advertised forces you to ground the break in real transcript content rather than guessing.

Transcript:
{transcript}"""


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
