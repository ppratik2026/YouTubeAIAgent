# YouTube AI Agent

Category bolo, count bolo - baaki sab apne aap: topic, script, awaaz, visuals, video, thumbnail, upload.
Hindi + English, Shorts + long videos. Free services par chalta hai; kisi bhi Linux VPS par Docker se.

```
category -> topic (Google News / YouTube trends / AI idea)
        -> 5 hooks, scored by hookscore.py        (yt-script skill)
        -> script, scene by scene                  (yt-script skill, Gemini free)
        -> 10 titles, linted by title.py, SEO      (yt-package + yt-seo skills)
        -> voice per scene                          (edge-tts free, or YOUR cloned voice)
        -> footage / photos / AI images            (Pexels, Pollinations, Cloudflare - all free)
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

AI image ka look (`./yt styles`): `cinematic realistic 3d anime 2d watercolor comic dark mythology pixel`.
Kisi bhi category par `--style 3d` lagao to footage ki jagah us style ki AI images aayengi.

Categories: `news crime drama music animation 2d 3d horror facts motivational mythology tech` -
`devotional bhajan` - ya koi bhi naam (`--category "cricket"`), wo bhi chalega. Apni category ka style
`config/categories.json` mein add/edit karo.

Ek video turant test karni ho (queue ke bina, upload nahi):

```sh
./yt make --category news --lang hi --format short
```

Videos `data/videos/<date-title-id>/` mein: `video.mp4`, `thumbnail.jpg`, `meta.json`, `script.txt`.

## 4. Apni awaaz (voice clone)

1. 10-30 second ki saaf recording (shor nahi, ek hi insaan, normal bolna) - WAV best, MP3 bhi chalega.
2. Server par `data/voices/male.wav` aur `data/voices/female.wav` naam se rakho
   (WinSCP / FileZilla se, ya `scp male.wav root@SERVER:YouTubeAIAgent/data/voices/`).
   **Female sample sirf usi ka jisne permission di hai.**
3. `sh install.sh clone` (pehli baar PyTorch + model download, ~4-5 GB, time lagega).
4. `./yt voices` -> "voice service: ready".
5. Job mein `--tts clone`: `./yt add --category drama --lang hi --format short --count 20 --tts clone --voice female`
   Ya `.env` mein `TTS_PROVIDER=clone` = har video aapki awaaz mein.

Model: [Chatterbox Multilingual](https://huggingface.co/ResembleAI/chatterbox) (MIT, Hindi + English),
CPU par chalta hai - **slow**: Short theek, 10 min ki video mein ghanta+ lag sakta hai.
Service band ho ya sample na ho to wo video free Microsoft voice mein banti hai (beech mein awaaz nahi badalti).

## 5. Apni recording se video

Poori script khud record karo (MP3/WAV/M4A), file server ke `data/inbox/` mein daalo, phir:

```sh
./yt record my-video.mp3 --category drama --lang hi --format long --style cinematic
```

Awaaz bilkul aapki recording rahegi. Whisper (free, CPU) usse sun kar subtitles + scenes banata hai,
har scene ki picture lagti hai, title/description banta hai, phir upload. File baad mein `data/inbox/done/` mein.

## 6. Free rehne ke liye (koi paisa nahi, sirf server)

- **Gemini**: sirf script ke liye, free key. App calls ke beech wait karta hai (`GEMINI_MIN_INTERVAL`),
  per-minute limit par Google ka bataya time rukta hai, aur daily quota khatam hote hi worker pause ho
  kar agle din continue karta hai - key par zor nahi padta. Gemini ki free key se images nahi banti,
  isliye images free sources se.
- **Images**: Pollinations (no key) -> Cloudflare Workers AI (free daily) -> Pexels. Koi image safety se
  block ho to Gemini prompt ko safe tarike se dobara likhta hai aur phir try hota hai; phir bhi na bane to
  agla source. Video kabhi beech mein nahi rukti.
- **Awaaz**: edge-tts free, ya aapki clone voice (aapke server par, free).
- **Upload**: YouTube API free hai; bas roz ki limit.

## 7. Monetization ke liye smart features

Koi tool monetization guarantee nahi kar sakta - YouTube har channel ko insaan se review karta hai, aur
"inauthentic content" policy (mass-produced / template wali videos) ke under AI channels sabse zyada
reject hote hain. Ye app wahi karta hai jo approval ke chances badhata hai:

| Feature | Kya karta hai | Kahan |
|---|---|---|
| Channel identity | Har script ek hi host, ek niche, ek point of view se - "ek creator" lagta hai, farm nahi | `config/channel.json` - **pehle ye bharo** |
| Har video alag | 7 video shapes (story, countdown, myth vs fact, case file...) rotate; pichhle hook formulas avoid | automatic |
| Copy check | Nayi script pichhli 60 scripts se milti-julti ho (30%+) to upload nahi hoti | automatic |
| Quality gate | Hook score + title score + kitne scenes mein asli picture + originality; kam ho to `./yt review` mein rukti hai | `quality_min` in channel.json |
| Shorts -> long | Har long video se 2 Shorts, description mein "Full video" link. Watch hours long videos se hi aate hain | `shorts_per_long` |
| Fixed time | Roz same prime-time slots par publish (default 6:30 PM, 8:30 PM IST) | `publish_times_ist` + `UPLOAD_PRIVACY=public` |
| Apne channel se seekhna | Har 12 ghante views laata hai; jo topics/hooks/shapes chale wahi zyada, jo nahi chale wo kam | automatic |
| Progress | Subscribers, 12 mahine ke watch hours (sirf long), 90 din ke Shorts views vs YPP | `./yt progress` |

```sh
./yt review            # rukhi hui videos + wajah
./yt approve <id>      # upload karo
./yt reject <id>
./yt progress          # monetization kitna door
```

`./yt progress` ke liye YouTube Analytics permission chahiye: `scripts/get_refresh_token.py` ek baar
dobara chalao aur naya `YT_REFRESH_TOKEN` daalo.

**Sabse zyada farak in cheezon se padta hai** (code nahi kar sakta, aap kar sakte ho):
- Ek niche par tike raho - har category mix karoge to na audience banegi na approval.
- Long videos 8+ minute (mid-roll ads), Shorts sirf long videos tak laane ke liye.
- Kuch videos apni awaaz / recording se (`--tts clone` ya `./yt record`) - asli insaan wala signal.
- Comments ka jawab khud do (`/yt-comment` skill draft deta hai).
- Health, finance, legal mein "expert advice" mat do.

## 8. Kai channels ek server par

```sh
./yt channel-add bhakti          # data/channels/bhakti/ banta hai
./yt channel-add newshindi
./yt channels                    # har channel: kitni banani baaki, ready, uploaded
./yt --channel bhakti add --category devotional --lang hi --format long --count 30
./yt --channel newshindi add --category news --lang hi --format short --count 50
./yt --channel bhakti review     # har command --channel ke saath us channel par chalti hai
```

Har channel ka apna folder `data/channels/<name>/`:

| File | Kya |
|---|---|
| `channel.json` | us channel ki pehchaan: niche, host, publish time, quality_min |
| `channel.env` | us channel ka `YT_REFRESH_TOKEN` (get_refresh_token.py chala kar **us channel ka** account chuno) + jo setting alag ho |
| `voices/male.wav`, `female.wav` | us channel ki clone awaaz (na ho to main `data/voices/` wali) |
| `inbox/` | us channel ki recordings / bhajan files |
| queue, history, videos, logs | sab alag |

Worker saare channels ko **baari-baari** chalata hai: har channel ki ek video aur ek upload, phir agla channel -
taaki ek channel ka 100 video ka job baaki channels ko na roke.

**Shared limits (dhyan do):**
- YouTube upload quota **Google Cloud project** ka hota hai, channel ka nahi. Sab channels ek hi OAuth
  client use karein to roz ~6 uploads **sab channels mila ke**. Zyada chahiye to project ka quota increase
  maango (free form). Har channel ke liye alag project bana kar limit todna YouTube API policy ke khilaf
  ho sakta hai - quota increase sahi raasta hai.
- Gemini free key bhi sab channels share karte hain (calls `./yt list` mein dikhti hain).

## 9. Music / devotional channel

Music ka matlab yahan teen alag cheezein hain:

| Kya chahiye | Kaise | Category |
|---|---|---|
| Bhakti kahaniyan, mantra/aarti ka arth, tyohar ki katha (narration) | Poora auto, jaise baaki categories. Devotional style images + shant music | `devotional` |
| Music ke baare mein - gaane/raag/gayak ki kahani | Poora auto, narration. Copyright gaane ke lyrics nahi bolta, gaana nahi bajata | `music` |
| **Asli bhajan / gaana** (aapka gaya hua, ya jiske rights aapke paas hain) | Aap audio do, app usse music video banata hai: lyrics screen par, har line par nayi picture, title/description | `bhajan` + `record --song` |

```sh
# bhajan.mp3 + bhajan.lrc ko data/channels/bhakti/inbox/ mein daalo, phir:
./yt --channel bhakti record bhajan.mp3 --song --lyrics bhajan.lrc --title "Shiv bhajan" --category bhajan --format long
# lyrics na ho (instrumental / flute / dhun): bina --lyrics, har ~10 sec nayi picture
./yt --channel bhakti record dhun.mp3 --song --title "Morning flute" --category bhajan --format long
```

- `.lrc` = har line ka time (`[00:07.50] हर हर महादेव`) - lyrics bilkul gaane ke saath chalte hain.
  `.txt` bhi chalega (line per line), lekin timing andaze se hogi.
- Gaane par background music nahi lagta. Audio bilkul aapka.

**Kya nahi hoga, aur kyun:**
- **App khud bhajan/gaana nahi gaata.** Free + commercial use wala koi achha music AI CPU par nahi chalta
  (MusicGen jaise free models ka license commercial use nahi deta, ACE-Step jaise ko GPU chahiye).
- **Kisi aur ka bhajan / film song / T-Series wagairah ki recording mat daalo** - Content ID claim aata hai,
  paisa unko jata hai, aur zyada hue to channel par strike. Purane bhajan/mantra ke **shabd** (jaise Hanuman
  Chalisa) public domain hain, lekin unki **recording** kisi ki hoti hai - apni ya licensed recording hi use karo.
- 1-1 ghante ke "mantra jaap loop" channels ko YouTube aksar "repetitive / reused content" maan kar monetize
  nahi karta. Apni recording + katha/arth wali videos mix karo.

## 10. Server badalna

```sh
# purane server se
tar czf backup.tgz .env data assets/music config   # data/ mein voices, queue, history sab
# naye server par: repo clone karo, backup.tgz copy + extract karo, phir
sh install.sh
```

## Limits - pehle padh lo

- **YPP (2026)**: 1,000 subscribers + (4,000 public watch hours in 12 months ya 10M Shorts views in
  90 days). Kuch reports ke hisaab se Feb 2027 se ye badh sakta hai - YouTube help page check karo.

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
