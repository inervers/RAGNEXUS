$ErrorActionPreference = "Stop"

$composeFile = Join-Path $PSScriptRoot "..\docker-compose.smoke.yml"
$apiBase = "http://127.0.0.1:18000"
$frontendBase = "http://127.0.0.1:18080"
$allowedOrigin = "http://localhost:5173"
$deniedOrigin = "https://untrusted.example"
$hadSmokeApiKey = Test-Path Env:RAG_SMOKE_API_KEY
$previousSmokeApiKey = $env:RAG_SMOKE_API_KEY
$env:RAG_SMOKE_API_KEY = "smoke-$([guid]::NewGuid().ToString('N'))"
$headers = @{ "X-API-Key" = $env:RAG_SMOKE_API_KEY; Origin = $allowedOrigin }

try {
    docker compose -f $composeFile up --build --detach --wait
    if ($LASTEXITCODE -ne 0) { throw "docker compose smoke startup failed" }

    $health = Invoke-RestMethod -Uri "$apiBase/health" -TimeoutSec 10
    if ($health.status -ne "ok" -or $health.chunks -lt 1) {
        throw "unexpected API health response"
    }

    $missingKey = Invoke-WebRequest -Uri "$apiBase/kb/docs" -Headers @{ Origin = $allowedOrigin } `
        -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 10
    if ($missingKey.StatusCode -ne 401) { throw "missing API key unexpectedly returned $($missingKey.StatusCode)" }
    if ($missingKey.Headers["Access-Control-Allow-Origin"] -ne $allowedOrigin) {
        throw "allowed origin could not read missing-key response"
    }

    $wrongKey = Invoke-WebRequest -Uri "$apiBase/kb/docs" `
        -Headers @{ "X-API-Key" = "wrong-smoke-key"; Origin = $allowedOrigin } `
        -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 10
    if ($wrongKey.StatusCode -ne 403) { throw "wrong API key unexpectedly returned $($wrongKey.StatusCode)" }
    if ($wrongKey.Headers["Access-Control-Allow-Origin"] -ne $allowedOrigin) {
        throw "allowed origin could not read wrong-key response"
    }

    $allowedPreflight = Invoke-WebRequest -Uri "$apiBase/query/hybrid" -Method Options -Headers @{
        Origin = $allowedOrigin
        "Access-Control-Request-Method" = "POST"
        "Access-Control-Request-Headers" = "X-API-Key,Content-Type"
    } -UseBasicParsing -TimeoutSec 10
    if ($allowedPreflight.Headers["Access-Control-Allow-Origin"] -ne $allowedOrigin) {
        throw "allowed CORS origin was not echoed"
    }

    $deniedPreflight = Invoke-WebRequest -Uri "$apiBase/query/hybrid" -Method Options -Headers @{
        Origin = $deniedOrigin
        "Access-Control-Request-Method" = "POST"
        "Access-Control-Request-Headers" = "X-API-Key,Content-Type"
    } -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 10
    if ($deniedPreflight.Headers["Access-Control-Allow-Origin"]) {
        throw "disallowed CORS origin received an allow-origin header"
    }

    $allowedProtected = Invoke-WebRequest -Uri "$apiBase/kb/docs" -Headers $headers -UseBasicParsing -TimeoutSec 10
    if ($allowedProtected.Headers["Access-Control-Allow-Origin"] -ne $allowedOrigin) {
        throw "allowed origin could not read a successful protected response"
    }

    $validationError = Invoke-WebRequest -Uri "$apiBase/query/hybrid" -Method Post -Headers $headers `
        -ContentType "application/json" -Body '{}' -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 10
    if ($validationError.StatusCode -ne 422) { throw "malformed request unexpectedly returned $($validationError.StatusCode)" }
    if ($validationError.Headers["Access-Control-Allow-Origin"] -ne $allowedOrigin) {
        throw "allowed origin could not read validation error response"
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

    $longText = "完整文档段落" * 1001
    $encodedText = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($longText))
    $uploadBody = @{ filename = "smoke-long.txt"; content = $encodedText } | ConvertTo-Json -Compress
    $preview = Invoke-RestMethod -Uri "$apiBase/doc/preview" -Method Post `
        -Headers $headers -ContentType "application/json" -Body $uploadBody -TimeoutSec 10
    if ($preview.preview.Length -ne 5000 -or $preview.full_length -ne $longText.Length -or -not $preview.truncated) {
        throw "document preview contract failed"
    }
    $imported = Invoke-RestMethod -Uri "$apiBase/doc/import" -Method Post `
        -Headers $headers -ContentType "application/json" -Body $uploadBody -TimeoutSec 30
    if ($imported.parsed_length -ne $longText.Length -or $imported.chunks -lt 2) {
        throw "formal document import was truncated"
    }

    $frontend = Invoke-WebRequest -Uri "$frontendBase/" -UseBasicParsing -TimeoutSec 10
    $proxiedHealth = Invoke-RestMethod -Uri "$frontendBase/health" -TimeoutSec 10
    if ($frontend.StatusCode -ne 200 -or $proxiedHealth.status -ne "ok") {
        throw "frontend or nginx proxy smoke failed"
    }

    $rateLimited = $null
    foreach ($attempt in 1..10) {
        $candidate = Invoke-WebRequest -Uri "$apiBase/kb/docs" -Headers $headers `
            -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 10
        if ($candidate.StatusCode -eq 429) { $rateLimited = $candidate; break }
        if ($candidate.StatusCode -ne 200) { throw "unexpected rate-limit probe status $($candidate.StatusCode)" }
    }
    if (-not $rateLimited) { throw "rate-limit response was not reached" }
    if ($rateLimited.Headers["Access-Control-Allow-Origin"] -ne $allowedOrigin) {
        throw "allowed origin could not read rate-limit response"
    }

    [PSCustomObject]@{
        ApiStatus = $health.status
        FixtureChunks = $health.chunks
        MissingKeyStatus = 401
        WrongKeyStatus = 403
        ValidationStatus = 422
        RateLimitStatus = 429
        AllowedCorsOrigin = $allowedPreflight.Headers["Access-Control-Allow-Origin"]
        DeniedCorsOrigin = "no allow-origin header"
        RetrievalStrategy = $hybrid.result.trace.strategy
        RetrievalSelected = $hybrid.result.selected.Count
        PreviewLength = $preview.preview.Length
        ImportedLength = $imported.parsed_length
        ImportedChunks = $imported.chunks
        FrontendStatus = $frontend.StatusCode
        ProxyHealth = $proxiedHealth.status
    } | Format-List
} finally {
    docker compose -f $composeFile down --volumes --remove-orphans
    if ($hadSmokeApiKey) { $env:RAG_SMOKE_API_KEY = $previousSmokeApiKey }
    else { Remove-Item Env:RAG_SMOKE_API_KEY -ErrorAction SilentlyContinue }
}
