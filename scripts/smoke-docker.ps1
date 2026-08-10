$ErrorActionPreference = "Stop"

$composeFile = Join-Path $PSScriptRoot "..\docker-compose.smoke.yml"
$apiBase = "http://127.0.0.1:18000"
$frontendBase = "http://127.0.0.1:18080"
$headers = @{ "X-API-Key" = "rag-secret-key-2024" }

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
        RetrievalStrategy = $hybrid.result.trace.strategy
        RetrievalSelected = $hybrid.result.selected.Count
        FrontendStatus = $frontend.StatusCode
        ProxyHealth = $proxiedHealth.status
    } | Format-List
} finally {
    docker compose -f $composeFile down --volumes --remove-orphans
}
