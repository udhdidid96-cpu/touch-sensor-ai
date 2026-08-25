# Deploying to Google Cloud Run

`deploy_google.bat` does the whole thing. This file explains what it does and
what to watch out for.

## Why Cloud Run and not the other Google options

| Option | Verdict |
|---|---|
| **Cloud Run** | **Use this.** Runs the Dockerfile already in this repo, respects `$PORT`, supports websockets, scales to zero. |
| Firebase Hosting | Static files only. It cannot run `main.py`, so there would be no model, no API, no live telemetry. |
| App Engine standard | Cannot carry the scikit-learn / scipy / pandas wheel stack this project needs. |
| Compute Engine | Works, but you would be running and paying for a VM around the clock and patching it yourself. |

## Before the first run

```
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

Billing must be enabled on the project — Cloud Run will not deploy without it.
Then double-click `deploy_google.bat`.

## The access key is not optional

`main.py` refuses to start on a non-loopback address unless
`PROJECT2_ACCESS_KEY` is set. That is deliberate and the script works with it,
not around it. The reason: the API serves every recording under `Data\`,
accepts CSV uploads, and accepts writes to the extubation audit trail. A Cloud
Run URL is public and gets scanned.

The service is deployed `--allow-unauthenticated` so that a plain browser can
reach it, and the app's own key is what actually guards it. The script prints a
link with `?key=...` on the end. **That link is a password.** Anyone who has it
has everything.

The script reuses the key already set on the service when you redeploy, so an
existing link keeps working. To rotate it, delete the service and redeploy.

## Three things that will surprise you

**1. The audit trail does not survive.** Cloud Run's filesystem is in-memory and
ephemeral. `Data\extubation_events_audit.json` and anything uploaded to
`Data\Custom_Uploads` are gone when the instance recycles, and they count
against the container's memory while they exist. For a demo this is fine. If
you need the trail to persist, the events have to go to Cloud Storage or a
database instead of a local file — that is a code change, not a deploy flag.

**2. Cold start takes several seconds.** With `--max-instances 3` and no minimum,
Google shuts the last instance down when idle and the next visitor waits while
the 9 MB model loads. `--min-instances 1` removes the wait but bills you around
the clock. The script leaves it at zero on purpose.

**3. The serial port is not there.** Live capture from the sensor patch reads a
COM port on the machine running the server. In a Google datacentre there is no
COM port. On Cloud Run the console works in Replay mode against the recordings
baked into the image; for live hardware you still run `start.bat` locally, or
`start_public.bat` for a tunnel from your own machine.

## Cost

Cloud Run bills per request-second. An idle service that nobody opens costs
essentially nothing because it scales to zero. A demo that a handful of people
open occasionally sits inside the free tier. The thing that costs money is
`--min-instances 1`, or leaving a websocket open for hours — the `--timeout 3600`
in the script allows a one-hour session, and you are billed for that hour.

## Taking it down

```
gcloud run services delete smart-extubation --region asia-southeast1
```

That stops all charges. The built image stays in Artifact Registry and costs a
few cents a month; delete the `cloud-run-source-deploy` repository there too if
you want it fully gone.

## Verified before shipping

The container's Python environment, the startup path and the access gate were
exercised on Linux/Python 3.11 with the pinned `requirements.txt`:

- `--host 0.0.0.0` with no key → refuses to start, prints the reason. Good.
- `--host 0.0.0.0` with a key → serves; model loaded from
  `Data/trained_model.joblib`, no retrain.
- Without the key: `/`, `/api/v6/metrics`, `/api/v5/datasets`, `/static/app.js`
  all return **401**.
- With the key: all return **200**, and the console, its stylesheet, `app.js`
  and the vendored Chart.js are served intact.

What was not exercised here: the Docker build itself (no Docker daemon in the
environment this was checked in) and websocket streaming behind Cloud Run's
proxy. Neither is likely to bite — the Dockerfile is a plain two-stage build and
Cloud Run supports websockets natively — but they are the two steps to watch on
your first deploy.
