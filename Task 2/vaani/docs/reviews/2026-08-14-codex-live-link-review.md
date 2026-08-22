• Verdict: the recommendation is directionally right, but the plan is not submission-safe
  yet. The biggest blockers are the current Hugging Face account requirement, Space cold
  starts, an outdated or unverified Sarvam WebSocket integration and the absence of spending
  controls.

  1. High: Cloudflared Quick Tunnel claims are mostly verified, and they disqualify it as
     the submitted URL.

     Every invocation creates a random trycloudflare.com subdomain. Restarting cloudflared,
     including through the proposed supervisor, produces a different URL. A brief Wi-Fi
     interruption might recover without rotation if the same process reconnects, but the
     service is unavailable during the outage.

     Cloudflare explicitly provides no SLA, calls Quick Tunnels development-only, limits
     them to 200 simultaneous in-flight requests with 429 after that and does not support
     SSE. There is no documented monthly request or bandwidth quota specific to Quick
     Tunnels. Cloudflare Tunnel does support WebSockets, although Cloudflare network updates
     can terminate existing sockets. Cloudflare Quick Tunnel limits
     (https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/),
     Cloudflare WebSocket behavior (https://developers.cloudflare.com/network/websockets/).

     Fix: never submit the Quick Tunnel URL. Keep it only as an optional fast mode.

  2. Critical: “Free CPU Docker Space” is currently refuted for a new free account.

     The hardware claim itself is correct: CPU Basic is 2 vCPU, 16GB RAM and 50GB
     non-persistent disk. The roughly 2.5-3GB core artifact set fits easily. However,
     current Hugging Face documentation says creating a new Gradio or Docker compute Space
     requires a paid account even though CPU Basic has no hourly hardware charge. Static
     Spaces remain free. Current Spaces overview
     (https://huggingface.co/docs/hub/spaces-overview), current hardware table
     (https://huggingface.co/docs/hub/en/spaces-gpus).

     Fix: verify immediately that this account can create and run a Docker CPU Space. If
     not, budget for PRO or select another host. Do not discover this after the cluster
     disappears. An existing eligible Space may behave differently, so test the actual
     account.

  3. High: “Stable and always up” is half false.

     The Space URL is stable, but free CPU Spaces sleep after 48 hours of inactivity. A
     visitor automatically restarts a sleeping Space. Hugging Face publishes no cold-start
     time guarantee. Space sleep behavior
     (https://huggingface.co/docs/hub/en/spaces-gpus#set-a-custom-sleep-time).

     Because this container must start llama.cpp, load a 1.1GB retrieval index, load e5 and
     possibly warm two guard models, a judge could see a starting page for tens of seconds
     or several minutes. Judging days after submission makes a cold click likely.

     Fix: measure a real restart from fully stopped state, including time until /healthz,
     text queries and voice all work. If spending outside the Sarvam budget is possible, the
     8-vCPU CPU Upgrade is currently $0.03/hour and does not sleep by default. That is
     materially safer for this submission window.

  4. Medium: Space disk, secrets and Sarvam egress claims are verified; incoming WebSocket
     support needs a deployed test.

     Hugging Face secrets are injected as runtime environment variables for Docker Spaces.
     Outbound HTTP/HTTPS on ports 80, 443 and 8080 is allowed, so server-side calls to
     https://api.sarvam.ai and wss://api.sarvam.ai have no documented Space-side blocker.
     Docker Space secrets (https://huggingface.co/docs/hub/en/spaces-sdks-docker), Space
     networking (https://huggingface.co/docs/hub/spaces-overview#networking).

     Docker Spaces expose one public application port, normally 7860. FastAPI WebSocket
     applications are used on Spaces, but Hugging Face does not publish a clear WebSocket
     proxy SLA or idle-limit contract.

     Fix: expose FastAPI and /ws/voice through the same port and test
     wss://<space>.hf.space/ws/voice from mobile data after a cold start. Add no .env file
     to the Space image or repository. The Sarvam key must remain a Space secret and must
     never appear in browser JavaScript, logs or Docker layers.

  5. Medium: The 1-2 second CPU generation estimate is plausible as a best case, but
     optimistic as a hosting promise.

     I ran the committed Q8 model through the bundled llama-bench with CPU-only inference
     and two threads on the i7-13650HX laptop. A 512-token prompt took about 0.13 seconds
     and generation ran at 41.1 tokens/second. That works out to roughly 0.9 seconds for 32
     tokens and 1.7 seconds for 64 tokens.

     This supports the estimate on a fast laptop CPU. Hugging Face does not guarantee its
     underlying CPU model, and the two vCPUs will also run retrieval, e5, guards and the web
     server. Concurrent users will make it worse.

     Verdict: replace “1 to 2 seconds” with an unverified 1-5 second expectation until
     benchmarked on the actual Space. Set concurrency to one for generation.

  6. High: The current application cannot complete a 1-2 second CPU generation.

     The default generation client timeout is 150 ms and the pipeline falls back after 175
     ms. There is no environment-variable override in the app factory. See the /C:/Users/
     Kartik/Documents/Kartik/EDU/Local/Projects/HHG/Task 2/vaani/src/vaani/
     pipeline_text.py:38 and /C:/Users/Kartik/Documents/Kartik/EDU/Local/Projects/HHG/Task
     2/vaani/src/vaani/pipeline_text.py:163.

     On the proposed CPU Space, almost every generative request will time out and become
     extractive. The plan’s CPU-generation description therefore does not match the code.

     Fix: add a Space-specific configurable timeout, probably 5-10 seconds, and report CPU
     latency separately from the under-200 ms cluster result. If extractive fallback is
     intentional, state that plainly in the live demo.

  7. High: The Space plan omits the guard service while claiming guards still behave
     correctly.

     The artifact list includes the index, corpus, e5 and GGUF, but not the two guard models
     or their service. Without VAANI_GUARD_URL, the current guard client uses permissive
     stubs. Even if the models are bundled, the input guard is joined for only 150 ms and
     HHEM gets 40 ms, so CPU execution is likely to fail open. See /C:/Users/Kartik/
     Documents/Kartik/EDU/Local/Projects/HHG/Task 2/vaani/src/vaani/guards.py:32 and /C:/
     Users/Kartik/Documents/Kartik/EDU/Local/Projects/HHG/Task 2/vaani/src/vaani/
     pipeline_text.py:131.

     Fix: either bundle and benchmark both guards with realistic CPU deadlines, or label the
     Space as a degraded CPU demo with unchecked/stubbed guards. Do not claim full guard
     behavior while omitting their host.

  8. Critical: The Sarvam realtime integration is not verified against the current canonical
     API.

     Current Sarvam documentation uses GET /speech-to-text/ws with saaras:v3. The guide
     describes final transcripts per utterance and does not promise the transcript.partial
     event sequence on which speculative retrieval currently depends. The repo instead uses
     /speech-to-text-realtime/ws, saaras:v3-realtime and older-looking event names in
     /C:/Users/Kartik/Documents/Kartik/EDU/Local/Projects/HHG/Task
     2/vaani/src/vaani/stt_realtime.py:26. Sarvam still has some integration documentation
     referencing that older endpoint, so it may be a legacy interface, but it cannot be
     treated as verified. Current Sarvam transport guide
     (https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/which-api-to-use),
     current WebSocket reference
     (https://docs.sarvam.ai/api-reference/speech-to-text/transcribe/ws).

     Fix: perform a real session now, preferably using the current official SDK or canonical
     protocol. Verify endpoint, model, query parameters, audio messages, VAD/final events,
     translation output and whether partial transcripts actually exist.

  9. Critical: A public link can exhaust ₹100 extremely quickly.

     Sarvam charges ₹30 per audio hour. ₹100 buys about 200 audio minutes. Starter permits
     20 concurrent STT WebSockets, and streaming has no duration limit. An attacker holding
     20 audio streams for ten minutes could exhaust the entire balance. Sarvam pricing
     (https://www.sarvam.ai/api-pricing), rate limits
     (https://docs.sarvam.ai/api/getting-started/ratelimits), stream duration
     (https://docs.sarvam.ai/api/speech-to-text/faq).

     The current public endpoints have no authentication, per-IP throttling, global
     concurrency limit, audio duration cap or enforced spending ceiling. The ledger only
     records completed REST calls, does not cover realtime streams and will disappear when
     an ephemeral Space restarts. See /C:/Users/Kartik/Documents/Kartik/EDU/Local/Projects/
     HHG/Task 2/vaani/src/vaani/server.py:91 and /C:/Users/Kartik/Documents/Kartik/EDU/
     Local/Projects/HHG/Task 2/vaani/src/vaani/stt.py:76.

     Fix before publication:
      - Limit voice sessions to roughly 15-20 seconds.
      - Allow only one or two paid STT sessions globally.
      - Add per-IP rate limiting and a judge token or bot challenge.
      - Cap REST upload bytes and reject audio over 30 seconds before calling Sarvam.
      - Keep a persistent global usage counter outside the Space and stop paid calls at
        perhaps ₹60-₹70, preserving a judge reserve.

      - Use a dedicated key, monitor it in Sarvam’s dashboard and be ready to revoke it.
      - Do not publish the fast-mode URL in a public README while paid voice is
        unrestricted.

  10. Medium: The plan misses two better stable laptop tunnels.

  Ngrok Free provides an account-assigned development domain that persists across agent
  restarts, has no endpoint timeout and supports WebSockets. Its limits are 1GB transfer and
  20,000 HTTP requests per month, plus a browser interstitial. Ngrok free limits
  (https://ngrok.com/docs/pricing-limits/free-plan-limits), Ngrok WebSockets
  (https://ngrok.com/docs/using-ngrok-with/websockets).

  Tailscale Funnel provides a predictable .ts.net name, resumes after reboot with --bg and
  is available on free plans. It remains beta and has non-configurable bandwidth limits.
  Tailscale Funnel persistence (https://tailscale.com/docs/reference/tailscale-cli/funnel),
  Funnel limits (https://tailscale.com/kb/1223/funnel).

  Fix: use one of these instead of Quick Tunnel for fast mode. Neither solves laptop power,
  Windows update or home-Wi-Fi availability, so neither should be the sole submitted
  backend.

  11. Medium: There is no obviously superior zero-cost turnkey host, but two alternatives
     can fit.

  - Oracle Always Free Ampere A1 has enough memory and up to 200GB block storage, so it can
    host this stack. Downsides are ARM rebuilding, frequent capacity shortages and possible
    reclamation when the VM is idle for seven days. Oracle Always Free resources
    (https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

  - Google Cloud Run supports WebSockets, up to 32GB memory and a stable service endpoint
    with a monthly compute free allowance. It scales to zero and cold-starts. A 3GB image
    also exceeds Artifact Registry’s 0.5GB free storage allowance, so it is low-cost rather
    than strictly free and requires billing. Cloud Run suitability
    (https://docs.cloud.google.com/run/docs/fit-for-run), Cloud Run pricing
    (https://cloud.google.com/run/pricing), Artifact Registry pricing
    (https://cloud.google.com/artifact-registry/pricing).

  Render, Koyeb and Railway free instances do not fit: their free RAM is 512MB and
  Koyeb/Railway free disk is 2GB/1GB. Render specs (https://render.com/docs/compute-plans),
  Koyeb specs (https://www.koyeb.com/docs/reference/instances), Railway limits
  (https://railway.com/pricing).

  Fix: only pivot to OCI if an account and A1 capacity already exist. Cloud Run is the more
  predictable emergency alternative if small charges are acceptable.

  12. High: Publicly bundling the corpus has an unresolved licensing risk.

  The MSMARCO-XI card does not grant a standard license. It directs users to the original MS
  MARCO terms. Those terms restrict use to non-commercial research, disclaim ownership of
  underlying documents and do not extend IP rights. MSMARCO-XI dataset card
  (https://huggingface.co/datasets/ai4bharat/MSMARCO-XI), official MS MARCO terms
  (https://microsoft.github.io/msmarco/).

  A public Space exposes and permits cloning of its source repository. Re-uploading the
  350MB corpus or derived passage bundle therefore creates a new public redistribution,
  which is not automatically authorized merely because the source dataset is already on
  Hugging Face.

  Fix: do not commit the corpus to a public Space repository until redistribution is
  confirmed. Prefer a protected Space, an attached original dataset volume or a build/
  runtime download from the original repository. Mark the dataset license as other, retain
  citations and terms and expose only answer snippets needed by the demo. A protected Space
  is especially sensible because PRO is now required for new compute Spaces anyway.

  13. High: The final recommendation is conditionally right, but the fallback decision is
     wrong.

  Between a validated Space and a Quick Tunnel, submit the Space URL. A slow stable demo
  that wakes up is recoverable; a rotated tunnel URL is permanently dead under the no-
  resubmission rule. The plan should not “flip” to the laptop solely because CPU generation
  feels slow.

  The safest design is a permanent front door you control, such as a small Cloudflare Pages
  pages.dev site, containing the primary Space link, optional fast-mode link, demo video and
  status note. Its destination can be updated without changing the submitted URL. Cloudflare
  Pages provides a stable project subdomain and free static traffic. Cloudflare Pages static
  hosting (https://developers.cloudflare.com/pages/framework-guides/deploy-anything/). Use
  this only if the submission permits a landing page; otherwise submit the direct .hf.space
  app URL.

  Final fix: submit only after the Space has passed a cold-start mobile test, current Sarvam
  WebSocket test, persistent budget-cap test and guard-mode verification. Keep the laptop
  endpoint secondary. Do not rely on Quick Tunnel for anything the judges must be able to
  reach.

  No files were changed.

