$ErrorActionPreference = "Stop"

$composeFile = Join-Path $PSScriptRoot "..\docker-compose.smoke.yml"
$apiBase = "http://127.0.0.1:18000"
$frontendBase = "http://127.0.0.1:18080"
$allowedOrigin = "http://localhost:5173"
$deniedOrigin = "https://untrusted.example"
$env:RAG_SMOKE_API_KEY = "smoke-$([guid]::NewGuid().ToString('N'))"
$headers = @{ "X-API-Key" = $env:RAG_SMOKE_API_KEY }

try {
    docker compose -f $composeFile up --build --detach --wait
    if ($LASTEXITCODE -ne 0) { throw "docker compose smoke startup failed" }

    $health = Invoke-RestMethod -Uri "$apiBase/health" -TimeoutSec 10
    if ($health.status -ne "ok" -or $health.chunks -lt 1) {
        throw "unexpected API health response"
    }

    try {
        Invoke-WebRequest -Uri "$apiBase/kb/docs" -UseBasicParsing -TimeoutSec 10 | Out-Null
        throw "missing API key unexpectedly succeeded"
    } catch {
        if ($_.Exception.Response.StatusCode.value__ -ne 401) { throw }
    }

    try {
        Invoke-WebRequest -Uri "$apiBase/kb/docs" -Headers @{ "X-API-Key" = "wrong-smoke-key" } `
            -UseBasicParsing -TimeoutSec 10 | Out-Null
        throw "wrong API key unexpectedly succeeded"
    } catch {
        if ($_.Exception.Response.StatusCode.value__ -ne 403) { throw }
    }

    $allowedPreflight = Invoke-WebRequest -Uri "$apiBase/query/hybrid" -Method Options -Headers @{
        Origin = $allowedOrigin
        "Access-Control-Request-Method" = "POST"
        "Access-Control-Request-Headers" = "X-API-Key,Content-Type"
    } -UseBasicParsing -TimeoutSec 10
    if ($allowedPreflight.Headers["Access-Control-Allow-Origin"] -ne $allowedOrigin) {
        throw "allowed CORS origin was not echoed"
    }

    try {
        $deniedPreflight = Invoke-WebRequest -Uri "$apiBase/query/hybrid" -Method Options -Headers @{
            Origin = $deniedOrigin
            "Access-Control-Request-Method" = "POST"
            "Access-Control-Request-Headers" = "X-API-Key,Content-Type"
        } -UseBasicParsing -TimeoutSec 10
    } catch {
        $deniedPreflight = $_.Exception.Response
    }
    if ($deniedPreflight.Headers["Access-Control-Allow-Origin"]) {
        throw "disallowed CORS origin received an allow-origin header"
    }

    $body = @{
        question = "Transformer attention"
        top_k = 3
        strategy = "hybrid"
        use_reranker = $false
    } | ConvertTo-Json
    $hybrid = Invoke-RestMethod -Uri "$apiBase/query/hybrid" -Method Post `
        -Headers $headers -ContentType "application/json" -Body $body -TimeoutSec 30
    if ($hybrid.result.trace.strategy -ne "hybrid" -or $hybrid.result.selected.Count -lt 1) {
        throw "hybrid retrieval smoke failed"
    }

    $frontend = Invoke-WebRequest -Uri "$frontendBase/" -UseBasicParsing -TimeoutSec 10
    $proxiedHealth = Invoke-RestMethod -Uri "$frontendBase/health" -TimeoutSec 10
    if ($frontend.StatusCode -ne 200 -or $proxiedHealth.status -ne "ok") {
        throw "frontend or nginx proxy smoke failed"
    }

    [PSCustomObject]@{
        ApiStatus = $health.status
        FixtureChunks = $health.chunks
        MissingKeyStatus = 401
        WrongKeyStatus = 403
        AllowedCorsOrigin = $allowedPreflight.Headers["Access-Control-Allow-Origin"]
        DeniedCorsOrigin = "no allow-origin header"
        RetrievalStrategy = $hybrid.result.trace.strategy
        RetrievalSelected = $hybrid.result.selected.Count
        FrontendStatus = $frontend.StatusCode
        ProxyHealth = $proxiedHealth.status
    } | Format-List
} finally {
    docker compose -f $composeFile down --volumes --remove-orphans
    Remove-Item Env:RAG_SMOKE_API_KEY -ErrorAction SilentlyContinue
}
