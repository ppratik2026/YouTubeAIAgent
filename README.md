# YouTube AI Agent

Category bolo, count bolo - baaki sab apne aap: topic, script, awaaz, visuals, video, thumbnail, upload.
Hindi + English, Shorts + long videos. Free services par chalta hai; kisi bhi Linux VPS par Docker se.

```
category -> topic (Google News / YouTube trends / AI idea)
        -> 5 hooks, scored by hookscore.py        (yt-script skill)
        -> script, scene by scene                  (yt-script skill, Gemini free)
        -> 10 titles, linted by title.py, SEO      (yt-package + yt-seo skills)
        -> voice per scene                          (edge-tts, free, Hindi + English)
        -> footage / photos / AI images            (Pexels free, Pollinations free)
        -> video + subtitles + music + chapters    (ffmpeg)
        -> upload, within YouTube's daily quota    (YouTube Data API)
```

The rules and scoring tools come from the
[youtube-agent-skill](https://github.com/Jakeschincariol/youtube-agent-skill) pack in `.claude/skills/`.

## 1. Server par install (Ubuntu / Debian, koi bhi VPS)

```sh
git clone https://github.com/ppratik2026/YouTubeAIAgent.git
cd YouTubeAIAgent
sh install.sh          # pehli baar: Docker install karke .env banata hai
nano .env              # keys bharo (neeche dekho)
sh install.sh          # app start
```

Recommended: 4 vCPU / 8-16 GB RAM (e.g. Hostinger KVM 4). 2 vCPU bhi chalega, bas render slow hoga.

## 2. Keys (sab free)

| `.env` | Kahan se |
|---|---|
| `GEMINI_API_KEY` | https://aistudio.google.com -> Get API key |
| `PEXELS_API_KEY` | https://www.pexels.com/api/ -> sign up -> key |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | neeche "YouTube connect" |

### YouTube connect (ek baar)

1. https://console.cloud.google.com -> new project.
2. APIs & Services -> Library -> **YouTube Data API v3** -> Enable.
3. OAuth consent screen -> External -> app name + email -> apna email **Test users** mein add karo.
   Phir **Publish app -> In production** karo. Testing mode mein login 7 din mein expire ho jata hai.
   ("Google hasn't verified this app" screen aayegi - apne liye hai, *Advanced -> Continue*.)
4. Credentials -> Create credentials -> OAuth client ID -> type **Desktop app** -> Client ID + Secret copy.
5. **Apne computer par** (browser wala, server nahi):
   ```sh
   python3 scripts/get_refresh_token.py CLIENT_ID CLIENT_SECRET
   ```
   Channel wala Google account chuno. Jo 3 lines print hon, server ki `.env` mein daalo, phir
   `docker compose up -d` (restart).

## 3. Use

```sh
./yt add --category crime --lang hi --format long --count 100 --minutes 8
./yt add --category 3d --lang en --format short --count 30 --voice female
./yt list                 # jobs: made / uploaded / failed, aaj kitne upload baaki
./yt cancel <job_id>
./yt logs                 # live log
./yt categories
```

Categories: `news crime drama music animation 2d 3d horror facts motivational mythology tech` -
ya koi bhi naam (`--category "cricket"`), wo bhi chalega. Apni category ka style
`config/categories.json` mein add/edit karo.

Ek video turant test karni ho (queue ke bina, upload nahi):

```sh
./yt make --category news --lang hi --format short
```

Videos `data/videos/<date-title-id>/` mein: `video.mp4`, `thumbnail.jpg`, `meta.json`, `script.txt`.

## 4. Server badalna

```sh
# purane server se
tar czf backup.tgz .env data assets/music config
# naye server par: repo clone karo, backup.tgz copy + extract karo, phir
sh install.sh
```

## Limits - pehle padh lo

- **YouTube quota**: default ~6 uploads/day per Google Cloud project. 100 videos bologe to banengi,
  upload roz ~6 karke hoga (`UPLOADS_PER_DAY`). Zyada chahiye to Google se quota increase maango
  (free form: YouTube API Services -> Audit and Quota Extension).
- **Private lock**: jab tak Google aapke API project ka audit pass nahi karta, API se upload hui har
  video private rehti hai. Tab tak Studio mein dekh kar public karo.
- **Custom thumbnail** sirf phone-verified channel par lagta hai.
- **AI label**: har upload par "altered or synthetic content" = yes jata hai.
- **YouTube policy**: mass-produced, repetitive videos ka monetization band ho sakta hai. Har video
  alag topic par banti hai, phir bhi roz kuch videos khud dekh lo.
- **Crime / news**: script sirf Google News headlines + snippets se banti hai. Galti ho sakti hai -
  public karne se pehle padh lo.
- **Free limits**: Gemini free tier per-minute limit par app khud wait karta hai; Pexels free = 200
  requests/hour (long video ~50 scenes) - zyada chahiye to Pexels se free increase maango.
- **edge-tts** Microsoft ki free online voices use karta hai; ye official paid API nahi hai, kabhi band
  ho sakti hai.

## Test without any keys

```sh
LLM_PROVIDER=offline TTS_PROVIDER=offline VISUALS_OFFLINE=1 python -m pipeline make --category drama --lang hi --format short
```
