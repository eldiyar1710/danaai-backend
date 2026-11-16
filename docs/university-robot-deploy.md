# University robot deployment on the separate Windows AI host

The university API is `app.robot_server:app`. It is separate from the existing
`drone-code-pilot-server` on `127.0.0.1:8000`. Use port 18000. The robot API
does not need the Semyzbay PostgreSQL, Qdrant, Redis, or MinIO stack.

## Windows setup

Copy this repository to the AI host without `.env` or `.venv`. From PowerShell
in the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
Copy-Item .env.example .env
# Edit .env locally. Set new OPENAI_API_KEY, ELEVENLABS_API_KEY,
# ELEVENLABS_VOICE_ID, ROBOT_API_KEY and the absolute KNOWLEDGE_DIR.
.\.venv\Scripts\python.exe -m pytest tests\unit\test_robot.py tests\unit\test_robot_bridge.py
.\.venv\Scripts\python.exe -m uvicorn app.robot_server:app --host 127.0.0.1 --port 18000
```

Keep `.env` out of Git and do not paste its values into chat. Previously exposed
provider keys should be replaced before unattended operation.

## Document review and index

`robot-approval.json` is intentionally empty. The document owner must review
each page allowed for public spoken answers, its effective status, and the
right to publish. Add an entry only after approval:

`robot-approval-candidates.json` contains the computed hashes and page counts
for 24 candidate files (1–25 excluding repealed `5.pdf`). It is a review aid,
not an approval. Regenerate it with `python -m scripts.prepare_robot_approvals`
if any PDF changes.

```json
{
  "file": "23.pdf",
  "sha256": "64 lowercase hexadecimal characters from Get-FileHash",
  "pages": [1],
  "approved_by": "name or role of reviewer",
  "approved_at": "YYYY-MM-DD"
}
```

The `sha256` must match the exact PDF in `knowledge/`. `5.pdf` and the catalog
are rejected by the loader. Run the index builder after review:

```powershell
.\.venv\Scripts\python.exe -m scripts.build_robot_index
.\.venv\Scripts\python.exe -m uvicorn app.robot_server:app --host 127.0.0.1 --port 18000
Invoke-RestMethod http://127.0.0.1:18000/ready
```

Rebuild the index and restart the API after changing the PDF or manifest.
`/health` confirms only that the process is alive; `/ready` requires approved
pages and a matching semantic index. Tune `ROBOT_MIN_SIMILARITY` using a reviewed
Kazakh/Russian question set before public operation.

## G1 network

After the real G1 network interface and IP are confirmed, bind the API to the
AI host address on that isolated network, for example `192.168.123.222`, and
allow port 18000 only from the robot-side PC2. Keep the other service on port
8000 unchanged. Test the bridge first with a prerecorded WAV, then with the G1
microphone and speaker. PC2 needs the official Unitree Python SDK, `ffmpeg`,
`httpx`, and the robot API key in its local environment. The bridge uses only
the G1 audio service and makes no movement calls.

Do not mark deployment complete until the actual robot passes Russian and
Kazakh questions, citation checks, unknown-question fallback, audio playback,
and latency measurements.
