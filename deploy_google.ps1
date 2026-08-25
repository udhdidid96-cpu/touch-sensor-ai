<#
    Deploy the Smart Extubation console to Google Cloud Run.

    Run:  .\deploy_google.ps1        (or double-click deploy_google.bat)

    There is nothing to fill in. The earlier instructions had you paste
    "<REGION>" literally; PowerShell treats "<" as a reserved operator, which is
    where the ParserError came from. This script finds the region itself.

    It looks before it leaps: if the service is already deployed and failing,
    the reason is printed before anything is rebuilt.
#>

# Native tools write progress to stderr. In PowerShell 7.4+ that combination
# plus ErrorActionPreference='Stop' turns ordinary gcloud chatter into a thrown
# exception, so both are turned off deliberately and exit codes are checked
# by hand instead.
$ErrorActionPreference = 'Continue'
$PSNativeCommandUseErrorActionPreference = $false

Set-Location -LiteralPath $PSScriptRoot

$SERVICE        = 'smart-extubation-ai'   # the service already in your project
$FALLBACKREGION = 'asia-southeast1'       # only if nothing is deployed yet
$MEMORY         = '1Gi'

function Say($msg, $colour = 'Gray') { Write-Host "  $msg" -ForegroundColor $colour }
function Rule { Write-Host '  --------------------------------------------------------------------' }

Write-Host ''
Rule
Write-Host '   Smart Extubation - deploy to Cloud Run' -ForegroundColor White
Rule
Say "folder : $PSScriptRoot"

# ------------------------------------------------------------- 1. gcloud ----
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Say 'gcloud is not on PATH. Install the Google Cloud CLI first:' 'Red'
    Say 'https://cloud.google.com/sdk/docs/install' 'Red'
    exit 1
}

$account = (& gcloud config get-value account 2>$null | Select-Object -First 1)
$project = (& gcloud config get-value project 2>$null | Select-Object -First 1)
if (-not $account -or $account -eq '(unset)') { Say 'Not logged in. Run:  gcloud auth login' 'Red'; exit 1 }
if (-not $project -or $project -eq '(unset)') { Say 'No project set. Run:  gcloud config set project YOUR_PROJECT_ID' 'Red'; exit 1 }
Say "account: $account"
Say "project: $project"

# ------------------------------------------------- 2. find its region -------
Say 'looking for an existing deployment ...'
$region  = $null
$existing = $null
$listJson = (& gcloud run services list --format=json 2>$null) -join "`n"
if ($listJson) {
    try {
        $existing = ($listJson | ConvertFrom-Json) | Where-Object { $_.metadata.name -eq $SERVICE }
        if ($existing) { $region = $existing.metadata.labels.'cloud.googleapis.com/location' }
    } catch { }
}

if ($region) {
    Say "found $SERVICE in $region" 'Green'
} else {
    $region = $FALLBACKREGION
    Say "no service named $SERVICE yet - it will be created in $region" 'Yellow'
}

# -------------------------------------------- 3. why is it not serving? -----
$existingKey = $null
if ($existing) {
    Write-Host ''
    Rule
    Say 'current state of the deployed service'
    $descJson = (& gcloud run services describe $SERVICE --region $region --format=json 2>$null) -join "`n"
    if ($descJson) {
        try {
            $desc  = $descJson | ConvertFrom-Json
            $ready = $desc.status.conditions | Where-Object { $_.type -eq 'Ready' } | Select-Object -First 1
            if ($ready) {
                $colour = if ($ready.status -eq 'True') { 'Green' } else { 'Red' }
                Say ("Ready = {0}" -f $ready.status) $colour
                if ($ready.message) { Say ("reason : {0}" -f $ready.message) $colour }
            }

            $envList = @($desc.spec.template.spec.containers[0].env)
            $entry   = $envList | Where-Object { $_.name -eq 'PROJECT2_ACCESS_KEY' } | Select-Object -First 1
            if ($entry -and $entry.value) {
                $existingKey = $entry.value
                Say 'PROJECT2_ACCESS_KEY is set on the service.' 'Green'
            } else {
                Say 'PROJECT2_ACCESS_KEY is NOT set on the service.' 'Red'
                Say 'That is very likely the whole problem: main.py refuses to serve' 'Red'
                Say '0.0.0.0 without it, so the container exits at boot, the revision' 'Red'
                Say 'never turns healthy, and there is nothing in the log to read.' 'Red'
                Say 'The deploy below sets it.' 'Red'
            }
        } catch { Say 'could not parse the service description - continuing anyway' 'Yellow' }
    }
    Rule
}

# --------------------------------------------------------------- 4. key -----
# Reuse the key already on the service, so a link you have handed out keeps
# working across redeploys.
if ($existingKey) {
    $KEY = $existingKey
    Say 'reusing the access key already on the service'
} else {
    $KEY = (& python -c "import secrets;print(secrets.token_urlsafe(24))" 2>$null | Select-Object -First 1)
    if (-not $KEY) { $KEY = [Convert]::ToBase64String([Guid]::NewGuid().ToByteArray()).TrimEnd('=').Replace('+','-').Replace('/','_') }
    Say 'generated a new access key'
}

# ------------------------------------------------------------ 5. deploy -----
Write-Host ''
Say 'enabling required APIs (no-op if already enabled) ...'
& gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --quiet 2>$null | Out-Null

Write-Host ''
Say "building from $PSScriptRoot and deploying to $region" 'Cyan'
Say 'first run takes about 5-8 minutes' 'Cyan'
Write-Host ''

& gcloud run deploy $SERVICE `
    --source . `
    --region $region `
    --platform managed `
    --allow-unauthenticated `
    --memory $MEMORY `
    --cpu 1 `
    --timeout 3600 `
    --session-affinity `
    --max-instances 3 `
    --set-env-vars "PROJECT2_ACCESS_KEY=$KEY"

if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Say 'Deploy failed. The usual causes, in order of likelihood:' 'Red'
    Say '  - billing is not enabled on this project' 'Red'
    Say '  - the account lacks Cloud Run Admin / Cloud Build Editor' 'Red'
    Say '  - the build ran out of memory: raise $MEMORY at the top of this file' 'Red'
    exit 1
}

# ---------------------------------------------------------------- 6. link ---
$url = (& gcloud run services describe $SERVICE --region $region --format='value(status.url)' 2>$null | Select-Object -First 1)

Write-Host ''
Rule
Write-Host '   Deployed. Open this - the key is part of the link:' -ForegroundColor Green
Write-Host ''
Write-Host "   $url/?key=$KEY" -ForegroundColor Cyan
Write-Host ''
Write-Host '   Anyone holding that link reaches the recordings, the upload endpoint'
Write-Host '   and the audit trail. Treat it as a password.'
Rule
Write-Host "   Take it down:  gcloud run services delete $SERVICE --region $region"
Write-Host ''
