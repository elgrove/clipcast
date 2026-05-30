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

For each ad break you identify, return:
- start_time and end_time of the whole break (the outer bounds covering every advert inside)
- adverts: the list of individual adverts within the break. For each advert, give its own start_time, end_time, and advert_for (the company/product being advertised). This breakdown is required — identifying who is being advertised forces you to ground each break in real transcript content rather than guessing at boundaries.

Transcript:
{transcript}"""


REFINE_AD_START_PROMPT = """You are listening to a short audio clip from a podcast.

Somewhere in this clip, regular podcast content transitions into an advertisement.

Listen carefully for the exact moment the advertisement begins — this is often
signalled by a change in tone, music sting, sponsorship cue ("brought to you by",
"this episode is sponsored by", a brand mention), or a clean cut in the audio.

Return ONLY a single integer: the offset in milliseconds from the start of this clip
where the advertisement begins. If you genuinely cannot determine the transition with
confidence, return -1.

Do not include any other text, units, JSON, or explanation. Just the integer."""


REFINE_AD_END_PROMPT = """You are listening to a short audio clip from a podcast.

Somewhere in this clip, an advertisement ends and regular podcast content resumes.

Listen carefully for the exact moment the podcast content resumes — this is often
signalled by a return to the host's regular voice/cadence, the end of advert music,
or a clean cut back to the show.

Return ONLY a single integer: the offset in milliseconds from the start of this clip
where the podcast content resumes. If you genuinely cannot determine the transition
with confidence, return -1.

Do not include any other text, units, JSON, or explanation. Just the integer."""
