TRANSCRIBE_AUDIO_PROMPT = """Transcribe this audio file with precise timestamps.
Return ONLY a JSON array of segments, each with start_time (seconds), end_time (seconds), and text.
Example format: [{"start_time": 0.0, "end_time": 5.5, "text": "Hello world"}]
Be precise with timestamps. Include all spoken content."""


ANALYSE_ADVERTS_PROMPT = """You are an AI assistant specialized in analyzing podcast transcripts to identify advertisement segments.

Guidelines for identifying advertisements:
- Analyze dialogue many lines at a time to understand the full context
- When you detect an advert, carefully identify the start and end based on surrounding context
- Ads can be pre-recorded (like radio ads) or host-read (common in podcasts)
- An ad typically spans 10 to 60 seconds, but rarely less than 10 seconds
- Ads may appear as singles or in clusters of multiple ads back-to-back
- Very rarely will you see back-to-back ads for the same company/brand/product
- Once an ad or cluster ends, it's extremely rare for another one within the next 10 minutes
- Look for sponsorship keywords: "sponsor," "brought to you by," "advertisement," "partner," "our friends at"
- Watch for known brand/product/company names, but be careful not to confuse person names with companies
- If any further instructions are appended to this prompt, they take precedence

For each advertisement you identify:
- Determine the precise start and end times from the transcript
- Identify what company, product, or service is being advertised
- Capture the first ~50-70 characters of the ad's text
- Capture the last ~50-70 characters of the ad's text

Transcript:
{transcript}"""
