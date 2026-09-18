# Deploying to Google Cloud Run

One `gcloud` command does the whole thing. This file carries that command and
explains what to watch out for.

The `deploy_google.bat` / `deploy_google.ps1` pair that used to wrap it was
removed on 2026-09-17: a deploy command you cannot read before you run it is
worse than one you type. What the script added over the raw command was finding
the region of an existing service and reusing its access key, and both steps are
spelled out below.

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

```
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

## Deploy

Generate an access key once and keep it — the link you hand out contains it:

```
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

```
gcloud run deploy smart-extubation \
    --source . \
    --region asia-southeast1 \
    --allow-unauthenticated \
    --memory 1Gi \
    --timeout 3600 \
    --max-instances 3 \
    --set-env-vars "PROJECT2_ACCESS_KEY=YOUR_KEY_HERE"
```

Then read back the URL, and append `?key=YOUR_KEY_HERE` to it:

```
gcloud run services describe smart-extubation --region asia-southeast1 --format="value(status.url)"
```

**Redeploying.** If the service already exists, find its region and reuse the
key that is already set on it, or every existing link stops working:

```
gcloud run services list --format="table(metadata.name, metadata.labels['cloud.googleapis.com/location'])"
gcloud run services describe smart-extubation --region REGION --format="value(spec.template.spec.containers[0].env)"
```

If the build fails saying it ran out of memory, raise `--memory`.

## The access key is not optional

`main.py` refuses to start on a non-loopback address unless
`PROJECT2_ACCESS_KEY` is set. That is deliberate — the deploy works with it, not
around it, and `--allow-public-no-key` must never be added to the Dockerfile
(invariant 6). The reason: the API serves every recording under `Data\`,
accepts CSV uploads, and accepts writes to the extubation audit trail. A Cloud
Run URL is public and gets scanned.

The service is deployed `--allow-unauthenticated` so that a plain browser can
reach it, and the app's own key is what actually guards it. The link you hand
out ends in `?key=...`. **That link is a password.** Anyone who has it has
everything.

Reuse the key already set on the service when you redeploy, or existing links
stop working. To rotate it deliberately, redeploy with a new
`--set-env-vars PROJECT2_ACCESS_KEY=...`.

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
baked into the image; for live hardware you still run `python run.py` locally,
or `python run.py share` for a tunnel from your own machine.

## Cost

Cloud Run bills per request-second. An idle service that nobody opens costs
essentially nothing because it scales to zero. A demo that a handful of people
open occasionally sits inside the free tier. The thing that costs money is
`--min-instances 1`, or leaving a websocket open for hours — the `--timeout 3600`
above allows a one-hour session, and you are billed for that hour.

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
